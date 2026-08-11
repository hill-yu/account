# 测试服务器跨日小时数据修复实施计划

> **面向执行者：** 按 TDD 小步实施；完成代码和测试后必须独立审阅，审阅无阻塞项才可提交与部署。

**目标：** 让测试服务器 `cpatobe` 的半小时调度始终按 Google Pacific 业务日拉取小时数据，并在 Pacific 跨日后受控刷新上一业务日，避免“任务成功但 0 行”和最后一小时永久缺失。

**架构：** 保持现有 scheduler、direct collector 和数据库结构不变。测试环境把现有 48 个半小时计划的时区改为 `America/Los_Angeles`；代码移植生产已验证的白名单跨日收尾逻辑，仅对 `cpatobe` 开启。现有本机 cpatobe API 作为真实 runtime 配置端点，Token 只保存于服务器环境和数据库，不进入 Git。

**技术栈：** Python、FastAPI、SQLAlchemy、pytest、systemd、SQLite。

---

### 任务 1：锁定跨日回归行为

**文件：**
- 修改：`backend/tests/test_fetch_scheduler.py`

- [ ] 增加北京时间已跨日但 Pacific 尚未跨日的测试，断言普通小时任务仍请求 Pacific 当日。
- [ ] 增加 Pacific 01:00–02:59 首次收尾测试，断言请求上一 Pacific 业务日并标记 `cross_day_finalize`。
- [ ] 增加成功幂等、失败两次封顶、窗口外、开关外、非 direct 模式和 DST 测试。
- [ ] 运行定向测试并确认因缺少实现而失败。

### 任务 2：最小实现跨日收尾

**文件：**
- 修改：`backend/app/config.py`
- 修改：`backend/app/collectors/scheduler.py`
- 修改：`backend/app/collectors/service.py`

- [ ] 增加默认关闭的 `cross_day_finalize_account_keys` 配置。
- [ ] scheduler 仅在 direct 模式、白名单账户和 Pacific 01:00–02:59 窗口复用本周期刷新上一业务日。
- [ ] 为收尾任务写入确定性请求 ID 和 `run_reason`；成功不重复，失败最多两次，耗尽写一条 blocked 标记。
- [ ] 运行定向测试直至通过，并运行后端全量测试。

### 任务 3：记录、审阅和 Git 提交

**文件：**
- 修改：`docs/问题记录.md`
- 修改：`docs/system-maintainer-onboarding-guide.md`

- [ ] 记录原因、范围、配置、测试、回滚和测试服务器发布状态；不记录 Token。
- [ ] 执行 `git diff --check` 和全量测试。
- [ ] 独立审阅差异、测试、错误处理、安全边界和部署方案；修复全部阻塞问题并复审。
- [ ] 仅提交本次文件到 Git，并将提交整合到 `dev`。

### 任务 4：测试服务器配置与验收

**服务器：** `97.64.83.11`；账号仅限已授权的 `cpatobe` 及其既有测试代理。

- [ ] 备份 cpatobe API 环境文件、中台环境文件和 SQLite 数据库。
- [ ] 生成 256 位随机 Token，同步设置 `report_account_key=cpatobe`、`report_base_url=http://127.0.0.1:9123` 和两端 Token。
- [ ] 将 cpatobe 计划时区改为 `America/Los_Angeles`，保留原 48 个半小时触发点。
- [ ] 配置白名单仅含 `cpatobe`，从已提交的 Git 版本部署并重启相关测试服务。
- [ ] 验证两个 health、鉴权、scheduler active、当前 Pacific 日期小时任务有入库数据，日报调度不再因 runtime 配置缺失跳过。
- [ ] 若异常，恢复环境文件、数据库、计划时区和部署前 Git 提交；不触碰生产服务器。
