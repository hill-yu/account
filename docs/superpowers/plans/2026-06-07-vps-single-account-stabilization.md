# VPS 单账号链路稳定化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前单账号 Cloudflare + VPS + PHP + Python + MySQL 链路收口为稳定、可公网触发、可公网读数、可排障的在线服务，并预留中台读取和多账号代理扩展边界。

**Architecture:** 保持现有 `Cloudflare -> 公网 PHP -> 127.0.0.1 Python API -> MySQL` 结构不变。本阶段只做稳定化收口：把 Python API 切到 `systemd` 常驻，固定内部读数 API 与公网 `report.php` 契约，整理运维检查与部署文档。代理层仍保留在 `VpsFetchService -> ProxyResolver -> AdxReportService` 这条链路中，但暂不实现账号级代理出站。

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, PHP 8.3, nginx, systemd, pytest, Google Ad Manager SOAP (`googleads`)

---

## File Structure

- Modify: `collector/app/vps_api.py`
  - 固定内部读数接口 `GET /internal/reports/site-daily`
  - 如有需要，补充只读响应模型
- Modify: `collector/app/vps_service.py`
  - 保持查询逻辑边界稳定
  - 为后续最新运行状态接口预留服务层形态
- Modify: `collector/app/vps_repository.py`
  - 保持读取 `adx_fetch_runs` / `adx_site_daily_reports` 的仓储边界清晰
- Create/Modify: `collector/tests/test_vps_api.py`
  - 覆盖内部读数接口的响应契约
- Create/Modify: `collector/tests/test_vps_service.py`
  - 覆盖服务层读数逻辑
- Modify: `deploy/vps/systemd/adx-fetch-api.service`
  - 固定使用虚拟环境 Python
- Modify: `deploy/vps/php/fetch.php`
  - 如需要，统一返回字段与错误形状
- Modify: `deploy/vps/php/report.php`
  - 固定公网读数返回契约
- Modify: `deploy/vps/nginx/api.example.conf`
  - 确保 `fetch.php` / `report.php` 都可走 PHP-FPM
- Modify: `deploy/vps/README.md`
  - 更新 systemd、部署与公网验证步骤
- Modify: `docs/operator-notes.md`
  - 增补运维检查与读数接口说明

### Task 1: 固定 Python API 常驻运行方式

**Files:**
- Modify: `deploy/vps/systemd/adx-fetch-api.service`
- Modify: `deploy/vps/README.md`
- Test: `deploy/vps/README.md`

- [ ] **Step 1: 写出 service 文件的目标状态**

```ini
[Unit]
Description=ADX VPS Fetch API
After=network.target

[Service]
Type=simple
WorkingDirectory=/srv/adx-account-isolated-collector/collector
EnvironmentFile=/srv/adx-account-isolated-collector/deploy/vps/env/adx-fetch-api.env
ExecStart=/bin/sh -c '/srv/adx-account-isolated-collector/collector/.venv/bin/python -m uvicorn app.vps_api:app --host "${ADX_VPS_BIND_HOST:-127.0.0.1}" --port "${ADX_VPS_BIND_PORT:-9100}"'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: 先写 README 中的部署命令说明**

```bash
sudo cp /srv/adx-account-isolated-collector/deploy/vps/systemd/adx-fetch-api.service /etc/systemd/system/adx-fetch-api.service
sudo systemctl daemon-reload
sudo systemctl enable adx-fetch-api
sudo systemctl restart adx-fetch-api
sudo systemctl status adx-fetch-api --no-pager
curl http://127.0.0.1:9100/health
```

- [ ] **Step 3: 修改 `deploy/vps/systemd/adx-fetch-api.service`**

```ini
[Service]
WorkingDirectory=/srv/adx-account-isolated-collector/collector
EnvironmentFile=/srv/adx-account-isolated-collector/deploy/vps/env/adx-fetch-api.env
ExecStart=/bin/sh -c '/srv/adx-account-isolated-collector/collector/.venv/bin/python -m uvicorn app.vps_api:app --host "${ADX_VPS_BIND_HOST:-127.0.0.1}" --port "${ADX_VPS_BIND_PORT:-9100}"'
Restart=always
RestartSec=3
```

- [ ] **Step 4: 更新 `deploy/vps/README.md` 的 Python API 部署段落**

```markdown
1. 安装 `collector/requirements.txt` 里的 Python 依赖。
2. 将 `deploy/vps/env/adx-fetch-api.env.example` 复制为 `deploy/vps/env/adx-fetch-api.env`。
3. 填写真实的 MySQL 连接串和触发令牌。
4. 运行 `python scripts/init_vps_schema.py` 初始化表结构。
5. 将 `deploy/vps/systemd/adx-fetch-api.service` 安装到 `/etc/systemd/system/`。
6. 使用 `systemctl enable --now adx-fetch-api` 启动常驻服务。
7. 用 `curl http://127.0.0.1:9100/health` 验证服务健康状态。
```

- [ ] **Step 5: 手工验证计划中的命令**

Run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart adx-fetch-api
sudo systemctl status adx-fetch-api --no-pager
curl http://127.0.0.1:9100/health
```

