# 权威日报刷新与北京时间小时查询实现计划

> **面向 AI 代理的工作者：** 使用 `superpowers:test-driven-development` 逐任务实现；每项行为先运行失败测试，再写最小代码。

**目标：** 在生产快照 `355a24e` 基础上，实现权威日报三次刷新、完整结果原子覆盖、小时与日报隔离，以及北京时间自然日小时查询。

**架构：** collector 在核心日报和日报维度全部成功后一次提交组合批次；backend 在单事务中替换全部日报投影并写轻量摘要。调度任务携带固定槽位序号以拒绝迟到覆盖；六个小时接口共享北京时间转 UTC 窗口函数。

**技术栈：** FastAPI、SQLAlchemy、Alembic、SQLite、pytest、Google Ad Manager SOAP collector。

---

### 任务 1：小时入库不再修改权威日报

**文件：**
- 修改：`backend/app/collectors/ingestion_service.py`
- 测试：`backend/tests/test_ingestion_service.py`

- [ ] 增加测试：预置核心日报和日报维度，提交 `admanager_hourly_dimension_v1` 后断言四类日报值不变、小时事实更新。
- [ ] 运行该测试并确认因小时分支调用日报 reset/rebuild 而失败。
- [ ] 删除小时分支对 `_reset_daily_projection`、`_rebuild_site_daily_reports_from_hourly`、`_rebuild_account_daily_report` 及日报维度投影的调用。
- [ ] 运行定向测试和 `backend/tests/test_ingestion_service.py`。

### 任务 2：collector 生成单个完整权威日报批次

**文件：**
- 修改：`collector/app/admanager_soap.py`
- 修改：`collector/app/adx_report_service.py`
- 修改：`collector/app/fetcher.py`
- 测试：`collector/tests/test_admanager_soap.py`
- 测试：`collector/tests/test_adx_report_service.py`
- 测试：`collector/tests/test_fetcher.py`

- [ ] 增加失败测试：核心日报或日报维度拉取失败时 `fetch()` 不返回批次；全部成功时只返回一个 `admanager_authoritative_daily_v1` 批次，payload 同时包含 `core_rows` 和 `dimension_rows`。
- [ ] 恢复日报维度 SOAP 定义和严格日期/必需列解析。
- [ ] 在 `AdxReportService` 增加日报维度拉取，并由 fetcher 聚齐两个完整结果后构建一个组合批次。
- [ ] 运行三个 collector 定向测试文件。

### 任务 3：日报组合批次单事务替换并记录轻量摘要

**文件：**
- 创建：`backend/app/models/authoritative_daily_version_summary.py`
- 修改：`backend/app/models/__init__.py`
- 创建：`backend/alembic/versions/20260805_0015_authoritative_daily_versions.py`
- 修改：`backend/app/collectors/ingestion_service.py`
- 测试：`backend/tests/test_ingestion_service.py`
- 测试：`backend/tests/test_models.py`

- [ ] 增加失败测试：完整组合批次同时替换核心与维度投影；指标下降也覆盖；任一行校验失败时四类旧投影均保留；合法空集合可替换。
- [ ] 增加模型/迁移测试：摘要只保存任务、槽位、汇总、行数、哈希，不保存完整 payload。
- [ ] 实现 `admanager_authoritative_daily_v1` 的事务内校验、四类投影替换和摘要写入。
- [ ] 成功后只保留当前批次 payload；旧日报批次 payload 清空但保留哈希、行数和元数据。
- [ ] 运行 ingestion、模型与迁移测试。

### 任务 4：05:00、06:00、07:00 调度及迟到覆盖保护

**文件：**
- 修改：`backend/app/models/collector_sync_task.py`
- 修改：`backend/alembic/versions/20260805_0015_authoritative_daily_versions.py`
- 修改：`backend/app/collectors/scheduler.py`
- 修改：`backend/app/collectors/service.py`
- 修改：`backend/app/collectors/schemas.py`
- 测试：`backend/tests/test_fetch_scheduler.py`
- 测试：`backend/tests/test_ingestion_service.py`

- [ ] 增加失败测试：按账户时区在 D+1 05/06/07 各创建固定槽位任务，同槽位幂等，失败不阻止后续槽位。
- [ ] 增加失败测试：07:00 已发布后，05:00/06:00 迟到批次返回 409 且不改日报。
- [ ] 为日报任务增加可空 `authoritative_slot`（5、6、7；人工刷新为 8），创建任务时写入并在入库前比较已发布摘要的最大槽位。
- [ ] 删除“已有一次成功日报即永久跳过”的判断，改为逐槽位幂等判断。
- [ ] 运行 scheduler 与 ingestion 定向测试。

### 任务 5：人工权威日报刷新接口

**文件：**
- 修改：`backend/app/collectors/schemas.py`
- 修改：`backend/app/collectors/service.py`
- 修改：`backend/app/collectors/router.py`
- 测试：`backend/tests/test_collector_router.py`

- [ ] 增加失败测试：operator 鉴权、指定账户/日期创建 `report_fetch`、`idempotency_key` 幂等、存在活动任务返回 409。
- [ ] 实现 `POST /api/v1/operator/accounts/{account_id}/authoritative-daily-refresh`，人工任务槽位为 8，不复用小时 `manual-fetch`。
- [ ] 运行路由定向测试。

### 任务 6：六个小时接口统一北京时间窗口

**文件：**
- 修改：`backend/app/collectors/service.py`
- 测试：`backend/tests/test_collector_router.py`
- 测试：`backend/tests/test_ingestion_service.py`

- [ ] 增加失败测试：北京时间 00:00 映射前一 UTC 日 16:00、23:00 映射当日 UTC 15:00；六个接口均跨 UTC 日查询且无遗漏重复。
- [ ] 增加失败测试：返回 `report_date/hour` 按北京时间派生，`report_time_utc/source_timezone` 不变，total/分页/coverage 使用相同窗口。
- [ ] 实现共享 `_beijing_date_range_utc()` 并替换六个接口的源 `report_date` 过滤。
- [ ] 运行六接口契约测试。

### 任务 7：回归、文档与独立审阅

**文件：**
- 修改：`docs/system-maintainer-onboarding-guide.md`
- 创建：`docs/authoritative-daily-and-beijing-hourly-api-guide.md`

- [ ] 运行 backend 全量、collector 全量、Alembic upgrade/downgrade/upgrade、`git diff --check` 和凭据扫描。
- [ ] 编写 user_system 对接文档，只说明现有接口日期语义和日报同步时间，不修改 user_system。
- [ ] 更新维护台账：内容、原因、方案、后果、影响、测试、回滚、审阅、Git 和发布状态。
- [ ] 请求独立审阅；修复全部 P0/P1 并复审通过后才提交 Git。
- [ ] 不执行真实 Google 拉取、不推送 `master`、不部署，等待用户后续明确授权。
