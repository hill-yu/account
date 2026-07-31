# OAuth 凭据统一控制面整改设计

**日期：** 2026-07-31

**状态：** 已选择方案 1，等待书面规格确认

**适用分支：** `codex/oauth-token-remediation-v1`

**生产基线：** `588e38e chore: capture production source baseline`

## 1. 目标

首个版本一次性完成 [OAuth Token 反复失效解决方案审阅报告](../../2026-07-31-oauth-token-failure-remediation-review.md) 中的整改要求：

1. 控制面成为 OAuth 凭据唯一事实源。
2. 失效凭据无法继续从自动小时、自动日报、手工任务或补数入口创建和执行任务。
3. 重新授权不会复用已失效旧 token，也不会未经真实验证就恢复调度。
4. 同一账号只有一个有效授权流程和一个活动凭据版本。
5. OAuth 错误可分类、可熔断、可审计、可恢复。
6. 授权恢复后通过最小健康任务确认，再恢复四小时 schedule 并只补真实缺口。
7. refresh token、client secret 和 access token 不进入日志、API 响应、Git 或任务错误明文。

用户已人工确认所有 Google OAuth 应用均为正式发布状态，因此 `Testing` 状态导致的 7 天 refresh token 失效不属于本轮代码整改范围。系统仍保留 publishing status 运维字段和检查清单，防止新节点配置回退。

## 2. 非目标

本版本不执行以下事项：

1. 不发布到生产服务器，只在本地工作树实现和验证。
2. 不迁移 SQLite 到 PostgreSQL。
3. 不重构小时事实表、日报事实表或 batch 合并语义。
4. 不删除节点 MySQL 中的历史 token 字段；该字段保留兼容和回滚用途，但新运行链路不再读取。
5. 不自动解除 `manual`、`account_banned` 或 `retired` 等人工停拉状态。
6. 不进行无边界历史全量补数，只处理系统计算出的真实数据缺口。

## 3. 已确认的架构决策

### 3.1 唯一 Google 拉取路径

小时和权威日报统一使用 `direct_collector`：

```text
schedule / operator API
  -> control plane 创建任务
  -> collector runtime 领取任务和版本化凭据
  -> 账号绑定 SOCKS5 代理
  -> Google Ad Manager
  -> batch 回传 control plane
```

控制面不再通过节点 `/ke/fetch.php` 触发第二条 Google 拉取路径。节点 `/ke/report.php` 可在兼容期继续用于只读快照诊断，但中台本地权威日报 API 不依赖该快照。

这一决策同时消除以下问题：

- 控制面凭据和节点 MySQL 凭据漂移。
- 同一 schedule 同时触发节点抓取和 collector 抓取。
- 重新授权后必须人工更新每个节点数据库。
- 节点运行环境继续读取旧 refresh token。

### 3.2 凭据唯一事实源

OAuth Client ID、redirect URI、scope 和运维元数据保存在 `oauth_app_configs`。client secret 与 refresh token 保存在新增的加密版本表 `oauth_credentials`。

加密规则：

- 使用 `cryptography.fernet.Fernet` 对 client secret 和 refresh token 分别加密。
- 加密密钥只从环境变量 `ADX_CREDENTIAL_ENCRYPTION_KEY` 读取，不写入数据库或仓库。
- 使用独立环境变量 `ADX_CREDENTIAL_FINGERPRINT_KEY` 计算 HMAC-SHA256 指纹，UI 和日志只显示前 12 位指纹。
- access token 只存在于单次验证或采集进程内存中，不再持久化。
- API schema、异常文本和日志对象禁止包含密文、明文或完整指纹。

控制面每次只允许一个 `active` 凭据版本。新授权先创建 `staged` 版本，所有验证通过后再用一个数据库事务将旧版本设为 `retired`、新版本设为 `active`。

### 3.3 节点兼容策略

`collector/app/vps_models.py` 中 `adx_accounts.refresh_token` 暂时保留，但：

- `direct_collector` 不读取该字段。
- 新授权不再同步该字段。
- 节点 `/ke/fetch.php` 对受统一控制面的账号返回 `409 FETCH_PATH_DISABLED`，避免误触发旧链路。
- 回滚 feature flag `ADX_DIRECT_COLLECTOR_ONLY=false` 仅允许在明确维护窗口使用，不自动回退到节点旧 token。

