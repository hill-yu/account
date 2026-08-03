# 单管理员登录实现计划

> **面向执行者：** 使用 `executing-plans` 逐项执行；每个代码行为先写失败测试，再写最小实现。

**目标：** 让中台前端通过一次登录使用现有 `ADX_COLLECTOR_OPERATOR_API_TOKEN` 作为管理员密码，并以安全会话 Cookie 访问全部 operator API；不把 Token 写入浏览器持久化存储、前端构建产物或 Git。

**架构：** 后端新增不受 operator 全局依赖保护的登录、登出和会话查询端点。登录仅在服务端用常量时间比较校验现有 Operator Token；成功后以该服务端密钥 HMAC 签名、12 小时有效的 HttpOnly、SameSite=Strict Cookie。现有 operator 依赖同时接受此 Cookie 或旧版 `X-ADX-Operator-Token`，保持脚本/API 调用兼容。前端启动时查询会话，未登录只显示登录页；所有 API 请求显式携带同源 Cookie。

**技术栈：** FastAPI、Pydantic、Python 标准库 HMAC、React 19、React Router、Vitest、pytest。

**文件与职责：**

- 修改 `backend/app/collectors/security.py`：生成、验证和识别管理员会话；保留旧 Header 认证。
- 修改 `backend/app/collectors/schemas.py`：登录请求和会话响应契约。
- 修改 `backend/app/collectors/router.py`：公开登录/登出、受保护会话查询端点。
- 修改 `backend/app/main.py`：注册公开认证路由，不改动采集或 OAuth 路由契约。
- 修改 `backend/tests/test_collector_router.py`：覆盖 Cookie 会话、错误密码、登出、Header 兼容性。
- 修改 `frontend/src/lib/api.ts`：会话 API 和明确的同源 Cookie 请求。
- 新建 `frontend/src/pages/LoginPage.tsx`：仅含密码输入与错误反馈的登录页。
- 修改 `frontend/src/App.tsx`、`frontend/src/router.tsx`、`frontend/src/components/layout/AppShell.tsx`、`frontend/src/styles.css`：登录门禁、登出操作和页面样式。
- 新建 `frontend/src/__tests__/login.test.tsx`：登录页与会话门禁的渲染测试。
- 修改 `docs/system-maintainer-onboarding-guide.md` 第 22 节：记录变更、测试、审阅、Git 和未发布状态。

---

### 任务 1：后端会话认证与回归测试

- [x] 写入失败测试：错误密码返回 401 且不签发 Cookie；正确密码签发 `HttpOnly`、`SameSite=Strict` Cookie；Cookie 可访问 `/api/v1/operator/accounts`；登出后不可继续访问；Header 仍可访问。
- [x] 运行 `backend/.venv/Scripts/python.exe -m pytest tests/test_collector_router.py -q`，确认新增断言在实现前失败。
- [x] 最小实现：HMAC 签名的过期会话、公开登录/登出、受保护会话端点，以及 Header/Cookie 双通道认证。
- [x] 重跑同一命令，确认通过；随后运行 `backend/.venv/Scripts/python.exe -m pytest tests -q`。

### 任务 2：前端登录门禁与测试

- [x] 写入失败测试：未认证应用显示密码登录页；登录页不含 Token 默认值或浏览器存储；认证状态可进入控制台。
- [x] 运行 `npm test -- --run src/__tests__/login.test.tsx`，确认新增测试先失败。
- [x] 最小实现：登录页、启动会话检查、注销、`credentials: "include"`，不添加 Token Header 或本地存储。
- [x] 重跑上述测试，并执行 `npm test` 与 `npm run build`。

### 任务 3：文档、独立审阅与发布前验证

- [x] 追加第 22 节台账，明确密码仅使用现有环境变量、Cookie 属性、兼容性影响、回滚和未部署状态，不记录任何密钥。
- [x] 审阅完整差异：认证绕过、Cookie 属性、过期处理、Header 兼容、前端是否持久化 Token、测试和文档。
- [x] 处理全部阻塞审阅问题并复审。
- [x] 运行后端全量测试、前端全量测试、前端生产构建和 `git diff --check`；仅在审阅和验证均无阻塞问题后提交 Git。部署不在本次计划内。
