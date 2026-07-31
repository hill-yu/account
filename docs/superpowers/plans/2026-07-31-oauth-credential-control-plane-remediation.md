# OAuth 凭据统一控制面实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 以生产源码 `588e38e` 为基线，实现加密版本化 OAuth 凭据、统一拉取策略、授权熔断和受验证恢复，消除失效 token 的重复任务风暴和新旧凭据漂移。

**架构：** 控制面是 OAuth 凭据唯一事实源，`direct_collector` 是唯一 Google 拉取路径。授权 callback 只创建 staged 凭据，collector 通过账号代理完成 refresh grant 和 Network API 验证，控制面收到版本 ACK 后激活，再以最小健康任务决定是否恢复四小时 schedule。所有自动、手工、补数、领取和提交入口共用数据库 policy 和 credential version 检查。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy 2、Alembic、SQLite/PostgreSQL 兼容 SQL、Fernet/HMAC、googleads SOAP、React 19、TypeScript、Vitest、pytest。

---

## 文件结构

### 新增文件

- `backend/app/models/oauth_credential.py`：加密凭据版本和状态。
- `backend/app/models/collector_account_policy.py`：灰度、自动任务、手工任务和停拉的单一策略源。
- `backend/app/models/oauth_event.py`：不含秘密的 OAuth 审计事件。
- `backend/app/collectors/credential_crypto.py`：Fernet 加解密和 HMAC 指纹。
- `backend/app/collectors/fetch_policy.py`：统一 `assert_fetch_allowed` 和熔断/恢复事务。
- `backend/app/collectors/oauth_errors.py`：Google OAuth 错误分类和值对象。
- `backend/app/scripts/migrate_oauth_credentials.py`：legacy 明文凭据迁移。
- `backend/app/scripts/migrate_collector_account_policies.py`：代码常量和 schedule 迁移。
- `backend/alembic/versions/20260731_0012_oauth_credential_control_plane.py`：新表、状态字段和索引。
- `collector/app/oauth_errors.py`：运行时 OAuth 异常解析和脱敏。
- `collector/app/oauth_validation.py`：refresh grant、Network API 和凭据 ACK 验证。
- `问题修改.md`：本版本每个代码提交的问题、原因、影响和结果。

### 主要修改文件

- `backend/app/config.py`、`backend/requirements.txt`
- `backend/app/models/__init__.py`、`backend/app/models/oauth_app_config.py`
- `backend/app/collectors/oauth_service.py`、`schemas.py`、`router.py`、`service.py`、`scheduler.py`
- `backend/app/collectors/ingestion_service.py`
- `collector/app/control_plane_client.py`、`models.py`、`runtime.py`、`oauth.py`、`admanager_soap.py`、`fetcher.py`
- `collector/app/vps_api.py`、`deploy/vps/php/fetch.php`
- `frontend/src/features/oauth/OAuthAppsSection.tsx`、`frontend/src/types/api.ts`、`frontend/src/lib/api.ts`
- 对应 `backend/tests`、`collector/tests` 和 `frontend/src/__tests__`。

## 任务 1：固定生产基线测试

**文件：**
- 修改：`backend/tests/test_collector_router.py`
- 修改：`backend/tests/test_fetch_scheduler.py`
- 修改：`backend/tests/test_ingestion_service.py`
- 修改：`backend/tests/test_models.py`
- 修改：`collector/tests/test_admanager_soap.py`
- 修改：`collector/tests/test_adx_report_service.py`
- 修改：`collector/tests/test_fetcher.py`
- 修改：`collector/tests/test_vps_api.py`
- 修改：`collector/tests/test_vps_service.py`
- 创建：`问题修改.md`

- [ ] **步骤 1：记录现有失败清单**

运行：

```powershell
cd backend; python -m pytest -q
cd ..\collector; python -m pytest -q
```

预期：backend `10 failed, 56 passed`；collector `17 failed, 56 passed`。

- [ ] **步骤 2：只修改旧测试以匹配生产实现**