## 4. 数据模型

### 4.1 `oauth_app_configs` 扩展字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `flow_status` | string | `pending/requested/exchange_failed/validation_pending/completed` |
| `runtime_status` | string | `unknown/healthy/degraded/revoked/policy_blocked/migration_required` |
| `active_credential_version` | integer nullable | 当前活动版本 |
| `pending_credential_version` | integer nullable | 当前待验证版本 |
| `failure_class` | string nullable | 最近一次结构化失败分类 |
| `failure_count` | integer | 连续失败次数 |
| `last_verified_at` | datetime nullable | 最近真实验证成功时间 |
| `revoked_at` | datetime nullable | 确认失效时间 |
| `publishing_status` | string | 固定记录 `in_production`，新节点接入必填 |
| `next_action` | string nullable | 面向运维的下一步动作代码 |

现有 `authorization_status` 在兼容期继续返回，但由新状态派生：

- `healthy -> authorized`
- `revoked -> revoked`
- `validation_pending -> validation_pending`
- 其他状态保持原授权流程语义

### 4.2 `oauth_credentials`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | integer | 主键 |
| `oauth_app_id` | integer | 外键 |
| `version` | integer | 同一 OAuth App 唯一递增 |
| `status` | string | `staged/active/retired/rejected/revoked` |
| `client_secret_ciphertext` | text | 非空 |
| `refresh_token_ciphertext` | text | 非空 |
| `token_fingerprint` | string | 非空，不保存明文 hash 输入 |
| `granted_scopes` | text | Google 实际返回 scope |
| `created_at` | datetime | 非空 |
| `validated_at` | datetime nullable | Network API 验证成功时间 |
| `activated_at` | datetime nullable | 正式启用时间 |
| `retired_at` | datetime nullable | 退出使用时间 |

数据库唯一约束保证 `(oauth_app_id, version)` 唯一。SQLite/PostgreSQL 分别使用条件唯一索引保证每个 OAuth App 最多一个 `active` 和一个 `staged` 版本，服务层仍在事务中复验并提供并发测试。

### 4.3 `collector_account_policies`

| 字段 | 类型 | 含义 |
|---|---|---|
| `account_id` | integer | 唯一账号 |
| `lifecycle_status` | string | `onboarding/active/suspended/retired` |
| `gray_enabled` | boolean | 是否灰度 |
| `hourly_fetch_enabled` | boolean | 自动小时 |
| `authoritative_daily_enabled` | boolean | 自动权威日报 |
| `manual_fetch_enabled` | boolean | 是否允许手工拉取 |
| `exclusion_reason` | string nullable | `invalid_grant/manual/account_banned/no_source_data/retired` |
| `exclusion_note` | text nullable | 脱敏说明 |
| `resume_gray_enabled` | boolean | 熔断前灰度开关快照 |
| `resume_hourly_fetch_enabled` | boolean | 熔断前小时开关快照 |
| `resume_authoritative_daily_enabled` | boolean | 熔断前日报开关快照 |
| `policy_version` | integer | 乐观并发控制 |
| `updated_at` | datetime | 最近变更时间 |

规则：

- `exclusion_reason` 非空时，所有会访问 Google 的入口默认禁止。
- `manual`、`account_banned` 和 `retired` 只能由运维显式解除。
- OAuth 恢复流程只能清除 `invalid_grant`。
- `gray_enabled=true` 与任何停拉原因互斥。
- 历史数据查询不受 acquisition policy 影响。
- 首次熔断在同一事务中保存三个 resume 快照；重复错误不得覆盖快照。
- 健康恢复只从 resume 快照恢复开关，恢复后清空快照。

### 4.4 `oauth_events`

用于审计授权链接生成、callback、验证、熔断、恢复和凭据版本切换。只保存账号、事件类型、版本、失败分类、HTTP 状态、时间和脱敏 metadata，不保存 token、code、client secret 或完整 callback URL。

## 5. OAuth 授权流程

### 5.1 生成授权链接

`POST /api/v1/operator/oauth-apps/{id}/authorization-url` 接受：

```json
{
  "force_reauthorize": false,
  "reason": "revoked_token_recovery"
}
```

行为：

