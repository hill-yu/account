# OAuth Token 反复失效解决方案审阅报告

版本：1.0

审阅日期：2026-07-31

审阅对象：[ADX 中台生产运维问题清单与整改方案](2026-07-30-production-operations-problems-and-remediation.md)，重点审阅 `OPS-08：授权失败没有熔断` 及其关联实现。

## 1. 审阅结论

方案提出的错误分级、失效熔断、重新授权后最小健康验证、人工停拉与授权恢复互不覆盖等方向是正确的，但当前版本**不能直接作为完整实施方案验收通过**。

最关键的问题不是“系统不会刷新 access token”。现有采集器已经能使用 refresh token 换取短期 access token。真正需要解决的是：

1. 为什么 refresh token 会反复失效。
2. 如何确保新 refresh token 被正确验证并同步到实际执行链路。
3. 如何在首次确认失效后立即停止所有自动和手工拉取入口。
4. 如何在恢复后只补真实缺口，并证明数据水位恢复。

在补齐本文列出的 P0、P1 项之前，重复重新授权只能暂时恢复，不能保证问题不再周期性发生。

## 2. 必须修正的问题

### P0-1：没有把 OAuth consent screen 的 `Testing` 状态列为首要根因

Google 官方明确说明：外部用户类型的 OAuth 应用如果发布状态为 `Testing`，且请求了 Ad Manager scope，签发的 refresh token 通常会在 7 天后失效。当前方案只描述“收到 `invalid_grant` 后熔断”，没有要求核对每个 OAuth Client 所属项目的发布状态，因此无法消除周期性失效根因。

这与近期“多个节点重新授权后又集中失效”的表现高度吻合，但在读取 Google Cloud Console 实际配置前只能视为高优先级待验证假设，不能直接认定为唯一根因。

必须增加：

1. 为每个节点登记 `google_cloud_project_id`、OAuth Client ID、用户类型和 publishing status。
2. 生产节点必须使用 `In production` 的 OAuth consent screen；如属于 Workspace 内部应用，则记录组织和管理员策略。
3. 上线前检查该节点是否获得了基于时间的授权，并保存 Google 返回的 `refresh_token_expires_in`（若返回）。
4. 禁止仅靠定期重新授权规避 7 天失效。

