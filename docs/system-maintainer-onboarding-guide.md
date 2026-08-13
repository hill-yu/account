# 中台系统维护接手指南

版本：2.0  
更新日期：2026-08-02  
适用项目：`adx-mid-platform` / `adx-account-isolated-collector`  
适用对象：新接手维护的后端、运维、数据排查同事

## 1. 这份文档解决什么问题

这份文档是新同事接手系统的总入口。目标不是替代已有 SOP，而是告诉接手人：

1. 应该先从哪里读起。
2. 每个目录、模块、代码文件大致负责什么。
3. 一次数据拉取从调度到入库经过哪些环节。
4. 常见运维动作应该查哪些表、看哪些服务、跑哪些命令。
5. 修改代码前应该先看哪些测试和文档。

读完本文后，新同事应该可以做到：

- 看懂控制面、节点运行时、前端控制台之间的关系。
- 根据账号节点名定位账号、实例、OAuth、代理、schedule、任务和报表数据。
- 判断小时数据和权威日报数据分别来自哪里。
- 独立完成一次授权失效排查、节点重授权、小时补跑和结果验证。
- 知道改某个功能时应该改哪些文件、跑哪些测试。

## 1.1 强制开发治理流程（所有功能与代码改动）

本节是本仓库所有后续开发任务的第一原则，适用于修复、重构、新功能、配置与数据库结构变更；不得因改动很小而省略。项目根目录的 `AGENTS.md` 会将这些要求带入每个新的开发任务。本节与该文件末尾的“功能/代码变更记录”共同构成唯一的维护台账。

### 必经顺序

```text
明确需求与影响范围
  -> 阅读现状代码、测试和相关 SOP，形成实施方案
  -> 本地隔离修改
  -> 独立审阅修改后的代码（通过后才可进入集成/真实账号测试）
  -> 本地自动化测试与必要的人工验证
  -> 更新本指南中的变更记录
  -> 提交 Git（提交内容须包含代码、测试、迁移和文档）
  -> 发布前检查、灰度发布、生产验证与回滚准备
```

1. **先说明再改动。** 每一次功能或代码变更必须先有可追溯的修改说明，至少写明：变更内容、修改原因、实施方案、预期结果与可能后果、影响范围、回滚方式、验证标准。
2. **本地修改和测试优先。** 不直接在生产服务器编辑源码。先在本地完成最小范围修改，并运行与改动对应的自动化测试；跨模块改动必须补充回归测试。
3. **Google 数据拉取的真实测试受控执行。** 涉及 OAuth、代理、Google Ad Manager SOAP、采集 runtime、实际报表拉取或任务调度的测试，必须在开始前明确指定一个已授权的测试账号和与其绑定的测试代理。未经明确授权，不得用生产账号、生产代理或批量调度做探测性测试；测试结束后核验任务、batch 与报表数据，并清理或标记测试产生的补跑任务。
4. **独立审阅在测试、提交和部署之前。** 代码完成后必须由未参与本次实现的独立审阅者（人员或独立审阅任务）审阅差异、测试覆盖、迁移、错误处理和安全边界。只有结论为“无阻塞问题”或全部阻塞问题已修复并复审通过，才可以进行集成/真实账号测试、Git 提交和部署。审阅结论与证据必须记入变更记录。
5. **先提交 Git，后部署。** 部署前，所有发布改动（含代码、测试、迁移、配置样例和本指南记录）必须已提交到 Git，且提交号写入变更记录。禁止以未提交的工作区内容发布；禁止把密码、Token、OAuth 回调、代理完整凭据或生产数据提交到仓库。
6. **生产变更可验证、可回滚。** 发布前确认备份、数据库迁移顺序、灰度范围、健康检查、回滚命令和负责人。发布后记录实际结果、异常与影响；若发生偏差，停止扩大范围并按回滚方案处置。

### 最小交付物清单

每个改动至少应具有：需求/问题链接或编号、实施方案、代码差异、相关测试及结果、独立审阅结论、本文第 22 节的变更记录、Git 提交号，以及（如发布）发布与验证记录。数据库结构变更还必须包含 Alembic migration、升级/降级验证和备份说明。

## 2. 推荐阅读顺序

不要一上来就从代码开始读。这个项目的生产行为和运维规则很重要，建议按下面顺序上手。

### 第一天：理解系统怎么跑

1. 先读本文。
2. 读 `docs/production-operations-and-development-sop.md`  
   重点看：生产路径、服务名、数据库、灰度名单、停拉名单、小时任务、权威日报、排障 SQL。
3. 读 `docs/standard-node-onboarding-and-proxy-fetch-sop.md`  
   重点看：新节点接入、OAuth 重授权、代理、节点库、schedule、灰度。
4. 读 `README.md`  
   用它建立最初的仓库结构印象，但注意 README 有些内容偏早期 MVP，生产逻辑以 SOP 和当前代码为准。

### 第二天：理解数据链路

1. 读 `backend/app/collectors/service.py`
2. 读 `backend/app/collectors/scheduler.py`
3. 读 `backend/app/collectors/ingestion_service.py`
4. 读 `collector/app/runtime.py`
5. 读 `collector/app/fetcher.py`
6. 读 `collector/app/admanager_soap.py`

读的时候围绕这两个链路看：

```text
小时实时链路：
FetchSchedule
  -> FetchScheduler
  -> report_fetch_hourly task
  -> collector runtime
  -> Google Ad Manager SOAP hourly report
  -> collector batch callback
  -> account_hourly_reports / site_hourly_reports

权威日报链路：
gray account list
  -> FetchScheduler authoritative daily scan
  -> report_fetch task
  -> collector runtime
  -> Google Ad Manager SOAP daily report
  -> collector batch callback
  -> account_daily_reports / site_daily_reports
```

### 第三天：能做日常维护

1. 在只读模式下查一次当前灰度名单。
2. 查一次所有灰度节点的 schedule 状态。
3. 查一次最近 24 小时小时任务状态。
4. 查一次最近业务日权威日报状态。
5. 找一个已成功节点，追踪它从任务到 batch 再到报表表的完整记录。

### 第四天以后：再开始改代码

改代码前至少要知道：

- FastAPI 路由在哪里。
- 核心业务服务在哪里。
- 调度器在哪里。
- 入库投影在哪里。
- ORM 模型和 Alembic migration 在哪里。
- 对应测试文件在哪里。

## 3. 系统全景

本系统是一个账号隔离的数据拉取平台。每个 Ad Manager 账号对应一个独立节点运行环境，独立 OAuth、独立代理、独立节点 MySQL。中台控制面负责管理账号、任务、调度、入库和对外查询。

### 3.1 主要组件

```text
user_system
  -> 中台公开 API
  -> backend FastAPI control plane
  -> SQLite control_plane.db

backend scheduler
  -> 创建小时任务 / 权威日报任务
  -> 启动 collector runtime

collector runtime
  -> 从 control plane 获取任务
  -> 用节点 OAuth + 节点代理访问 Google Ad Manager
  -> 把 batch 回传 control plane

collector node service
  -> 每个节点独立 FastAPI 服务
  -> 提供 /health
  -> 提供 /public/fetch.php 和 /public/report.php 兼容入口
  -> 使用独立 MySQL adx_data_<account_key>
```

### 3.2 生产中最重要的事实

1. 小时报表用于实时观察，不是权威日报来源。
2. 权威日报必须由 Google Ad Manager 完整日报重新拉取。
3. 中台日报 API 应返回中台本地已入库的权威日报。
4. 拉取 Google 数据必须走账号绑定代理。
5. 停拉名单优先级高于灰度名单。
6. 在灰度名单中不等于小时自动拉取已开启；小时自动拉取还要看 `fetch_schedules.enabled`。
7. 自动权威日报扫描使用灰度名单作为候选范围，并排除停拉名单。

## 4. 仓库目录职责

| 目录 | 职责 |
|---|---|
| `backend/` | 中台控制面。FastAPI、SQLAlchemy、调度器、任务、OAuth、入库、对外 API。 |
| `collector/` | 节点运行时和节点 API。负责真实访问 Google Ad Manager，提交 batch。 |
| `frontend/` | 运维控制台。React + Vite，用于账号、OAuth、实例、代理、任务、报表查询。 |
| `deploy/` | 部署资产。Docker、systemd、Nginx、PHP 兼容入口、节点 env 示例。 |
| `docs/` | 运维 SOP、节点接入 SOP、历史设计、排障记录、交接文档。 |
| `scripts/` | 一次性或辅助脚本，例如本地虚拟流、同步生产数据、迁移小时字段。 |
| `outputs/` | 运行中导出的分析结果，不属于核心代码。 |
| `tmp/` / `tmp_*.py` | 临时排查脚本。只能作为参考，不能当作长期接口。 |

## 5. 核心概念

### 5.1 Account

控制面里的账号。关键字段：

- `accounts.id`
- `accounts.name`
- `accounts.external_account_id`
- `accounts.timezone`
- `accounts.status`

生产中 `external_account_id` 通常是 Google Ad Manager network code。

### 5.2 CollectorInstance

一个账号对应的采集实例。关键字段：

- `collector_instances.id`
- `collector_instances.account_id`
- `collector_instances.report_account_key`
- `collector_instances.report_base_url`
- `collector_instances.report_token`
- `collector_instances.instance_token`
- `collector_instances.status`

运维时通常用 `report_account_key` 定位节点，例如：

```text
domeband
liberatedu
reboroots
```

### 5.3 OAuthAppConfig

Google OAuth 配置和授权状态。关键字段：

- `client_id`
- `client_secret`
- `redirect_uri`
- `authorization_status`
- `authorization_state`
- `refresh_token`
- `refresh_token_updated_at`
- `access_token_expires_at`

重授权时只更新已有 OAuth 配置，不创建重复 account 或 instance。

### 5.4 ProxyBinding

账号绑定代理。真实拉数必须走代理，不能失败后降级直连。

### 5.5 FetchSchedule

小时自动调度配置。关键字段：

- `enabled`
- `mode`
- `interval_hours`
- `next_run_at`
- `last_triggered_at`
- `last_trigger_status`
- `last_trigger_message`

灰度节点要自动每小时拉实时数据，必须满足：

```text
report_account_key 在 TARGETED_BACKFILL_ACCOUNT_KEYS
且不在停拉排除名单
且 fetch_schedules.enabled = true
且 fetch_schedules.interval_hours = 1
```

### 5.6 CollectorSyncTask

中台任务表。任务类型：

- `report_fetch_hourly`：小时实时任务
- `report_fetch`：权威日报任务

任务状态：

- `pending`
- `in_progress`
- `succeeded`
- `failed`
- `cancelled`
- `blocked`

### 5.7 CollectorIngestionBatch

collector 回传的 batch 元数据。排查时用它判断任务是否真的上传过数据。

### 5.8 报表事实表

小时事实表：

- `account_hourly_reports`
- `site_hourly_reports`

权威日报事实表：

- `account_daily_reports`
- `site_daily_reports`

