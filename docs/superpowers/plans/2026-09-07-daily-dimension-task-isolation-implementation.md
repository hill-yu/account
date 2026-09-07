# 权威维度日报独立任务实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪；因仓库 `AGENTS.md` 要求代码先独立审阅再提交，本计划在审阅通过前不提交实现中间态。

**目标：** 将权威维度日报从核心日报中拆为可人工触发、可受控自动调度、可独立失败和入库的任务，并只对 `ahzhhj.com` 做首批生产灰度。

**架构：** 新任务 `report_fetch_daily_dimension` 只产生 `admanager_daily_dimension_v1`；核心 `report_fetch` 只产生 `admanager_site_core_v1`。控制面以默认空 allowlist 控制自动维度任务，要求业务日成熟、核心日报成功且同日没有任何维度尝试；自动失败不重建，人工入口可重试。

**技术栈：** FastAPI、Pydantic v2、SQLAlchemy 2、SQLite、Google Ad Manager SOAP、pytest、systemd。

---

## 文件职责

- 修改 `collector/app/fetcher.py`：按三个报表任务类型显式分派，隔离核心和维度。
- 修改 `collector/tests/test_fetcher.py`：覆盖核心/维度独立、异常隔离与未知任务。
- 修改 `backend/app/config.py`：增加默认空的维度账号 allowlist。
- 修改 `backend/app/collectors/fetch_policy.py`：把人工维度日报归入人工拉数 policy。
- 修改 `backend/app/collectors/service.py`：维度任务查找/创建、人工触发、自动尝试判定及 OAuth 失败处理。
- 修改 `backend/app/collectors/schemas.py`、`router.py`：增加人工维度拉取响应和独立端点。
- 修改 `backend/app/collectors/scheduler.py`：核心成功后为 allowlist 账号创建一次维度任务。
- 修改 `backend/tests/test_collector_router.py`、`test_fetch_scheduler.py`、`test_fetch_policy.py`、`test_oauth_service.py`：控制面红绿测试。
- 更新 `docs/system-maintainer-onboarding-guide.md`、`docs/问题记录.md`：记录实现、审阅、Git、备份、灰度、验证与回滚。

## 任务 1：采集任务严格分派

- [ ] 修改 `collector/tests/test_fetcher.py`，先把旧双 batch 测试改成两个红灯：`report_fetch` 期望仅核心 schema 且维度调用为 0；`report_fetch_daily_dimension` 期望仅维度 schema 且核心调用为 0。Fake service 分别记录 `core_calls` 和 `daily_dimension_calls`。
- [ ] 新增 `test_admanager_soap_fetcher_rejects_unknown_report_task`，断言未知任务抛 `ValueError("Unsupported report task type")`。
- [ ] 运行：`python -m pytest collector/tests/test_fetcher.py -q`。预期至少维度独立任务和核心隔离测试因现有双 batch 行为失败；失败必须是行为断言，不是收集错误。
- [ ] 最小修改 `collector/app/fetcher.py`：

```python
if task.task_type == "report_fetch":
    rows = self._service.fetch_site_daily_report(...)
    batch = self._service.build_fetch_batch(rows=rows)
elif task.task_type == "report_fetch_daily_dimension":
    rows = self._service.fetch_site_daily_dimension_report(...)
    batch = self._service.build_daily_dimension_fetch_batch(rows=rows)
else:
    raise ValueError(f"Unsupported report task type: {task.task_type}")
return () if batch is None else (batch,)
```

- [ ] 重跑 `collector/tests/test_fetcher.py -q`，预期全通过；再运行 `collector/tests/test_runtime.py -q`，确认 runtime 任务失败边界未回归。

## 任务 2：控制面人工维度任务

- [ ] 在 `backend/tests/test_collector_router.py` 先写红灯，覆盖端点 `/api/v1/operator/fetch-schedules/manual-daily-dimension-fetch`：成熟且核心成功时创建 `report_fetch_daily_dimension` 并启动对应实例 runtime；active 任务复用；既有 failed 任务允许新建；未成熟、核心未成功、实例不匹配分别返回 409/400。
- [ ] 在 `backend/tests/test_fetch_policy.py` 写红灯，证明 `manual_fetch_enabled=false` 拒绝 `manual_daily_dimension`。
- [ ] 运行精确测试节点，预期因端点/函数不存在返回 404 或断言失败。
- [ ] 在 `backend/app/collectors/fetch_policy.py` 将 `manual_daily_dimension` 加入 `MANUAL_FETCH_KINDS`。
- [ ] 在 `backend/app/collectors/schemas.py` 增加：

```python
class ManualDailyDimensionFetchResponse(BaseModel):
    ok: bool
    status: str
    request_id: str
    dimension_sync_task_id: int
    dimension_sync_task_status: str
    dimension_sync_task_created: bool
```

- [ ] 在 `backend/app/collectors/service.py` 增加 `_find_active_daily_dimension_sync_task`、`has_daily_dimension_attempt`、`_get_or_create_daily_dimension_sync_task`、`_create_daily_dimension_sync_task` 和 `trigger_manual_daily_dimension_fetch`。成熟时间必须复用 `is_authoritative_daily_ready`；核心前置必须复用 `has_successful_authoritative_daily_fetch`；任务凭据版本必须复用 `_active_credential_version_for_task`。
- [ ] 在 `backend/app/collectors/router.py` 增加独立 POST 端点，使用既有 timeout/direct-collector 设置，不修改原 `/manual-fetch`。
- [ ] 把 `report_fetch_daily_dimension` 加入 `complete_task` 的 OAuth refresh revoked 数据任务集合。
- [ ] 重跑上述精确测试，预期全通过。

