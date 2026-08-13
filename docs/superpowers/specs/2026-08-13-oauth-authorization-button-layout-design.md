# OAuth 授权按钮布局修复设计

日期：2026-08-13

## 背景与问题

控制台 `OAuth Apps` 页面将授权操作放在九列表格最右侧的独立 `Action` 列。该表格位于双栏布局的右半栏，外层 `.table-card` 又使用 `overflow: hidden`。当可用宽度不足时，最右侧操作列会被裁切，导致用户找不到“生成授权链接”或“重新授权”按钮。

## 目标

- 让每个 OAuth App 的授权操作在应用信息旁始终可见。
- 保持现有 OAuth 状态机、按钮文案、禁用条件、确认流程和 API 调用完全不变。
- 缩减表格横向宽度，改善窄屏和双栏布局下的可用性。

## 非目标

- 不修改后端 API、OAuth state/code 处理、凭据存储或安全边界。
- 不改变 OAuth App 创建、callback JSON 导入或健康检查流程。
- 不重构其他 Operations 页面或通用表格组件。

## 设计

在 `OAuthAppsSection` 中，将授权按钮从最右侧独立 `Action` 单元格移动到 `Account / App` 单元格。单元格按以下顺序展示：

1. account ID 与 client ID；
2. redirect URI；
3. 当前 OAuth App 对应的授权按钮。

删除表头和每行中的独立 `Action` 列，空状态的 `colSpan` 从 9 调整为 8。按钮继续调用现有 `handleGenerate(oauthApp)`，继续使用 `getOAuthAuthorizationAction(flow_status, runtime_status)` 决定文案、是否强制重新授权、是否要求原因以及是否禁用。

为 OAuth 表格和应用信息区域增加专用布局类，避免继续依赖通用表格的自动宽度行为：

- OAuth 表格使用明确的列宽策略，`Account / App` 列获得可收缩的主内容宽度，状态和时间列保持紧凑；
- client ID 与 redirect URI 使用 `overflow-wrap: anywhere`，超长值在单元格内换行，不能继续撑宽整张表；
- 应用信息内容纵向排列，授权按钮位于信息下方并左对齐，按钮自身不压缩到不可辨识；
- 窄屏下允许 OAuth 表格在自身容器内横向滚动作为兜底，但按钮所在的第二列必须在常用视口首屏可见，不能依赖滚动到最右侧才能操作。

样式仅作用于 OAuth App 表格，避免影响其他数据表。

## 错误处理与安全

沿用现有 toast、确认框、重新授权原因校验和 API 错误处理。页面不会展示 client secret、refresh/access token、OAuth code/state 或完整凭据。本次布局变更不会放宽授权操作的状态门禁。

## 测试与验收

采用 TDD：

1. 先增加组件回归测试，通过 DOM 表头和单元格关系断言授权按钮位于 `Account / App` 单元格内，且表格不再渲染独立 `Action` 表头；不得用可能命中正文的字符串 contains 代替结构查询。确认测试在现状实现上失败。
2. 实施最小 JSX 与 CSS 修改，使定向测试通过。
3. 保留并扩展授权状态矩阵测试，至少覆盖 `Generate URL`、`Reauthorize`、`Restore authorization` 和一个禁用状态，确认文案与禁用行为未改变。
4. 运行前端全量测试和生产构建。
5. 在 1440px 桌面视口和 768px 窄屏视口检查布局：使用包含超长 client ID 与 redirect URI 的测试数据；授权按钮的 bounding box 必须位于 OAuth 表格可视容器内且未被裁切，长文本必须在应用信息单元格内换行。768px 下若其他诊断列需要横向滚动，按钮仍须在初始滚动位置可见。

验收标准：

- 在 1440px 和 768px 视口打开 `OAuth Apps` 标签后，无需横向滚动即可在对应应用信息旁找到授权按钮；其他诊断列可在窄屏下通过表格容器滚动查看。
- `Generate URL`、`Reauthorize`、`Restore authorization` 及各禁用状态行为与修改前一致。
- 表格保留 Flow、Runtime、Credential、Failure、Verified 和 Next action 信息。
- 前端全量测试与构建通过，`git diff --check` 无问题。

## 影响范围与回滚

影响仅限 `frontend/src/features/oauth/OAuthAppsSection.tsx`、对应局部样式、前端测试和维护台账第 22 节追加记录。台账必须写明独立审阅结论、测试结果、Git 提交和未发布状态。没有数据库迁移、后端、OAuth 数据、任务、schedule、代理或生产配置影响。

回滚方式为用反向提交恢复原表头、独立 Action 单元格和 `colSpan=9`，并移除本次专用样式；测试应同步调整为回滚后的预期行为，不通过删除回归测试掩盖布局变化。部署前仍须遵守独立审阅、Git 提交和生产发布门禁。
