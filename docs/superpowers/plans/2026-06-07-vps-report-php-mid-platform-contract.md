# VPS `report.php` 中台读取契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 `fetch.php` / `report.php` 的公网调用方式正式收口成一份可交付给中台的稳定读取契约，并确保代码、测试与文档中的字段语义完全一致。

**Architecture:** 继续保持现有 `Cloudflare -> 公网 PHP -> 127.0.0.1 Python API -> MySQL` 架构不变，不新增接口。实现重点是固定 `fetch.php` 的触发语义、固定 `report.php` 的读取语义，并让内部 API、PHP 转发层、部署文档和中台契约文档使用同一套字段定义。

**Tech Stack:** FastAPI, Pydantic, PHP 8.3, pytest, Markdown docs

---

## File Structure

- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_api.py`
  - 如有必要，补充或收紧 `SiteDailyReportResponse` 字段语义
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_api.py`
  - 固定中台依赖字段的测试覆盖
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/php/fetch.php`
  - 固定 accepted 语义，不再暗示同步成功
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/php/report.php`
  - 固定 `report.php` 对状态字段的透明转发行为
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/README.md`
  - 补充中台接入顺序与状态解释
- Modify: `D:/code/adx-account-isolated-collector/docs/operator-notes.md`
  - 补充面向运行维护的中台读取说明
- Create/Modify: `D:/code/adx-account-isolated-collector/docs/superpowers/specs/2026-06-07-vps-report-php-mid-platform-contract-design.md`
  - 作为正式契约文档来源

### Task 1: 固定 `report.php` 字段与状态语义的测试和代码边界

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/collector/tests/test_vps_api.py`
- Modify: `D:/code/adx-account-isolated-collector/collector/app/vps_api.py`

- [ ] **Step 1: 先写一条“未触发”状态的失败测试**

```python
def test_internal_site_daily_endpoint_returns_not_started_shape() -> None:
    from app.vps_api import create_app

    class FakeFetchService:
        def enqueue_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise AssertionError("not used")

        def get_site_daily_report(self, *, account_key, report_date):
            return VpsSiteDailyReportResult(
                account_key=account_key,
                report_date=report_date.isoformat(),
                has_run=False,
                run_status=None,
                run_id=None,
                row_count=0,
                error_message=None,
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
        "has_run": False,
        "run_status": None,
        "run_id": None,
        "row_count": 0,
        "error_message": None,
        "items": [],
    }
```

- [ ] **Step 2: 运行测试确认当前行为不偏移**

Run:

```bash
python -m pytest collector/tests/test_vps_api.py::test_internal_site_daily_endpoint_returns_not_started_shape -q
```

Expected:

- PASS；如果失败，说明当前响应模型与契约不一致，需要先修代码

- [ ] **Step 3: 检查 `SiteDailyReportResponse` 是否与契约完全一致**

在 `D:/code/adx-account-isolated-collector/collector/app/vps_api.py` 中确认或调整为：

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

并确认路由返回始终使用：

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

- [ ] **Step 4: 运行相关 API 测试**

Run:

```bash
python -m pytest collector/tests/test_vps_api.py -q
```

Expected:

- 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add collector/tests/test_vps_api.py collector/app/vps_api.py
git commit -m "test: lock report api contract semantics"
```

### Task 2: 固定公网 PHP 层的契约表达

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/php/fetch.php`
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/php/report.php`

- [ ] **Step 1: 检查 `fetch.php` 是否仍然只表达 accepted 语义**

确认 `D:/code/adx-account-isolated-collector/deploy/vps/php/fetch.php` 的成功路径不再自行推断最终结果，而是保持：

```php
http_response_code($status > 0 ? $status : 502);
$decodedBody = json_decode($body, true);
if (is_array($decodedBody) && !array_key_exists('request_id', $decodedBody)) {
    $decodedBody['request_id'] = $requestId;
    echo json_encode($decodedBody, JSON_UNESCAPED_SLASHES);
    exit;
}

