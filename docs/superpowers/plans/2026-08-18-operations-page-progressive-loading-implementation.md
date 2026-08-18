# Operations 页面渐进加载与任务分页实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 Accounts/OAuth 只加载自身依赖，并让 Tasks 使用固定快照、每页 100 条的稳定分页端点，消除每次进入控制台都下载全部历史任务的性能问题。

**架构：** 保留旧 `/operator/tasks` 全量升序契约，新增 `/operator/tasks/paged`，用 `snapshot_max_id + id DESC + COUNT/OFFSET/LIMIT` 提供对 scheduler 新增任务稳定的分页快照。前端把统一 `loadAll` 拆成逐资源状态控制器，标签激活时按依赖加载，Tasks 单独保存分页快照；成功、失败、loading 和 request ID 均按资源隔离。

**技术栈：** FastAPI、SQLAlchemy 2、SQLite、Pydantic、React 19、TypeScript、Vitest/jsdom、pytest。

---

## 文件结构

- 修改 `backend/app/collectors/schemas.py`：新增分页任务响应模型，不改变 `SyncTaskList`。
- 修改 `backend/app/collectors/service.py`：新增数据库级固定快照分页查询。
- 修改 `backend/app/collectors/router.py`：新增分页路由及参数门禁。
- 修改 `backend/tests/test_collector_router.py`：覆盖旧契约、新分页、稳定快照、参数边界和 SQL 查询形态。
- 修改 `frontend/src/types/api.ts`：增加分页响应类型。
- 修改 `frontend/src/lib/api.ts`：增加显式分页 API，不改变旧 `listTasks`。
- 创建 `frontend/src/features/operations/useOperationsData.ts`：集中管理逐资源加载、缓存、错误、请求去重和 request ID。
- 修改 `frontend/src/pages/OperationsPage.tsx`：按标签触发资源依赖，传递 Tasks 分页状态。
- 修改 `frontend/src/features/tasks/TasksSection.tsx`：显示分页信息和前后页控件。
- 修改 `frontend/src/features/fetch/FetchSchedulesSection.tsx`：区分 schedule 保存与手动拉取后的缓存动作。
- 创建 `frontend/src/__tests__/operationsLoading.test.tsx`：真实渲染页面，验证请求隔离、失败缓存、刷新和乱序防护。
- 创建 `frontend/src/__tests__/tasksPagination.test.tsx`：验证分页 UI 和交互。
- 修改 `docs/system-maintainer-onboarding-guide.md` 第 22 节：记录 TDD、验证、审阅、提交与发布状态。
- 条件修改 `docs/问题记录.md`：仅在实施中出现真实命令/代码/操作错误时追加；不得为凑交付物创建空记录。

## 治理顺序

本计划服从 `AGENTS.md`：任务 1–5 期间不提交 Git。完成全部本地测试后先做规格符合性审阅，再做代码质量审阅；修复阻塞项并复审通过后，更新最终台账，对完整差异再审阅，最后一次性提交。

### 任务 1：以后端测试锁定旧契约和新快照分页契约

**文件：**
- 测试：`backend/tests/test_collector_router.py`

- [ ] **步骤 1：增加分页测试数据辅助函数**

在测试文件中增加只供本模块使用的辅助函数。每个任务使用不同 `report_date` 或 `external_request_id`，返回创建顺序 ID：

```python
def _create_task_fixture(client: TestClient) -> tuple[int, int]:
    account = client.post(
        "/api/v1/operator/accounts",
        json={"name": "paged-tasks", "external_account_id": "paged-tasks-network", "status": "active"},
    ).json()
    instance = client.post(
        "/api/v1/operator/instances",
        json={
            "account_id": account["id"],
            "name": "paged-tasks",
            "instance_token": "paged-tasks-instance-token",
            "status": "ready",
            "expected_egress_ip": "203.0.113.20",
        },
    ).json()
    return account["id"], instance["id"]


def _create_tasks_for_pagination(
    client: TestClient,
    *,
    account_id: int,
    instance_id: int,
    start_index: int,
    count: int,
) -> list[int]:
    ids: list[int] = []
    for index in range(start_index, start_index + count):
        response = client.post(
            "/api/v1/operator/tasks",
            json={
                "account_id": account_id,
                "collector_instance_id": instance_id,
                "task_type": "report_fetch",
                "report_date": "2026-08-18",
                "status": "pending",
                "external_request_id": f"paged-task-{index}",
            },
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    return ids
```