注意：日报表里可能曾经存在小时投影或历史数据，判断权威日报是否完成时，要结合成功的 `report_fetch` 任务，而不是只看 `account_daily_reports` 有无数据。

## 6. Backend 文件导览

### 6.1 应用入口与配置

| 文件 | 作用 | 维护关注点 |
|---|---|---|
| `backend/app/main.py` | FastAPI 控制面入口。注册 CORS、`/health`、collector 路由；Web ASGI 默认不启动 scheduler。 | 如果服务启动或健康检查异常，先看这里；调度问题看独立 `app.scheduler_main` 和 scheduler systemd 服务。 |
| `backend/app/config.py` | 控制面配置。数据库 URL、超时、应用名等。 | 生产配置变更和本地环境差异从这里入手。 |
| `backend/app/database.py` | SQLAlchemy engine、session factory、Base。 | SQLite timeout、连接参数、测试库配置都与这里有关。 |

### 6.2 Collector 控制面模块

| 文件 | 作用 | 维护关注点 |
|---|---|---|
| `backend/app/collectors/router.py` | FastAPI 路由层。operator API、collector callback、OAuth callback、报表 API 都在这里注册。 | 对外 API 行为变更先找路由，再跳 service。 |
| `backend/app/collectors/service.py` | 控制面核心业务逻辑。账号、实例、任务、schedule、灰度名单、停拉名单、手动拉取、报表查询、runtime 启动。 | 最重要文件之一。改灰度、停拉、任务创建、报表返回语义都要看这里。 |
| `backend/app/collectors/scheduler.py` | 定时调度器。扫描 `fetch_schedules` 创建小时任务，扫描灰度账号创建权威日报任务，回收 stale in_progress 任务。 | 小时自动任务、权威日报自动任务、卡住任务回收问题看这里。 |
| `backend/app/collectors/ingestion_service.py` | batch 入库投影。把 collector 回传的 batch 写入小时表或日报表。 | 数据入库失败、422、字段缺失、SQLite 写锁重点看这里。 |
| `backend/app/collectors/oauth_service.py` | OAuth 授权 URL、callback code 兑换、refresh token 保存。 | 节点重授权、redirect_uri mismatch、invalid_grant 看这里。 |
| `backend/app/collectors/security.py` | collector token 鉴权。 | callback 被拒绝或 instance token 异常看这里。 |
| `backend/app/collectors/schemas.py` | Pydantic 请求/响应 schema。 | API 字段变更、响应兼容性、422 校验错误看这里。 |
| `backend/app/collectors/__init__.py` | Python package 标记。 | 通常不需要改。 |

### 6.3 Backend ORM 模型

| 文件 | 表 | 作用 |
|---|---|---|
| `backend/app/models/account.py` | `accounts` | 账号主表。 |
| `backend/app/models/collector_instance.py` | `collector_instances` | 节点实例、回调 token、节点 report 配置。 |
| `backend/app/models/oauth_app_config.py` | `oauth_app_configs` | Google OAuth client、state、token。 |
| `backend/app/models/proxy_binding.py` | `proxy_bindings` | 账号代理绑定。 |
| `backend/app/models/fetch_schedule.py` | `fetch_schedules` | 自动小时调度配置。 |
| `backend/app/models/collector_sync_task.py` | `collector_sync_tasks` | 中台任务表。 |
| `backend/app/models/collector_sync_log.py` | `collector_sync_logs` | 任务日志。 |
| `backend/app/models/collector_ingestion_batch.py` | `collector_ingestion_batches` | batch 元数据和 payload hash。 |
| `backend/app/models/account_hourly_report.py` | `account_hourly_reports` | 账户小时事实表。 |
| `backend/app/models/site_hourly_report.py` | `site_hourly_reports` | 站点小时事实表。 |
| `backend/app/models/account_daily_report.py` | `account_daily_reports` | 账户权威日报事实表。 |
| `backend/app/models/site_daily_report.py` | `site_daily_reports` | 站点权威日报事实表。 |
| `backend/app/models/__init__.py` | - | 导入模型，保证 Alembic / metadata 能发现表。 |

### 6.4 Alembic migration

| 文件 | 作用 |
|---|---|
| `backend/alembic/env.py` | Alembic 环境入口，绑定 SQLAlchemy metadata。 |
| `backend/alembic/script.py.mako` | migration 模板。 |
| `backend/alembic/versions/*.py` | 表结构演进记录。 |

重要 migration：

- `20260522_0001_phase1_foundation.py`：基础账号、实例、任务等。
- `20260522_0002_oauth_authorization_state.py`：OAuth 授权状态。
- `20260608_0006_mid_platform_node_config.py`：中台节点 report 配置。
- `20260623_0008_add_fetch_schedules.py`：小时 schedule。
- `20260623_0009_hourly_fact_timezone_dimensions.py`：小时事实表时区维度。
- `20260626_0010_add_requests_metric_columns.py`：requests 指标。

### 6.5 Backend 测试

| 文件 | 覆盖范围 |
|---|---|
| `backend/tests/test_collector_router.py` | API 路由、operator 操作、collector callback、报表接口。 |
| `backend/tests/test_fetch_scheduler.py` | 自动小时调度、权威日报调度、灰度/排除名单、stale 任务回收。 |
| `backend/tests/test_ingestion_service.py` | batch 入库、小时/日报投影、幂等。 |
| `backend/tests/test_oauth_service.py` | OAuth URL、callback、token 兑换逻辑。 |
| `backend/tests/test_models.py` | ORM 模型基础关系。 |
| `backend/tests/test_database.py` | DB 初始化和连接。 |
| `backend/tests/test_virtual_flow_script.py` | 本地虚拟端到端流程。 |

改后端常见测试命令：

```bash
cd backend
python -m pytest tests/test_fetch_scheduler.py -q
python -m pytest tests/test_ingestion_service.py -q
python -m pytest tests/test_collector_router.py -q
```

## 7. Collector 文件导览

### 7.1 一次性 runtime

| 文件 | 作用 | 维护关注点 |
|---|---|---|
| `collector/app/main.py` | 一次性 collector runtime 入口。获取 runtime config，执行一个任务。 | 控制面启动子进程、任务消费问题看这里。 |
| `collector/app/runtime.py` | CollectorRuntime 主流程。领取任务、调用 fetcher、上传 batch、回写状态。 | 任务卡在 pending/in_progress、batch 未上传、状态未回写看这里。 |
| `collector/app/control_plane_client.py` | 调用控制面 API 的客户端。 | 控制面连接失败、认证失败、callback 失败看这里。 |
| `collector/app/config.py` | runtime 配置和 bootstrap 配置。 | env、runtime config 字段变化看这里。 |
| `collector/app/models.py` | runtime 内部数据结构。 | 控制面 config 到 runtime settings 的映射看这里。 |

### 7.2 Google 拉取实现

| 文件 | 作用 | 维护关注点 |
|---|---|---|
| `collector/app/fetcher.py` | fetcher 选择器。按 task type 调用小时或日报 fetch。 | 新增 fetch mode 或改小时/日报分流看这里。 |
| `collector/app/admanager_soap.py` | Google Ad Manager SOAP 报表定义、下载、CSV 解析。 | 报表字段、维度、指标、Google 返回异常看这里。 |
| `collector/app/admanager_api.py` | 早期 REST/Beta API fetcher。 | 目前生产主链路多用 SOAP，维护时先确认是否仍被使用。 |
| `collector/app/adx_report_service.py` | 报表服务封装。把 SOAP rows 转为 batch rows。 | batch 格式、日报/小时字段映射看这里。 |
| `collector/app/oauth.py` | 用 refresh token 获取 access token。 | `invalid_grant`、token expired、代理下 token 刷新失败看这里。 |
| `collector/app/proxy.py` | 代理配置结构。 | SOCKS/HTTP 代理格式和请求配置看这里。 |
| `collector/app/egress.py` | 出口 IP 检查。 | 代理出口 IP 不匹配看这里。 |

### 7.3 节点常驻 API

| 文件 | 作用 | 维护关注点 |
|---|---|---|
| `collector/app/vps_api.py` | 每个节点的 FastAPI 服务。提供 `/health`、`/public/fetch.php`、`/public/report.php`、`/internal/fetch`。 | 节点服务健康、PHP 兼容入口、节点 snapshot 查询看这里。 |
| `collector/app/vps_config.py` | 节点 API env 配置。 | `ADX_VPS_DATABASE_URL`、端口、trigger token 看这里。 |
| `collector/app/vps_database.py` | 节点 MySQL session factory。 | 节点库连接问题看这里。 |
| `collector/app/vps_models.py` | 节点 MySQL ORM。`adx_accounts`、`adx_fetch_runs`、`adx_site_daily_reports`。 | 节点库 schema、运行状态、snapshot 表看这里。 |
| `collector/app/vps_repository.py` | 节点库读写封装。 | fetch run 状态、site rows 查询看这里。 |
| `collector/app/vps_service.py` | 节点 API 业务逻辑。创建/执行 fetch run，写节点库 snapshot。 | 节点 `/ke/fetch.php` 返回失败、active run 冲突看这里。 |
| `collector/app/vps_proxy_resolver.py` | 从节点库解析代理配置。 | 节点真实拉数代理是否生效看这里。 |

### 7.4 Collector 测试

| 文件 | 覆盖范围 |
|---|---|
| `collector/tests/test_runtime.py` | 一次性 runtime 主流程。 |
| `collector/tests/test_fetcher.py` | fetcher 分流和 batch 生成。 |
| `collector/tests/test_admanager_soap.py` | SOAP 查询和 CSV 解析。 |
| `collector/tests/test_adx_report_service.py` | 报表服务字段映射。 |
| `collector/tests/test_oauth.py` | OAuth refresh token 刷新。 |
| `collector/tests/test_proxy.py` | 代理配置。 |
| `collector/tests/test_vps_api.py` | 节点 API。 |
| `collector/tests/test_vps_service.py` | 节点 fetch run 生命周期。 |
| `collector/tests/test_vps_models.py` | 节点 ORM。 |

常用测试命令：

```bash
cd collector
python -m pytest tests/test_runtime.py tests/test_fetcher.py tests/test_admanager_soap.py -q
python -m pytest tests/test_vps_api.py tests/test_vps_service.py -q
```

## 8. Frontend 文件导览

前端是运维控制台，不是 user_system。维护重点是帮助 operator 创建账号、OAuth、实例、代理、任务，并查看报表。

| 文件 | 作用 |
|---|---|
| `frontend/src/main.tsx` | React 入口。 |
| `frontend/src/App.tsx` | 应用根组件。 |
| `frontend/src/router.tsx` | 页面路由。 |
| `frontend/src/pages/OperationsPage.tsx` | 运维操作页，聚合账号、OAuth、实例、代理、任务、schedule。 |
| `frontend/src/pages/ReportsPage.tsx` | 报表查看页。 |
| `frontend/src/pages/OAuthCallbackPage.tsx` | 前端 OAuth callback 页面。 |
| `frontend/src/lib/api.ts` | 调用后端 API 的封装。 |
| `frontend/src/lib/errorMessages.ts` | 错误信息显示。 |
| `frontend/src/lib/format.ts` | 格式化函数。 |
| `frontend/src/lib/oauth.ts` | OAuth 前端辅助逻辑。 |
| `frontend/src/lib/operatorGuidance.ts` | 操作提示文案。 |
| `frontend/src/types/api.ts` | 前端 API 类型。 |
| `frontend/src/styles.css` | 全局样式。 |