1. 未存在活动凭据或 `runtime_status=revoked` 时加入 `prompt=consent`。
2. `runtime_status=healthy` 时默认返回 `409 OAUTH_REAUTH_CONFIRMATION_REQUIRED`；只有 `force_reauthorize=true` 且 reason 非空才生成强制授权链接。
3. 同一 OAuth App 已存在未过期 state 时返回 `409 OAUTH_FLOW_ALREADY_ACTIVE`，不生成第二个 state。
4. 新 state 使 `flow_status=requested`，但不改变当前活动凭据和 schedule。
5. state 仍为高熵随机值，十分钟过期且 callback 成功或失败后立即消费。

### 5.2 callback 和授权码兑换

callback 必须校验 state、过期时间、issuer、redirect URI 和一次性消费状态。

授权码兑换结果处理：

- Google 返回新 refresh token：创建下一个 `staged` 凭据版本，状态进入 `validation_pending`。
- `runtime_status=revoked` 或没有活动凭据，但 Google 未返回新 refresh token：返回 `422 OAUTH_NEW_REFRESH_TOKEN_REQUIRED`，不得复用旧 token。
- 当前凭据仍健康但强制重授权未返回新 refresh token：保留原活动版本，记录本次尝试失败，不中断已有 schedule。
- 兑换阶段的 `invalid_grant` 归类为 `oauth_code_invalid`，不能把运行凭据标记为 revoked。

callback 返回 `validation_pending`，不再在授权码兑换成功后直接返回 `authorized`。

## 6. 凭据验证与激活

### 6.1 验证任务

callback 创建 `oauth_credential_validate` 控制面任务。该任务只能领取对应 `staged` 版本，且不能读取其他账号凭据。

验证顺序固定为：

1. 使用账号绑定 SOCKS5 代理调用 Google token endpoint，执行 refresh grant。
2. 校验 access token 响应、scope 和 token 类型。
3. 通过同一代理调用 Google Ad Manager NetworkService `getCurrentNetwork()`。
4. 校验返回 network code 等于 `accounts.external_account_id`。
5. 读取真实 Network 时区并与 `accounts.timezone` 比较；不一致时在激活事务中同步。
6. 提交 credential ACK，包含账号、任务、凭据版本、指纹、network code 和时区，不含秘密。

任何一步失败，新版本设为 `rejected`，原活动版本不受影响。如果账号原状态为 revoked，则继续保持熔断。

### 6.2 激活事务

ACK 验证通过后在一个事务中：

1. 锁定 OAuth App 和账号 policy。
2. 确认 ACK 版本仍是当前 `pending_credential_version`。
3. 旧活动版本设为 `retired`。
4. staged 版本设为 `active`。
5. 更新 `active_credential_version`、`last_verified_at` 和 Network 时区。
6. `runtime_status` 进入 `degraded`，表示凭据有效但业务健康任务尚未通过。
7. 创建最小健康任务。

迟到 ACK、旧版本 ACK 或指纹不匹配返回 `409 STALE_CREDENTIAL_ACK`。

### 6.3 最小健康任务

最小健康任务使用新活动版本拉取一个已成熟、数据量可控的业务日期。成功标准是 Google 报表完成、batch schema 合法且任务进入终态；零行允许作为技术成功，但必须有显式 coverage 结果。

健康任务成功后：

- `runtime_status=healthy`
- 仅当 `exclusion_reason=invalid_grant` 时清除该原因
- 恢复账号原先的灰度、小时和权威日报开关
- 按账号四小时周期重新计算错峰 `next_run_at`
- 创建缺口扫描任务

健康任务失败时保持 `degraded` 和 schedule 禁用，不自动无限重试。

## 7. 统一拉取策略门

新增单一服务接口：

```python
assert_fetch_allowed(db, *, account_id, fetch_kind, credential_version=None)
```

必须由以下入口调用：

1. 自动小时 schedule 扫描。
2. 自动权威日报扫描。
3. 手工小时和手工日报。
4. targeted-recent 及其他补数接口。
5. 任务创建通用服务。
6. collector 领取任务。
7. runtime 配置获取。
8. batch 和终态提交。

检查内容：

