# 新老窗口交接技能与初始化脚本实施计划

**目标：** 提供可复用的个人技能与可重复执行的 PowerShell 脚本，创建、校验或续接任务 worktree，并强制验证三份治理文件、Git 基线与工作区状态。

**方案：** `$adx-worktree-handoff` 负责识别新任务、严格交接或同任务续接，并调用 `scripts/project-handoff.ps1` 的 `Create`、`Validate` 或 `Resume`。任何门禁失败返回非零；不自动修改已有 worktree，也不授予生产写权限。

**文件：**

- 新增 `scripts/project-handoff.ps1`：交接入口。
- 新增 `scripts/tests/project-handoff.Tests.ps1`：无外部测试框架的隔离 Git 仓库测试。
- 修改 `AGENTS.md`：要求新窗口先运行验证模式。
- 追加维护手册第 22 节和问题记录。

## 实施步骤

- [ ] 先编写测试，覆盖脚本缺失时红灯、合法 worktree、治理文件未跟踪、dirty、落后 master、创建模式。
- [ ] 运行测试确认因脚本不存在而失败。
- [ ] 实现最小脚本并运行测试至通过。
- [ ] 更新治理文档、执行真实当前 worktree 验证和敏感信息扫描。
- [ ] 独立审阅，无阻塞问题后提交；经用户授权再单独集成 `master`。
