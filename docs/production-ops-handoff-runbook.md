# ADX 中台生产运维交接清单与单节点接入 Runbook

版本：2026-08-13

适用工作树：`D:/code/adx-mid-platform/.worktrees/production-ops-handoff`

分支：`codex/production-ops-handoff`
创建基线：`origin/master@b157a63000763c8ef7b9967fc3d74cfe4822a4e7`

本文是新运维任务的首要入口。它不替代生产现场核验；文中标为“已知”的值仍须在每次写操作前以只读证据重新确认。

## 1. 生产现状清单

### 1.1 固定事实与现场门禁

| 项目 | 当前已知值 | 每次操作前的确认方式 |
| --- | --- | --- |
| 生产服务器 | `43.134.119.164`，用户 `ubuntu` | 只连接用户明确指定的主机；禁止根据 SSH 历史猜测主机 |
| 项目根目录 | `/srv/adx-account-isolated-collector` | 从 systemd 的 `WorkingDirectory`、`EnvironmentFile`、`ExecStart` 交叉确认 |
| 控制库 | `/srv/adx-account-isolated-collector/backend/control_plane.db` | 从运行配置确认后执行只读 `PRAGMA quick_check`；禁止使用根目录同名空文件 |
| 控制面服务 | `adx-control-plane.service` | `systemctl is-active` 和 localhost `/health` |
| scheduler | `adx-control-plane-scheduler.service` | 只读确认状态和唯一进程；单节点接入不得擅自重启或改全局状态 |
| collector runtime | `/srv/adx-account-isolated-collector/collector/.venv/bin/python -m app.main` | 仅为目标 instance 按需启动；代理诊断必须使用该虚拟环境 |
| Operator API | `/api/v1/operator/...` | Token 仅从服务器实际 `EnvironmentFile` 经 `get_settings().operator_api_token` 在进程内读取，禁止输出 |
| 小时报表源时区 | `America/Los_Angeles` / Pacific | schedule 固定使用该时区，不能改成账户报告时区 |
| 权威日报成熟门禁 | 账户实际报告时区的次日 `00:00` 后等待 5 个实际小时 | 调用当前运行代码的成熟判断；不得以 schedule 时区代替账户时区 |

生产代码版本不是只凭本地分支推断。每次先记录服务器 Git HEAD、工作区状态、运行目录受控文件哈希，并与预期发布提交比较；不一致即停止写操作。

### 1.2 当前架构边界

单节点只通过控制面资源接入：账户、collector instance、OAuth App/托管凭据、代理绑定、fetch policy、可选 schedule、任务与 ingestion batch。根据当前已知生产架构，不使用每节点 MySQL、独立节点 Nginx、节点 cron 或 `adx-fetch-api-*.service`；每次仍须通过 systemd、运行进程和端口清单只读复核，发现不一致立即停止。

小时链路和权威日报链路完全独立。任何小时任务、小时补拉或小时投影都不得写入、重建或覆盖权威日报表。

## 2. 精确接入步骤

每个阶段均只允许操作一个用户明确指定的 `account_key`。上一步验证不通过时停止，不得继续下一阶段。

### 接入前一次性预演

正式连接生产前，维护者必须在同一张接入检查单中一次性列出并确认以下内容，避免执行到中途才发现门禁：

1. 工作树绝对路径、分支、HEAD、clean 状态和目标生产提交。
2. 唯一生产服务器、SSH 身份及全新无副作用连接验收结果。
3. account key、network code、账户报告时区、币种、redirect URI、专属代理和预期出口 IP。
4. 当前生产 schema、API schema、systemd 环境文件、控制库路径及磁盘空间。
5. 基础资源、OAuth URL、callback、credential validation、policy active、health check、manual、gray/hourly、authoritative daily、schedule 的逐阶段授权边界。
6. 以纯只读 dry-run 计算首次启用 schedule 时当前代码可能生成的恢复候选日期和任务数量；预演不得创建任务、修改 schedule 或 policy，该范围必须先与用户授权范围比较。
7. 每一阶段的在线备份、验证证据、补偿回滚和停止条件。