更新测试 fixture 和期望值：日报使用 `DATE` + `PUBLISHER`，小时维度包含国家、广告单元和 requests；本地权威日报测试不再 mock `/ke/report.php`；灰度列表使用生产 key；coverage 断言包含 value-match 字段；模型表包含 `fetch_schedules` 和 `account_report_day_statuses`。

不得修改运行代码。

- [ ] **步骤 3：验证基线测试全绿**

运行同上命令。预期 backend 和 collector 均为 `0 failed`。

- [ ] **步骤 4：记录并提交**

在 `问题修改.md` 记录“生产实现与旧测试漂移”，提交：

```powershell
git add backend/tests collector/tests 问题修改.md
git commit -m "test: 对齐生产采集行为基线"
```

## 任务 2：建立加密凭据和账号策略模型

**文件：**
- 创建：`backend/app/models/oauth_credential.py`
- 创建：`backend/app/models/collector_account_policy.py`
- 创建：`backend/app/models/oauth_event.py`
- 创建：`backend/alembic/versions/20260731_0012_oauth_credential_control_plane.py`
- 修改：`backend/app/models/oauth_app_config.py`
- 修改：`backend/app/models/__init__.py`
- 修改：`backend/tests/test_models.py`
- 创建：`backend/tests/test_oauth_credential_models.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：先写失败的模型测试**

测试至少包含：

```python
def test_oauth_app_allows_one_active_and_one_staged_credential(db_session): ...
def test_account_policy_rejects_gray_with_exclusion_reason(db_session): ...
def test_oauth_event_has_no_secret_payload_columns(): ...
```

运行：`cd backend; python -m pytest tests/test_models.py tests/test_oauth_credential_models.py -q`

预期：模型或表不存在而失败。

- [ ] **步骤 2：实现模型和迁移**

实现 `OAuthCredential`、`CollectorAccountPolicy`、`OAuthEvent`，扩展 `OAuthAppConfig`：

```python
flow_status = mapped_column(String(32), default="pending", nullable=False)
runtime_status = mapped_column(String(32), default="unknown", nullable=False)
active_credential_version = mapped_column(Integer)
pending_credential_version = mapped_column(Integer)
failure_class = mapped_column(String(64))
failure_count = mapped_column(Integer, default=0, nullable=False)
last_verified_at = mapped_column(DateTime(timezone=True))
revoked_at = mapped_column(DateTime(timezone=True))
publishing_status = mapped_column(String(32), default="in_production", nullable=False)
next_action = mapped_column(String(128))
```

迁移增加 `(oauth_app_id, version)` 唯一约束以及 active/staged 条件唯一索引。

- [ ] **步骤 3：验证迁移升级降级和模型测试**

运行：

```powershell
cd backend
python -m pytest tests/test_models.py tests/test_oauth_credential_models.py tests/test_database.py -q
alembic upgrade head
alembic downgrade 20260708_0011
alembic upgrade head
```

- [ ] **步骤 4：记录并提交**

```powershell
git add backend/app/models backend/alembic backend/tests 问题修改.md
git commit -m "feat: 建立 OAuth 凭据与拉取策略模型"
```

## 任务 3：实现凭据加密和脱敏

**文件：**
- 创建：`backend/app/collectors/credential_crypto.py`
- 修改：`backend/app/config.py`
- 修改：`backend/requirements.txt`
- 创建：`backend/tests/test_credential_crypto.py`
- 创建：`backend/tests/conftest.py`，集中提供 OAuth 凭据、策略和事件模型测试 fixture
- 修改：`问题修改.md`

- [ ] **步骤 1：写失败的加密测试**

```python
def test_cipher_round_trips_without_storing_plaintext(): ...
def test_fingerprint_is_stable_and_does_not_contain_token(): ...
def test_missing_keys_fail_closed_when_credentials_are_used(): ...
def test_ciphertext_or_secret_never_appears_in_repr(): ...
```

- [ ] **步骤 2：运行并确认失败**

运行：`cd backend; python -m pytest tests/test_credential_crypto.py -q`

- [ ] **步骤 3：实现最少加密服务**

新增配置：

```python
credential_encryption_key: str | None = None
credential_fingerprint_key: str | None = None
```

实现 `CredentialCipher.encrypt/decrypt/fingerprint`，错误消息只能使用固定错误码。

- [ ] **步骤 4：验证和提交**

```powershell
python -m pytest tests/test_credential_crypto.py -q
git add backend/app/config.py backend/app/collectors/credential_crypto.py backend/requirements.txt backend/tests 问题修改.md
git commit -m "feat: 加密并指纹化 OAuth 凭据"
```

## 任务 4：数据库化拉取策略和统一策略门

**文件：**
- 创建：`backend/app/collectors/fetch_policy.py`
- 创建：`backend/tests/test_fetch_policy.py`
- 修改：`backend/app/collectors/service.py`
- 修改：`backend/app/collectors/scheduler.py`
- 修改：`backend/app/collectors/ingestion_service.py`
- 修改：`backend/tests/test_fetch_scheduler.py`
- 修改：`backend/tests/test_collector_router.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写每个入口的失败测试**

