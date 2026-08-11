# 跨源时区小时报最终刷新设计

## 目标

修复 Pacific 小时报在源日期切换后不再回查上一业务日，导致源小时 23（PDT 下对应次日北京时间 14:00）永久缺失的问题，同时不增加正常调度任务量、不扩大到非灰度节点、不触碰权威日报。

## 已确认根因

小时 schedule 使用 `America/Los_Angeles` 的当前日期作为 `report_date`。源时区跨日后，后续任务只请求新日期；上一源日期最后一小时如果在跨日前最后一次快照中尚未成熟，就没有后续刷新机会。生产数据中多个高量灰度节点连续缺失源小时 23，而在日期结束后人工拉取的 `tqchq.com` 可得到完整 24 小时，验证了该根因。

## 行为设计

1. 每个启用的小时 schedule 正常仍每小时只触发一个任务。
2. 在 Pacific 新业务日 `01:00 <= local time < 03:00` 的到期周期，若上一源日期尚无成功的 `cross_day_finalize`，本周期改拉上一源日期；否则拉当前源日期。
3. 最终刷新任务使用 `run_reason=cross_day_finalize` 和确定性的 `external_request_id=hourly-finalize-{account_id}-{report_date}-{attempt}`。
4. 成功后不再重复；Pending/In Progress 时不重复；失败最多允许下一周期重试一次。达到两次失败后恢复当前日期正常拉取，遗留问题交由告警和人工处理。
5. 最终刷新复用当前完整小时快照入库，仅替换该 `account_id + Pacific report_date` 的小时分区。禁止写入或重建账户/站点权威日报。

## 门禁与影响边界

- 仅适用于 lifecycle active、gray/hourly enabled、无 exclusion 且 schedule enabled 的现有节点。
- 不创建额外 schedule，不批量启动额外任务；最终刷新替代窗口内的一次正常当前日刷新。
- 停拉、OAuth 熔断、代理异常仍由现有策略和 runtime 门禁处理。
- 不以 24 个非空小时判断完成，因为真实零数据小时可能不会由 Google 返回；以最终刷新任务成功作为源日快照关闭证据。
- DST 日期统一使用 `ZoneInfo("America/Los_Angeles")` 计算本地日期，不使用固定 UTC 偏移。

## 历史修复边界

本次代码发布不自动重拉历史日期。历史缺口必须另行生成候选清单，逐账号、逐源日期备份和受控补拉，不能把所有少于 24 小时的低量节点认定为缺失。

## 测试与发布

- TDD 覆盖窗口选择、成功幂等、活跃任务去重、最多两次失败、窗口外不回查、DST、策略门禁和权威日报不变。
- 独立审阅无阻塞问题后提交 Git。
- 功能先仅灰度 `coeurdazur.com`，观察两个 Pacific 跨日周期，再决定是否逐节点扩大。
- 回滚为恢复上一版本代码并重启 scheduler；任务逻辑无数据库迁移。已创建但未执行的 `cross_day_finalize` 任务仅按目标账号定向取消。