- [ ] **步骤 2：编写旧端点兼容和默认分页红灯测试**

```python
def test_operator_task_pagination_preserves_legacy_list_and_returns_latest_snapshot(client: TestClient) -> None:
    account_id, instance_id = _create_task_fixture(client)
    ids = _create_tasks_for_pagination(
        client, account_id=account_id, instance_id=instance_id, start_index=0, count=205
    )

    legacy = client.get("/api/v1/operator/tasks")
    assert legacy.status_code == 200
    assert legacy.json() == {"items": legacy.json()["items"]}
    assert [item["id"] for item in legacy.json()["items"]] == ids

    paged = client.get("/api/v1/operator/tasks/paged")
    assert paged.status_code == 200
    body = paged.json()
    assert body["page"] == 1
    assert body["page_size"] == 100
    assert body["total"] == 205
    assert body["snapshot_max_id"] == ids[-1]
    assert [item["id"] for item in body["items"]] == list(reversed(ids[-100:]))
```

- [ ] **步骤 3：编写页间新增任务仍稳定的红灯测试**

```python
def test_operator_task_pagination_keeps_snapshot_stable_when_new_tasks_arrive(client: TestClient) -> None:
    account_id, instance_id = _create_task_fixture(client)
    ids = _create_tasks_for_pagination(
        client, account_id=account_id, instance_id=instance_id, start_index=0, count=205
    )
    first = client.get("/api/v1/operator/tasks/paged?page=1&page_size=100").json()

    new_ids = _create_tasks_for_pagination(
        client, account_id=account_id, instance_id=instance_id, start_index=205, count=2
    )
    second = client.get(
        "/api/v1/operator/tasks/paged",
        params={"page": 2, "page_size": 100, "snapshot_max_id": first["snapshot_max_id"]},
    ).json()
    refreshed = client.get("/api/v1/operator/tasks/paged?page=1&page_size=100").json()

    first_ids = [item["id"] for item in first["items"]]
    second_ids = [item["id"] for item in second["items"]]
    assert set(first_ids).isdisjoint(second_ids)
    assert first_ids + second_ids == list(reversed(ids[-200:]))
    assert second["total"] == 205
    assert refreshed["snapshot_max_id"] == new_ids[-1]
    assert [item["id"] for item in refreshed["items"]][:2] == list(reversed(new_ids))
```

- [ ] **步骤 4：编写参数边界和空快照红灯测试**

使用 `pytest.mark.parametrize` 断言 `page=0`、`page_size=0/201`、`snapshot_max_id=0`、`page=2` 缺少快照均为 422；显式断言合法边界 `page_size=1` 只返回 1 条、`page_size=200` 最多返回 200 条。另以空数据库断言第一页返回 `items=[]`、`total=0`、`snapshot_max_id=0`，以超出末页断言 200 和空 items。

- [ ] **步骤 5：运行红灯**

运行：

```powershell
cd backend
python -m pytest tests/test_collector_router.py -k "task_pagination" -q
```

预期：新增测试因 `/api/v1/operator/tasks/paged` 返回 404 而失败；旧端点断言仍通过。404 是目标红灯，fixture/导入/数据库错误不算有效红灯。

### 任务 2：实现数据库级固定快照分页

**文件：**
- 修改：`backend/app/collectors/schemas.py`
- 修改：`backend/app/collectors/service.py`
- 修改：`backend/app/collectors/router.py`
- 测试：`backend/tests/test_collector_router.py`

- [ ] **步骤 1：增加独立响应模型**