依据：[Google OAuth 2.0 官方说明](https://developers.google.com/identity/protocols/oauth2#expiration)。

### P0-2：授权回调会保留旧 refresh token，并可能产生“假恢复”

当前实现位于 [`backend/app/collectors/oauth_service.py`](../backend/app/collectors/oauth_service.py)：

- 第 278 行在 token 响应未包含 refresh token 时回退使用数据库中的旧值。
- 第 281 行随后直接把状态设为 `authorized`。
- 第 295 至 297 行提交数据库后立即返回成功。

如果账号原 refresh token 已经 `invalid_grant`，而本次授权码兑换没有返回新 refresh token，系统会继续保存旧 token，同时向前端报告授权成功。这会直接造成“刚授权成功，拉数仍失败”。

必须修改为：

1. 对 `revoked`、`authorization_failed` 或已确认 `invalid_grant` 的账号，回调响应没有新 refresh token 时必须判定恢复失败，不能复用旧值。
2. 新 token 入库前后必须执行一次真实 refresh grant，再调用一个最小只读 Google Network API 验证 scope、账号身份和 network code。
3. 只有验证通过后才能写入 `authorized`；验证失败时保留停拉状态和失败分类。
4. 不应把“数据库中 token 非空”等同于“token 可用”。

### P0-3：当前没有覆盖所有入口的统一授权熔断

方案要求失效 token 不再进入任务队列，但当前代码没有实现这一保证：

- [`backend/app/collectors/scheduler.py`](../backend/app/collectors/scheduler.py) 第 195 至 228 行处理小时 schedule 时不检查 `authorization_status` 或统一停拉策略。
- [`backend/app/collectors/service.py`](../backend/app/collectors/service.py) 第 1030 至 1105 行的 targeted-recent 回补入口不检查授权状态或停拉原因。
- 同文件第 589 至 704 行的手工拉取只检查节点 report 配置，没有检查账号是否被授权熔断。
- 自动日报主要依赖代码常量排除；授权状态、灰度、手工停拉和 schedule 仍不是单一事实源。

结果是：即使某一入口把节点移出灰度，其他入口仍可能创建任务或启动采集进程。

必须建立数据库策略状态并让以下入口共用一个 `assert_fetch_allowed(account_id, fetch_kind)`：

1. 自动小时 schedule。
2. 自动权威日报。
3. targeted-recent 和其他补数接口。
4. 手工小时和手工日报。
5. runtime 领取任务和 batch 提交。

授权熔断应在创建任务之前执行，worker 领取时再复验一次。人工永久停拉的优先级必须高于授权恢复。

### P0-4：运行时错误没有结构化分类，无法可靠自动熔断

[`collector/app/oauth.py`](../collector/app/oauth.py) 当前直接调用 `response.raise_for_status()`。它没有解析 Google 响应中的 `error`、`error_description` 和 `error_subtype`，也没有把账号、OAuth Client、token 指纹、请求阶段等结构化信息回传控制面。

因此系统无法可靠区分：

- refresh token 已撤销或到期。
- OAuth Client 配置错误。
- Workspace 会话策略导致的 `invalid_rapt`。
- 授权码重复使用、过期或 redirect URI 不匹配。
- 代理、DNS、超时、Google 5xx 等可重试错误。

必须定义统一 `failure_class`，至少包含 `oauth_refresh_revoked`、`oauth_code_invalid`、`oauth_client_invalid`、`oauth_policy_blocked`、`transport_error`、`source_rate_limited` 和 `source_server_error`。只有受控 refresh grant 复验仍返回不可重试授权错误时，才能把账号设为 `revoked`。

## 3. 重要改进项

### P1-1：控制面和节点库存在两个 token 副本，缺少版本与确认机制

控制面使用 `oauth_app_configs.refresh_token`，节点抓取链路还会使用节点 MySQL `adx_accounts.refresh_token`。重新授权后依赖人工同步，正是反复使用旧 token 的主要风险之一。

推荐以控制面 secret store 为唯一事实源。节点只在任务执行时获取短期、版本化运行配置，不再永久保存 refresh token。若短期内必须双存，至少增加：

- `credential_version` 或不可逆 token fingerprint。
- 原子更新记录、节点同步任务和节点 ACK。
- 控制面版本与节点实际版本不一致时禁止恢复 schedule。
- 凭据更新审计，但日志不得记录 token 明文。

### P1-2：授权状态模型不足

[`backend/app/models/oauth_app_config.py`](../backend/app/models/oauth_app_config.py) 目前只描述 `pending`、`authorization_requested`、`authorized`、`authorization_failed`，没有实际定义方案中使用的 `revoked`，也没有 `last_verified_at`、`failure_class`、`failure_count`、`token_fingerprint`、`credential_version`、`revoked_at` 和 `next_action`。

建议将“授权流程状态”和“运行健康状态”分开：

- 授权流程：`pending / requested / exchange_failed / completed`。
- 运行健康：`unknown / healthy / degraded / revoked / policy_blocked`。

这样可以避免一次授权码兑换失败覆盖原本仍可用的运行 token，也能避免授权码成功就被误认为运行链路健康。

### P1-3：重新授权后的恢复流程缺少完整事务边界

建议采用以下恢复顺序：

1. 兑换到新的 refresh token，写入暂存版本。
2. 使用该版本真实换取 access token。
3. 通过节点绑定的 SOCKS5 代理调用 Google Network API，核对 network code、scope 和网络时区。
4. 发布凭据版本，并确认实际执行节点已加载同一 fingerprint。
5. 清除且只清除 `invalid_grant` 熔断原因。
6. 创建最小健康任务，成功后恢复灰度和四小时 schedule。
7. 根据数据水位生成缺口清单，按账号串行补小时和已成熟权威日报。

任何一步失败都不得恢复 schedule，也不能覆盖人工停拉或永久停用状态。

### P1-4：缺少对“重复授权造成旧 token 被顶掉”的治理

当前授权 URL 使用 `prompt=consent`，频繁重新授权会持续签发 refresh token。Google 对同一 Google 账号和 OAuth Client ID 的有效 refresh token 数量有限，超过限制时会在无提示的情况下使最旧 token 失效。

必须：

1. 禁止把重新授权作为日常健康检查。
2. 每个节点只保留一个当前生效的凭据版本。
3. 授权链接应有操作者、节点、过期时间和一次性使用审计。
4. 不允许同一节点并行生成多个待处理授权 state。

依据：[Google refresh token 有效性和数量限制](https://developers.google.com/identity/protocols/oauth2#expiration)。

### P1-5：告警只写了原则，缺少可执行阈值和数据延迟闭环

建议至少落地以下指标：

| 指标 | 告警条件 | 自动动作 |
|---|---|---|
| `oauth_refresh_failure_total` | 首次不可重试授权错误 | 受控复验一次，确认后熔断 |
| `oauth_credential_version_mismatch` | 控制面与执行节点版本不一致 | 禁止恢复 schedule |
| `hourly_watermark_lag` | 超过当前调度周期加 2 小时 | 告警并生成缺口，不盲目全量重跑 |
| `authoritative_daily_lag` | 成熟后 4 小时仍无成功任务 | 告警并排队补拉 |
| `revoked_account_task_created_total` | 大于 0 | P0 告警，说明入口绕过策略 |

## 4. 测试与验收缺口

现有测试主要覆盖授权 URL、授权码兑换和 access token 刷新成功路径，没有覆盖生产事故的关键场景。实施前必须补齐：

1. 已 revoked 账号兑换响应无 refresh token 时不得恢复。
2. 新 refresh token 验证失败时不得写 `authorized`。
3. `invalid_grant` 与 `invalid_rapt`、`invalid_client`、HTTP 429、5xx、超时分类正确。
4. 同一账号并发回调只有一个凭据版本生效。
5. 熔断账号无法从自动小时、自动日报、手工接口和 targeted-recent 创建任务。
6. 重新授权只解除 `invalid_grant`，不会解除人工停拉。
7. 控制面与节点 credential version 不一致时不能恢复任务。
8. 恢复后只补缺失窗口，不重复拉取已完整数据。
9. 日志、API 响应和任务错误中不包含 client secret 或 refresh token。

验收不能只看 `authorization_status=authorized`。最终标准应同时满足：

- refresh grant 成功。
- Google Network API 最小调用成功且 network code 匹配。
- 实际执行节点使用的 credential version/fingerprint 与控制面一致。
- 最小健康任务成功。
- 小时水位和已成熟权威日报恢复到目标范围。
- 连续 14 天没有同原因批量 `invalid_grant`，且熔断账号没有新增拉取任务。

## 5. 建议后的最终方案

建议把原方案调整为四层治理：

1. **根因治理**：生产 OAuth 应用发布到 `In production`，登记 Client、项目、用户类型和 Workspace 策略，停止依赖周期性人工重授权。
2. **凭据治理**：refresh token 使用单一事实源和版本化发布，节点加载后必须 ACK；不在数据库、日志、脚本和聊天记录中散落明文。
3. **运行治理**：所有拉取入口统一执行授权策略检查，结构化识别不可重试错误，受控复验后立即熔断。
4. **恢复治理**：新 token 验证、Network API 验证、节点版本确认、最小任务验证、恢复 schedule、缺口回补依次执行。

## 6. 最终判断

原方案可以保留为总体整改文档，其中 `OPS-08` 的熔断方向正确，但需要按本文补充后才能进入开发和发布阶段。优先顺序应为：

1. 立即核对所有生产 OAuth Client 的 publishing status，先排除 7 天失效根因。
2. 修复“无新 refresh token 仍保留旧 token 并标记授权成功”的逻辑。
3. 建立统一授权熔断策略，覆盖所有任务创建和领取入口。
4. 实现凭据版本同步、最小健康验证、告警和缺口回补闭环。

在以上四项完成前，不应宣称“token 反复失效问题已解决”，只能称为“已具备人工重新授权和临时停拉能力”。
