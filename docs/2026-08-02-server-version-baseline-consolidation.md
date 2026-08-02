# 新服务器代码版本基线与整合记录

- 状态：审阅通过，待提交并推送
- 创建日期：2026-08-02
- 整合分支：`codex/server-version-consolidation`
- 权威运行基线：`6085a5b35b02be7d0314812c8c405f9ee70e54c9`

## 1. 结论

新服务器当前运行的中台代码目录为 `/srv/adx-account-isolated-collector/backend`。该运行目录不是 Git 工作树；其部署来源为 `/srv/gitcode/adx-account-isolated-collector`，Git 远程为 `https://github.com/hill-yu/account.git`，源码提交为本记录中的权威运行基线。

本地 `D:\code\adx-mid-platform` 使用相同远程仓库，但当前分支 `codex/mid-platform-standalone-init` 的提交为 `f6a759a6ce18bfd22b850c3c04bf21d7eb4c59b6`，不是服务器基线的后续提交。该分支相对服务器基线会删除 OAuth 凭据控制面、账号拉取策略、数据库迁移和配套测试，不能整体合并或部署。

后续开发唯一允许的代码基线为本分支；新功能必须从本分支继续创建，不得从 `codex/mid-platform-standalone-init` 或服务器运行目录直接开发。

## 2. 本地未提交改动处理

原本地工作区存在 26 个已修改的受跟踪文件，以及文档、输出和临时文件等未跟踪内容。已完成只读补丁适用性检查：这些改动无法自动应用到服务器基线，并在 OAuth、调度、任务、入库、模型和 API 等至少 17 个核心文件发生冲突。

处理原则：

1. 不批量复制、`merge`、`stash pop` 或覆盖这些改动。
2. 每个候选改动必须先说明来源、目的、影响范围、与服务器基线的冲突点及回滚方式。
3. 只将经确认仍需要的最小代码片段移植到本分支，并同时移植对应测试、迁移和文档。
4. 每一批移植完成后必须独立审阅、运行针对性测试和全量回归测试，再单独提交 Git。
5. 临时脚本、导出文件、密钥、密码、Token、OAuth 回调和代理完整凭据不得进入整合分支。

## 3. 服务器基线保护项

以下文件或能力已经在服务器基线中存在，而本地旧分支缺失；整合中必须保留：

- OAuth 凭据控制与加密：`credential_crypto.py`、`oauth_errors.py`、`oauth_credential.py`、`oauth_event.py`。
- 账号拉取策略和熔断恢复：`fetch_policy.py`、`collector_account_policy.py` 及对应 migration、测试和脚本。
- OAuth 凭据数据库迁移：`20260731_0012_oauth_credential_control_plane.py`、`20260731_0013_bind_sync_tasks_to_credential_version.py`。
- 恢复缺口、健康摘要、凭据绑定和 scheduler 的现有行为与测试。

## 4. 验证证据

### 4.1 生产部署一致性（只读核验）

核验时间：`2026-08-02T19:27:55+08:00`。

- `adx-control-plane` 的 `WorkingDirectory` 为 `/srv/adx-account-isolated-collector/backend`，启动命令为该目录虚拟环境中的 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。
- 运行目录与 Git 源码目录的 `backend/app/main.py` SHA-256 均为 `2a45928a48948353032f2c3eab70ef93d58bfecc2639cce3fafe25ad960c803f`。
- 该核验只能证明本次抽样文件及启动位置一致；每次首次选择性移植部署前，必须重新核验实际部署制品、服务单元和目标提交，并将结果追加到本记录。

在本隔离分支完成本地依赖准备后，执行结果如下：

| 组件 | 命令 | 结果 |
|---|---|---|
| Backend | `backend/.venv/Scripts/python.exe -m pytest -q` | 139 passed，0 failed |
| Collector | `collector/.venv/Scripts/python.exe -m pytest -q` | 87 passed，0 failed |

执行环境：Windows 10 `10.0.26200.0`，Python `3.11.9`。Windows 环境首次执行时缺少时区数据库 `tzdata`；backend 的虚拟流程测试还需要 `uvicorn`。二者通过 `python -m pip install tzdata uvicorn`（backend）和 `python -m pip install tzdata`（collector）仅安装于本隔离工作区的开发虚拟环境，未修改源码、运行环境或服务器，也不得提交虚拟环境。

当前依赖清单尚未完整声明上述测试环境依赖；在任何后续代码批次中，应以单独、受审阅的变更将测试依赖固化为开发依赖或明确的测试环境文档，不能依赖人工记忆。

## 5. 后续工作顺序

1. 对原工作区 26 项受跟踪改动建立候选清单：每项必须包含文件、来源/目的、所依赖的迁移、测试、冲突点和“移植 / 放弃 / 另立任务”结论。该清单完成前禁止复制任何业务代码。
2. 仅对批准移植的改动，在本分支按测试驱动方式完成最小重实现。
3. 通过独立审阅和完整回归后，提交并推送本分支。
4. 本分支提交号成为“国家、广告单元和三项比率”需求的唯一开发起点；在版本整合完成前不得开始该功能实现。

## 6. 独立审阅结论

审阅日期：2026-08-02。结论：无 Critical；允许进入逐项选择性移植阶段，也允许提交本基线记录。

审阅确认了基线提交可由远程分支 `origin/codex/oauth-token-remediation-v1` 追溯，运行目录与源码目录已正确区分，旧分支的整分支合并风险真实，且原工作区改动未被覆盖。提交完成后，必须推送 `codex/server-version-consolidation`，使权威基线不只保留在本机。