紧邻 `SyncTaskList` 增加：

```python
class PaginatedSyncTaskList(BaseModel):
    items: list[SyncTaskRead]
    page: int
    page_size: int
    total: int
    snapshot_max_id: int
```

- [ ] **步骤 2：增加 service 查询**

导入 SQLAlchemy `func`，新增：

```python
def list_tasks_page(
    db: Session,
    *,
    page: int,
    page_size: int,
    snapshot_max_id: int | None,
) -> schemas.PaginatedSyncTaskList:
    if snapshot_max_id is None:
        snapshot_max_id = db.scalar(select(func.max(CollectorSyncTask.id))) or 0

    if snapshot_max_id == 0:
        return schemas.PaginatedSyncTaskList(
            items=[], page=page, page_size=page_size, total=0, snapshot_max_id=0
        )

    snapshot_filter = CollectorSyncTask.id <= snapshot_max_id
    total = db.scalar(select(func.count()).select_from(CollectorSyncTask).where(snapshot_filter)) or 0
    tasks = list(
        db.scalars(
            select(CollectorSyncTask)
            .where(snapshot_filter)
            .order_by(CollectorSyncTask.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return schemas.PaginatedSyncTaskList(
        items=tasks,
        page=page,
        page_size=page_size,
        total=total,
        snapshot_max_id=snapshot_max_id,
    )
```

分页稳定性来自 COUNT 和数据查询都显式限定 `id <= snapshot_max_id`，且当前任务是无删除路径的审计记录；不得把 SQLite Session 的隐式事务快照当作必要保证。测试必须证明新增任务不进入已取得的 `snapshot_max_id`。

- [ ] **步骤 3：增加分页路由与语义校验**

在旧 `/operator/tasks` 路由之后增加：

```python
@router.get("/operator/tasks/paged", response_model=schemas.PaginatedSyncTaskList)
def list_tasks_paged(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    snapshot_max_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> schemas.PaginatedSyncTaskList:
    if page > 1 and snapshot_max_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="snapshot_max_id is required after the first page",
        )
    return service.list_tasks_page(
        db,
        page=page,
        page_size=page_size,
        snapshot_max_id=snapshot_max_id,
    )
```

- [ ] **步骤 4：验证绿灯与旧契约**

运行：

```powershell
cd backend
python -m pytest tests/test_collector_router.py -k "task_pagination or operator_can_create_list" -q
```

预期：新增分页测试和旧端点测试全部通过。

- [ ] **步骤 5：验证 SQL 没有 Python 全量切片**

从现有 TestClient 的 dependency override 获取同一测试 Engine，再挂 listener；不得引用 fixture 未暴露的局部变量：

```python
override = client.app.dependency_overrides[get_db]
session_generator = override()
session = next(session_generator)
engine = session.get_bind()
session.close()
session_generator.close()

statements: list[str] = []
def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
    statements.append(" ".join(statement.lower().split()))

event.listen(engine, "before_cursor_execute", capture_sql)
try:
    response = client.get("/api/v1/operator/tasks/paged?page=1&page_size=100")
    assert response.status_code == 200
finally:
    event.remove(engine, "before_cursor_execute", capture_sql)

assert any("count(" in statement and "where" in statement for statement in statements)
assert any(
    all(fragment in statement for fragment in ("where", "order by", "limit", "offset"))
    for statement in statements
)
```

在测试文件导入 `from sqlalchemy import event` 和现有 `get_db`。该测试证明分页发生在数据库层，未退化为 Python 全量切片。

### 任务 3：以前端红灯锁定标签请求隔离和分页交互

**文件：**
- 创建：`frontend/src/__tests__/operationsLoading.test.tsx`
- 创建：`frontend/src/__tests__/tasksPagination.test.tsx`

- [ ] **步骤 1：建立无第三方测试库的真实渲染 harness**

