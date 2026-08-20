# 小时快照防倒退最小修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:test-driven-development 逐任务实现本计划。步骤使用复选框跟踪进度。

**目标：** 以最小改动阻止较小 Google 小时快照删除既有小时/维度事实，并让现有 Pacific 跨日回查在固定上限内观察稳定水位。

**架构：** 复用现有 `BatchIngestionRequest` 与 `CollectorIngestionBatch` 的 `merge_mode/touched_hours/expected_hour_count`，仅调整 `admanager_hourly_dimension_v1` 投影；复用现有 `cross_day_finalize` 任务和 exhausted 标记，不增加新表、迁移、API 或独立 producer。

**技术栈：** Python、FastAPI、SQLAlchemy、SQLite、pytest。

---

### 任务 1：小时 ingestion 安全合并

**文件：**
- 修改：`backend/app/collectors/ingestion_service.py`
- 测试：`backend/tests/test_ingestion_service.py`

- [x] 写失败测试：已有 0—18、新 payload 0—9 且声明 0—23 时保留 10—18。
- [x] 写失败测试：同小时 incoming 维度键为 existing 真子集时保留缺失键；相同键指标使用新值。
- [x] 写失败测试：空 payload 不删除；非法 merge mode、重复/越界 touched hours 返回 422 且无部分写入。
- [x] 写失败测试：旧 collector 缺少合并字段时小时数据不倒退；batch 持久化合并元数据；重复 batch 幂等。
- [x] 写失败测试：小时任务前后四张权威日报事实及更新时间不变。
- [x] 运行 `cd backend; python -m pytest tests/test_ingestion_service.py -q`，确认因现有 full reset/未校验元数据得到预期红灯。
- [x] 最小实现：校验并持久化合并元数据；以 payload 实际小时限制触达集合；小时/维度键采用防倒退 upsert；空 payload 不删除；日报路径保持原样。
- [x] 重跑 ingestion 专项测试至全绿。

### 任务 2：现有跨日 scheduler 受控稳定观察

**文件：**
- 修改：`backend/app/collectors/scheduler.py`
- 修改：`backend/app/collectors/service.py`（仅在需要查询合法 batch 水位时）
- 测试：`backend/tests/test_fetch_scheduler.py`

- [x] 写失败测试：第一次 succeeded 后仍创建下一 observation，attempt ID 不重复。
- [x] 写失败测试：succeeded 但无合法 hourly batch 不计稳定；最近两次合并后水位相同且达到成熟时间才停止。
- [x] 写失败测试：水位变化继续观察；低量少于 24 小时但稳定可以停止。
- [x] 写失败测试：最多 3 次、active 不重复、达到上限只生成一个 exhausted marker、重启幂等。
- [x] 写失败测试：窗口外恢复当前源日，DST 与固定 Pacific 源时区保持正确。
- [x] 运行 `cd backend; python -m pytest tests/test_fetch_scheduler.py -q`，确认因首次 success 即停止和 max=2 得到预期红灯。
- [x] 最小实现：只调整既有跨日分支停止条件、attempt 计数和合法 batch 水位比较；不新增 producer、表或 API。
- [x] 重跑 scheduler 专项测试至全绿。

### 任务 3：回归、治理记录与独立审阅

**文件：**
- 修改：`docs/system-maintainer-onboarding-guide.md` 第 22 节
- 修改：`docs/问题记录.md`

- [x] 运行 backend 全量测试与 collector 相关回归测试。
- [x] 运行编译、`git diff --check`、敏感信息扫描，并确认无 migration/API/frontend 差异。
- [x] 记录红灯、绿灯、影响、已知副作用、回滚和主目录错误入口。
- [x] 请求独立规格与代码质量审阅；P0/P1 清零后才允许 Git 提交。
- [x] 本轮不部署生产；生产灰度、备份和真实账号验证需另行授权。
