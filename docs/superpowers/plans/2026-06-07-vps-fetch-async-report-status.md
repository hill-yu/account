# VPS 公网触发异步化与 report 状态语义 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前公网 `fetch.php` 改成异步受理模式，避免 Cloudflare 长请求超时，并在不新增接口的前提下让 `report.php` 能区分未触发、执行中、成功空结果、成功有结果和失败。

**Architecture:** 保持现有 `Cloudflare -> PHP -> 127.0.0.1 Python API -> MySQL` 架构不变。`POST /internal/fetch` 改成只创建 `pending` run 并立即返回 `accepted`，由同一个 FastAPI 进程内的后台线程轮询消费；`GET /internal/reports/site-daily` 与 `report.php` 扩充状态字段，统一由 `report.php` 承载最小状态语义。

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, MySQL/SQLite tests, PHP 8.3, pytest, threading

---

## File Structure

- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_repository.py`
  - 将 `create_fetch_run()` 改为创建 `pending`
  - 增加 pending run 查询、抢占、按最近 run 查询的仓储方法
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_service.py`
  - 拆分 `run_fetch()` 为 `enqueue_fetch()` 与 `execute_fetch_run()`
  - 扩充读数结果对象，暴露 `has_run` / `run_status` / `error_message`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_api.py`
  - `POST /internal/fetch` 改成 accepted 语义
  - 在 app 生命周期中启动后台轮询线程
  - 扩充 `GET /internal/reports/site-daily` 响应模型
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/php/fetch.php`
  - 适配 `accepted` 响应，不再依赖最终 `row_count`
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/php/report.php`
  - 原样透出新的状态字段
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_service.py`
  - 覆盖入队、后台执行、状态读取三类行为
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_api.py`
  - 覆盖 accepted 响应、后台线程不影响测试、扩充后的 report 响应
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/README.md`
  - 更新异步触发后的验证命令
- Modify: `D:/code/adx-account-isolated-collector/docs/operator-notes.md`
  - 补充“触发后轮询 report.php”的操作说明

### Task 1: 将 fetch 从同步执行改成入队受理

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_service.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_api.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_repository.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_service.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_api.py`

- [ ] **Step 1: 先写服务层入队测试**

```python
def test_vps_fetch_service_enqueue_fetch_creates_pending_run(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "enqueue.db")
    _seed_active_account(session_factory)

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    result = service.enqueue_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-enqueue-1",
    )

    assert result.status == "accepted"
    assert result.row_count == 0

    with session_factory() as db:
        from app.vps_models import AdxFetchRun

        run = db.query(AdxFetchRun).one()
        assert run.status == "pending"
        assert run.request_id == "req-enqueue-1"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