使用 `createRoot`、React `act`、`ToastContext.Provider` 渲染 `OperationsPage`。在每个测试后 `root.unmount()`、`vi.restoreAllMocks()`，通过按钮文本查找并 dispatch click。所有 API mock 返回完整最小响应结构，不 mock 页面内部 hook。

- [ ] **步骤 2：编写 Accounts/OAuth 请求隔离红灯**

关键断言：初次渲染只调用 `api.listAccounts`；切换 OAuth 后只新增 `api.listOAuthApps`，不会调用 `listTasks/listInstances/listProxies/listFetchSchedules`；切回 Accounts 不重复账户请求。

```typescript
expect(api.listAccounts).toHaveBeenCalledTimes(1);
expect(api.listOAuthApps).not.toHaveBeenCalled();
expect(api.listTasks).not.toHaveBeenCalled();

await clickButton(container, "OAuth Apps");
expect(api.listAccounts).toHaveBeenCalledTimes(1);
expect(api.listOAuthApps).toHaveBeenCalledTimes(1);
expect(api.listTasks).not.toHaveBeenCalled();
```

- [ ] **步骤 3：编写部分失败、重试和乱序红灯**

用 deferred promise 控制 accounts/OAuth 完成顺序。覆盖：accounts 成功、OAuth 失败后账户缓存仍保留；切走再切回 OAuth 只 ensure 并重试失败的 OAuth，不重复成功 accounts；点击 OAuth 标签内“刷新数据”则强制刷新 accounts 和 oauthApps 两项依赖；普通标签切换不重复正在加载的 accounts；显式刷新产生新 request ID 后，旧响应晚到不覆盖新数据。

- [ ] **步骤 4：编写 Tasks 翻页红灯**

`tasksPagination.test.tsx` 直接渲染 `TasksSection`，传入 `page=1/pageSize=100/total=205/loading=false`、`onPreviousPage/onNextPage`。断言“第 1 / 3 页”“共 205 条”、上一页 disabled、下一页 enabled；点击下一页只调用 `onNextPage`。再覆盖空集显示第 1/1 页且双按钮 disabled。

- [ ] **步骤 5：运行前端红灯**

运行：

```powershell
cd frontend
npm ci
npm test -- src/__tests__/operationsLoading.test.tsx src/__tests__/tasksPagination.test.tsx
```

预期：Operations 测试因现有 `loadAll()` 调用六接口而失败；Tasks 测试因组件尚无分页 props/UI 而出现 TypeScript/断言失败。依赖未安装或 harness 错误不算目标红灯。

### 任务 4：实现前端分页契约和 Tasks UI

**文件：**
- 修改：`frontend/src/types/api.ts`
- 修改：`frontend/src/lib/api.ts`
- 修改：`frontend/src/features/tasks/TasksSection.tsx`
- 测试：`frontend/src/__tests__/tasksPagination.test.tsx`

- [ ] **步骤 1：增加分页类型和 API**

```typescript
export interface PaginatedSyncTaskList {
  items: SyncTaskRead[];
  page: number;
  page_size: number;
  total: number;
  snapshot_max_id: number;
}
```

```typescript
listTasksPaged: (page = 1, pageSize = 100, snapshotMaxId?: number) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (snapshotMaxId !== undefined) params.set("snapshot_max_id", String(snapshotMaxId));
  return request<PaginatedSyncTaskList>(`/api/v1/operator/tasks/paged?${params}`);
},
```

旧 `listTasks()` 保留，避免破坏其他调用。

- [ ] **步骤 2：扩展 TasksSection props 和分页 UI**

增加 `page/pageSize/total/loading/onPreviousPage/onNextPage`。总页数使用 `Math.max(1, Math.ceil(total / pageSize))`；按钮 disabled 分别为 `loading || page <= 1` 和 `loading || page >= totalPages`。创建成功后的 `onChanged` 由上层负责回第一页建立新快照。

- [ ] **步骤 3：运行 Tasks 绿灯**

```powershell
cd frontend
npm test -- src/__tests__/tasksPagination.test.tsx
```

预期：分页显示、边界和回调测试全部通过。

