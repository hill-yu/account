# Operations 页面渐进加载与任务分页设计

## 背景与问题

生产只读测量确认，账户与 OAuth App 接口本身响应很快，但 `OperationsPage` 首次进入时通过同一个 `Promise.all` 并发请求账户、OAuth App、实例、代理、schedule 和全部历史任务。页面只有在六个请求全部完成后才更新账户和 OAuth 状态。

生产任务接口当前返回 27,084 条记录、约 10.42 MB；账户接口只有 41 条、约 8.7 KB，OAuth App 接口只有 40 条、约 38.5 KB。因此账户与 OAuth 页面实际被无关的全量任务下载、JSON 解析和统一 loading 生命周期阻塞。任何资源创建或更新后的 `loadAll()` 还会再次下载全部任务。

## 目标

1. 账户页面不再等待任何无关资源请求。
2. OAuth 页面仅等待账户与 OAuth App，不请求任务列表。
3. Tasks 页面只在首次打开或翻页时请求任务，并按固定快照内的 ID 倒序每页显示 100 条。
4. 其他标签仅加载自身展示和表单所需的数据依赖。
5. 单个标签的失败、刷新和 loading 状态不影响其他标签已成功加载的数据。
6. 保留完整历史任务访问能力，不改变任务创建、OAuth、代理、调度或报表行为。

## 非目标

- 不修改数据库表或执行数据迁移。
- 不删除、归档或重写历史任务。
- 不改变任务创建与执行顺序。
- 不增加前端全局缓存框架或第三方数据请求库。
- 不改变生产 OAuth、代理、schedule、scheduler 或任何节点配置。

## 方案选择

采用“后端数据库分页 + 前端按标签独立加载”。仅做前端懒加载会把 10 MB 问题推迟到 Tasks 标签；只加固定 `limit` 会使历史任务无法完整访问。分页和独立加载共同解决当前阻塞及任务持续增长后的长期性能问题。

## 后端 API 设计

### 兼容边界

保留现有 `GET /api/v1/operator/tasks` 的全部历史任务、ID 升序语义和既有 `SyncTaskList` 响应，不修改其参数或结构。仓库中的虚拟流程、后端测试及未知外部运维调用方可以继续使用旧接口。

新增 `GET /api/v1/operator/tasks/paged`，仅供分页客户端显式使用。新前端 Tasks 标签切换到该端点；旧接口本次不删除、不重定向，也不声称已解决旧调用方的全量响应开销。

### 请求

`GET /api/v1/operator/tasks/paged` 接受：

- `page`：从 1 开始，默认 1。
- `page_size`：默认 100，允许 1–200。
- `snapshot_max_id`：可选正整数。第一页省略；后续页必须回传第一页响应中的值。

FastAPI 参数校验应对小于 1 的 `page`、小于 1 或大于 200 的 `page_size`、小于 1 的 `snapshot_max_id` 返回 422。`page>1` 且缺少 `snapshot_max_id` 时返回 422，禁止悄悄创建新的翻页快照。

### 响应

新 `PaginatedSyncTaskList` 响应为：

```json
{
  "items": [],
  "page": 1,
  "page_size": 100,
  "total": 27084,
  "snapshot_max_id": 27084
}
```

分页端点使用新的 `PaginatedSyncTaskList`，不改变旧 `SyncTaskList` 或任务项结构。

### 查询语义

- 第一页在同一只读事务/会话中取得当前最大任务 ID 作为 `snapshot_max_id`；无任务时使用 `0` 作为响应快照标识，仅响应允许 0，请求参数仍要求正整数。
- `COUNT(*)` 与数据查询均限定 `id <= snapshot_max_id`，得到该快照的稳定 `total`。
- 数据查询固定 `WHERE id <= snapshot_max_id ORDER BY collector_sync_tasks.id DESC`。
- 使用 `OFFSET (page - 1) * page_size LIMIT page_size`。
- scheduler 在翻页期间新增的更大 ID 不进入当前快照，因此不会移动后续页 offset；刷新或创建任务成功后回到第一页才建立新快照。
- 任务属于审计记录，本设计不引入删除路径；若未来增加任务删除，必须重新评估 offset 快照语义。
- 超出末页返回空 `items`，同时保留请求的 `page`、`page_size`、快照 `total` 和 `snapshot_max_id`。
- 不在内存中读取全部任务后切片。

## 前端加载架构

### 标签依赖

| 标签 | 加载数据 |
| --- | --- |
| Accounts | accounts |
| OAuth Apps | accounts + oauthApps |
| Instances | accounts + instances |
| Proxies | accounts + instances + proxies |
| Fetch | accounts + instances + fetchSchedules |
| Tasks | accounts + instances + 当前任务页 |

### 状态与请求行为

- 删除统一的 `loadAll()` 和页面级单一 `loading`。
- 每种资源保留独立的 loaded/loading/error 状态和单调递增 request ID；标签激活时只加载未成功缓存、失败后明确重试或明确要求刷新的依赖。
- OAuth 的两个请求并发启动，但各自独立提交成功结果和错误；可使用独立 promise handler 或 `Promise.allSettled`，不得在统一 `Promise.all` 成功分支才提交结果，也不得包含 Tasks 或其他无关接口。
- 切换回已加载标签不自动重复请求；点击“刷新数据”只刷新当前标签所需资源。
- 创建或修改成功后，组件通过当前标签刷新函数只刷新受影响依赖，不下载任务历史。
- 单个请求失败时设置该资源 `error`、清除其 `loading`，但不把已有成功缓存改回未加载，也不清空同标签中其他资源的成功结果；用户再次激活仍缺失的资源或点击刷新时可重试失败资源。
- 每个资源只有当前 request ID 匹配时才提交成功/失败状态；旧请求晚到不得覆盖新请求。标签切换等普通加载在相同资源处于 loading 时不得再发重复请求；用户显式刷新可以使旧请求失效并启动新请求，因此必须保留 request ID 防护。