功能组件：

| 文件 | 作用 |
|---|---|
| `frontend/src/features/accounts/AccountsSection.tsx` | 账号管理。 |
| `frontend/src/features/oauth/OAuthAppsSection.tsx` | OAuth app 和授权。 |
| `frontend/src/features/instances/InstancesSection.tsx` | collector instance 管理。 |
| `frontend/src/features/proxies/ProxiesSection.tsx` | 代理绑定。 |
| `frontend/src/features/tasks/TasksSection.tsx` | 任务查看和创建。 |
| `frontend/src/features/fetch/FetchSchedulesSection.tsx` | 小时 schedule 管理。 |
| `frontend/src/features/reports/AccountDailySection.tsx` | 账户日报展示。 |
| `frontend/src/features/reports/SiteDailySection.tsx` | 站点日报展示。 |
| `frontend/src/features/reports/NodeResultsSection.tsx` | 节点结果展示。 |
| `frontend/src/features/reports/SummarySection.tsx` | 汇总展示。 |

UI 组件：

| 文件 | 作用 |
|---|---|
| `frontend/src/components/layout/AppShell.tsx` | 页面框架。 |
| `frontend/src/components/ui/CopyButton.tsx` | 复制按钮。 |
| `frontend/src/components/ui/Field.tsx` | 字段显示。 |
| `frontend/src/components/ui/SectionCard.tsx` | 区块容器。 |
| `frontend/src/components/ui/StatusBadge.tsx` | 状态标签。 |
| `frontend/src/components/ui/ToastProvider.tsx` / `useToast.ts` | toast 提示。 |

前端测试：

| 文件 | 覆盖范围 |
|---|---|
| `frontend/src/__tests__/oauth.test.ts` | OAuth 前端流程。 |
| `frontend/src/__tests__/errorMessages.test.ts` | 错误信息。 |
| `frontend/src/__tests__/format.test.ts` | 格式化。 |
| `frontend/src/__tests__/operatorGuidance.test.ts` | 运维提示文案。 |

常用命令：

```bash
cd frontend
npm install
npm run test
npm run build
```

## 9. Deploy 文件导览

| 文件 | 作用 |
|---|---|
| `deploy/docker-compose.yml` | 本地 Docker 编排。 |
| `deploy/backend/Dockerfile` | backend 镜像。 |
| `deploy/collector/Dockerfile` | collector 镜像。 |
| `deploy/README.md` | 本地部署说明。 |
| `deploy/vps/README.md` | VPS 节点部署说明。 |
| `deploy/vps/systemd/adx-fetch-api.service` | 节点 systemd 服务模板。 |
| `deploy/vps/env/adx-fetch-api.env.example` | 节点 env 示例。 |
| `deploy/vps/cron/run-fetch.sh` | 早期 cron 拉取脚本。生产当前主要由中台 schedule 触发。 |
| `deploy/vps/cron/adx-fetch-cron.env.example` | cron env 示例。 |
| `deploy/vps/php/fetch.php` | PHP 兼容 fetch 入口。 |
| `deploy/vps/php/report.php` | PHP 兼容 report 入口。 |
| `deploy/vps/php/oauth-callback-download.php` | OAuth callback 下载 JSON 辅助页。 |
| `deploy/vps/nginx/api.example.conf` | Nginx 示例。 |
| `deploy/vps/sql/single-account-node-template.sql.example` | 节点 MySQL 初始化示例。 |

## 10. Scripts 文件导览

| 文件 | 作用 |
|---|---|
| `scripts/virtual_flow.py` | 本地虚拟端到端流程，不依赖真实 Google。适合新同事体验任务生命周期。 |
| `scripts/init_vps_schema.py` | 初始化节点 MySQL schema。 |
| `scripts/migrate_hourly_timezone.py` | 小时时区字段迁移辅助脚本。 |
| `scripts/sync_prod_data_to_local.py` | 同步生产数据到本地排查。使用前注意敏感信息和目标库。 |

## 11. 关键生产路径和服务名

生产路径以 SOP 为准，当前常用路径：

```text
项目根目录：
/srv/adx-account-isolated-collector

控制面：
/srv/adx-account-isolated-collector/backend

控制面数据库：
/srv/adx-account-isolated-collector/backend/control_plane.db

节点 env：
/srv/adx-account-isolated-collector/deploy/vps/env/adx-fetch-api-<account_key>.env

节点代码：
/srv/adx-account-isolated-collector/collector
```

常用 systemd：

```text
adx-control-plane.service
adx-fetch-api-<account_key>.service
```

健康检查：

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:<node_port>/health
```

## 12. 常见数据排查路径

### 12.1 查一个节点的基础配置

核心对象：

- account
- collector instance
- OAuth app
- proxy binding
- fetch schedule

建议查询顺序：

```text
collector_instances.report_account_key
  -> account_id
  -> oauth_app_configs
  -> proxy_bindings
  -> fetch_schedules
