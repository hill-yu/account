# 跨源时区小时报最终刷新实现计划

> **面向 AI 代理的工作者：** 使用 TDD 逐项执行；实现完成后必须独立审阅并在发布前重新验证。

**目标：** 在不增加每小时任务总量的前提下，每个灰度节点在 Pacific 跨日后受控最终刷新上一源业务日一次，补齐迟到小时且不影响权威日报。

**架构：** scheduler 在现有单次 schedule 触发点选择当前源日期或上一源日期；service 提供最终刷新状态查询和带 `run_reason` 的小时任务创建；沿用现有小时完整快照投影和策略门禁。

**技术栈：** FastAPI、SQLAlchemy、SQLite、pytest、ZoneInfo。

---

### 任务 1：固化任务日期选择与幂等规则

**文件：**
- 修改：`backend/tests/test_fetch_scheduler.py`
- 修改：`backend/app/collectors/scheduler.py`
- 修改：`backend/app/collectors/service.py`

- [ ] 写测试：Pacific 01:xx 首次选择上一日期并标记 `cross_day_finalize`。
- [ ] 运行定向测试，确认因缺少行为而失败。
- [ ] 最小实现日期选择和最终刷新任务查询/创建。
- [ ] 运行定向测试确认通过。
- [ ] 写测试并实现：成功后跳过、活跃任务不重复、首次失败后重试一次、第二次失败后恢复当前日期。
- [ ] 写测试并实现：窗口外正常拉当前日期、DST 日期计算正确。

### 任务 2：验证策略边界与日报隔离

**文件：**
- 修改：`backend/tests/test_fetch_scheduler.py`
- 修改：`backend/tests/test_ingestion_service.py`（仅在现有覆盖不足时）

- [ ] 验证停拉/非灰度/小时关闭/schedule disabled 不创建最终刷新任务。
- [ ] 验证最终刷新任务仍走现有 OAuth、代理和账户策略门禁。
- [ ] 验证小时完整快照只替换小时分区，账户和站点权威日报及更新时间不变。
- [ ] 运行 scheduler、ingestion 相关完整测试。

### 任务 3：文档、全量验证与独立审阅

**文件：**
- 修改：`docs/system-maintainer-onboarding-guide.md` 第 22 节
- 修改：`docs/问题记录.md`

- [ ] 记录变更内容、原因、方案、影响、测试、回滚、Git 和发布状态。
- [ ] 更新问题记录的统一修复状态，明确历史数据不自动回补。
- [ ] 运行 backend 全量测试并检查 git diff。
- [ ] 独立审阅差异、测试、错误处理、调度负载、日报隔离和安全边界。
- [ ] 修复所有阻塞问题并复审。
- [ ] 提交并推送分支。

### 任务 4：生产单节点灰度

- [ ] 核对生产 HEAD、服务、数据库和 `coeurdazur.com` OAuth/代理/策略状态。
- [ ] 执行 SQLite 在线备份并通过 `quick_check`。
- [ ] 从已提交 Git 版本发布，默认仅对 `coeurdazur.com` 开启最终刷新功能。
- [ ] 重启并验证控制面与 scheduler 健康。
- [ ] 观察两个 Pacific 跨日周期，核对任务、batch、小时覆盖、任务量和权威日报哈希。
- [ ] 无异常后再单独申请扩大节点范围；异常立即回滚代码并定向取消未执行任务。