检查单任何一项缺失时，只能继续只读排查。禁止边执行边猜测字段、路径、Token 位置、policy 状态或自动任务范围。

### 阶段 0：填写接入申请

必须明确：账户名、GAM network code、账户实际报告时区、币种、OAuth Web client JSON、精确 redirect URI、专属代理、是否仅基础接入、是否授权生成链接/兑换/真实拉数/灰度/schedule。缺项时只读排查，不写生产。

### 阶段 1：生产只读门禁

1. 确认 SSH 目标严格为 `ubuntu@43.134.119.164`。公钥“已生成”或“已写入”不等于可用；必须用一次全新无副作用连接验收。
2. 核对 systemd、运行目录、环境文件、服务器 Git HEAD、工作区、服务健康、磁盘空间和数据库实际路径。
3. 先用 `PRAGMA table_info(...)` 读取当前生产 schema，再写查询；禁止凭本地模型记忆猜字段名。
4. 按账户名、network code、域名、OAuth client ID、redirect URI 查询唯一性；目标已存在时转入“重授权/修复”，禁止重复创建。
5. 确认目标账户没有 `pending/in_progress/blocked` 冲突任务，且没有活动 OAuth state。
6. 在生产 collector 虚拟环境通过目标代理探测实际出口，只输出 observed IP 和是否匹配；不得从 Windows 本机探测后据此判定生产代理。

### 阶段 2：备份和最小基础资源

1. 用 SQLite online backup 创建带 UTC 时间戳的独立备份，备份与生产库均须 `quick_check=ok`。
2. 当前公开 API 对 account、instance、OAuth App 和 proxy 分别提交，不能宣称整个接入原子完成。必须严格按“account → timezone → instance → OAuth App → proxy”执行，每步保存返回 ID、立即只读复核；任一步失败，停止并按 5.1 对已创建资源执行补偿回滚。
3. policy 当前没有公开创建 API。先读取生产 `collector_account_policies` schema，再在单个 `BEGIN IMMEDIATE` 事务中仅为返回的 `ACCOUNT_ID` 创建一行 onboarding policy；事务内断言该 account 存在、policy 不存在、写入后仅新增一行，任何断言失败立即 `ROLLBACK`。禁止复用旧字段或猜测默认值。
4. 新节点保持账户 `pending`、instance `provisioning`，policy 四项拉取开关关闭，无 schedule、无任务。
5. OAuth App API 会通过当前生产加密组件保存 client secret；秘密只允许从权限 `0600` 的临时 JSON 在服务器进程内读取，请求结束立即删除。禁止将秘密放进 shell 参数、输出、Markdown 或 Git。
6. 全部步骤后重新查询所有资源配对和数量，并再次执行 `quick_check`。

### 阶段 3：授权链接与 callback 兑换

1. 生成 OAuth state 前重新备份并校验，无活动 state、client secret 可在当前环境解密、代理绑定正确。
2. 从服务器进程内部读取 Operator Token，调用 localhost API：`POST /api/v1/operator/oauth-apps/{id}/authorization-url`。重授权必须显式提供 `force_reauthorize=true` 和真实原因。
3. state 有效期 10 分钟。过期后重新执行门禁并生成新链接；禁止手工恢复、伪造或重放 state。
4. callback 导入前核对 account/OAuth App、redirect URI/path、state、issuer、有效期。调用 `POST /api/v1/operator/oauth-apps/import-callback-json`；一个 code 只消费一次。
5. callback 临时载荷权限必须为 `0600`，提交后无论成功失败都删除；文档和台账只记录脱敏结果。

### 阶段 4：凭据和代理验证

严格顺序：

```text
oauth_credential_validate pending
  -> 启动一次目标 instance runtime
  -> validation succeeded / 新版本 active
  -> policy lifecycle 必须允许 health check，四项拉取开关仍关闭
  -> oauth_health_check pending
  -> 再启动一次目标 instance runtime
  -> health succeeded
  -> authorized + healthy
```