## Tasks 分页交互

- 首次打开 Tasks 请求 `page=1&page_size=100`，保存响应中的 `snapshot_max_id`。
- 表格按任务 ID 从大到小显示。
- 显示总记录数、当前页和总页数。
- “上一页”在第一页禁用；“下一页”在当前页已覆盖 `total` 时禁用。
- 翻页只请求 Tasks，并回传同一个 `snapshot_max_id`；已加载的 accounts 和 instances 继续复用。
- 创建任务成功后回到第 1 页并刷新当前任务页，以显示最新任务。
- 当 `total=0` 时显示第 1 页、共 1 页，并保持前后翻页按钮禁用。

## 错误处理与兼容性

- 后端分页参数错误使用框架标准 422，不修改鉴权和通用错误结构。
- 前端继续使用现有 `getErrorMessage` 与 toast。
- 新分页 API 使用独立响应结构；旧 Tasks API 和 `SyncTaskRead` 均保持不变。
- 不以响应压缩替代分页。是否启用 Nginx 压缩属于独立发布优化，不在本次范围。

## 测试策略

### 后端 TDD

先在现有实现上加入失败测试，证明：

1. 新分页端点默认只返回快照内最新 100 条，按 ID 倒序，并返回正确 `total/page/page_size/snapshot_max_id`；旧端点仍返回全部任务且保持 ID 升序。
2. 指定第二页返回正确、不重复的下一批任务。
3. 第一页与第二页之间插入更大 ID 的任务时，使用原 `snapshot_max_id` 的第二页不重复、不漏掉原快照记录；刷新第一页后才能看到新任务。
4. `page_size=1` 和 `page_size=200` 可用；0、201、`page=0`、非法快照及第二页缺少快照返回 422。
5. 超出末页返回空数组而不是错误。
6. SQL 级断言或查询 spy 证明分页查询使用数据库 `COUNT/WHERE/ORDER/OFFSET/LIMIT`，未退化为 Python 全量切片。

### 前端 TDD

先在现有统一 `loadAll` 实现上加入失败测试，证明：

1. 首次 Accounts 标签只调用账户接口，不调用 Tasks/OAuth/代理等接口。
2. 切换 OAuth 只调用缺失的 OAuth 数据，并复用已有 accounts。
3. Tasks 首次加载调用 `page=1&page_size=100`，翻页携带快照 ID 且只重新请求 Tasks。
4. Tasks 分页按钮、总数和边界禁用状态正确。
5. 当前标签刷新不会调用无关接口。
6. accounts 成功而 OAuth 失败、OAuth 成功而 accounts 失败时，成功资源分别保留并缓存；重试只请求失败资源。
7. 同一资源重复触发时不并发重复请求，较旧请求晚到不会覆盖较新结果。

实现后运行后端路由定向测试、前端定向测试、后端相关回归、前端全量测试和生产构建。

## 验收标准

1. 首次进入 Accounts 不发起 Tasks 请求；无需在前端单测构造 27,084 个任务对象。
2. 首次进入 OAuth 只发起 Accounts/OAuth 请求，授权按钮和表格在二者完成后可用。
3. Tasks 单次响应不超过 100 个任务项；生产当前规模下响应体从约 10.42 MB 降到分页后的合理大小。
4. scheduler 持续新增任务时，Tasks 在同一 `snapshot_max_id` 内可连续翻页且无重复、无漏页，顺序稳定为 ID 倒序；主动刷新后建立新快照并显示新增任务。
5. 现有账户、OAuth、实例、代理、schedule 和任务创建功能回归通过。
6. 无数据库迁移，无生产 OAuth、代理、任务、schedule 或服务状态变化。

## 影响范围

- 后端：任务列表路由、service 查询、schema 和路由测试。
- 前端：Operations 页面加载编排、Tasks 组件、API 类型与前端测试。
- 文档：第 22 节变更台账及必要的问题记录。
- 不影响 collector、Google 拉取、报表投影、数据库 schema 和生产配置。

## 发布与回滚

发布前必须完成 TDD、全量回归、独立审阅和 Git 提交；只允许从已提交并集成的正式 `master` 目标提交发布。发布前按 Runbook 现场核验 systemd、运行 Git/文件、环境文件、实际运行路径与数据库，执行 SQLite online backup 和双 `quick_check`；同步前以相同排除项 dry-run，显式保护环境文件、数据库、备份与虚拟环境。后端与前端作为同一兼容发布单元，顺序为先发布新增分页端点的后端，再发布使用它的前端。

若发布异常，优先使用已提交的上一正式 `master` 构建物执行受控紧急回退；常规回滚在本地对目标提交创建反向提交，完成测试、独立审阅并集成 `master` 后，再按同一 Runbook 同步流程发布该回滚提交。禁止在服务器 Git 克隆或运行目录手工编辑源码。回退后逐文件核对运行内容与目标提交，验证 `/health`、登录、Accounts、OAuth、Tasks、唯一服务进程和数据库完整性。本次无数据库迁移或数据回滚。
