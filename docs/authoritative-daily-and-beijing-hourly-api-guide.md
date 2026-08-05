# 权威日报与北京时间小时接口对接说明

## 权威日报同步

- 权威日报按账户时区业务日生成，中台在业务日 D+1 的 05:00、06:00、07:00 各创建一次固定槽位任务。
- 每次 Google 核心日报和维度日报全部分页成功后，才在同一事务中替换当前版本；任一环节失败均保留旧版本。
- 三个成功版本均按完整版本发布，允许指标增加或减少。`user_system` 建议在账户时区 07:00 后读取；异常时由运维人工刷新。
- 现有权威日报读取接口及字段保持兼容，本次不修改 `user_system`。

### 日报完整标志

以下五个日报读取接口返回的每条 `items` 记录均包含 `"is_finalized": true`：

- `GET /api/v1/operator/mid-platform/reports/account-daily`
- `GET /api/v1/operator/mid-platform/reports/site-daily`
- `GET /api/v1/operator/mid-platform/reports/link-daily`
- `GET /api/v1/operator/mid-platform/reports/account-daily-dimensions`
- `GET /api/v1/operator/mid-platform/reports/site-daily-dimensions`

该字段表示该记录是中台当前已入库、允许消费方正式入库的权威日报版本。它不表示 Google 后续不会延迟更新或回滚；05:00、06:00、07:00 或人工刷新产生的新成功版本仍可能覆盖当前值。接口不返回 `is_finalized=false` 的处理中间态，`user_system` 可继续以 `is_finalized is true` 作为正式入库条件。该字段只属于日报接口，小时接口不返回此字段。

人工刷新接口为 `POST /api/v1/operator/accounts/{account_id}/authoritative-daily-refresh`：

```json
{"report_date":"2026-08-04","idempotency_key":"user-system-20260804-retry-1"}
```

请求使用现有 Operator 鉴权。相同幂等键返回同一任务；同账户同业务日已有活动日报任务时，新幂等键返回 `409`。人工任务使用槽位 `8`。

## 北京时间小时数据

- `report_date=2026-08-05` 固定表示北京时间 8 月 5 日 00:00（含）至 8 月 6 日 00:00（不含）。
- 对应 UTC 区间为 8 月 4 日 16:00（含）至 8 月 5 日 16:00（不含）。
- 返回的 `report_date/hour` 按北京时间派生；`report_time_utc/source_timezone` 保留来源信息。
- 账户汇总、站点汇总、账户维度、站点维度及中台兼容接口统一采用该日期语义。

## 兼容和失败边界

- 小时批次只更新小时事实，不重建或覆盖权威日报。
- 完整但无数据的日报快照会清空对应业务日旧投影。
- 服务端重新计算并校验行数和 payload 哈希。
- 新日报发布后仅保留当前完整 payload；历史版本保留轻量摘要、行数、哈希和任务元数据。
- 固定槽位由数据库唯一索引防重复；晚槽位发布后，迟到早槽位返回 `409`。
- 真实 Google 集成测试仍须明确指定已授权测试账户及代理。