参数化测试：

```python
@pytest.mark.parametrize("entrypoint", [
    "operator_task", "manual_hourly", "targeted_recent",
    "automatic_hourly", "automatic_daily", "claim", "batch", "terminal_status",
])
def test_revoked_account_is_blocked_at_every_fetch_entrypoint(entrypoint): ...
```

另测 `manual` 停拉不能被 OAuth 恢复解除、历史查询仍可读。

- [ ] **步骤 2：验证测试因缺少策略门失败**

运行：`cd backend; python -m pytest tests/test_fetch_policy.py -q`

- [ ] **步骤 3：实现 `assert_fetch_allowed`**

接口：

```python
def assert_fetch_allowed(
    db: Session,
    *,
    account_id: int,
    fetch_kind: str,
    credential_version: int | None = None,
) -> CollectorAccountPolicy:
    ...
```

普通任务要求 healthy + active version；validation 和 health-check 按设计例外。把检查接入所有任务创建、scheduler、claim、batch 和终态提交。

- [ ] **步骤 4：删除运行时账号常量依赖**

保留常量仅供迁移脚本导入，不再由 scheduler 和 service 查询。

- [ ] **步骤 5：验证和提交**

```powershell
python -m pytest tests/test_fetch_policy.py tests/test_fetch_scheduler.py tests/test_collector_router.py -q
git add backend/app/collectors backend/tests 问题修改.md
git commit -m "feat: 统一所有拉取入口的账号策略"
```

## 任务 5：重构授权链接和 callback 状态机

**文件：**
- 修改：`backend/app/collectors/oauth_service.py`
- 修改：`backend/app/collectors/schemas.py`
- 修改：`backend/app/collectors/router.py`
- 修改：`backend/tests/test_oauth_service.py`
- 修改：`backend/tests/test_collector_router.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写授权流程失败测试**

覆盖：健康账号默认 409、force reason 必填、同账号并行 state 409、首次/revoked URL 含 `prompt=consent`、revoked callback 无新 token 返回 422、健康旧版本不被失败重授权覆盖、callback 只进入 validation_pending。

- [ ] **步骤 2：验证旧实现错误通过或错误行为**

运行：`cd backend; python -m pytest tests/test_oauth_service.py -q`

- [ ] **步骤 3：实现授权请求 schema 和一次性 state**

```python
class AuthorizationUrlRequest(BaseModel):
    force_reauthorize: bool = False
    reason: str | None = None
```

生成 URL 时根据 runtime status 决定 prompt。callback 消费 state，兑换结果只有新 refresh token 才创建 staged 凭据；不持久化 access token。

- [ ] **步骤 4：保证事件脱敏**

事件 metadata 不包含 code、callback URL、token 响应或 Google 原始 body。

- [ ] **步骤 5：验证和提交**

```powershell
python -m pytest tests/test_oauth_service.py tests/test_collector_router.py -q
git add backend/app/collectors backend/tests 问题修改.md
git commit -m "feat: 增加受验证的 OAuth 授权状态机"
```

## 任务 6：实现结构化 OAuth 错误分类

**文件：**
- 创建：`backend/app/collectors/oauth_errors.py`
- 创建：`collector/app/oauth_errors.py`
- 修改：`collector/app/oauth.py`
- 创建：`backend/tests/test_oauth_errors.py`
- 修改：`collector/tests/test_oauth.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写分类失败测试**

