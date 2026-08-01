# 新服务器直接采集迁移实施计划

> **面向执行者：** 在当前会话内逐项执行；每个会改变生产状态的步骤必须记录命令结果和回滚点。

**目标：** 将控制面数据库、OAuth 凭据和 Google Ad Manager 采集运行时迁至新服务器，保留旧服务器数据和可回退能力。

**架构：** 新服务器使用 `control_plane.db`、受保护的 OAuth 密钥和本地 collector runtime 直接采集。旧服务器在数据快照完成后停止旧中台及其采集触发器，但其数据库和节点服务保留，不作为新中台依赖。

**技术栈：** FastAPI、SQLAlchemy/Alembic、SQLite WAL、pytest、systemd、rsync/SFTP。

---

### 任务 1：固定新服务器为直接采集模式

**文件：**
- 修改：`/srv/adx-account-isolated-collector/backend/.env`
- 验证：`backend/tests/test_fetch_scheduler.py`

- [ ] 将 `ADX_COLLECTOR_DIRECT_COLLECTOR_ONLY=true` 写入新服务器环境文件；保留 0600 权限。
- [ ] 在新服务器运行：

```bash
PYTHONPATH=. ../.venv/bin/python -c "from app.config import get_settings; assert get_settings().direct_collector_only is True"
```

- [ ] 运行：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/test_fetch_scheduler.py -q
```

预期：所有调度测试通过；自动任务进入新服务器 local collector 路径，不调用旧节点 HTTP。

### 任务 2：新服务器部署验证

**文件：**
- 修改：`/srv/adx-account-isolated-collector/`
- 验证：`backend/tests/`、`collector/tests/`、`frontend/`

- [ ] 校验工作目录提交为 `279fdc7` 或其后经审阅的提交。
- [ ] 同步 Git 工作树到运行目录，但排除 `.env`、SQLite 文件、虚拟环境和 `node_modules`。
- [ ] 运行后端、collector、前端测试和前端构建；服务必须保持 disabled/inactive。

### 任务 3：旧库一致性快照

**文件：**
- 读取：旧服务器 `/srv/adx-account-isolated-collector/backend/control_plane.db`
- 创建：本地受限临时传输副本和新服务器 staging 文件

- [ ] 先记录旧库 SHA-256、任务状态、计划状态和磁盘余量。
- [ ] 仅停止旧 `adx-control-plane.service` 及旧中台采集 crontab/timer；不得停止旧节点 MySQL 或不相关的 Docker 8001 栈。
- [ ] 确认无旧中台写入进程后执行 `PRAGMA wal_checkpoint(TRUNCATE)`；确认 `-wal` 无残留数据。
- [ ] 通过本地临时文件两段 SFTP 传输数据库；两端 SHA-256 必须一致。
- [ ] 在新服务器 staging 副本执行 `PRAGMA integrity_check`，预期为 `ok`。

### 任务 4：数据库与 OAuth 升级

**文件：**
- 修改：新服务器 `/srv/adx-account-isolated-collector/backend/control_plane.db`
- 读取：旧库中的 `oauth_app_configs`

- [ ] 先保留新服务器零字节/旧数据库副本到有时间戳的备份目录。
- [ ] 用运行用户恢复已校验的 staging 数据库，权限设为 0600。
- [ ] 在新服务器运行 `alembic upgrade head`；记录 revision。
- [ ] 使用新服务器生成的 encryption/fingerprint key 运行 OAuth 凭据迁移脚本；验证旧明文凭据已清空、加密凭据和健康任务统计正确。
- [ ] 确认所有 fetch schedule 仍禁用，且没有 `in_progress` 任务被重置为 pending。

### 任务 5：新服务器灰度和切换

**文件：**
- 修改：新服务器 systemd/Nginx 配置（仅在提供中央控制域名与 TLS 后）
- 验证：新服务健康、OAuth、单账号采集与落库

- [ ] 在仍禁用 scheduler 的情况下启动新服务并验证 operator API 授权、健康检查和数据库 schema。
- [ ] 对单个已完成 OAuth 健康检查的账号手动创建 direct collector 采集；验证任务、报告和日志均在新服务器产生，且没有旧节点 HTTP 请求。
- [ ] 仅为通过验证的账号启用计划；观察一个计划周期后再扩大范围。
- [ ] 保留旧服务停止状态和完整旧库；出现异常时先禁用新计划、停止新服务，再按记录恢复旧服务，不覆盖新库。