- lifecycle、灰度和相应 fetch 开关。
- exclusion reason。
- 普通采集任务要求 OAuth runtime status 为 `healthy`。
- `oauth_credential_validate` 是受控例外，只允许当前 staged 版本。
- `oauth_health_check` 是受控例外，只允许当前 active 版本且 runtime status 为 `degraded`。
- 活动凭据版本必须存在。
- worker 使用的版本必须等于活动版本。

任务创建前检查用于避免浪费；领取和提交时复验用于阻止停拉后已经排队或迟到 worker 继续写入。

## 8. 错误分类和熔断

统一 `failure_class`：

| 分类 | 是否重试 | 动作 |
|---|---|---|
| `oauth_refresh_revoked` | 否 | 受控复验一次，确认后熔断 |
| `oauth_code_invalid` | 否 | 只结束本次授权流程 |
| `oauth_client_invalid` | 否 | policy_blocked，等待修复 Client 配置 |
| `oauth_policy_blocked` | 否 | policy_blocked，展示管理员策略原因 |
| `oauth_session_expired` | 否 | revoked，要求重新授权 |
| `source_rate_limited` | 是 | 遵守 Retry-After，有界退避 |
| `source_server_error` | 是 | 有界退避，最多三次 |
| `transport_error` | 是 | 有界退避，代理和 DNS 告警 |
| `data_contract_error` | 否 | 任务失败，不撤销 OAuth |

`invalid_grant` 必须结合请求阶段和 `error_subtype` 分类。运行时 refresh grant 首次出现不可重试错误后，仅允许控制面执行一次受控复验；复验仍失败才执行熔断：

1. `runtime_status=revoked`。
2. `exclusion_reason=invalid_grant`。
3. 保存原灰度和 schedule 开关用于恢复。
4. 禁用小时和权威日报 schedule。
5. 将未开始任务标记为 `blocked`，原因只保存 failure class。
6. 运行中任务不再允许提交 batch 或成功终态。
7. 写入一次告警事件，重复错误只增加计数，不重复告警和入队。

## 9. 凭据迁移

Alembic 迁移只创建新表和字段，不在 migration 脚本中读取环境密钥或搬运秘密。

新增一次性命令 `python -m app.scripts.migrate_oauth_credentials`：

1. 要求两个加密环境变量存在。
2. 逐账号读取现有 client secret 和 refresh token。
3. 创建 version 1 的加密 `active` 凭据。
4. 计算指纹并回读解密校验。
5. 设置 `runtime_status=unknown` 和 `next_action=validate_existing_credential`。
6. 全部账号迁移成功后，清空 legacy secret/token/access-token 字段。
7. 输出仅包含账号 ID、版本和指纹的迁移报告。

同一发布还提供 `python -m app.scripts.migrate_collector_account_policies`：

1. 从当前灰度常量、invalid-grant 常量、人工停拉常量和 `fetch_schedules` 生成初始 policy。
2. 发现同一账号同时灰度和停拉时终止迁移并输出账号 key，不自行选择优先级。
3. policy 写入完成后，运行代码不再读取这些账号常量。
4. 凭据迁移完成后为 `runtime_status=unknown` 的活动账号创建一次验证任务；验证通过前不恢复自动 schedule。

迁移命令幂等。已存在活动版本的账号不重复创建。任何账号失败则整体事务回滚，不产生半迁移状态。

本地测试使用临时 Fernet 密钥。生产发布前必须先备份控制库，并通过独立 secret 注入工具配置密钥。

## 10. 缺口恢复

账号恢复 healthy 后，控制面根据以下信息生成缺口：

- 小时目标 UTC 水位与本地实际水位。
- coverage manifest 中的缺失小时。
- Google Network 时区下已成熟但无成功 `report_fetch` 的权威日报日期。

恢复任务按账号串行，优先级顺序：

1. 最小健康任务。
2. 最新小时缺口。
3. 已成熟权威日报。
4. 更早历史缺口。

不按“最近三天全部重跑”生成任务，不重拉已经证明完整的日期。每完成一个账号后检查 CPU、内存、队列和数据库写入压力。

## 11. API 和前端

OAuth 列表新增非敏感字段：

- `flow_status`
- `runtime_status`
- `active_credential_version`
- `credential_fingerprint`
- `failure_class`
- `failure_count`
- `last_verified_at`
- `publishing_status`
- `next_action`