表驱动输入和期望：

```python
CASES = [
    ("authorization_code", "invalid_grant", None, "oauth_code_invalid"),
    ("refresh_token", "invalid_grant", None, "oauth_refresh_revoked"),
    ("refresh_token", "invalid_grant", "invalid_rapt", "oauth_session_expired"),
    ("refresh_token", "invalid_client", None, "oauth_client_invalid"),
]
```

另测 429、5xx、timeout 和数据契约错误。

- [ ] **步骤 2：实现 `OAuthFailure` 和安全消息**

异常字段只含 failure_class、retryable、http_status、error_subtype 和固定 public_message。禁止存储原始 token 请求。

- [ ] **步骤 3：验证和提交**

```powershell
cd backend; python -m pytest tests/test_oauth_errors.py -q
cd ..\collector; python -m pytest tests/test_oauth.py -q
git add backend/app/collectors/oauth_errors.py collector/app/oauth.py collector/app/oauth_errors.py backend/tests collector/tests 问题修改.md
git commit -m "feat: 分类并脱敏 OAuth 运行错误"
```

## 任务 7：实现 staged 凭据验证、Network API 和 ACK

**文件：**
- 创建：`collector/app/oauth_validation.py`
- 修改：`collector/app/admanager_soap.py`
- 修改：`collector/app/control_plane_client.py`
- 修改：`collector/app/models.py`
- 修改：`collector/app/runtime.py`
- 修改：`backend/app/collectors/router.py`
- 修改：`backend/app/collectors/oauth_service.py`
- 修改：`backend/app/collectors/schemas.py`
- 创建：`collector/tests/test_oauth_validation.py`
- 修改：`collector/tests/test_runtime.py`
- 修改：`backend/tests/test_oauth_service.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写验证顺序和 ACK 失败测试**

验证 refresh grant、scope、NetworkService、network code、时区；旧版本 ACK、错误指纹和重复 ACK 返回 409。

- [ ] **步骤 2：实现验证任务类型**

`oauth_credential_validate` runtime config 只解密当前 staged 版本，并携带 `credential_version` 和 fingerprint。collector 使用账号 SOCKS5 代理完成验证。

- [ ] **步骤 3：实现 ACK endpoint 和激活事务**

```text
POST /api/v1/collector/oauth/credential-ack
```

ACK 成功后旧 active -> retired，新 staged -> active，OAuth runtime -> degraded，同步 network timezone，创建 `oauth_health_check`。

- [ ] **步骤 4：验证秘密不泄露**

对日志、API JSON、任务 message 和事件 metadata 扫描测试 token 值，必须零命中。

- [ ] **步骤 5：验证和提交**

```powershell
cd collector; python -m pytest tests/test_oauth_validation.py tests/test_runtime.py -q
cd ..\backend; python -m pytest tests/test_oauth_service.py -q
git add backend collector 问题修改.md
git commit -m "feat: 验证并激活版本化 OAuth 凭据"
```

## 任务 8：切换为唯一 direct collector 拉取路径

**文件：**
- 修改：`backend/app/collectors/service.py`
- 修改：`backend/app/collectors/scheduler.py`
- 修改：`backend/app/config.py`
- 修改：`collector/app/vps_api.py`
- 修改：`deploy/vps/php/fetch.php`
- 修改：`backend/tests/test_collector_router.py`
- 修改：`backend/tests/test_fetch_scheduler.py`
- 修改：`collector/tests/test_vps_api.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写失败测试证明不会调用 `/ke/fetch.php`**

手工和自动 schedule 应只创建控制面任务并启动一个 runtime。节点旧入口在 `ADX_DIRECT_COLLECTOR_ONLY=true` 时返回 409 `FETCH_PATH_DISABLED`。

- [ ] **步骤 2：实现 direct-only feature flag**

默认 `direct_collector_only=True`。删除 `trigger_manual_fetch` 对 `httpx.get(.../ke/fetch.php)` 的调用，使用控制面生成的 request ID。

