# 权威维度日报独立任务设计

## 背景与根因

生产控制面已经具备 `admanager_daily_dimension_v1` 入库能力、账户/站点维度日报事实表和查询 API，但生产采集端三份运行文件仍停留在提交 `355a24e`，没有维度日报 SOAP 抓取路径。`origin/master` 中已有的实现把核心日报和维度日报放在同一个 `report_fetch` 中，并在两次 Google 请求都成功后才返回 batch；维度请求失败会使核心 batch 也无法上传，扩大既有权威日报链路的故障面。

## 目标

1. 新增独立任务类型 `report_fetch_daily_dimension`，只生成 `admanager_daily_dimension_v1` batch。
2. 保持现有 `report_fetch` 只负责核心权威日报，维度失败不得改变核心任务、核心 batch 或核心事实。
3. 支持受控自动创建和人工重试维度日报任务。
4. 第一批真实 Google 验证只允许 `ahzhhj.com` 使用其当前已绑定生产代理。
5. 发布前形成可验证保护点；出现异常时可停止新行为并精确恢复运行文件，不以整库恢复覆盖正常业务写入。

## 非目标

- 不修改小时任务、跨日小时保护、核心日报成熟时间或既有聚合/维度查询 API 契约。
- 不新增数据库表或迁移；`collector_sync_tasks.task_type` 已是字符串，现有维度事实表已部署。
- 不回补维度功能上线前的历史数据，不自动扩大到 `ahzhhj.com` 以外节点。
- 不在服务器直接编辑源码；所有运行文件必须来自已测试、已审阅并集成到 `master` 的提交。

## 任务协议与数据流

### 核心权威日报

`report_fetch` 保持现有生产语义：采集器只执行 `fetch_site_daily_report`，只上传 `admanager_site_core_v1`，成功与失败状态不依赖维度请求。

### 权威维度日报

`report_fetch_daily_dimension` 执行 `fetch_site_daily_dimension_report`，只上传 `admanager_daily_dimension_v1`。后端沿用现有 ingestion 投影，按账号、Publisher 业务日、站点、国家、广告单元和 `source_kind=authoritative_daily` 幂等替换维度事实，并重建账户维度聚合；不触碰 `account_daily_reports` 或 `site_daily_reports`。

采集器对已知任务类型显式分派；未知报表任务不得静默退化为核心日报。

## 自动调度

新增配置 `ADX_COLLECTOR_DAILY_DIMENSION_ACCOUNT_KEYS`，默认空字符串，即默认不自动创建任何维度日报任务。只有同时满足下列条件才创建：

- 实例属于现有灰度权威日报集合，账号/实例/OAuth/代理及 policy 通过既有 `automatic_daily` 门禁；
- `report_account_key` 位于维度 allowlist；
- Publisher 业务日已经通过现有五小时成熟门禁；
- 同账号同业务日的核心 `report_fetch` 已成功；
- 同账号同业务日不存在任何 `report_fetch_daily_dimension` 自动尝试。

自动任务每个账号、业务日最多创建一次。失败后不在每轮 scheduler 自动重建，避免任务风暴；人工入口可以在定位原因后受控重试。任务 external request id 使用独立 `auto-daily-dimension-...` 前缀。

第一批生产配置只写入 `ahzhhj` 对应的实际 `report_account_key`，不得按账号展示名猜测 key。

## 人工入口

新增 `POST /api/v1/operator/fetch-schedules/manual-daily-dimension-fetch`，请求继续使用账号、采集实例和 Publisher 业务日三个字段，响应返回独立维度任务 id、状态和是否新建。

入口必须验证：账号和实例严格匹配；`manual_fetch_enabled=true` 且 OAuth/实例配置通过现有门禁；目标业务日已成熟；同日核心日报任务已成功；已有 active 维度任务时复用并启动 runtime，已有终态失败任务时允许新建人工重试。

## 故障与安全边界

- 维度 SOAP、解析、batch 上传或入库失败，只把维度任务标记失败。
- OAuth refresh revoked 仍使用现有熔断机制，因为同一凭据对核心和维度都已不可用；普通维度报表错误不得熔断核心链路。
- 零行维度结果允许任务成功但没有 batch，自动调度以“任务已经尝试”为停止条件，避免空报表任务风暴；状态查询必须区分任务成功、batch 存在和事实存在。
- scheduler 每轮仍只启动一次对应 runtime，维度任务在核心成功后的后续轮次创建，避免与核心任务抢占同一次运行。

## TDD 与验证标准

采集端必须证明核心任务只调用核心日报、维度任务只调用维度日报、维度失败不会出现在核心路径、未知任务类型明确失败。控制面必须证明默认空 allowlist 不创建任务，allowlist 账号只在成熟且核心成功后创建一次，任何既有维度尝试均阻止自动重建，人工入口能正确拒绝边界、复用 active 并允许失败后的人工重试；新任务可被认领，维度 OAuth 失效进入现有熔断。既有小时、核心日报、scheduler、OAuth、ingestion 回归必须全部通过。

## Git、发布和备份

实现必须在独立 worktree 以 TDD 完成，经独立审阅无 P0/P1 后提交并受控快进集成 `master`。生产发布前停止 scheduler，等待当前 collector 子进程退出，并创建权限受限的保护目录，保存：

- `backend/control_plane.db` 的 SQLite online backup，源库和备份库均执行 `PRAGMA quick_check`；
- 本次涉及的全部运行文件、`.env`、相关 systemd unit 文本、服务状态、进程清单和 SHA-256 清单；
- `ahzhhj.com` 最新成熟核心日报任务/batch/事实及维度表写前行数的脱敏快照。

发布使用 staging、hash 校验和原子替换，只同步已集成 `master` 的精确文件。先把 allowlist 配为仅 `ahzhhj`，运行编译、Alembic、服务 health、数据库 quick check，再启动 scheduler 并人工触发一个已成熟业务日的维度任务。验收必须同时确认核心日报值未改变，维度任务、batch、账户/站点维度事实存在，API 可读取，其他账号没有维度任务，且无新增异常任务风暴。

## 回滚

1. 立即清空 allowlist 并停止 scheduler，阻断新维度任务。
2. 从保护点恢复本次精确运行文件和 `.env`，校验 hash、编译、Alembic、服务 health 与数据库 quick check 后恢复原 scheduler 状态。
3. 新增维度事实与任务默认保留为审计证据；如数据需撤销，必须再次备份后按 `ahzhhj.com + report_date + task_id` 定向清理，不能整库恢复。
4. 只有数据库损坏且定向恢复不可行时才评估完整 SQLite 备份；执行前必须明确其会丢失保护点之后的正常生产写入。

## 影响范围

代码影响限于任务创建/分派、维度 allowlist 和人工入口。默认配置不产生新任务；首批只增加 `ahzhhj.com` 每个成熟 Publisher 业务日最多一次 Google 维度报表请求。核心日报、小时任务及其他节点保持原行为。