前端 OAuth 页面显示授权流程和运行健康两个状态，不再只显示 `authorization_status` 和 token present。操作按钮规则：

- healthy：显示“重新授权”，点击后要求明确确认和原因。
- revoked：显示“恢复授权”。
- validation_pending：禁用重复生成链接，显示验证中。
- degraded：显示健康任务状态，不允许恢复 schedule。
- policy_blocked：显示需要修复的 Client 或管理员策略。

前端不得显示或复制 token、client secret、密文和完整指纹。

## 12. 可观测性和告警

首版必须提供可查询指标或结构化计数：

- `oauth_refresh_failure_total{failure_class}`
- `oauth_runtime_status_accounts{status}`
- `oauth_credential_version_mismatch_total`
- `revoked_account_task_created_total`
- `hourly_watermark_lag_hours`
- `authoritative_daily_lag_hours`

告警规则：

- 首次确认 `oauth_refresh_revoked`：立即告警一次。
- revoked 账号创建或领取到任务：P0。
- 控制面与 worker credential version 不一致：P0。
- 小时水位超过调度周期加两小时：告警并生成缺口。
- 权威日报成熟四小时后仍无成功结果：告警。

## 13. 测试策略

全部行为按 TDD 实现。必须覆盖：

1. revoked 账号 callback 无新 refresh token 不得恢复。
2. 健康账号强制授权未取得新 token 时保留旧活动版本。
3. 同一账号不能并行生成两个有效 state。
4. 普通健康账号生成授权链接需要显式确认；首次和 revoked 流程包含 `prompt=consent`。
5. staged 凭据验证失败不影响旧活动版本。
6. refresh grant、scope、network code、时区和 ACK 全部通过才激活。
7. 迟到版本和指纹不匹配的 ACK 被拒绝。
8. 所有任务入口都拒绝 revoked、manual stop 和 credential mismatch。
9. OAuth 恢复只清除 `invalid_grant`。
10. 错误分类覆盖 code invalid、refresh revoked、invalid_rapt、invalid_client、429、5xx 和网络异常。
11. 迁移命令加密、幂等、失败整体回滚且清除 legacy secrets。
12. 日志、API 和任务错误不泄露秘密。
13. 前端正确显示状态并限制操作。
14. 恢复只创建真实缺口，使用四小时错峰 schedule。

生产基线当前已有 `10` 个后端和 `17` 个 collector 测试因实现与测试漂移而失败。实现前先用独立提交同步这些旧测试与生产真实行为，不改变运行代码。最终发布门槛是 backend、collector 和 frontend 全部测试通过。

## 14. 发布与回滚设计

虽然本轮只改本地，代码必须具备以下生产发布顺序：

1. 发布数据库 schema 和只读兼容代码。
2. 配置加密和指纹密钥。
3. 停止 scheduler，备份数据库，运行凭据迁移并核对报告。
4. shadow 模式验证策略门，不阻断任务但记录差异。
5. 单个灰度账号切换 direct collector，完成凭据和数据对账。
6. 扩大灰度，确认节点旧 `/ke/fetch.php` 不再收到调用。
7. 全量启用统一策略门和熔断。

回滚时：

- 保留加密凭据表和审计记录，不把秘密重新复制到日志或 Git。
- 可回退应用代码和策略 enforcement，但不得自动恢复已确认 revoked 的旧 token。
- 节点旧链路只能在维护窗口显式启用，并要求人工确认节点 token 版本。

## 15. 验收标准

1. 控制面是运行时 refresh token 唯一事实源，节点 MySQL token 不再被读取或更新。
2. 同一账号最多一个活动凭据版本和一个有效授权流程。
3. callback 不会把失效旧 token 误标记为 authorized。
4. 不可重试运行时授权错误最多产生一次受控复验、一次熔断和一次告警。
5. revoked 账号无法通过任何入口创建、领取或提交拉数任务。
6. 重新授权经过 refresh grant、Network API、版本 ACK 和最小健康任务后才恢复调度。
7. 恢复不会解除人工停拉，只补真实小时和日报缺口。
8. API、日志、Git 和错误信息不包含 OAuth 秘密。
9. backend、collector、frontend 测试全部通过。
10. 连续 14 天没有同原因批量 `invalid_grant`；真实外部撤销能被首次发现后立即隔离，不形成重复任务风暴。