### 任务 5：实现逐资源 Operations 数据控制器

**文件：**
- 创建：`frontend/src/features/operations/useOperationsData.ts`
- 修改：`frontend/src/pages/OperationsPage.tsx`
- 测试：`frontend/src/__tests__/operationsLoading.test.tsx`

- [ ] **步骤 1：实现资源状态原语**

在 hook 文件内部定义：

```typescript
export interface ResourceState<T> {
  data: T;
  loaded: boolean;
  loading: boolean;
  error: string | null;
}

type ResourceKey = "accounts" | "oauthApps" | "instances" | "proxies" | "fetchSchedules";
```

每个资源使用 state、`requestIds.current[key]` 和 `pending.current[key]`。普通 `ensureResource` 在 loaded 或 pending 时复用；`refreshResource` 增加 request ID、允许显式新请求。promise 完成时仅在 ID 仍匹配时提交结果；失败保留旧 data/loaded，并写 error。

- [ ] **步骤 2：实现标签依赖表和激活加载**

```typescript
const TAB_DEPENDENCIES: Record<TabKey, readonly ResourceKey[]> = {
  accounts: ["accounts"],
  oauth: ["accounts", "oauthApps"],
  instances: ["accounts", "instances"],
  proxies: ["accounts", "instances", "proxies"],
  fetch: ["accounts", "instances", "fetchSchedules"],
  tasks: ["accounts", "instances"],
};
```

`useEffect` 在 activeTab 改变时对依赖逐个调用 `ensureResource`，使用 `Promise.allSettled` 仅负责等待，不统一提交结果。Tasks 另由 `loadTaskPage(1, undefined)` 首次建立快照。

- [ ] **步骤 3：实现 Tasks 快照状态**

保存 `items/page/pageSize/total/snapshotMaxId/loaded/loading/error/requestId`。`loaded=false` 是唯一“尚未建立快照”标识，不能用 `snapshotMaxId===0` 判断，因为空快照合法返回 0。首次打开只在 `loaded=false` 时请求第一页；切走再切回复用缓存。第一页显式刷新不传快照；下一页传当前 `snapshotMaxId`。任务创建后的回调强制第一页新快照。旧响应只在 request ID 匹配时写入。

- [ ] **步骤 4：定义跨标签写操作后的刷新/失效矩阵**

每个 Section 的 `onChanged` 必须使用下表，不允许统一刷新：

| 写操作 | 成功后动作 |
| --- | --- |
| 创建 Account | 强制刷新 accounts |
| 创建 OAuth App、导入 callback、生成授权 URL | 强制刷新 oauthApps |
| 创建 Instance | 强制刷新 instances |
| 创建 Proxy | 强制刷新 proxies |
| 创建/更新 Fetch schedule | `onScheduleChanged`：强制刷新 fetchSchedules |
| Fetch 手动拉取 | `onManualFetchChanged`：invalidate Tasks；停留 Fetch 时不立即请求 Tasks |
| 创建 Task | 强制请求 Tasks 第 1 页并建立新 snapshot |

修改 `FetchSchedulesSection.tsx` 的单一 `onChanged` prop 为 `onScheduleChanged` 与 `onManualFetchChanged`：schedule create/update 成功只 await 前者，manual fetch 成功只 await 后者。`OperationsPage` 分别传 `refreshFetchSchedules` 和 `invalidateTasks`。在 `operationsLoading.test.tsx` 至少覆盖“Tasks 已加载 → Fetch 手动拉取成功 → 返回 Tasks 会重新请求第一页”“保存 schedule 不使 Tasks 缓存失效”和“创建 Task 后立即刷新第一页”。

- [ ] **步骤 5：改造 OperationsPage**

删除统一 `loadAll` 和页面级 loading。使用 hook 返回的资源 data、当前标签 loading、`refreshActiveTab` 和 Tasks 分页操作。页面刷新按钮只刷新 `TAB_DEPENDENCIES[activeTab]`；Tasks 标签还刷新第一页。各 Section 的 `onChanged` 传入对应局部刷新函数，不允许回退到六接口全量刷新。