任务日志 message 不能作为唯一结论；联合核对任务终态、credential version、OAuth 状态和实际代理出口。验证前不得拉报表。

### 阶段 5：受控数据验收

只有用户明确授权真实拉数时才能执行。先完成目标日期计算，再逐日期串行，每个任务等待终态并核对 batch。

- 小时报表使用 Pacific `report_date`；北京时间自然日可能跨两个 Pacific 日期。
- 查询北京时间自然日时，必须先把北京时间 `[00:00, 次日 00:00)` 换算成 UTC 半开区间 `[start_utc, end_utc)`，再从相交的两个 Pacific `report_date` 中按 `report_time_utc >= start_utc AND report_time_utc < end_utc` 精确截取；禁止直接合计两个完整源日。账户小时、站点小时及维度 API 的结果也必须按同一 UTC 边界二次校验。例如北京时间 2026-08-17 对应 UTC `[2026-08-16 16:00, 2026-08-17 16:00)`，PDT 下跨源日 2026-08-16 09:00 至 2026-08-17 08:59。
- `task=succeeded` 不代表 24 个非空小时完整；Google 可能省略真实零数据小时。当前源日只能称“当前快照”。
- 权威日报只使用 `report_fetch`，必须通过账户实际时区的成熟门禁。
- 每次小时补拉前后核对既有权威日报指标、hash/`updated_at` 未变化。
- 客户端超时后先按 `external_request_id + account + report_date` 查询已有任务并复用；禁止直接重跑创建脚本。

### 阶段 6：灰度与 schedule

加入灰度、开启 hourly、authoritative daily 和创建 schedule 是四个不同授权边界，不得互相推定。

在首次启用 schedule 前，必须只读预演当前生产代码的 OAuth 恢复缺口扫描和其他自动候选日期。优先完成用户授权的定向补拉，再创建唯一 schedule。生产小时 schedule 使用 `interval_hours=1`、`timezone=America/Los_Angeles`。

启用后观察至少两个小时周期，检查任务范围、凭据版本、代理、batch、重复活跃任务及权威日报是否保持不变。发现额外日期或节点入队时，立即通过 `PATCH /operator/fetch-schedules/{id}` 提交 `{"enabled":false}`；再验证服务已自动把该 schedule 的 `next_run_at` 置空。不直接提交 schema 不支持的 `next_run_at`，不强杀已认领任务，并等待终态核对。

## 3. 已验证命令模板

以下命令不包含秘密。路径和字段必须先按阶段 1 现场校准；含 `<...>` 的占位符必须替换为已经核验的非敏感目标值。

### 3.1 SSH 与服务只读验收

```powershell
ssh -o BatchMode=yes -o IdentitiesOnly=yes -i "<private-key-path>" ubuntu@43.134.119.164 "id -un; hostname; true"
```

```bash
systemctl show adx-control-plane.service \
  -p User -p WorkingDirectory -p EnvironmentFiles -p ExecStart --no-pager
systemctl show adx-control-plane-scheduler.service \
  -p User -p WorkingDirectory -p EnvironmentFiles -p ExecStart --no-pager
systemctl is-active adx-control-plane.service
systemctl is-active adx-control-plane-scheduler.service
curl --fail --silent http://127.0.0.1:8000/health
```

### 3.2 数据库 schema、完整性与在线备份

```bash
CONTROL_DB=/srv/adx-account-isolated-collector/backend/control_plane.db
sqlite3 "$CONTROL_DB" 'PRAGMA quick_check;'
sqlite3 "$CONTROL_DB" 'PRAGMA table_info(accounts);'
sqlite3 "$CONTROL_DB" 'PRAGMA table_info(collector_instances);'
sqlite3 "$CONTROL_DB" 'PRAGMA table_info(oauth_app_configs);'
sqlite3 "$CONTROL_DB" 'PRAGMA table_info(oauth_credentials);'
sqlite3 "$CONTROL_DB" 'PRAGMA table_info(proxy_bindings);'
sqlite3 "$CONTROL_DB" 'PRAGMA table_info(collector_account_policies);'
sqlite3 "$CONTROL_DB" 'PRAGMA table_info(fetch_schedules);'
```