## 任务 3：默认关闭的自动维度调度

- [ ] 在 `backend/tests/test_fetch_scheduler.py` 写红灯，覆盖：默认空 allowlist 不创建维度任务；allowlist 账号在成熟且核心成功后创建一个维度任务；无核心成功不创建；任意 succeeded/failed/pending/in_progress 维度尝试都不自动重复；非 allowlist 账号不创建。
- [ ] 运行新增测试，预期失败原因是配置字段或维度调度行为不存在。
- [ ] 在 `backend/app/config.py` 增加 `daily_dimension_account_keys: str = ""`。
- [ ] 在 `backend/app/collectors/scheduler.py` 解析去空格 allowlist。在现有最近三业务日循环内保持核心任务逻辑；只有核心成功时再检查 allowlist 和 `has_daily_dimension_attempt`，调用 `_get_or_create_daily_dimension_sync_task`，external id 使用 `auto-daily-dimension-{account_key}-{date}-{nonce}`。
- [ ] 确认一次 scheduler pass 每实例最多启动一次 runtime，且新增任务计入 processed。
- [ ] 重跑 `backend/tests/test_fetch_scheduler.py -q`，预期全通过。

## 任务 4：回归、文档与发布资产

- [ ] 运行 collector 全量：`python -m pytest collector/tests -q`。
- [ ] 运行 backend 全量：`python -m pytest backend/tests -q`。
- [ ] 运行 `python -m compileall -q backend/app collector/app`、`git diff --check`，检查无敏感值：`git diff | rg -i "client_secret|refresh_token|proxy_password|operator_api_token"` 只能出现既有字段名/测试占位符，不能出现生产值。
- [ ] 更新维护台账和问题记录，写清红灯、绿灯、影响范围、无 migration、测试结果、待审阅/待发布状态和精确回滚。

## 任务 5：独立审阅、整改与提交

- [ ] 以 `BASE_SHA=cc0e693` 和当前未提交 diff 请求独立审阅，覆盖任务隔离、scheduler 防重、人工重试、成熟门禁、OAuth、测试、无迁移、备份与回滚。
- [ ] 修复全部 P0/P1；每项修复必须先增加或调整失败测试，再最小实现，之后请求复审。P2 要么修复，要么在问题记录中说明不采纳理由和遗留风险。
- [ ] 复审结论必须为 P0=0、P1=0。
- [ ] 重新运行 collector/backend 全量测试、compileall、diff check 和敏感信息扫描。
- [ ] 更新台账审阅结论后，只暂存计划列出的代码、测试和治理文档；核对 staged 路径，再提交 `feat: isolate authoritative daily dimension tasks`。

## 任务 6：受控集成 master

- [ ] 验证正式 master worktree clean、与 `origin/master` ahead/behind=0；若不满足立即停止，不 stash/reset/覆盖。
- [ ] 在临时集成 worktree 或正式干净 master 上 `git merge --ff-only codex/daily-dimension-task-isolation`，重新运行全量测试与 compileall。
- [ ] fetch 后确认远端未移动，再 push `origin master`；记录最终提交号。服务器运行目录不是 Git，Git 推送本身不等于生产发布。

## 任务 7：生产保护点与单节点灰度

- [ ] 只读预检：确认目标运行文件 hash 仍匹配已知生产基线；`ahzhhj.com` 唯一账号/实例、真实 `report_account_key`、OAuth、代理、policy、最新成熟核心日报、无 active 任务；确认磁盘空间和真实 systemd unit。
- [ ] 停止 scheduler，等待 scheduler 进程和本项目临时 collector 子进程退出；Web 只在替换后端文件的最短窗口重启。
- [ ] 创建 `/srv/adx-account-isolated-collector/backups/<UTC>-pre-daily-dimension-isolation`，权限 0700；使用 Python sqlite3 backup API 备份真实 `backend/control_plane.db`，源库/备份库 `quick_check=ok`；复制目标文件、`.env`、unit 文本，保存 hash、服务/进程状态和脱敏 ahzhhj 写前快照，敏感副本 0600。
- [ ] 从已集成 master 的本地文件构建 staging；上传后逐文件 hash 与本地一致，再原子替换目标运行文件。原子更新 `.env`，仅设置 `ADX_COLLECTOR_DAILY_DIMENSION_ACCOUNT_KEYS=<现场实际 ahzhhj account key>`，不输出其他环境值。
- [ ] 运行 production venv `compileall`、`alembic current`/`upgrade head`（预期无新迁移）、启动 Web，验证 `/health`、journal、数据库 quick check，再启动 scheduler。
- [ ] 通过新人工端点只为 `ahzhhj.com` 最新成熟 Publisher 业务日创建一次维度任务；条件轮询至终态，不固定 sleep。
- [ ] 验证维度任务 succeeded、`admanager_daily_dimension_v1` batch 存在、账户/Site 维度事实大于 0、维度 API 返回；核心日报写前/写后全指标和更新时间未改变；其他账号新增维度任务数为 0；无任务风暴、服务 active、health 和 quick check 正常。
- [ ] 任一关键验证失败立即清空 allowlist、停止 scheduler并按规格恢复精确文件和 `.env`；恢复后验证 hash、compileall、health、服务和 quick check。不得整库恢复。
- [ ] 将真实结果、保护点、hash、任务/batch/事实证据、回滚状态和发布范围追加到两份治理文档，提交并推送文档闭环；除非用户另行授权，不扩大其他节点。