- [ ] **步骤 6：实现 pending 清理、错误和 toast 契约**

每个 promise 只在 `requestId` 和 `pending promise identity` 同时匹配时清除 loading/pending，避免旧请求 finally 清掉新 force-refresh 请求。为资源定义固定标题：accounts=`加载账户失败`、oauthApps=`加载 OAuth Apps 失败`、instances=`加载实例失败`、proxies=`加载代理失败`、fetchSchedules=`加载调度失败`、tasks=`加载任务失败`。只有 request ID 与 promise identity 仍为 current 时，失败才用 `getErrorMessage(error as ApiError)` 写该资源 `error` 并调用 `pushToast({ title: RESOURCE_ERROR_TITLES[key], message, tone: "error" })`；陈旧请求失败不得写 error 或弹 toast。旧成功 data/loaded 保留，显式刷新开始时只清除本资源 error，不清空 data。

`invalidateTasks()` 必须同步执行：递增 Tasks request ID，使旧响应失效；把 `pending` 置空、`loading=false`、`loaded=false`、`error=null`；清空 snapshot/page/items/total。这样返回 Tasks 时 ensure 可立即启动新请求，而不是复用旧 promise。旧 promise 后续成功、失败或 finally 均因 ID/identity 不匹配而不得覆盖状态、弹 toast或清理新 pending。

在竞态测试中建立：旧 Tasks 请求 pending → manual fetch 调用 invalidate → 返回 Tasks 立即产生第二个分页请求 → 第二请求成功 → 旧请求再成功或失败；最终只保留第二请求数据且旧失败不产生 toast。

- [ ] **步骤 7：运行 Operations 绿灯**

```powershell
cd frontend
npm test -- src/__tests__/operationsLoading.test.tsx src/__tests__/tasksPagination.test.tsx
```

预期：请求隔离、缓存、部分失败、重试、去重、乱序防护和 Tasks 翻页全部通过。

### 任务 6：完整本地验证与性能契约核验

**文件：**
- 不修改生产代码；只验证当前差异。

- [ ] **步骤 1：后端定向与全量回归**

```powershell
cd backend
python -m pytest tests/test_collector_router.py -q
python -m pytest tests -q
```

预期：全部通过，无新增失败。

- [ ] **步骤 2：前端定向、全量和构建**

```powershell
cd frontend
npm test -- src/__tests__/operationsLoading.test.tsx src/__tests__/tasksPagination.test.tsx
npm test
npm run build
```

预期：全部通过，TypeScript 和 Vite 构建成功。

- [ ] **步骤 3：格式、范围和敏感信息门禁**

```powershell
git diff --check
git -c core.quotepath=false status --short
git -c core.quotepath=false diff --name-only
```

人工检查新增行不含密码、Operator Token、OAuth code/state、client secret、refresh/access token或完整代理凭据；不得用会把字段名或空字符串误判为秘密的宽泛正则替代人工复核。

- [ ] **步骤 4：本地等价性能验收**

使用后端测试数据库创建 205 条任务并请求新端点，记录响应恰为 100 items；用前端 API mock 证明 Accounts/OAuth 请求日志中没有 `/tasks`。不把本地时间阈值设为易波动的硬失败条件，性能门禁以请求数量和响应条数为确定性契约。

### 任务 7：两阶段独立审阅和问题闭环

**文件：**
- 审阅当前全部未提交实现、测试和文档差异。

- [ ] **步骤 1：规格符合性审阅**

独立审阅者逐条核对已批准规格：旧 Tasks API 兼容、新端点固定快照、持续新增稳定翻页、逐资源加载/失败隔离/request ID、Tasks UI、无迁移、安全和回滚。P0/P1 不为 0 时停止，修复后复审。

- [ ] **步骤 2：代码质量审阅**