- [ ] **步骤 3：验证任务去重和单路径**

同账号/日期并发请求只能有一个 active task，不产生节点 fetch run。

- [ ] **步骤 4：验证和提交**

```powershell
cd backend; python -m pytest tests/test_collector_router.py tests/test_fetch_scheduler.py -q
cd ..\collector; python -m pytest tests/test_vps_api.py -q
git add backend collector deploy 问题修改.md
git commit -m "feat: 统一使用 direct collector 拉取数据"
```

## 任务 9：实现受控复验、熔断和健康恢复

**文件：**
- 修改：`backend/app/collectors/fetch_policy.py`
- 修改：`backend/app/collectors/oauth_service.py`
- 修改：`backend/app/collectors/service.py`
- 修改：`collector/app/runtime.py`
- 创建：`backend/tests/test_oauth_circuit_breaker.py`
- 修改：`collector/tests/test_runtime.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写熔断状态机失败测试**

首次 refresh revoked 创建一次复验；复验失败保存 resume 快照、revoked、invalid_grant、禁用 schedule、block pending；重复错误不覆盖快照、不重复告警。

- [ ] **步骤 2：实现 collector 安全失败上报**

任务失败上报结构化 `failure_class`，不发送 `str(exc)` 原文。

- [ ] **步骤 3：实现健康任务恢复**

health-check 成功后 runtime -> healthy，只清除 invalid_grant，恢复 resume 开关和四小时错峰 schedule，清空快照并创建缺口扫描。

- [ ] **步骤 4：测试人工停拉不可解除**

manual、account_banned、retired 保持停拉，即使新 token 验证成功。

- [ ] **步骤 5：验证和提交**

```powershell
cd backend; python -m pytest tests/test_oauth_circuit_breaker.py tests/test_fetch_policy.py -q
cd ..\collector; python -m pytest tests/test_runtime.py -q
git add backend collector 问题修改.md
git commit -m "feat: 熔断并安全恢复失效 OAuth 账号"
```

## 任务 10：实现凭据和 policy 迁移工具

**文件：**
- 创建：`backend/app/scripts/__init__.py`
- 创建：`backend/app/scripts/migrate_oauth_credentials.py`
- 创建：`backend/app/scripts/migrate_collector_account_policies.py`
- 创建：`backend/tests/test_migrate_oauth_credentials.py`
- 创建：`backend/tests/test_migrate_collector_account_policies.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写幂等和回滚失败测试**

凭据迁移成功后 legacy secret/token/access token 为空；重复执行不新增版本；任一账号解密回读失败则整体回滚。policy 冲突时不写入任何账号。

- [ ] **步骤 2：实现命令和脱敏报告**

报告只输出 account_id、version、fingerprint、policy status。不得输出账号 OAuth code、secret、token 和代理密码。

- [ ] **步骤 3：实现迁移后验证任务创建**

迁移成功账号为 unknown，创建一个 credential validation task，schedule 保持禁用直到恢复闭环完成。

- [ ] **步骤 4：验证和提交**

```powershell
cd backend
python -m pytest tests/test_migrate_oauth_credentials.py tests/test_migrate_collector_account_policies.py -q
git add backend/app/scripts backend/tests 问题修改.md
git commit -m "feat: 迁移 OAuth 凭据和账号拉取策略"
```

## 任务 11：实现缺口扫描和串行回补