python -m pytest collector/tests/test_vps_service.py::test_vps_fetch_service_enqueue_fetch_creates_pending_run -q
```

Expected:

- FAIL，提示 `VpsFetchService` 没有 `enqueue_fetch`

- [ ] **Step 3: 再写 API accepted 响应测试**

```python
def test_internal_fetch_endpoint_returns_accepted_payload() -> None:
    from app.vps_api import create_app
    from app.vps_service import VpsFetchResult

    class FakeFetchService:
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            return VpsFetchResult(
                run_id=17,
                account_key=account_key,
                report_date=report_date.isoformat(),
                row_count=0,
                status="accepted",
            )

        def get_site_daily_report(self, *, account_key, report_date):
            raise AssertionError("not used")

    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)

    response = client.post(
        "/internal/fetch",
        json={
            "account_key": "a1",
            "report_date": "2026-06-03",
            "trigger_source": "php_manual",
            "request_id": "req-001",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": 17,
        "account_key": "a1",
        "report_date": "2026-06-03",
        "row_count": 0,
        "status": "accepted",
    }
```

- [ ] **Step 4: 运行 API 测试确认失败**

Run:

```bash
python -m pytest collector/tests/test_vps_api.py::test_internal_fetch_endpoint_returns_accepted_payload -q
```

Expected:

- FAIL，提示 `FakeFetchService` 缺少 `run_fetch` 或返回值不匹配

- [ ] **Step 5: 实现仓储层 pending run 基础方法**

在 `D:/code/adx-account-isolated-collector/collector/app/vps_repository.py` 中补齐下面这些方法或同等职责的方法：

```python
def create_fetch_run(
    self,
    *,
    account_id: int,
    report_date: date,
    trigger_source: str,
    request_id: str,
) -> AdxFetchRun:
    run = AdxFetchRun(
        account_id=account_id,
        report_date=report_date,
        trigger_source=trigger_source,
        request_id=request_id,
        status="pending",
        row_count=0,
    )
    self._db.add(run)
    self._db.flush()
    return run

def get_latest_fetch_run(self, *, account_id: int, report_date: date) -> AdxFetchRun | None:
    return (
        self._db.query(AdxFetchRun)
        .filter(
            AdxFetchRun.account_id == account_id,
            AdxFetchRun.report_date == report_date,
        )
        .order_by(AdxFetchRun.id.desc())
        .first()
    )
```

- [ ] **Step 6: 实现服务层 enqueue 行为**

在 `D:/code/adx-account-isolated-collector/collector/app/vps_service.py` 中新增：

```python
def enqueue_fetch(
    self,
    *,
    account_key: str,
    report_date: date,
    trigger_source: str,
    request_id: str,
) -> VpsFetchResult:
    with self._session_factory() as db:
        repo = VpsRepository(db)
        account = repo.get_active_account_by_key(account_key, lock_for_update=True)
        if account is None:
            raise AccountConfigError(f"Unknown active account_key: {account_key}")

        existing_run = repo.get_running_fetch_run(account_id=account.id, report_date=report_date)
        if existing_run is not None:
            raise FetchExecutionError(
                "Fetch already running for "
                f"account_key={account_key} report_date={report_date.isoformat()} "
                f"(run_id={existing_run.id}, request_id={existing_run.request_id})"
            )

        run = repo.create_fetch_run(
            account_id=account.id,
            report_date=report_date,
            trigger_source=trigger_source,
            request_id=request_id,
        )
        db.commit()

        return VpsFetchResult(
            run_id=run.id,
            account_key=account.account_key,
            report_date=report_date.isoformat(),
            row_count=0,
            status="accepted",
        )
```

- [ ] **Step 7: 将 API 从 `run_fetch` 切到 `enqueue_fetch`**

在 `D:/code/adx-account-isolated-collector/collector/app/vps_api.py` 中把协议和路由都改成：

```python
class FetchService(Protocol):
    def enqueue_fetch(
        self,
        *,
        account_key: str,
        report_date: date,
        trigger_source: str,
        request_id: str,
    ):
        ...

    def get_site_daily_report(
        self,
        *,
        account_key: str,
        report_date: date,
    ):
        ...

@application.post("/internal/fetch", response_model=FetchResponse)
def internal_fetch(payload: FetchRequest) -> FetchResponse:
    result = service.enqueue_fetch(
        account_key=payload.account_key,
        report_date=payload.report_date,
        trigger_source=payload.trigger_source,
        request_id=payload.request_id,
    )
    return FetchResponse(
        ok=True,
        run_id=result.run_id,
        account_key=result.account_key,
        report_date=result.report_date,
        row_count=result.row_count,
        status=result.status,
    )
```

- [ ] **Step 8: 运行相关测试确认通过**

Run:

```bash
python -m pytest collector/tests/test_vps_service.py::test_vps_fetch_service_enqueue_fetch_creates_pending_run collector/tests/test_vps_api.py::test_internal_fetch_endpoint_returns_accepted_payload -q
```

Expected:

- PASS

- [ ] **Step 9: Commit**

```bash
git add collector/tests/test_vps_service.py collector/tests/test_vps_api.py collector/app/vps_repository.py collector/app/vps_service.py collector/app/vps_api.py
git commit -m "feat: enqueue vps fetch runs asynchronously"
```

### Task 2: 增加进程内后台线程消费 pending run

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_service.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_api.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_repository.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_service.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_api.py`

- [ ] **Step 1: 先写服务层执行 pending run 的测试**

```python
def test_vps_fetch_service_execute_fetch_run_consumes_pending_run(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "worker.db")
    _seed_active_account(session_factory)
    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    accepted = service.enqueue_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-worker-1",
    )

    result = service.execute_fetch_run(accepted.run_id)

    assert result.status == "success"
    assert result.row_count == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
python -m pytest collector/tests/test_vps_service.py::test_vps_fetch_service_execute_fetch_run_consumes_pending_run -q
```

Expected:

- FAIL，提示 `execute_fetch_run` 不存在

- [ ] **Step 3: 再写 report 状态读取的失败测试**

```python
def test_vps_fetch_service_report_exposes_pending_status(tmp_path) -> None:
    from app.vps_service import VpsFetchService

    session_factory = _build_test_session_factory(tmp_path, "pending-report.db")
    _seed_active_account(session_factory)
    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    service.enqueue_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-pending-status",
    )

    report = service.get_site_daily_report(account_key="a1", report_date=date(2026, 5, 14))

    assert report.has_run is True
    assert report.run_status == "pending"
    assert report.row_count == 0
    assert report.items == []
```

- [ ] **Step 4: 运行状态测试确认失败**

Run:

```bash
python -m pytest collector/tests/test_vps_service.py::test_vps_fetch_service_report_exposes_pending_status -q
```

Expected:

- FAIL，提示 `VpsSiteDailyReportResult` 没有 `has_run` 或 `run_status`

- [ ] **Step 5: 实现 pending 抢占与执行方法**

在 `D:/code/adx-account-isolated-collector/collector/app/vps_repository.py` 和 `D:/code/adx-account-isolated-collector/collector/app/vps_service.py` 中补齐这组逻辑：

```python
def claim_fetch_run(self, *, run_id: int) -> AdxFetchRun | None:
    run = (
        self._db.query(AdxFetchRun)
        .filter(AdxFetchRun.id == run_id, AdxFetchRun.status == "pending")
        .with_for_update()
        .one_or_none()
    )
    if run is None:
        return None
    run.status = "running"
    run.error_message = None
    self._db.flush()
    return run

def get_next_pending_fetch_run(self) -> AdxFetchRun | None:
    return (
        self._db.query(AdxFetchRun)
        .filter(AdxFetchRun.status == "pending")
        .order_by(AdxFetchRun.id.asc())
        .first()
    )
```

```python
def execute_fetch_run(self, run_id: int) -> VpsFetchResult | None:
    with self._session_factory() as db:
        repo = VpsRepository(db)
        run = repo.claim_fetch_run(run_id=run_id)
        if run is None:
            return None

        account = db.get(AdxAccount, run.account_id)
        if account is None:
            repo.mark_run_failed(run, message=f"Missing account for run_id={run.id}")
            db.commit()
            return VpsFetchResult(
                run_id=run.id,
                account_key="",
                report_date=run.report_date.isoformat(),
                row_count=0,
                status="failed",
            )

        proxy_binding = repo.get_active_proxy_for_account(account.id)
        proxy_route = self._proxy_resolver.resolve(account=account, proxy_binding=proxy_binding)
        report_service = self._report_service_factory(account, proxy_route)

        try:
            rows = report_service.fetch_site_daily_report(report_date=run.report_date, task_id=run.id)
            repo.replace_site_rows(
                account_id=account.id,
                report_date=run.report_date,
                fetch_run_id=run.id,
                rows=rows,
            )
            repo.mark_run_success(run, row_count=len(rows))
            db.commit()
            return VpsFetchResult(
                run_id=run.id,
                account_key=account.account_key,
                report_date=run.report_date.isoformat(),
                row_count=len(rows),
                status="success",
            )
        except Exception as exc:
            db.rollback()
            run = db.get(type(run), run.id)
            repo.mark_run_failed(run, message=str(exc))
            db.commit()
            return VpsFetchResult(
                run_id=run.id,
                account_key=account.account_key,
                report_date=run.report_date.isoformat(),
                row_count=0,
                status="failed",
            )
```

- [ ] **Step 6: 扩充 report 结果对象的状态字段**

将 `D:/code/adx-account-isolated-collector/collector/app/vps_service.py` 中的数据类和读取逻辑改成：

```python
@dataclass(frozen=True)
class VpsSiteDailyReportResult:
    account_key: str
    report_date: str
    has_run: bool
    run_status: str | None
    run_id: int | None
    row_count: int
    error_message: str | None
    items: list[dict[str, object]]

def get_site_daily_report(
    self,
    *,
    account_key: str,
    report_date: date,
) -> VpsSiteDailyReportResult:
    with self._session_factory() as db:
        repo = VpsRepository(db)
        account = repo.get_active_account_by_key(account_key)
        if account is None:
            raise AccountConfigError(f"Unknown active account_key: {account_key}")

        run = repo.get_latest_fetch_run(account_id=account.id, report_date=report_date)
        rows = repo.list_site_rows(account_id=account.id, report_date=report_date)

        return VpsSiteDailyReportResult(
            account_key=account.account_key,
            report_date=report_date.isoformat(),
            has_run=run is not None,
            run_status=run.status if run is not None else None,
            run_id=run.id if run is not None else None,
            row_count=len(rows) if run is not None and run.status == "success" else 0,
            error_message=run.error_message if run is not None else None,
            items=[_site_row_to_payload(row) for row in rows] if run is not None and run.status == "success" else [],
        )
```

- [ ] **Step 7: 在 `vps_api.py` 中添加后台轮询线程**

在 `D:/code/adx-account-isolated-collector/collector/app/vps_api.py` 中补上最小后台轮询器：

```python
import threading
import time
from contextlib import asynccontextmanager

def _start_background_worker(service: FetchService) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()

    def loop() -> None:
        while not stop_event.is_set():
            try:
                service.process_next_pending_fetch()
            except Exception:
                pass
            stop_event.wait(2.0)

    thread = threading.Thread(target=loop, name="adx-vps-fetch-worker", daemon=True)
    thread.start()
    return stop_event, thread

@asynccontextmanager
async def lifespan(application: FastAPI):
    stop_event = worker_thread = None
    if hasattr(service, "process_next_pending_fetch"):
        stop_event, worker_thread = _start_background_worker(service)
    try:
        yield
    finally:
        if stop_event is not None:
            stop_event.set()
        if worker_thread is not None:
            worker_thread.join(timeout=5)
```

并在 `create_app()` 中改成：

```python
application = FastAPI(title="ADX VPS Fetch API", lifespan=lifespan)
```

- [ ] **Step 8: 给服务层补一个轮询入口**

在 `D:/code/adx-account-isolated-collector/collector/app/vps_service.py` 中新增：

```python
def process_next_pending_fetch(self) -> VpsFetchResult | None:
    with self._session_factory() as db:
        repo = VpsRepository(db)
        run = repo.get_next_pending_fetch_run()
        if run is None:
            return None
        run_id = run.id

    return self.execute_fetch_run(run_id)
```

- [ ] **Step 9: 运行相关测试确认通过**

Run:

```bash
python -m pytest collector/tests/test_vps_service.py::test_vps_fetch_service_execute_fetch_run_consumes_pending_run collector/tests/test_vps_service.py::test_vps_fetch_service_report_exposes_pending_status -q
```

Expected:

- PASS

- [ ] **Step 10: Commit**

```bash
git add collector/tests/test_vps_service.py collector/app/vps_repository.py collector/app/vps_service.py collector/app/vps_api.py
git commit -m "feat: process pending vps fetch runs in background"
```

### Task 3: 扩充 report 响应语义并收口 PHP 与文档

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_api.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_api.py`
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/php/fetch.php`
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/php/report.php`
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/README.md`
- Modify: `D:/code/adx-account-isolated-collector/docs/operator-notes.md`

- [ ] **Step 1: 先写内部 report API 的状态响应测试**

```python
def test_internal_site_daily_endpoint_returns_run_status_fields() -> None:
    from app.vps_api import create_app

    class FakeFetchService:
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise AssertionError("not used")

        def get_site_daily_report(self, *, account_key, report_date):
            return VpsSiteDailyReportResult(
                account_key=account_key,
                report_date=report_date.isoformat(),
                has_run=True,
                run_status="failed",
                run_id=17,
                row_count=0,
                error_message="boom",
                items=[],
            )

    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)
    response = client.get(
        "/internal/reports/site-daily",
        params={"account_key": "a1", "report_date": "2026-06-03"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "account_key": "a1",
        "report_date": "2026-06-03",
        "has_run": True,
        "run_status": "failed",
        "run_id": 17,
        "row_count": 0,
        "error_message": "boom",
        "items": [],
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
python -m pytest collector/tests/test_vps_api.py::test_internal_site_daily_endpoint_returns_run_status_fields -q
```

Expected:

- FAIL，提示响应模型缺少 `has_run` / `run_status` / `error_message`

- [ ] **Step 3: 扩充 API 响应模型**

在 `D:/code/adx-account-isolated-collector/collector/app/vps_api.py` 中将 `SiteDailyReportResponse` 改成：

```python
class SiteDailyReportResponse(BaseModel):
    ok: bool
    account_key: str
    report_date: str
    has_run: bool
    run_status: str | None
    run_id: int | None
    row_count: int
    error_message: str | None
    items: list[SiteDailyReportItem]
```

并调整路由返回：

```python
return SiteDailyReportResponse(
    ok=True,
    account_key=result.account_key,
    report_date=result.report_date,
    has_run=result.has_run,
    run_status=result.run_status,
    run_id=result.run_id,
    row_count=result.row_count,
    error_message=result.error_message,
    items=[SiteDailyReportItem.model_validate(item) for item in result.items],
)
```

- [ ] **Step 4: 更新 `fetch.php` 和 `report.php` 说明性行为**

将 `D:/code/adx-account-isolated-collector/deploy/vps/php/fetch.php` 的成功分支视为 accepted 响应，不做额外逻辑推断；保持现有 request_id 注入逻辑即可。

将 `D:/code/adx-account-isolated-collector/deploy/vps/php/report.php` 保持为：

```php
$decodedBody = json_decode($body, true);
if (is_array($decodedBody) && !array_key_exists('request_id', $decodedBody)) {
    $decodedBody['request_id'] = $requestId;
    echo json_encode($decodedBody, JSON_UNESCAPED_SLASHES);
    exit;
}
```

要求是不要过滤掉新字段，让 `has_run`、`run_status`、`error_message` 原样透出。

- [ ] **Step 5: 更新部署与操作文档**

在 `D:/code/adx-account-isolated-collector/deploy/vps/README.md` 中把公网验证改成这种顺序：

```markdown
1. 调用 `fetch.php`，确认返回 `status=accepted`
2. 等待数秒
3. 轮询 `report.php`
4. 当 `run_status=success` 时读取 `items`
5. 当 `run_status=failed` 时查看 `error_message`
```

在 `D:/code/adx-account-isolated-collector/docs/operator-notes.md` 中补上这组命令：

```bash
curl "https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me"
curl "https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me"
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT id, report_date, status, row_count, request_id, error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
```

- [ ] **Step 6: 运行完整测试集**

Run:

```bash
python -m pytest collector/tests/test_vps_models.py collector/tests/test_vps_service.py collector/tests/test_vps_api.py -q
```

Expected:

- 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add collector/tests/test_vps_api.py collector/app/vps_api.py deploy/vps/php/fetch.php deploy/vps/php/report.php deploy/vps/README.md docs/operator-notes.md
git commit -m "feat: expose async vps fetch status via report api"
```

## Self-Review

- **Spec coverage:** 计划覆盖了 accepted 入队、后台 pending 消费、`report.php` 状态语义、无新增接口、无新增表、文档验证路径。没有把 token 改造或多账号代理拉进来，和 spec 范围一致。
- **Placeholder scan:** 计划中没有 `TODO`、`TBD`、`后续补充` 之类占位词。每个任务都给了明确文件、代码片段、测试命令和预期。
- **Type consistency:** 全程统一使用 `enqueue_fetch()`、`execute_fetch_run()`、`process_next_pending_fetch()`、`has_run`、`run_status`、`error_message` 这些名字，没有前后漂移。`fetch.php` 返回 `accepted`，`report.php` 返回状态字段，和 spec 一致。