```bash
CONTROL_DB=/srv/adx-account-isolated-collector/backend/control_plane.db
ACCOUNT_KEY='<account-key>'
ACTION='<action>'
[[ "$ACCOUNT_KEY" =~ ^[A-Za-z0-9._-]+$ ]] && [[ "$ACTION" =~ ^[A-Za-z0-9._-]+$ ]] || exit 2
BACKUP_DIR="/srv/adx-account-isolated-collector/backups/$(date -u +%Y%m%dT%H%M%SZ)-pre-${ACCOUNT_KEY}-${ACTION}"
sudo install -d -o ubuntu -g ubuntu -m 700 "$BACKUP_DIR"
test "$(stat -c '%U:%G %a' "$BACKUP_DIR")" = "ubuntu:ubuntu 700"
sqlite3 "$CONTROL_DB" ".backup '$BACKUP_DIR/control_plane.db'"
sqlite3 "$BACKUP_DIR/control_plane.db" 'PRAGMA quick_check;'
sqlite3 "$CONTROL_DB" 'PRAGMA quick_check;'
test -s "$BACKUP_DIR/control_plane.db"
```

### 3.3 创建基础资源的精确 API 顺序

下列 JSON 是 `b157a63` 的 schema。真实值从服务器权限 `0600` 的临时 JSON 读取，不在命令参数中展开；请求客户端每一步必须保存响应中的 ID，并以该 ID 构造下一步。

```json
POST /api/v1/operator/accounts
{"name":"<account-key>","status":"pending","external_account_id":"<network-code>","currency":"<ISO-currency>"}

PATCH /api/v1/operator/accounts/<ACCOUNT_ID>/timezone
{"timezone":"<IANA-timezone>"}

POST /api/v1/operator/instances
{"account_id":<ACCOUNT_ID>,"name":"<account-key>","status":"provisioning","expected_egress_ip":"<verified-ip>","report_account_key":"<account-key>"}

POST /api/v1/operator/oauth-apps
{"account_id":<ACCOUNT_ID>,"client_id":"<from-0600-file>","client_secret":"<from-0600-file>","redirect_uri":"https://<domain>/oauth/google/callback","scopes":"https://www.googleapis.com/auth/admanager","app_status":"pending","verification_status":"pending"}

POST /api/v1/operator/proxies
{"account_id":<ACCOUNT_ID>,"collector_instance_id":<INSTANCE_ID>,"provider_name":"<provider>","protocol":"socks5","host":"<from-0600-file>","port":<port>,"username":"<from-0600-file>","password":"<from-0600-file>","expected_egress_ip":"<verified-ip>","status":"active"}
```

每次响应必须断言 HTTP `201`、返回 account/instance 配对正确且 ID 为正整数。代理创建响应的 schema 含 username/password，禁止打印完整响应，只提取 proxy ID、account/instance ID、状态和 expected egress IP。`instance_token` 只在创建响应出现一次，立即写入服务器权限 `0600` 的受限运行文件或既有密钥存储；禁止回显。API 分步失败时不得继续创建后续资源。

policy 的具体列会随迁移变化，因此不能在固定文档中伪造永远有效的 SQL。正确执行方式是：现场 `PRAGMA table_info(collector_account_policies)`，再使用当前部署代码中的 `CollectorAccountPolicy` 模型构造一个只含 `ACCOUNT_ID` 的 SQLAlchemy 事务；写前、写后均断言目标 ID，默认 `lifecycle_status=onboarding`，`gray/hourly/authoritative_daily/manual=false`。如果当前模型、迁移和表列不一致，停止接入，不能退回历史 SQL。

### 3.4 安全调用 Operator API 的模式

在 backend 目录、由受限运行环境执行；Token 只保存在子进程内存，不打印：