**文件：**
- 修改：`backend/app/collectors/service.py`
- 修改：`backend/app/collectors/scheduler.py`
- 创建：`backend/tests/test_recovery_gap_backfill.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写失败测试**

测试已完整日期不创建任务、缺失小时优先、成熟权威日报其次、同账号串行、不同账号不在同轮无界启动。

- [ ] **步骤 2：实现 gap scan 结果**

以 coverage、UTC 水位和成功 authoritative task 为依据生成缺口，不使用“最近三天全部重跑”。

- [ ] **步骤 3：实现串行队列约束**

每账号最多一个 active recovery task；本机首版全局恢复并发为 1，完成一个账号后再领取下一个。

- [ ] **步骤 4：验证和提交**

```powershell
cd backend; python -m pytest tests/test_recovery_gap_backfill.py tests/test_fetch_scheduler.py -q
git add backend/app/collectors backend/tests 问题修改.md
git commit -m "feat: 按真实缺口串行恢复 OAuth 延迟数据"
```

## 任务 12：增加前端授权健康和操作限制

**文件：**
- 修改：`frontend/src/types/api.ts`
- 修改：`frontend/src/lib/api.ts`
- 修改：`frontend/src/features/oauth/OAuthAppsSection.tsx`
- 修改：`frontend/src/lib/operatorGuidance.ts`
- 修改：`frontend/src/__tests__/oauth.test.ts`
- 创建：`frontend/src/__tests__/oauthHealth.test.tsx`
- 修改：`问题修改.md`

- [ ] **步骤 1：写失败组件测试**

验证 healthy 需要确认和 reason、revoked 显示恢复、validation_pending 禁止重复链接、degraded 显示健康任务、页面不渲染秘密字段。

- [ ] **步骤 2：实现类型和 UI**

显示 flow status、runtime status、版本、短指纹、failure class、last verified 和 next action。沿用现有紧凑表格，不新增营销式页面。

- [ ] **步骤 3：验证前端**

```powershell
cd frontend
npm test -- --run
npm run build
```

- [ ] **步骤 4：记录和提交**

```powershell
git add frontend 问题修改.md
git commit -m "feat: 展示 OAuth 健康与恢复状态"
```

## 任务 13：增加健康摘要、指标和告警数据

**文件：**
- 修改：`backend/app/collectors/schemas.py`
- 修改：`backend/app/collectors/router.py`
- 修改：`backend/app/collectors/oauth_service.py`
- 创建：`backend/tests/test_oauth_health_summary.py`
- 修改：`问题修改.md`

- [ ] **步骤 1：写失败 API 测试**

`GET /api/v1/operator/oauth/health-summary` 返回各 runtime status 账号数、failure class 计数、version mismatch、revoked task violations、小时和日报延迟，不返回秘密。

- [ ] **步骤 2：实现结构化摘要**

摘要使用数据库聚合，不为每个请求访问 Google。事件只保留一次首次告警和后续计数。

- [ ] **步骤 3：验证和提交**

```powershell
cd backend; python -m pytest tests/test_oauth_health_summary.py -q
git add backend/app/collectors backend/tests 问题修改.md
git commit -m "feat: 增加 OAuth 运行健康摘要"
```

## 任务 14：安全、兼容和全量验收

**文件：**
- 修改：`docs/2026-07-31-oauth-token-failure-remediation-review.md`
- 修改：`docs/superpowers/specs/2026-07-31-oauth-credential-control-plane-remediation-design.md`
- 修改：`问题修改.md`
- 修改：实现中发现的测试文件，不增加新业务范围。

- [ ] **步骤 1：运行秘密扫描**

```powershell
rg -n "1//|refresh_token\s*[:=]\s*['\"]|client_secret\s*[:=]\s*['\"]|4/0A" backend collector frontend docs 问题修改.md
```

只允许测试 fixture 的显式假 token；生产日志、响应和文档零命中真实凭据。

- [ ] **步骤 2：运行全量测试和构建**

```powershell
cd backend; python -m pytest -q
cd ..\collector; python -m pytest -q
cd ..\frontend; npm test -- --run; npm run build
```

预期全部通过，不能以生产基线旧失败为例外。

- [ ] **步骤 3：验证迁移演练**

使用临时 SQLite 副本执行 upgrade、凭据迁移、policy 迁移、验证任务、恢复任务和 downgrade schema 演练。核对 legacy secrets 已清空、policy 互斥、历史报表仍可查询。

- [ ] **步骤 4：审阅实现与规格**

逐条核对设计第 15 节 10 项验收标准，更新审阅文档为“本地实现完成，尚未生产发布”。

- [ ] **步骤 5：最终提交**

```powershell
git add docs 问题修改.md
git commit -m "docs: 记录 OAuth 凭据整改实现结果"
git status --short
```

预期工作树干净。