echo $body;
```

同时保留当前较短超时：

```php
CURLOPT_TIMEOUT => 15,
```

- [ ] **Step 2: 检查 `report.php` 是否透明转发状态字段**

确认 `D:/code/adx-account-isolated-collector/deploy/vps/php/report.php` 没有手动过滤这些字段：

- `has_run`
- `run_status`
- `run_id`
- `row_count`
- `error_message`
- `items`

并保持：

```php
$decodedBody = json_decode($body, true);
if (is_array($decodedBody) && !array_key_exists('request_id', $decodedBody)) {
    $decodedBody['request_id'] = $requestId;
    echo json_encode($decodedBody, JSON_UNESCAPED_SLASHES);
    exit;
}

echo $body;
```

- [ ] **Step 3: 如果需要，收紧注释或错误文案**

如代码中仍有“同步成功”意味的注释或命名，直接改成契约一致表达。例如：

```php
'message' => 'failed to initialize curl',
```

保持中性，不把 `fetch.php` 描述成最终完成接口。

- [ ] **Step 4: 在有 PHP 的环境重新做语法检查**

Run on VPS:

```bash
php -l /www/wwwroot/api.wangmengmeng.fun/ke/fetch.php
php -l /www/wwwroot/api.wangmengmeng.fun/ke/report.php
```

Expected:

- 两条都返回 `No syntax errors detected`

- [ ] **Step 5: Commit**

```bash
git add deploy/vps/php/fetch.php deploy/vps/php/report.php
git commit -m "docs: align php entrypoints with mid-platform contract"
```

### Task 3: 收口部署文档和中台接入文档

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/README.md`
- Modify: `D:/code/adx-account-isolated-collector/docs/operator-notes.md`
- Modify: `D:/code/adx-account-isolated-collector/docs/superpowers/specs/2026-06-07-vps-report-php-mid-platform-contract-design.md`

- [ ] **Step 1: 在部署 README 中明确中台调用顺序**

将 `D:/code/adx-account-isolated-collector/deploy/vps/README.md` 收口到下面这种结构：

```markdown
1. 调 `fetch.php`，确认 `status=accepted`
2. 等待数秒
3. 轮询 `report.php`
4. 当 `run_status=success` 时读取 `items`
5. 当 `run_status=failed` 时读取 `error_message`
```

并保留对以下状态的解释：

- `has_run=false`
- `run_status=pending|running`
- `run_status=success`
- `run_status=failed`

- [ ] **Step 2: 在 operator notes 中增加中台视角说明**

在 `D:/code/adx-account-isolated-collector/docs/operator-notes.md` 中补上这段说明：

```markdown
中台集成时，应将：

- `fetch.php` 视为“提交任务接口”
- `report.php` 视为“读取任务当前结果视图接口”

不要仅根据 `row_count` 判断结果，必须结合 `run_status` 一起解释。
```

并附上查询命令：

```bash
curl "https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me"
curl "https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me"
```

- [ ] **Step 3: 回看 spec 文档，补一段“稳定字段清单”摘要**

在 `D:/code/adx-account-isolated-collector/docs/superpowers/specs/2026-06-07-vps-report-php-mid-platform-contract-design.md` 中确保以下稳定字段已经成组列出：

```markdown
- `ok`
- `account_key`
- `report_date`
- `has_run`
- `run_status`
- `run_id`
- `row_count`
- `error_message`
- `items`
- `site_name`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`
```

如果缺失，就补进去；如果已存在，保持一致即可。

- [ ] **Step 4: 做一次完整回归**

Run:

```bash
python -m pytest collector/tests/test_vps_models.py collector/tests/test_vps_service.py collector/tests/test_vps_api.py -q
```

Expected:

- 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add deploy/vps/README.md docs/operator-notes.md docs/superpowers/specs/2026-06-07-vps-report-php-mid-platform-contract-design.md
git commit -m "docs: finalize mid-platform report contract"
```

## Self-Review

- **Spec coverage:** 计划覆盖了 `fetch.php` 契约、`report.php` 契约、状态语义、调用顺序、字段稳定性、适用边界和文档收口，没有引入新的中台接口或额外功能。
- **Placeholder scan:** 计划中没有 `TODO`、`TBD`、`后续补充` 这类占位要求。每个任务都给了明确文件、代码片段、测试命令和预期结果。
- **Type consistency:** 统一使用 `ok`、`has_run`、`run_status`、`run_id`、`row_count`、`error_message`、`items` 这一组字段名，和现有实现及 spec 保持一致。