```bash
./.venv/bin/python - <<'PY'
import requests
from app.config import get_settings

token = get_settings().operator_api_token
assert token
response = requests.get(
    "http://127.0.0.1:8000/api/v1/operator/accounts",
    headers={"X-ADX-Operator-Token": token},
    timeout=30,
)
response.raise_for_status()
print(response.status_code)
PY
```

授权与运行阶段的 `b157a63` payload：

```json
POST /api/v1/operator/oauth-apps/<OAUTH_APP_ID>/authorization-url
{"force_reauthorize":false,"reason":null}

POST /api/v1/operator/oauth-apps/import-callback-json
{"state":"<from-0600-file>","code":"<from-0600-file>","redirect_uri":"https://<domain>/oauth/google/callback","callback_url":"<complete-callback-from-0600-file>","scope":"<optional>","iss":"https://accounts.google.com"}

POST /api/v1/operator/fetch-schedules/manual-fetch
{"account_id":<ACCOUNT_ID>,"collector_instance_id":<INSTANCE_ID>,"report_date":"<Pacific-YYYY-MM-DD>"}

POST /api/v1/operator/fetch-schedules
{"account_id":<ACCOUNT_ID>,"collector_instance_id":<INSTANCE_ID>,"enabled":true,"mode":"interval_hours","daily_times":null,"interval_hours":1,"timezone":"America/Los_Angeles"}

PATCH /api/v1/operator/fetch-schedules/<SCHEDULE_ID>
{"enabled":false}
```

真实执行前仍须以服务器当前运行代码 `backend/app/collectors/schemas.py` 再校准一次；若运行版本不是 `b157a63` 或兼容后继提交，停止并更新 Runbook。

### 3.5 目标 instance runtime

不要在 shell 参数中放 instance token。`b157a63` 没有公共 runtime 启动 API，实际函数为私有的 `service._launch_hourly_sync_runtime(instance)`。只能在服务器 backend 虚拟环境执行下列受限模式；传入非敏感的 ID，代码从控制库唯一查询 instance，并断言 account 配对后再调用真实函数：

```bash
INSTANCE_ID='<verified-instance-id>' ACCOUNT_ID='<verified-account-id>' ./.venv/bin/python - <<'PY'
import os
from sqlalchemy import select
from app.collectors import service
from app.database import SessionLocal
from app.models.collector_instance import CollectorInstance

instance_id = int(os.environ["INSTANCE_ID"])
account_id = int(os.environ["ACCOUNT_ID"])
with SessionLocal() as db:
    instance = db.scalar(
        select(CollectorInstance).where(
            CollectorInstance.id == instance_id,
            CollectorInstance.account_id == account_id,
        )
    )
    assert instance is not None
    service._launch_hourly_sync_runtime(instance)
print("runtime_started_for_verified_instance")
PY
```

启动后只查询目标 instance 的任务终态；凭据验证和健康检查通常各需要启动一次。若生产函数名或签名不同，停止并按实际运行代码更新文档，禁止自行猜函数。

### 3.6 policy 的逐阶段迁移

每次 policy 修改都必须在独立事务中按 `account_id + 当前 policy_version` 定位，断言恰好更新一行并令 `policy_version=旧值+1`；提交后重新读取完整 policy。失败时回滚该事务，不能改其他账户。

1. 基础接入：`onboarding`，四开关均 false。
2. callback 兑换和 `oauth_credential_validate` 成功后、启动 `oauth_health_check` 前：仅改 `lifecycle_status=active`；四开关继续 false。
3. 用户明确授权真实手工拉数时：仅将 `manual_fetch_enabled=true`。补拉结束或异常时恢复 false。
4. 用户明确授权灰度小时任务时：设置 `gray_enabled=true`、`hourly_fetch_enabled=true`；`authoritative_daily_enabled` 仍按独立授权保持原值。
5. 用户另行明确授权自动权威日报时，才将 `authoritative_daily_enabled=true`；不得从小时灰度授权推定。

每阶段变更前保存目标 policy 的定向 JSON 快照。回滚只把该 account 恢复到上一 `policy_version` 对应的字段值；schedule 异常时先禁用目标 schedule，再回滚 policy。`exclusion_reason` 非空时不得开启 gray。