Expected:

- `systemctl status` 显示 `active (running)`
- `/health` 返回 `{"status":"ok"}`

- [ ] **Step 6: Commit**

```bash
git add deploy/vps/systemd/adx-fetch-api.service deploy/vps/README.md
git commit -m "feat: stabilize vps python api service runtime"
```

### Task 2: 固定内部读数 API 与服务层契约

**Files:**
- Modify: `collector/app/vps_api.py`
- Modify: `collector/app/vps_service.py`
- Modify: `collector/app/vps_repository.py`
- Test: `collector/tests/test_vps_api.py`
- Test: `collector/tests/test_vps_service.py`

- [ ] **Step 1: 写内部读数接口的失败测试**

```python
def test_internal_site_daily_endpoint_returns_report_payload() -> None:
    response = client.get(
        "/internal/reports/site-daily",
        params={"account_key": "a1", "report_date": "2026-06-03"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["account_key"] == "a1"
    assert response.json()["report_date"] == "2026-06-03"
    assert response.json()["row_count"] == 2
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest collector/tests/test_vps_api.py::test_internal_site_daily_endpoint_returns_report_payload -q
```

Expected:

- 失败，提示 `404 != 200` 或路由不存在

- [ ] **Step 3: 写服务层读数失败测试**

```python
def test_vps_fetch_service_returns_site_daily_report_rows(tmp_path) -> None:
    service.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-report-1",
    )

    report = service.get_site_daily_report(account_key="a1", report_date=date(2026, 5, 14))

    assert report.account_key == "a1"
    assert report.row_count == 1
    assert report.items[0]["site_name"] == "jane.ghfkl.com"
```

- [ ] **Step 4: 运行测试并确认失败**

Run:

```bash
python -m pytest collector/tests/test_vps_service.py::test_vps_fetch_service_returns_site_daily_report_rows -q
```

Expected:

- 失败，提示 `VpsFetchService` 没有 `get_site_daily_report`

- [ ] **Step 5: 在 `collector/app/vps_repository.py` 增加只读查询**

```python
def get_latest_completed_fetch_run(self, *, account_id: int, report_date: date) -> AdxFetchRun | None:
    return (
        self._db.query(AdxFetchRun)
        .filter(
            AdxFetchRun.account_id == account_id,
            AdxFetchRun.report_date == report_date,
            AdxFetchRun.status == "success",
        )
        .order_by(AdxFetchRun.id.desc())
        .first()
    )

def list_site_rows(self, *, account_id: int, report_date: date) -> list[AdxSiteDailyReport]:
    return (
        self._db.query(AdxSiteDailyReport)
        .filter(
            AdxSiteDailyReport.account_id == account_id,
            AdxSiteDailyReport.report_date == report_date,
        )
        .order_by(AdxSiteDailyReport.site_name.asc())
        .all()
    )
```

- [ ] **Step 6: 在 `collector/app/vps_service.py` 增加只读结果对象和查询方法**

```python
@dataclass(frozen=True)
class VpsSiteDailyReportResult:
    account_key: str
    report_date: str
    run_id: int | None
    row_count: int
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

        run = repo.get_latest_completed_fetch_run(account_id=account.id, report_date=report_date)
        rows = repo.list_site_rows(account_id=account.id, report_date=report_date)

        return VpsSiteDailyReportResult(
            account_key=account.account_key,
            report_date=report_date.isoformat(),
            run_id=run.id if run is not None else None,
            row_count=len(rows),
            items=[_site_row_to_payload(row) for row in rows],
        )
```

- [ ] **Step 7: 在 `collector/app/vps_api.py` 暴露内部读数接口**

```python
@application.get("/internal/reports/site-daily", response_model=SiteDailyReportResponse)
def internal_site_daily_report(
    account_key: str = Query(min_length=1, max_length=100),
    report_date: date = Query(...),
) -> SiteDailyReportResponse:
    result = service.get_site_daily_report(
        account_key=account_key,
        report_date=report_date,
    )
    return SiteDailyReportResponse(
        ok=True,
        account_key=result.account_key,
        report_date=result.report_date,
        run_id=result.run_id,
        row_count=result.row_count,
        items=[SiteDailyReportItem.model_validate(item) for item in result.items],
    )
```

- [ ] **Step 8: 运行相关测试并确认通过**

Run:

```bash
python -m pytest collector/tests/test_vps_service.py collector/tests/test_vps_api.py -q
```

Expected:

- 所有相关测试通过

- [ ] **Step 9: Commit**

```bash
git add collector/app/vps_api.py collector/app/vps_service.py collector/app/vps_repository.py collector/tests/test_vps_api.py collector/tests/test_vps_service.py
git commit -m "feat: add vps site-daily read api"
```