```

### 12.2 查小时任务是否正常

看三层：

1. `collector_sync_tasks` 是否有 `report_fetch_hourly` 任务。
2. `collector_ingestion_batches` 是否有 batch。
3. `account_hourly_reports` / `site_hourly_reports` 是否有实际维度行。

注意：Google 返回 0 行时，任务可以是 succeeded，batch row_count 可以是 0，本地小时事实表不会凭空写 0 维度行。

### 12.3 查权威日报是否正常

看三层：

1. 是否存在成功的 `report_fetch` 任务。
2. 是否有 batch。
3. `account_daily_reports` / `site_daily_reports` 是否有本地权威日报结果。

不要只因为 `account_daily_reports` 有数据就判断权威日报已经正式完成；要结合 `report_fetch` 成功任务。

### 12.4 查授权失败

典型错误：

```text
invalid_grant: Token has been expired or revoked.
invalid_grant: Bad Request
redirect_uri_mismatch
```

处理路径：

1. 生成授权 URL。
2. 用户完成授权，返回完整 callback URL 或 callback JSON。
3. 确认 state 和 redirect_uri 与生产 OAuth app 匹配。
4. 兑换 code。
5. 更新控制面 OAuth。
6. 同步最新 refresh token 到节点 MySQL `adx_accounts`。
7. 重启节点服务。
8. 跑一次真实小时任务验证。

### 12.5 查任务卡住

判断标准：

- `pending` 超过 10 分钟需要关注。
- `in_progress` 超过 20 分钟需要排查。
- 2 小时以上 stale 任务应由 scheduler 自动标失败。

排查路径：

1. 查任务状态、created_at、started_at。
2. 查 `collector_sync_logs`。
3. 查是否有 runtime 进程。
4. 查 `adx-control-plane.service` 日志。
5. 查节点 service 是否健康。
6. 必要时把明确卡死的任务标 failed，并写日志说明。

## 13. 灰度名单、停拉名单和 schedule 的关系

当前代码名单在：

```text
backend/app/collectors/service.py
```

关键常量：

```python
TARGETED_BACKFILL_ACCOUNT_KEYS
INVALID_GRANT_DO_NOT_FETCH_ACCOUNT_KEYS
MANUAL_DO_NOT_FETCH_ACCOUNT_KEYS
AUTOMATIC_DAILY_FETCH_EXCLUDED_ACCOUNT_KEYS
```

规则：

| 状态 | 小时自动任务 | 权威日报自动任务 |
|---|---|---|
| 在灰度名单，schedule enabled | 会自动每小时创建小时任务 | 会参与权威日报扫描 |
| 在灰度名单，schedule disabled | 不会自动创建小时任务 | 会参与权威日报扫描 |
| 在停拉排除名单 | 不应拉取数据 | 不应参与自动日报 |
| 不在灰度名单 | 不参与灰度默认补跑 | 不参与自动日报扫描 |

如果业务目标是“进入灰度后自动每小时拉实时数据 + 自动权威日报”，需要同时确认：

```text
1. 节点在 TARGETED_BACKFILL_ACCOUNT_KEYS
2. 节点不在 AUTOMATIC_DAILY_FETCH_EXCLUDED_ACCOUNT_KEYS
3. fetch_schedules.enabled = true
4. fetch_schedules.interval_hours = 1
5. OAuth authorized 且 refresh token 可用
6. 节点 service /health ok
```

## 14. 修改代码时的定位指南

| 需求 | 优先看哪些文件 |
|---|---|
| 改 operator API | `backend/app/collectors/router.py`、`service.py`、`schemas.py`、`backend/tests/test_collector_router.py` |
| 改小时自动调度 | `backend/app/collectors/scheduler.py`、`service.py`、`backend/tests/test_fetch_scheduler.py` |
| 改权威日报自动调度 | `scheduler.py`、`service.py`、`backend/tests/test_fetch_scheduler.py` |
| 改 batch 入库 | `ingestion_service.py`、报表模型、`backend/tests/test_ingestion_service.py` |
| 改 OAuth | `oauth_service.py`、`schemas.py`、`backend/tests/test_oauth_service.py` |
| 改 Google 报表字段 | `collector/app/admanager_soap.py`、`adx_report_service.py`、`fetcher.py`、collector tests、backend ingestion tests |
| 改节点 API | `collector/app/vps_api.py`、`vps_service.py`、`vps_repository.py`、collector VPS tests |
| 改前端展示 | `frontend/src/features/*`、`frontend/src/lib/api.ts`、`frontend/src/types/api.ts` |
| 改数据库结构 | ORM model、Alembic migration、相关 tests、生产迁移 SOP |

## 15. 本地开发建议

### 15.1 后端

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
```

如果从仓库根目录跑后端测试出现 `No module named app`，切到 `backend/` 目录再跑。

### 15.2 Collector

```bash
cd collector
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
```

### 15.3 Frontend

```bash
cd frontend
npm install
npm run test
npm run build
```

## 16. 交接人应该提供哪些信息

把系统交给新同事时，至少提供：

1. 生产机器地址和登录方式。敏感信息不要写进 Git。
2. 当前控制面服务名和节点服务命名规则。
3. 当前灰度名单。
4. 当前停拉排除名单。
5. 当前 user_system 使用的中台 API。
6. 当前最近三天各灰度节点小时任务和权威日报状态。
7. 当前授权失效或待处理节点。
8. 当前本地未发布代码改动和生产已手工变更记录。
9. 最近一次数据库备份位置。
10. 最近一次线上发布文件清单。

## 17. 新同事上手练习任务

建议安排 5 个练习任务，由老同事旁路 review。

### 练习 1：只读巡检

目标：

- 查灰度名单。
- 查停拉名单。
- 查所有灰度节点 schedule。
- 查最近 24 小时小时任务。
- 查最近一个权威业务日的日报任务。

验收：

- 能列出异常节点和异常原因。
- 不做任何写操作。

### 练习 2：追踪一个成功小时任务

目标：

- 找一个成功 `report_fetch_hourly` task。
- 找到对应 batch。
- 找到对应 `account_hourly_reports` 和 `site_hourly_reports`。

验收：

- 能解释 batch row_count 和事实表 rows 的区别。

### 练习 3：处理一次授权失效

目标：

- 找到 `invalid_grant` 节点。
- 生成授权 URL。
- 导入 callback。
- 同步节点库。
- 跑真实任务验证。

验收：

- 控制面 OAuth authorized。
- 节点库 refresh token 已同步。
- 真实任务 succeeded。

### 练习 4：补跑两天小时数据

目标：

- 为指定节点补跑两个业务日小时数据。
- 避免撞旧失败任务的 `external_request_id`。
- 验证 batch 和本地事实表。

验收：

- 能说明 0 行成功和失败的区别。

### 练习 5：小改动带测试

目标：

- 改一个低风险行为，例如调整测试里的灰度样本。
- 跑对应测试。
- 写清楚改动影响。

验收：

- 测试通过。
- 不影响生产未授权节点。

## 18. 不要做的事

1. 不要把 SSH 密码、OAuth token、代理密码写进 Git。
2. 不要跳过备份直接改生产 SQLite。
3. 不要把停拉账号加入自动拉取流程。
4. 不要用小时表聚合结果冒充权威日报。
5. 不要在不了解 `external_request_id` 唯一约束时重复创建同名任务。
6. 不要看到 `authorization_status=authorized` 就假设 refresh token 一定可用；必须真实拉取验证。
7. 不要只看任务 succeeded 就认为有数据；还要看 batch row_count 和事实表。
8. 不要只改灰度名单却忘了 schedule。
9. 不要直接改生产代码后不重启服务。
10. 不要在 dirty worktree 里随手回滚别人的改动。

## 19. 最短接手路线

如果新同事只有半天时间，按这个最短路线：

1. 读本文第 1-5 节。
2. 读 `docs/production-operations-and-development-sop.md` 第 3-5 节。
3. 读 `backend/app/collectors/service.py` 顶部名单和任务相关函数。
4. 读 `backend/app/collectors/scheduler.py`。
5. 读 `backend/app/collectors/ingestion_service.py`。
6. 在生产只读查询一次：
   - 灰度名单
   - 停拉名单
   - schedule
   - 最近任务
   - 最近入库数据
7. 再开始接具体问题。

## 20. 文档地图

| 文档 | 什么时候读 |
|---|---|
| `docs/production-operations-and-development-sop.md` | 日常生产运维、巡检、排障、发布。 |
| `docs/standard-node-onboarding-and-proxy-fetch-sop.md` | 新节点接入、代理、OAuth、节点库、灰度。 |
| `docs/oauth-callback-json-workflow.md` | OAuth callback JSON 文件处理。 |
| `docs/2026-07-12-automatic-authoritative-daily-fetch-rollout.md` | 自动权威日报功能背景。 |
| `docs/2026-07-17-authoritative-daily-completion-fix.md` | 权威日报完成判定修复背景。 |
| `docs/2026-06-23-mid-platform-hourly-interface-contract-for-user-system.md` | user_system 对接小时接口时读。 |
| `docs/operator-notes.md` | 早期 operator 流程说明，可作为补充。 |
| `docs/new-node-onboarding-sop-template.md` | 老版节点接入模板，当前以 standard SOP 为准。 |

## 21. 接手后的维护原则

1. 先看生产事实，再下结论。
2. 先区分小时实时数据和权威日报。
3. 先查任务，再查 batch，再查事实表。
4. 先确认授权和代理，再判断 Google 是否无数据。
5. 先停住无效自动任务，再做重授权和补跑。
6. 任何生产写操作先备份、后执行、再验证。
7. 任何代码变更先补测试或更新测试，再发布。
8. 文档要跟着行为变化更新，尤其是灰度、停拉、权威日报规则。
9. 代码流固定为：从最新 `origin/master` 创建独立任务分支和 worktree → 本地测试 → 独立审阅 → Git 提交 → 受控合并或精确 cherry-pick 至 `master` → 新服务器从 `master` 同步 → 灰度验证。旧 `dev` 分支和 `D:\code\adx-mid-platform-oauth-remediation` 仅用于已有历史任务兼容，不再是新任务强制入口；不得从运行目录开发或以未提交内容部署。
10. 新服务器仅承担 `master` 发布运行；旧服务器已停止生产，仅可承担隔离测试，不得启用生产 scheduler、正式采集任务或生产数据库写入。

## 22. 功能/代码变更记录（追加式台账）

每次功能、代码、配置或数据库结构修改都必须在本节**追加**一条记录；不得覆盖历史记录。记录应在代码审阅通过、Git 提交和部署前补齐，发布后再补充实际验证结果。敏感信息只写标识或脱敏摘要，绝不写密码、Token、OAuth 回调内容、代理完整凭据或生产数据。

### 记录模板

```markdown
### YYYY-MM-DD — <变更标题>

- 状态：方案中 / 审阅中 / 已提交待发布 / 灰度中 / 已发布 / 已回滚
- 需求或问题：<链接、编号或简述>
- 变更内容：<修改了什么功能、代码路径、配置或数据结构>
- 修改原因：<为什么现在要改>
- 实施方案：<关键步骤、迁移顺序；涉及 Google 拉取时注明测试账号标识和代理标识，不记录凭据>
- 预期结果与实施后果：<预期行为、已知副作用、兼容性变化>
- 影响范围：<用户、接口、节点、任务、数据库表、服务、性能与安全影响>
- 验证与测试：<本地命令及结果；真实拉取测试的账号/代理标识、任务/batch/数据核验结果>
- 独立审阅：<审阅者或独立审阅任务、日期、结论、已处理问题；无阻塞问题后方可测试/提交/部署>
- Git：<分支、提交号；部署前必须已有提交>
- 发布与回滚：<灰度范围、发布时间、健康检查、回滚方案及实际结果>
```

### 2026-08-02 — 建立统一维护与开发治理规则

- 状态：审阅中
- 需求或问题：统一项目背景、架构、实施方案与后续维护开发规范。
- 变更内容：在本指南新增第 1.1 节强制开发治理流程和第 22 节追加式变更台账；新增仓库根目录 `AGENTS.md`，使后续任务默认遵守相同规则。
- 修改原因：确保新接手开发人员能够快速定位系统资料，并使每次功能变更在审阅、测试、Git 提交和部署前均有一致、可追溯的质量门禁。
- 实施方案：以本指南作为唯一维护总入口；以 `AGENTS.md` 作为任务启动约束；要求本地开发、受控 Google 测试、独立审阅、Git 提交和发布验证按固定顺序执行。
- 预期结果与实施后果：后续改动将增加必要的文档和审阅工作量，但能降低未审阅代码、未提交发布、凭据泄露及生产探测性测试的风险。
- 影响范围：影响本仓库全部后续开发与发布流程；不改变运行时代码、数据库结构或现有生产服务。
- 验证与测试：已核对指南中的系统架构、目录职责、关键链路、开发建议和文档地图均保留；已核对根目录规则指向本节并覆盖本次提出的全部强制要求。
- 独立审阅：待独立审阅；在该文档自身提交/发布前应完成独立审阅并将结论更新到此处。
- Git：待提交。
- 发布与回滚：无需运行时发布；若规则表述需调整，可通过后续 Git 提交修改文档并保留本条历史记录。
### 2026-08-02 — 形成 GAM Service Account PoC 设计与实施文档
- 状态：方案中
- 需求或问题：针对当前 GAM 拉数 refresh token 时效与恢复成本问题，评估并设计 Service Account PoC 落地路径。
- 变更内容：新增 `docs/superpowers/specs/2026-08-02-gam-service-account-poc-design.md` 和 `docs/superpowers/plans/2026-08-02-gam-service-account-poc-implementation.md`，明确当前项目基础上的 SA 可行性判断、推荐架构、风险、验证标准、实施任务和回滚原则。
- 修改原因：把“SA 是否值得做、如何做、做到什么边界、如何验证和回滚”沉淀成可评审、可执行文档，避免后续 PoC 在认证模型、真实测试门禁和 SOAP 生命周期判断上反复返工。
- 实施方案：基于当前仓库代码结构、既有 OAuth/SOAP 链路和维护治理规则，输出一份设计文档和一份实施计划；计划坚持 OAuth 现网不动、SA 仅做测试账号白名单 PoC、真实测试晚于独立审阅。
- 预期结果与实施后果：团队可以先评审文档再决定是否进入代码 PoC；短期会增加一套候选认证模型的设计复杂度，但能降低凭空开工或直接全量切换的风险。
- 影响范围：当前仅影响设计文档、实施计划和维护台账；不改变后端、节点、前端、数据库或生产服务行为。
- 验证与测试：已本地核对设计文档覆盖背景、目标、非目标、方案对比、推荐架构、安全约束、验证路径和回滚原则；已核对实施计划覆盖 schema、model、migration、collector、控制面、SOP、独立审阅和真实测试顺序。未运行自动化测试，因本次仅文档变更。
- 独立审阅：待独立审阅；进入任何代码实现或真实账号测试前，必须先对该设计与实施计划完成独立审阅并记录结论。
- Git：待提交。
- 发布与回滚：无需运行时发布；若评审后否决 SA PoC，可仅通过后续 Git 提交修订或归档文档，不涉及线上回滚。

### 2026-08-02 — 国家与广告单元维度明细报表

- 状态：独立审阅通过，待 Git 提交与发布审批。
- 需求或问题：为 `user_system` 新增国家 × 广告单元的小时明细和权威日报明细，并提供覆盖率、点击率、曝光率；历史数据不回补。
- 变更内容：新增两张权威日报维度事实表及迁移；采集端保留核心日报批次并新增独立维度日报批次；新增四个维度查询 API，支持筛选、单日或最长 31 天范围、稳定数据库分页与小时 UTC/源时区字段。
- 修改原因：现有聚合日报无法满足按国家和广告单元定位投放表现的需求。
- 实施方案：日报维度只使用上游权威日报；维度快照按账号、日期和来源替换；小时维度读取既有小时事实；分母为零的三项比率返回 `0.0`；维度首批写入不清除核心日报或小时汇总。
- 预期结果与实施后果：新增 API 不改变旧聚合 API 契约；数据库增加维度明细存储与受控范围查询负载，分页使用数据库 `COUNT(*)`、`OFFSET/LIMIT` 限制单次读取。
- 影响范围：控制面后端、collector、Alembic、维度报表 API 与 `user_system` 对接；不涉及历史数据回填或生产调度变更。
- 验证与测试：后端全量 `pytest tests -q` 141 通过；采集端全量 `pytest tests -q` 89 通过；覆盖双日报链、快照替换、小时汇总保留、筛选、范围、分页、三项比率和零分母。
- 独立审阅：第四轮独立审阅通过；快照误删小时汇总与内存分页问题均已通过 TDD 整改并复审关闭。
- Git：当前分支 `dev`，待提交；部署前必须完成提交并合并到 `master`。
- 发布与回滚：尚未部署或真实 Google 拉取。发布前须获得明确批准并提供指定测试账号与代理标识；回滚为停止新 API 使用、回退 `master` 至上一已验证提交，新增维度表不影响旧报表表。

### 2026-08-02 — 调度进程启动边界整改

- 状态：独立审阅通过，待提交与部署。
- 变更内容：Web ASGI 模块默认不启动 scheduler；新增独立 scheduler 入口及 Compose/systemd 部署定义，并以 backend 健康和 Alembic `head` 作为启动门禁。
- 修改原因：防止 Web 重启意外调度生产任务，同时防止 scheduler 在数据库迁移未完成时推进失败任务。
- 实施方案与影响：Web 服务仅提供 API；scheduler 由专用进程运行。该变更不修改报表数据和既有 API，但部署时必须同时安装 scheduler systemd unit。
- 验证与审阅：scheduler 专项测试 14 通过、后端全量 142 通过；独立审阅确认无未关闭 P0/P1。
- Git 与发布：待本条随代码提交；尚未部署。

### 2026-08-02 — 生产部署环境文件与 systemd 路径防护

- 状态：整改中，规则已落地，待随本次文档变更提交。
- 问题：同步运行目录时使用了未排除运行时文件的删除式同步，导致 `.env` 被删除；随后 scheduler 模板又引用了与实际服务器不一致的环境文件路径，造成控制面和 scheduler 启动失败。
- 整改措施：发布前备份 `control_plane.db`、`control_plane.db-wal`、`control_plane.db-shm`、`.env`、systemd unit 和运行目录清单；同步命令必须先以相同排除项 `--dry-run`，再执行正式同步，且显式排除 `.env`、三个 SQLite 文件、备份目录、虚拟环境。部署后按“环境文件存在且权限正确 → Alembic head → Web health → scheduler active → 节点心跳/任务”顺序验证。
- systemd 要求：以服务器实际 unit 为权威，逐项核对 `WorkingDirectory`、`EnvironmentFile`、`ExecStart`、运行用户和权限；scheduler 必须使用与 Web 相同的实际环境文件，并在启动前完成 schema-ready 门禁。
- 影响与回滚：本规则增加发布前检查步骤，但避免因配置覆盖导致 API 中断、scheduler 无法启动或任务被错误推进。若同步失败，先恢复 `.env` 和服务健康，再继续任何迁移或调度动作。
- 验证：本次已从迁移前备份恢复环境文件和 Operator Token，控制面健康恢复；scheduler 模板路径已修正为运行目录 `.env` 并成功启动。

### 2026-08-03 — 单一管理员登录会话支持

- 状态：已发布。
- 需求或问题：控制台没有安全的登录入口，前端无法使用 operator API；后台仅需要一个管理员。
- 变更内容：在 `backend/app/collectors/security.py` 增加服务端密钥控制的 HMAC 签名会话；在 `backend/app/collectors/router.py` 增加 login/logout/session 端点；控制台增加密码登录页、会话检查和退出登录。既有 `X-ADX-Operator-Token` 方式保留兼容。
- 修改原因：仅有控制台地址不能构成可靠鉴权，且前端没有注入 Operator Token 的能力，导致管理员无法完成日常操作。
- 实施方案：登录请求只在 HTTPS 提交一次 Operator Token，服务端使用常量时间比较验证并签发 12 小时 `HttpOnly`、`SameSite=Strict`、生产环境 `Secure` 的 Cookie。前端只发送同源 Cookie，不写入 localStorage、sessionStorage、打包配置或 Git。现有 OAuth callback 路由继续公开，不被前端登录门禁拦截。
- 预期结果与实施后果：管理员登录后可使用全部 operator 控制台功能；Token 轮换会使无状态会话失效，用户需重新登录；旧脚本调用不受影响。
- 影响范围：控制台和 `/api/v1/operator/*` 鉴权；不改变 Google 拉取、OAuth 凭证、采集运行时、调度、数据库或任务创建。
- 验证与测试：后端定向 `pytest tests/test_collector_router.py -q` 为 39 passed；后端全量 `pytest tests -q` 为 145 passed；前端全量 `npm test` 为 22 passed；前端 `npm run build` 成功；`git diff --check` 通过。
- 独立审阅：2026-08-03 独立审阅发现本地跨端口 Cookie 传递 P1 和畸形 Cookie P2，均已按 TDD 修复并复审通过；最终无 P0/P1。
- Git：功能提交 `ed12ef5`、文档提交 `aaf2a91`，已合并并推送至 `master` 提交 `efd2c7c`。
- 发布与回滚：2026-08-03 已发布至新服务器控制面。发布前在服务器创建了受限权限备份 `/srv/adx-account-isolated-collector/backups/20260803T032344Z-pre-single-admin-login`，其中含运行时代码、前端静态资源、SQLite 一致性备份、环境文件副本和 unit 清单；同步前的 dry-run 仅包含 7 个后端运行时文件及前端构建产物，未迁移数据库、未改动 `.env`、OAuth/代理或任务数据。发布后 `/health` 为 200，前端资源为 200，登录、会话、受保护 `/api/v1/operator/instances`、登出和登出后拒绝访问依次验证为 200/200/200/204/401，scheduler 保持 inactive。首次静态资源同步因暂存目录 `0700` 权限被 `rsync -a` 保留，Nginx 返回 403；已定位为发布工艺问题，按最小范围将 `frontend/dist` 目录设为 755、文件设为 644 后复验前端 200，并将该权限要求纳入本条记录。回滚为从上述备份还原 7 个后端文件和前端 `dist`，重启 `adx-control-plane` 后复验健康；不触碰 SQLite 或任务数据。

### 2026-08-03 — 维度报表日期范围错误响应兼容修复

- 状态：已发布。
- 需求或问题：后端全量回归显示维度报表超过 31 天的日期范围会因引用不存在的框架状态常量而抛出 500，未返回预期的 422。
- 变更内容：`backend/app/collectors/service.py` 的三个日期范围校验分支及 `backend/app/collectors/ingestion_service.py` 的六个批次输入校验分支，统一改用当前依赖提供的 `HTTP_422_UNPROCESSABLE_ENTITY`。
- 修改原因：保证无效的维度日期参数返回稳定的客户端错误，不将校验异常升级成服务器错误。
- 实施方案：不改动日期范围规则、批次规则、查询、数据表或 API 成功响应；只替换错误状态常量。先以现有失败全量测试定位，再扫描并清除同类不兼容常量，运行定向测试和全量后端回归。
- 预期结果与实施后果：无效日期范围和批次输入分支均返回 422；不影响有效日期范围、维度数据、采集任务或鉴权。
- 影响范围：四个维度查询 API 的无效日期参数及 collector 批次输入错误响应；无数据库、调度、任务或安全影响。
- 验证与测试：`tests/test_ingestion_service.py::test_hourly_dimension_batch_projects_hourly_facts_and_rebuilds_daily_rollups` 为 1 passed；后端全量 `pytest tests -q` 为 145 passed；`rg HTTP_422_UNPROCESSABLE_CONTENT backend/app` 无残留。
- 独立审阅：2026-08-03 两轮独立复审通过；无 P0/P1，且已确认同类不兼容常量无残留。
- Git：随单管理员登录功能提交 `ed12ef5`，已合并并推送至 `master` 提交 `efd2c7c`。
- 发布与回滚：2026-08-03 随同一控制面发布；未执行数据库迁移，不影响现有任务或数据。发布后控制面健康检查为 200。若需回滚，只还原这 9 处错误状态常量，不涉及数据恢复。

### 2026-08-03 — 服务器运行代码与 Git 基线一致性门禁

- 状态：已完成只读审计与独立审阅，待 Git 提交；本条不发布服务器代码。
- 需求或问题：防止服务器 Git 克隆、实际运行目录和本地开发基线不一致时，被本地发布覆盖而丢失线上有效变更。
- 变更内容：在 `AGENTS.md` 明确指定本地开发目录为 `D:\code\adx-mid-platform-oauth-remediation`，要求每次以实际 Git 分支为准；新增服务器代码一致性门禁，禁止直接修改服务器 Git/运行目录，并要求发布前后记录和逐文件校验目标提交与运行目录。
- 修改原因：本次只读审计确认新服务器 Git 克隆 `/srv/gitcode/adx-account-isolated-collector` 为干净的 `master` 提交 `1317648`，但远程 `origin/master` 已为 `81397f2`；实际运行目录 `/srv/adx-account-isolated-collector` 不含 `.git`，与当前 `master` 在 10 个 backend/collector 受控文件上不一致，与该服务器 Git 克隆在 12 个文件上不一致。
- 实施方案：后续先从运行目录导出完整受控差异，建立本地服务器基线恢复分支并完成测试、独立审阅和 Git 提交；再将其与 `master`/`dev` 整合。任何发布仅可从记录的 `master` 提交产生，并在发布后以文件清单/哈希复核运行目录。
- 预期结果与实施后果：阻断未提交服务器改动被覆盖；发布过程增加基线比对和台账记录步骤，但使每个运行版本可追溯和可回滚。
- 影响范围：仅治理规则、发布流程和后续代码整合；不修改服务器源码、服务、数据库、任务、OAuth 或代理。
- 验证与测试：已完成只读 SSH 审计、服务器 Git 状态/远程引用查询、107 个 backend/collector 受控文件哈希比对及本地分支比对；未执行真实拉取或生产写操作。
- 独立审阅：2026-08-03 独立审阅通过，无阻塞项；已确认目录仅为指定入口而不替代实际 Git 分支，规则覆盖 Git 克隆、运行目录与容器漂移，且不包含凭据或不安全服务器操作。
- Git：治理规则提交 `d15040b`（`docs: enforce server Git consistency`）。
- 发布与回滚：不发布。若后续需恢复服务器基线，先创建可验证备份和本地恢复分支；发现偏差时停止同步并保留运行目录证据。

### 2026-08-05 — 权威日报自动尝试窗口调整为业务日结束后五小时

- 状态：已发布，scheduler 保持停止。
- 需求或问题：2026-08-02 的 `coeurdazur` 事故表明，业务日结束后两小时仅代表上游允许查询，不代表 Google Ad Manager 日报快照已经稳定；用户要求将自动尝试时间改为业务日结束后五小时。
- 变更内容：将 `backend/app/collectors/service.py` 的 `MID_PLATFORM_DAILY_SAFETY_DELTA` 从两小时调整为五小时，并新增 `backend/tests/test_fetch_scheduler.py` 的时区边界回归测试。
- 修改原因：避免 scheduler 或 OAuth 恢复流程在日报仍生成时过早写入局部快照，并降低下游把非最终数据当作权威日报的风险。
- 实施方案：保留按账户业务时区计算“报告日次日 00:00”的规则，先转换为 UTC 再增加五个实际经过小时，避免 DST 切换日少等或多等；不更改日报 API 契约、数据表、已有日报记录、手动操作路径或 scheduler 的启停状态。
- 预期结果与实施后果：自动路径最早仅在账户业务日结束后五小时才会认定该日报可尝试。以 `Asia/Shanghai` 为例，8 月 4 日日报最早为北京时间 8 月 5 日 05:00；以夏令时的 `America/Los_Angeles` 为例，最早为当地 8 月 5 日 05:00（UTC 12:00）。代价是自动日报的最早可用时间较原规则延后三小时。
- 影响范围：影响调用 `is_authoritative_daily_ready` 的自动日报调度与 OAuth 恢复缺口判断；不影响小时任务、既有数据、数据库结构、认证、代理、对外 API 字段或当前 scheduler 的 inactive 状态。
- 验证与测试：TDD 红灯已确认原两小时时间分别产生 UTC 18:00（上海）和 UTC 09:00（洛杉矶），与五小时要求不符；独立审阅发现 DST 边界缺陷后，新增洛杉矶 2026 年春季/秋季切换日红灯用例（原实现分别错误产生 UTC 12:00/13:00），修复后为 UTC 13:00/12:00。隔离工作区定向 `pytest tests/test_fetch_scheduler.py -q` 为 18 passed；完整 `pytest tests -q` 为 149 passed，只有既有依赖弃用警告；`git diff --check` 通过。未使用真实账号、代理或生产拉取。
- 独立审阅：首轮独立审阅发现 DST P1，已按 TDD 修复；复审确认以 UTC 增加五个实际经过小时，春/秋 DST 边界可捕获原错误，且 scheduler 启停、迁移、错误处理和安全边界均未变更。复审无 P0/P1 阻塞；同时已采纳 P2 注释修正。
- Git：分支 `codex/daily-maturity-window`，运行时代码提交 `4175bdd`，审阅与发布台账提交 `d25cdeb`；不包含任何密码、Token、OAuth 或代理凭据。
- 发布与回滚：2026-08-05 已发布到生产服务器。发布前创建受限权限备份 `/srv/adx-account-isolated-collector/backups/20260805T123426Z-pre-daily-five-hour-window`，其中含原 `service.py`、运行环境文件副本、systemd unit 文本和 SQLite 一致性备份；仅同步已提交的 `service.py`，未修改数据库业务数据、OAuth、代理或 API 契约。发布后控制面 `/health` 返回 `{"status":"ok"}`，服务为 `active`，本地与生产 `service.py` SHA-256 一致，运行时确认等待量为 `5.0` 小时且洛杉矶春季 DST 边界为 `2026-03-08T13:00:00+00:00`。发布前发现 scheduler 意外处于 `active`，为阻止旧两小时规则继续创建任务已先停止；发布后保持 `inactive`。其 systemd 启动策略仍为 `enabled`，服务器重启时会自动启动，未在本次未经额外授权的范围内修改。回滚为恢复上述备份中的 `service.py` 并重启 `adx-control-plane`；不触碰数据库业务数据，也不启动 scheduler。

### 2026-08-05 — 禁止小时批次覆盖权威日报并恢复 8 月 4 日灰度日报

- 状态：已发布；生产日报数据已恢复，小时批次覆盖权威日报的代码路径已移除，scheduler 保持 `inactive`。
- 需求或问题：用户查询 `2026-08-04` 权威日报时，发现当前值与上午已确认的权威日报值不一致。生产证据表明，后续 `report_fetch_hourly` 批次完成时间与 `account_daily_reports.updated_at` 一致，小时入库覆盖了已存在的权威日报。
- 根因与引入阶段：提交 `3b82481`（2026-07-14，“hourly merge finalization + authoritative daily cutover”）在 `admanager_hourly_dimension_v1` 分支中加入 `_reset_daily_projection`、`_rebuild_site_daily_reports_from_hourly` 和 `_rebuild_account_daily_report`，导致小时批次清空并重建 `site_daily_reports`/`account_daily_reports`。提交说明声称停止小时覆盖，但实际差异加入了覆盖调用。`origin/dev` 的 WIP 提交 `54711dc` 已删除这些调用，但从未合并到生产 `master`。
- 生产数据恢复：在 scheduler 保持 `inactive` 的前提下，通过控制面正常任务接口为 11 个当前灰度节点创建 `2026-08-04` 日报任务 `22326` 至 `22336`，使用各节点既有 OAuth 与代理串行执行；11 个任务全部 `succeeded`。恢复后的 Requests 包括 `coeurdazur.com=594570`、`stones=12304`，与上午权威日报记录一致。
- 生产写操作备份：执行刷新前创建受限目录 `/srv/adx-account-isolated-collector/backups/20260805T131148Z-pre-20260804-authoritative-daily-refresh`，保存受影响日期四张日报表及灰度节点清单的定向 JSON 快照；未复制 Token、OAuth 或代理凭据。此前五小时窗口发布记录误将根目录 0 字节 `control_plane.db` 当作实际数据库备份，真实数据库为 `backend/control_plane.db`；该错误备份不可用于数据回滚，生产数据本身未受此次路径判断错误影响。
- 代码整改方案：小时批次只重置和写入 `site_hourly_reports`/`account_hourly_reports`，不再调用任何日报清空或日报重建函数；删除仅供“从小时重建日报”使用的私有函数。`admanager_site_core_v1` 日报批次继续独占写入现有聚合日报表，日报维度表逻辑不变。
- 预期结果与影响范围：任何小时实时拉取、小时补齐或小时维度批次都不能改变既有权威日报；小时表、小时维度 API、覆盖率对比仍正常更新。无数据库迁移、API 字段、OAuth、代理或 scheduler 启停变更。
- TDD 与验证：先将现有小时入库测试改为预置不同数值的权威日报，再入库小时批次；修复前红灯显示权威站点日报被从 1 条替换为 2 条小时汇总，修复后测试通过。`pytest tests/test_ingestion_service.py -q` 为 6 passed，完整 `pytest tests -q` 为 149 passed；`git diff --check` 通过。代码扫描确认小时分支不再引用日报重建函数，唯一 `_reset_daily_projection` 调用只保留在日报 schema 分支。
- 独立审阅：2026-08-05 独立审阅通过，无 P0/P1；确认小时分支、日报分支、维度表、迁移、API、OAuth、代理、scheduler、错误处理和安全边界均符合本次范围。P2 后续项：现有逻辑在首个小时分页 `rows=[]`、后续分页非空时可能不重置旧小时事实；该问题不写日报、不阻塞本次紧急修复，须另立 TDD 任务处理。
- Git：分支 `codex/protect-authoritative-daily-from-hourly`，代码、测试与初始台账提交 `689b5b4c068a081b36f3d0aa647bd010a98e9dec`；不包含密码、Token、OAuth、代理凭据或生产数据。
- 发布与回滚：2026-08-05 已发布提交 `689b5b4` 中的 `backend/app/collectors/ingestion_service.py`。发布前逐行核对生产文件与 Git 父提交一致（SHA 差异仅由 CRLF/LF 换行造成），并备份原文件至 `/srv/adx-account-isolated-collector/backups/20260805T132836Z-pre-protect-authoritative-daily`；部署后生产文件 SHA-256 为 `6e7c1a2fdcaad07524983965314a88aa3b85271012119ffa0148c815f1140d2a`，`adx-control-plane` 为 `active`，`/health` 返回 `{"status":"ok"}`，scheduler 保持 `inactive`。发布后只读复核 11 个节点的 `2026-08-04` 权威日报，Requests 等指标与任务 `22326` 至 `22336` 的恢复值完全一致。回滚为恢复上述备份中的原文件并重启控制面，但原逻辑存在已确认的数据覆盖缺陷，仅在新版本无法启动时用于短时恢复 API，且 scheduler 与小时任务必须保持停止。
### 2026-08-11 — Pacific 跨日小时报最终刷新

- 状态：开发与独立复审完成，已仅对 `coeurdazur` 发布生产灰度；等待两个 Pacific 跨日周期验证，未扩大范围。
- 需求或问题：小时 scheduler 在 Pacific 跨日后永久切换到新 `report_date`，多个高量灰度节点连续缺失源小时 23（PDT 下对应次日北京时间 14:00）。
- 变更内容：新增按账号 key 默认关闭的跨日最终刷新开关；仅在 direct collector 模式下，于 Pacific 01:00–02:59 用一次正常调度周期刷新上一源日期；任务使用 `cross_day_finalize` 原因和确定性请求 ID，成功后不重复、失败最多重试一次；两次失败后写入唯一的 `cross_day_finalize_exhausted` 阻塞记录。
- 修改原因：从源头补齐上游迟到的上一业务日末小时，同时避免全量回补、额外任务洪峰和对低量真实零数据小时的误判。
- 实施方案：仅命中显式灰度 key 的 enabled schedule；复用当前小时完整快照投影，只更新账号与源日期对应的小时分区；继续禁止小时批次更新账户/站点权威日报；历史日期不自动回补。
- 预期结果与实施后果：每账号每天最多一个成功最终刷新；窗口内一次当前日刷新延后一小时，但总任务量不增加；失败两次后恢复当前日拉取并留下可查询、可去重的阻塞记录等待人工处置；非 direct 模式保持原行为。
- 影响范围：`backend/app/config.py`、`backend/app/collectors/scheduler.py`、`backend/app/collectors/service.py`、scheduler 测试及运维文档；无数据库迁移、无 API 字段变化、无 OAuth/代理变化。
- 验证与测试：TDD 首个用例在旧实现上失败、最小实现后通过；独立审阅提出的非 direct 门禁与重试耗尽记录均先以失败测试复现、修复后通过。后端全量测试 `164 passed`，`compileall` 与 `git diff --check` 通过；未使用真实账号、代理或生产拉取。
- 独立审阅：首轮发现两个 P1：非 direct 远端调用不能可靠限制两次、重试耗尽会静默。已按最小范围增加 direct-only 门禁与幂等耗尽记录；复审确认两个 P1 均关闭，无 P0/P1，可提交并仅在确认 `direct_collector_only=true` 后对 `coeurdazur` 单节点灰度。剩余 P2 为双 scheduler 并发创建耗尽标记时竞争进程可能收到唯一键冲突（当前生产仅单 scheduler），以及尚未单列 spring-forward 测试，不阻塞本次单节点灰度。
- Git：分支 `codex/cross-day-hourly-finalize`；设计/计划提交 `e3afbd1`，代码、测试、问题记录与初始运维台账提交 `3546895`；不包含密码、Token、OAuth、代理凭据或生产数据。
- 发布与回滚：2026-08-11 已发布远程 `master` 提交 `08d2501` 中的 `config.py`、`scheduler.py`、`service.py`，环境仅设置 `ADX_COLLECTOR_CROSS_DAY_FINALIZE_ACCOUNT_KEYS=coeurdazur`。发布前确认生产运行代码精确对应 `af75eb9`、Git 工作仓库可快进到 `08d2501`、运行时 `direct_collector_only=True`、唯一 scheduler、`coeurdazur` 的 OAuth/代理/计划健康；创建受限备份 `/srv/adx-account-isolated-collector/backups/20260811T034000Z-pre-cross-day-hourly-finalize`，其中实际数据库在线备份约 4.8 GB 且 `quick_check=ok`。发布后三个运行文件与服务器 Git `08d2501` 完全一致，Git 工作区干净，控制面和 scheduler 均 `active`，scheduler 进程数为 1，`/health` 正常，生产数据库 `quick_check=ok`；未创建即时最终刷新任务，因为尚未进入 Pacific 01:00–02:59 窗口。继续仅观察 `coeurdazur` 两个 Pacific 跨日周期，未验证前不得扩大账号范围。回滚先从环境清空灰度 key 并重启 scheduler；若代码异常，再恢复上述备份中的三个文件和环境文件并重启服务，只定向取消该账号尚未执行的 `cross_day_finalize` 任务，不整库回滚。
- 扩大灰度：2026-08-11 用户明确要求不再等待 `coeurdazur` 单节点周期验证，扩大到其他当前健康节点。只读门禁筛选标准为账号/实例有效、OAuth `healthy+authorized`、代理 `active`、schedule `enabled`、`interval_hours=1`、schedule timezone 为 `America/Los_Angeles`；最终配置为 `coeurdazur,cpatobe,dddfdc,ddgjcj,linkzclub,onlyfungogo,reboroots,skouje,tqchq,uragnv,zilote`。`stones` 因每 4 小时计划可能错过最终刷新窗口而未纳入；停用、授权异常、非健康或无每小时计划的节点均未扩大。配置写入前创建 `/srv/adx-account-isolated-collector/backups/20260811T071500Z-pre-expand-cross-day-finalize`，含环境文件、scheduler unit 和约 4.8 GB SQLite 在线一致性备份，`quick_check=ok`。首次 SFTP 普通 rename 因不支持覆盖而失败，自动恢复旧环境并重启 scheduler；改用 POSIX 原子覆盖后配置验证通过，控制面和 scheduler 均 `active`、scheduler 进程数为 1、`/health` 正常。回滚只需恢复该备份中的 `backend.env` 并重启 scheduler；不修改数据库业务数据。

### 2026-08-12 — linkzclub 失效定位、重授权与生产指令修订

- 状态：根因已确认，v3 重授权及健康检查已完成；缺失数据补拉待按本条门禁执行。
- 问题与原因：`linkzclub.com` 的活动 v2 refresh token 被 Google 撤销或过期，但数据库仍显示 `authorized + healthy`，造成小时和权威日报连续失败。代理实际出口验证正常。任务日志只保留 `collector_task_failed`，且权威日报失败形成高频重复任务，暴露熔断、幂等、退避和可观测性缺陷。
- 错误操作记录：① 曾用控制面 Python 环境测试 SOCKS，因缺少 SOCKS 依赖得到 `InvalidSchema`，正确做法是使用 `/srv/adx-account-isolated-collector/collector/.venv/bin/python`；② 曾从 `oauth_app_configs.refresh_token` 旧字段读取 token，得到“缺少 refresh_token”，正确来源是 `oauth_credentials` 中 `active_credential_version` 对应的 active 密文，并由 `CredentialCipher` 在内存解密；③ 第一次授权 URL 请求未提交 `force_reauthorize`，被 `OAUTH_REAUTH_CONFIRMATION_REQUIRED` 拒绝，正确请求体必须带 `{"force_reauthorize":true,"reason":"refresh_token_revoked_confirmed"}`；④ callback 导入前只看链接不够，必须校验 OAuth App/account、redirect path、state、issuer、有效期、活动凭据可解密和代理绑定；⑤ collector runtime 每次只处理一个任务，凭据验证后必须再次启动同一实例 runtime 处理健康检查并等待终态；⑥ 不得把 health task 的日志 message 当作唯一真相，本次任务 succeeded 但 message 错写失败，应以任务终态、credential 状态和 OAuth 状态机联合判定。
- 正确授权 URL 调用：先从受限 `.env` 在服务器内读取 Operator Token，调用 `POST /api/v1/operator/oauth-apps/{oauth_app_id}/authorization-url`，请求 JSON 为 `{"force_reauthorize":true,"reason":"refresh_token_revoked_confirmed"}`；不得输出 Token。生成 state 前执行 SQLite online backup 与 `quick_check`。
- 正确 callback 兑换：调用 `POST /api/v1/operator/oauth-apps/import-callback-json`，JSON 必须精确包含 `state`、`code`、`redirect_uri`、完整 `callback_url`；`scope` 和 `iss` 在 schema 中可选，其中 `scope` 仅留档、不作为当前服务端门禁，若上游返回应原样提交，`iss` 若提交必须为 Google。当前服务端安全校验实际覆盖 redirect URI、callback URL/path、state/code、state 有效期及 issuer。callback 临时文件权限必须为 0600，提交后无论成功失败都删除。一个 code 只允许消费一次，失败后不得重放。
- 正确验证顺序：`oauth_credential_validate pending → 启动目标实例 runtime → succeeded/新版本 active → oauth_health_check pending → 再次启动同一实例 runtime → succeeded → authorized + healthy`。仅查询 account 33 的任务和凭据版本，禁止修改其他账号；验证完成前不得补拉数据。
- 安全诊断代码要求：代理与 token 检查必须使用 collector 虚拟环境；只输出 `observed_ip/expected_match`、HTTP 状态和 Google 安全错误描述，不输出 proxy URL、client secret、refresh/access token。托管凭据只在进程内用 `CredentialCipher` 解密，脚本结束即释放。活动凭据可解密和代理绑定有效是运维人员在调用 callback import API 前执行的独立只读门禁，并非 import API 自动完成的校验。
- 备份与回滚：授权链接生成前备份 `/srv/adx-account-isolated-collector/backups/20260812T-linkzclub-reauth-url`；callback 兑换前备份 `/srv/adx-account-isolated-collector/backups/20260812T065900Z-pre-linkzclub-callback-exchange`，均为 SQLite online backup 且 `quick_check=ok`。不得通过整库恢复回滚已成功的 OAuth state/code；若兑换失败，保留证据并重新生成 state/code。只有误改其他业务数据时才评估定向恢复。
- 实施结果：callback 仅命中 OAuth App 32/account 33；生成 staged v3，验证任务 `25334` succeeded，v3 active、v2 retired；健康检查任务 `25335` succeeded，最终 `authorized + healthy`、failure_count=0。未修改其他节点、代理、schedule 或报表数据。
- 缺口补拉门禁：只允许 account 33、v3 active、`authorized + healthy`、代理实际出口匹配、schedule 保持原状、无同账号同日报表 active 任务；写前 SQLite online backup + `quick_check`。小时源日逐日串行且只更新小时分区，任务后核对 batch/源小时并确认既有权威日报 `updated_at` 与指标不变；当前源日只称“当前快照”，不得称最终完整。权威日报必须逐日调用 `is_authoritative_daily_ready` 成熟门禁，且必须传账户实际报告时区，不能把 schedule 固定使用的 Pacific 时区误当成账户报告时区。生产只读核验确认 `linkzclub.com` 的账户时区为 `Asia/Hong_Kong`，因此 8 月 9、10、11 日均已成熟，其中 8 月 11 日最早可用时间为北京时间 2026-08-12 05:00。任何任务失败立即停止，不扩大日期或账号。
- 补拉实施结果（2026-08-12）：写前在线备份为 `/srv/adx-account-isolated-collector/backups/20260812T072216Z-pre-linkzclub-backfill/control_plane.db`（约 4.9 GB，`quick_check=ok`）。小时任务 `25346/25347/25348/25349` 分别补拉 8 月 8—11 日，全部使用 credential v3 并成功；8—10 日各覆盖 24 个源小时，8 月 11 日 Google 当前仅返回 12 个非空小时，故只记为当前快照。任务前后 8 月 8 日权威日报指标和 `updated_at` 未变，8 月 10 日原日报也未被小时任务覆盖。权威日报任务 `25350/25352/25354` 分别补拉 8 月 9—11 日并成功，Requests 分别为 `165602/168346/92995`。补拉没有修改 schedule、代理、OAuth 配置或其他账号。
- 收尾核验：account 33 无 `pending/in_progress`，schedule 仍为启用、每 4 小时、`America/Los_Angeles`，OAuth v3 为 `authorized + healthy`，控制面与 scheduler 均 `active`，`/health` 正常，生产数据库最终 `quick_check=ok`。
- 补拉脚本重入注意：长任务若本地调用超时，不得直接重跑整段创建脚本。先按 `external_request_id` 和 account/date 查询生产任务；本次日报脚本首次后台调用已创建任务，第二次使用相同幂等键时被数据库唯一约束安全拒绝。正确做法是复用已存在任务、等待其终态，仅当确认没有已创建任务时才生成新的唯一请求号；这次约束避免了重复任务和重复写入。

### 2026-08-13 — 单独将治理文档统一基线规则集成至 master

- 状态：已完成。
- 需求或问题：用户要求只把新任务启动门禁和治理文档统一版本规则先合并到 `master`，不得夹带分类索引、交接 Runbook 等其他任务分支成果。
- 变更内容：更新根目录 `AGENTS.md` 规则 9，并新增规则 14–16；同步更新本指南第 21 节开发流程，明确新任务必须从最新 `origin/master` 创建独立任务分支/worktree，启动时先读取当前工作区规则和指定文档，并报告 Git 基线；三份治理文档以 `origin/master` 为唯一正式事实基线。
- 修改原因：不同 worktree 属于不同分支，未合并规则不会自动传播；直接合并 `codex/production-ops-handoff` 会同时带入 9 个提交，不符合本次单独集成授权。
- 实施方案：从 `origin/master@b157a63` 新建临时集成 worktree `codex/governance-rule-master-integration`，仅移植规则文字和本条最小台账/问题记录；不 cherry-pick 原分支提交，不复制整份文档。验证和独立审阅通过后提交该分支，再以 fast-forward 更新 `master`。
- 预期结果与实施后果：更新后的 `master` 将成为新 worktree 的正式治理基线；既有 worktree 仍不会自动同步，必须显式 fetch/rebase/merge 或 cherry-pick。不会引入分类索引或其他功能代码。
- 影响范围：仅 `AGENTS.md`、本指南第 21/22 节和 `docs/问题记录.md`；无生产服务器、代码、API、数据库、OAuth、代理、任务或 schedule 变更。
- 验证与测试：首次范围脚本直接比较 `git diff --name-only` 输出与中文路径，因 Git 默认 `core.quotepath` 转义而把实际存在的 `docs/问题记录.md` 误判为缺失；脚本按门禁停止，未提交、未推送、未影响 `master`。改用 `git -c core.quotepath=false diff --name-only` 后验证通过：差异仅为三份治理文档；规则关键字、敏感信息扫描及 `git diff --check` 均通过。
- 独立审阅：P0/P1 均为 0，可以提交；P2 要求更新 `master` 前再次 fetch 并执行 fast-forward/祖先关系检查，远程基线若移动必须停止、重新移植验证和审阅，禁止强推。
- Git：源基线 `origin/master@b157a63`；集成分支 `codex/governance-rule-master-integration`；实施提交 `cd2bcc7`，本次台账闭环提交紧随其后生成。
- 发布与回滚：只更新 Git `master`，不部署生产。若需撤销，对本次 master 提交做反向提交；禁止重写 master 历史或覆盖追加式台账。

### 2026-08-13 — 新老窗口 worktree 交接技能与初始化脚本

- 状态：审阅中。
- 需求或问题：仅靠文字规则无法稳定保证新对话对应真实、干净、基于最新 `origin/master` 的 worktree，也不能自动证明 `AGENTS.md`、维护手册和问题记录均被 Git 跟踪且与正式基线一致。
- 变更内容：安装个人技能 `$adx-worktree-handoff`，由技能选择严格 `Validate`、只读续接 `Resume` 或新建 `Create`；新增仓库内 `scripts/project-handoff.ps1` 作为确定性、可审计实现及隔离 Git 仓库测试；在 `AGENTS.md` 新增规则 17，要求每个新窗口优先调用技能，技能不可用时显式降级为直接运行仓库脚本并报告。
- 修改原因：把新任务启动检查从人工记忆变为失败即停止的可重复门禁，避免新对话冒充新 worktree、治理文件未跟踪或使用旧基线。
- 实施方案：`Validate` 检查命名分支、三份治理文件存在且被跟踪、工作区 clean、治理文件与 `origin/master` 一致且 behind=0；`Resume` 允许同一已有任务 dirty 或落后，但只读报告；所有模式始终输出 `ProductionWritesAuthorized=False`，严格门禁仅以 `StrictGatePassed` 表示本地任务入口状态；`Create` 校验任务名和绝对目标路径，锁定创建前 master OID，新建 `codex/<任务名>` 后严格复核，失败只清理由本次精确创建的 worktree/分支。脚本不自动修改既有 worktree，不执行 stash/rebase/merge/生产操作。
- 预期结果与实施后果：新任务创建和交接具有统一入口及机器可验证输出；严格 `Validate` 拒绝 dirty worktree，`Resume` 仅只读报告并保护同一任务的既有修改。技能或脚本成功均不能替代完整阅读治理文件，也不授予合并、发布或生产写权限。
- 影响范围：PowerShell 开发工具、测试及三份治理文档；不涉及运行时代码、数据库、生产服务、OAuth、代理、任务或 schedule。
- 验证与测试：TDD 红灯先因测试字符串插值错误未到目标断言，修正后确认因脚本缺失而失败；实现后测试依次捕获单行 Git 输出被取首字符、预期失败子进程被 `$ErrorActionPreference=Stop` 中断等缺陷，修正后 `PASS project-handoff tests`。真实 worktree 验证又发现 Windows PowerShell 5.1 将无 BOM 脚本内中文路径误解码、`git diff` 遗漏未跟踪文件，以及 `git status --short` 将未跟踪目录折叠而非列出内部测试文件；现改为 ASCII 源码动态构造问题记录文件名。技能初始化首次因 `short_description` 仅 20 个字符被官方生成器拒绝并留下模板目录；清理后重建的组合命令被安全策略拦截且未删除文件，正确替代为保留目录并精确补丁写入。官方验证器首次又因中文 Windows 用户路径按 GBK 读取 UTF-8 文件失败，改用进程级 `PYTHONUTF8=1` 后返回 `Skill is valid!`。多文件补丁两次因单个文档锚点不匹配被整体拒绝，均无部分写入。以上失败均未连接生产、未修改业务数据。
- 独立审阅：脚本首轮发现 3 个 P1：Create 失败不回滚、Validate 不拒绝 behind、新窗口 strict clean 阻断 dirty 任务续接；已按 TDD 修复。脚本复审 P0/P1=0。技能组合审阅发现 `ProductionWritesAllowed=True` 会把严格本地门禁误表达为生产授权；已先增加红灯测试，再改为 `StrictGatePassed`，并保证三种模式始终 `ProductionWritesAuthorized=False`，等待复审。
- Git：分支 `codex/handoff-bootstrap-script`，源基线 `origin/master@32aad8b`，提交待生成。
- 发布与回滚：不部署生产。审阅和提交后需单独 fast-forward 集成至 `master` 才能成为新窗口正式入口；回滚使用反向提交，不删除其他台账。

#### 2026-08-13 交接技能提交与集成闭环

- 实施结果：个人技能安装在 `C:\Users\喻远飞\.codex\skills\adx-worktree-handoff`；仓库脚本、测试、规则、计划和脱敏记录提交为 `7a44c8b`，分支 `codex/handoff-bootstrap-script` 已推送，远程 `master` 已由 `32aad8b` 以 fast-forward 更新到 `7a44c8b`。未修改主目录既有工作区。
- 验证与审阅：PowerShell 隔离仓库测试返回 `PASS project-handoff tests`；官方技能校验在 `PYTHONUTF8=1` 下返回 `Skill is valid!`；`git diff --check` 通过。最终独立复审为 P0=0、P1=0、P2=0。
- 发布状态与回滚：仅发布 Git 治理基线和本机个人技能，未部署生产、未连接生产服务、未修改数据库/OAuth/代理/任务/schedule。Git 回滚使用反向提交；个人技能回滚仅移除该精确技能目录，但执行前必须重新核验目标路径并另行记录。

### 2026-08-13 — OAuth 授权按钮布局修复设计

- 状态：实现与两阶段独立审阅完成，待提交；未发布。
- 需求或问题：控制台 `OAuth Apps` 表格位于双栏布局右侧，授权按钮又处于最右侧独立 Action 列；表格自动宽度、超长 client ID/redirect URI 与容器裁切共同导致按钮难以发现或不可见。
- 变更内容：授权按钮已移动到 `Account / App` 单元格，删除独立 Action 列并将空状态及表格结构从 9 列调整为 8 列；为 OAuth 表格增加局部专用 CSS，固定列宽策略、长文本换行和窄屏横向滚动兜底，不影响其他表格。
- 修改原因：确保管理员无需滚动到表格最右侧即可找到生成授权链接、重新授权或恢复授权操作。
- 实施方案：按 TDD 先增加 DOM 归属、八列结构和局部 CSS 契约测试，在现状实现上取得 3 失败、4 通过的有效红灯（旧 9 列、仍有 Action 列、缺少专用 CSS），再做最小 JSX/CSS 修改；保留现有 OAuth 状态机、按钮文案、禁用条件和 API 行为，并用真实浏览器在 1440px、768px 视口复核脱敏超长字段布局。
- 预期结果与实施后果：授权操作与应用身份信息相邻且在常用视口初始位置可见；Flow、Runtime、Credential、Failure、Verified 和 Next action 等诊断列保持完整，窄屏时可横向滚动查看。不会改变 OAuth state/code、凭据、后端接口或生产数据。
- 影响范围：仅涉及 `OAuthAppsSection` 前端组件、OAuth 局部样式、对应前端测试、实现计划和维护文档；无数据库迁移、后端、任务、schedule、代理、OAuth 凭据或生产配置影响。
- 验证与测试：依赖正确安装后，有效红灯为 3 失败、4 通过，失败原因分别覆盖旧 9 列/独立 Action 列和缺少局部 CSS；实现后定向测试 11/11、前端全量测试 29/29、生产构建成功，`git diff --check` 通过。Chrome 151 真实 SSR+CSS 验收使用 160 字符脱敏 client ID/redirect URI：1440px 视口实际内容宽 1422px、768px 视口实际内容宽 750px，两档均为 `buttonVisible=true`、`scrollLeft=0` 且长文本换行无溢出；768px 下保留 15px 右侧横向滚动兜底。提交前敏感扫描曾因规则把源码字段名、空字符串和表单属性误判为秘密值而停止，未 stage/commit；改为检查私钥头、疑似非空或高熵赋值并人工复核 staged 新增行后，再重新执行完整差异复核。未运行真实 OAuth、未连接生产。
- 独立审阅：规格符合性审阅首轮因缺少真实布局证据报 P1，补齐 Chrome 两档视口证据后复审关闭至 P0/P1/P2=0；代码质量审阅发现 P2 类型状态问题，修正后复审确认 P0/P1/P2=0。差异、测试、错误处理和安全边界均已覆盖。
- Git：分支 `codex/oauth-button-layout-fix`；实现提交号以包含本条记录及实现差异的本次提交自身为准。
- 发布与回滚：已发布并验证。实现提交 `7afd21c` 已快进合并并推送至远程 `master`；过程记录提交 `3df5546`、`3afd574` 也已推送，最终闭环提交以本条提交自身为准。生产写前备份 `/srv/adx-account-isolated-collector/backups/20260813T061039Z-pre-oauth-button-layout-frontend` 为 `ubuntu:ubuntu 0700`，SQLite online backup 大小约 5.30 GB，源库和备份库 `quick_check=ok`，并保存发布前前端、Nginx 配置和 systemd 单元。构建产物共 3 个文件，本地与服务器 staging SHA-256 一致；使用同一 `rsync -a --delete --chmod=D755,F644` 参数先 dry-run，确认仅替换 `index.html` 和两份带 hash 的静态资源后正式同步。生产三文件哈希与本地构建完全一致，权限为 0644；`nginx -t` 通过并仅 reload Nginx，未重启控制面或 scheduler。真实 HTTPS 域名的 HTML、JS、CSS 和 `/health` 均返回 200，下载的三份静态内容 SHA-256 与本地构建一致；Nginx、控制面、scheduler 均 active，控制面与 scheduler 进程各 1，生产数据库最终 `quick_check=ok`。服务器 Git 克隆仍为发布前的干净 `master@ded76b1f`，实际运行目录无 Git；本次授权范围仅为已提交 `master` 构建出的三份前端静态文件，未同步后端或声称整个运行目录等于最新 `master`。若需运行时回滚，仅从上述备份恢复精确 `frontend/dist` 并 reload Nginx，再核对哈希、页面、服务和数据库；代码回滚使用反向提交，不得整库恢复。
- 发布后只读复核：首次复核误用不存在的 `adx-collector-scheduler.service`，并硬编码发布前构建资源名，因而产生 scheduler `inactive` 和静态文件不存在的假异常；后续两次命令又分别在本机 PowerShell 和 SSH 远端参数拼接层发生正则引号解析错误，均立即停止且未产生生产写。改用 UTF-8 Base64 传递固定只读脚本后，现场确认实际单元 `adx-control-plane-scheduler.service` 为 `loaded/active/running` 且存在 MainPID，Nginx 与控制面 active；当前 `index.html` 实际引用的两份带 hash JS/CSS 均存在，真实 HTTPS 首页与 `/health` 均为 200，生产数据库 `quick_check=ok`，服务器 Git 克隆仍为干净 `ded76b1f`。结论为核验命令目标与引用过期，不是线上服务或静态资源故障；未重启、重新同步或修改生产状态。