### 3.7 Git 和运行代码一致性

```bash
git -C /srv/adx-account-isolated-collector rev-parse HEAD
git -C /srv/adx-account-isolated-collector status --short --branch
git -C /srv/adx-account-isolated-collector diff --check
```

若 systemd `WorkingDirectory` 不是该 Git 目录，继续对实际运行文件与目标提交逐文件计算 SHA-256；未建立一致性证据前禁止发布或修改源码。

## 4. 禁止事项

- 禁止根据历史命令、known_hosts、目录名或聊天记忆猜生产服务器、数据库路径、字段名或运行提交。
- 禁止在脏主目录开发；独立任务必须使用独立 worktree/分支，成果通过 Git 提交合并。
- 禁止直接编辑生产源码，禁止以未提交工作区发布。
- 禁止把密码、Operator Token、OAuth code/state、client secret、refresh/access token或完整代理凭据写入命令文本、文件、日志、Markdown、Git 或普通输出。
- 禁止复制正在运行的 SQLite `.db` 作为备份；必须使用 online backup 并验证。
- 禁止从本机代理测试推断生产出口；禁止代理失败后降级直连 Google。
- 禁止重复创建账户、instance、OAuth App、schedule 或同幂等键任务。
- 禁止重放 OAuth code、恢复已消费 state，或在本地伪造授权链接。
- 禁止把数据库 `authorized/healthy/active` 单独当成真实 OAuth/代理健康证明。
- 禁止把小时任务写入或重建权威日报；禁止把小时汇总冒充权威日报。
- 禁止因单节点接入改动全局 scheduler、其他节点 policy、灰度名单或停拉名单。
- 禁止在启用 schedule 前忽略 OAuth 恢复缺口扫描；禁止把额外自动日期误报成用户授权范围。
- 禁止客户端超时后未经查询就重试创建任务。
- 禁止用 PowerShell 分号连接“检查 → commit → push”等必须短路的步骤；每个原生命令后必须验证 `$LASTEXITCODE`，检查失败立即抛错并停止。

## 5. 回滚步骤

### 5.1 授权前基础资源回滚

先确认目标账户没有任务、batch、报表或有效授权。禁用目标 policy/schedule 后，按实际外键关系逆序只删除本次新增的 policy、proxy binding、staged credential、OAuth App、instance、account。删除前后均执行 `quick_check`，禁止整库恢复。

### 5.2 OAuth 兑换异常

OAuth code/state 不做数据库倒带。保留脱敏错误证据，停止目标节点，重新备份后生成新的 state，并由用户重新授权。只有确认误改了非 OAuth 业务数据时才评估定向恢复。

### 5.3 schedule 或任务范围异常

立即通过目标 schedule 的 PATCH API 设置 `enabled=false`，并验证服务自动将 `next_run_at` 置空；保持其他节点和全局 scheduler 不变。不要强杀已经认领的任务，等待其安全终态；定向取消尚未执行且确定超出授权范围的目标账户任务。

### 5.4 数据投影异常

先停止目标账户产生新任务，再按账户、报告日期和表精确恢复备份覆盖范围。不得使用历史整库备份覆盖其他节点的新数据。小时异常只恢复小时分区；权威日报异常只恢复目标日期的账户/站点日报投影。

### 5.5 代码或配置发布异常

先关闭对应功能开关或目标灰度 key；必要时恢复发布前备份的明确文件和环境项，再重启受影响服务并验证唯一进程、`/health`、Git/文件哈希和数据库完整性。不得使用未经核验的 `rsync --delete`。

## 6. 每次任务的交接输出

最终报告必须给出：目标与授权范围、生产 Git/运行基线、账户/instance/OAuth/proxy/policy/schedule 的脱敏 ID 与状态、写前备份及 `quick_check`、实际操作、任务和 batch 证据、是否影响其他节点、回滚点、最终 Git 状态和发布状态。所有失败尝试和正确替代方法同步追加到维护台账和问题记录。