### Task 3: 收口公网 `fetch.php` / `report.php` 入口

**Files:**
- Modify: `deploy/vps/php/fetch.php`
- Modify: `deploy/vps/php/report.php`
- Modify: `deploy/vps/nginx/api.example.conf`
- Modify: `deploy/vps/README.md`
- Modify: `docs/operator-notes.md`

- [ ] **Step 1: 固定 `report.php` 的请求参数与转发方式**

```php
$query = http_build_query([
    'account_key' => $accountKey,
    'report_date' => $reportDate,
]);

$ch = curl_init('http://127.0.0.1:9100/internal/reports/site-daily?' . $query);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 120,
]);
```

- [ ] **Step 2: 统一 `report.php` 成功响应补 `request_id` 的逻辑**

```php
$decodedBody = json_decode($body, true);
if (is_array($decodedBody) && !array_key_exists('request_id', $decodedBody)) {
    $decodedBody['request_id'] = $requestId;
    echo json_encode($decodedBody, JSON_UNESCAPED_SLASHES);
    exit;
}
```

- [ ] **Step 3: 确认 `fetch.php` 与 `report.php` 使用同一套 token / 参数校验风格**

```php
if ($expectedToken === '' || !hash_equals($expectedToken, $token)) {
    http_response_code(401);
    echo json_encode([
        'ok' => false,
        'error_code' => 'REQUEST_ERROR',
        'message' => 'invalid token',
    ], JSON_UNESCAPED_SLASHES);
    exit;
}
```

- [ ] **Step 4: 更新 nginx 样板，让两个 PHP 路由都走 PHP-FPM**

```nginx
server {
    listen 80;
    server_name api.example.com;
    root /srv/adx-account-isolated-collector/deploy/vps/php;
    index fetch.php report.php;

    location ~ ^/ke/(fetch|report)\.php$ {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root/$1.php;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }
}
```

- [ ] **Step 5: 更新 README 与操作文档中的公网验证命令**

```bash
curl "https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me"
curl "https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me"
```

- [ ] **Step 6: 在 VPS 上做本机与公网两轮验证**

Run:

```bash
curl -k --resolve api.example.com:443:127.0.0.1 "https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me"
curl -k --resolve api.example.com:443:127.0.0.1 "https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me"
curl "https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me"
curl "https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me"
```

Expected:

- `fetch.php` 返回 `ok: true`
- `report.php` 返回 `row_count > 0`
- 公网与本机返回形状一致

- [ ] **Step 7: Commit**

```bash
git add deploy/vps/php/fetch.php deploy/vps/php/report.php deploy/vps/nginx/api.example.conf deploy/vps/README.md docs/operator-notes.md
git commit -m "feat: stabilize public vps fetch and report entrypoints"
```

### Task 4: 固定最小运维与排障路径

**Files:**
- Modify: `deploy/vps/README.md`
- Modify: `docs/operator-notes.md`

- [ ] **Step 1: 在 README 中加入运行状态检查命令**

```markdown
### 常用检查命令

```bash
sudo systemctl status adx-fetch-api --no-pager
sudo journalctl -u adx-fetch-api -n 100 --no-pager
curl http://127.0.0.1:9100/health
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT id, account_id, report_date, status, row_count, request_id, error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
```
```

- [ ] **Step 2: 在 `docs/operator-notes.md` 中加入站点结果查询命令**

```markdown
```bash
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT account_id, report_date, site_name, responses_served, impressions, clicks, revenue, ecpm FROM adx_site_daily_reports ORDER BY id DESC LIMIT 20;"
curl "https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me"
```
```

- [ ] **Step 3: 明确记录已接受风险**

```markdown
## 风险接受项

- 当前触发 token 按用户决定继续沿用，不在本阶段轮换。
```

- [ ] **Step 4: 手工检查文档与当前实现是否一致**

Checklist:

- 文档中的 Python API 路径是 `app.vps_api:app`
- 文档中的 systemd 服务名是 `adx-fetch-api`
- 文档中的公网接口是 `/ke/fetch.php` 和 `/ke/report.php`
- 文档中的 MySQL 表名与当前实现一致

- [ ] **Step 5: Commit**

```bash
git add deploy/vps/README.md docs/operator-notes.md
git commit -m "docs: finalize vps stabilization operations guide"
```

## Self-Review

- **Spec coverage:** 计划覆盖了 `systemd` 常驻化、公网触发与读数接口、内部读数 API、运维检查、接口边界与风险接受项。未把多账号代理做深，符合 spec 范围。
- **Placeholder scan:** 计划中没有 `TODO`、`TBD` 或“自行实现”类占位语。每个代码步骤都给了实际代码或命令。
- **Type consistency:** 内部只读接口统一使用 `account_key + report_date`，公网读数入口与内部 API 参数一致；返回字段在 `fetch.php` / `report.php` / `vps_api.py` 中保持一致。

Plan complete and saved to `docs/superpowers/plans/2026-06-07-vps-single-account-stabilization.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