另一独立阶段检查 SQL 查询计划、事务视图、FastAPI 422、React effect 依赖、请求竞态、测试有效性、错误处理、敏感信息和无关改动。P0/P1 不为 0 时停止，修复后复审。

- [ ] **步骤 3：重跑受影响验证**

每轮修复后重跑对应定向测试；最终重新运行任务 6 的全部命令，不复用旧输出。

### 任务 8：台账、最终完整差异审阅和一次性提交

**文件：**
- 修改：`docs/system-maintainer-onboarding-guide.md`
- 条件修改：`docs/问题记录.md`
- 提交：本计划列出的全部代码、测试和文档。

- [ ] **步骤 1：闭环第 22 节**

把状态更新为“实现、验证和两阶段独立审阅完成，待提交；未发布”，写入有效红灯原因、绿灯/全量测试数量、构建、SQL/请求隔离证据、审阅问题及修复、影响范围和受控回滚。Git 字段在提交前写“以包含本条记录的本次提交自身为准”，不得预填未知哈希。

- [ ] **步骤 2：记录真实错误**

若实施中出现命令、代码或操作错误，按“错误、原因、正确替代、验证结果、是否产生状态变化”追加 `docs/问题记录.md`；若没有真实错误，不修改该文件。

- [ ] **步骤 3：最终完整差异独立复核**

独立审阅者检查最终所有未提交文件（包括台账），确认 P0/P1=0、测试证据匹配、无敏感信息、无生产数据、无未说明范围。通过前不得 stage/commit。

- [ ] **步骤 4：stage 后复核并提交**

```powershell
git add -- backend/app/collectors/schemas.py backend/app/collectors/service.py backend/app/collectors/router.py backend/tests/test_collector_router.py frontend/src/types/api.ts frontend/src/lib/api.ts frontend/src/features/operations/useOperationsData.ts frontend/src/pages/OperationsPage.tsx frontend/src/features/tasks/TasksSection.tsx frontend/src/features/fetch/FetchSchedulesSection.tsx frontend/src/__tests__/operationsLoading.test.tsx frontend/src/__tests__/tasksPagination.test.tsx docs/system-maintainer-onboarding-guide.md
git diff --cached --check
git -c core.quotepath=false diff --cached --name-only
git commit -m "fix: load operations data progressively"
```

若 `docs/问题记录.md` 有本任务真实记录，将其加入精确 `git add` 清单；否则不得顺带提交。

实现计划文件已在实现开始前单独经过独立审阅并提交，不属于本步骤的未提交实现差异；任务 8 应确认它仍由 Git 跟踪且提交存在，不得留下未跟踪计划。

### 任务 9：集成与发布门禁

**文件：**
- 不直接编辑生产服务器源码。

- [ ] **步骤 1：提交后本地收尾**

确认 worktree clean，记录实现提交；fetch 最新 `origin/master`，若远程已移动则停止并重新处理集成冲突、测试和审阅。只有用户明确要求推送/集成时才推送任务分支并将精确提交受控集成 `master`。

- [ ] **步骤 2：生产发布前门禁**

只有用户明确授权发布后，按 Runbook 现场核验唯一主机、systemd、运行 Git/文件、实际 DB/schema、环境文件和磁盘；创建 SQLite online backup 并对源/备执行 `quick_check`；准备已提交目标 `master` 构建物、dry-run 排除持久文件和精确回滚提交。

- [ ] **步骤 3：受控发布和验证**

先发布后端分页端点并验证 `/health`、旧 `/tasks` 契约和新 `/tasks/paged` 100 items；再发布前端构建物，验证 Accounts/OAuth 不请求 Tasks、Tasks 可稳定翻页。记录运行文件与目标提交逐文件一致、服务唯一进程、数据库完整性。任何偏差立即停止，不扩大同步范围。

- [ ] **步骤 4：回滚**

紧急回退只使用上一正式 `master` 的已提交构建物；常规回滚使用本地反向提交，经测试和独立审阅集成 `master` 后按同一 Runbook 发布。禁止在服务器手工编辑源码或整库恢复。
