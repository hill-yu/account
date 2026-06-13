# 操作说明

这份文档描述的是当前独立 MVP 在接入真实 Google OAuth 和 runtime-config 握手之后的本地操作流程。

## 服务与启动顺序

## 最快的虚拟演示

如果你想最快体验本地全链路，但暂时不需要真实 Google OAuth，可以直接运行：

```bash
python scripts/virtual_flow.py
```

这个脚本会完成一次完整的本地往返流程，包括：

- 一个临时 SQLite 数据库
- 一个真实启动的 backend 进程
- 一个真实启动的 collector 进程
- 一份 stub 站点数据

它会输出一段 JSON 摘要，包含：

- collector 退出码
- 最终任务状态
- 投影后的 `site_daily` 行数
- 第一条站点 URL
- 最终账号级 `responses_served`
- 最终账号级 `revenue`

推荐启动顺序：

1. 启动 PostgreSQL。
2. 启动 backend，并等待 `/health` 返回 `{"status":"ok"}`。
3. 创建账号、OAuth 应用、collector 实例、代理绑定和第一条同步任务。
4. 为该账号完成 Google OAuth 授权。
5. 使用真实 `instance_token` 运行示例 collector。

命令如下：

```bash
docker compose -f deploy/docker-compose.yml up -d postgres
docker compose -f deploy/docker-compose.yml up -d backend
curl http://localhost:8000/health
```

backend 容器会在启动 Uvicorn 之前自动执行 `alembic upgrade head`，所以 schema 初始化已经包含在正常启动流程里。

## Runtime 边界

collector 不再直接从 Compose 接收代理配置和 Google OAuth 密钥。

现在的流程是：

1. 操作端通过 operator 路由创建账号、OAuth、实例和代理记录
2. collector 使用自己的 `instance_token` 进行认证
3. collector 拉取 `GET /api/v1/collector/runtime-config`
4. backend 将代理绑定和 Google runtime 凭据一起返回给该 collector 实例

这仍然是本地 MVP。当前阶段里，密钥会以原始形式存储在 backend 数据库中，然后返回给已认证的 collector 实例。这只适用于当前阶段，也只适用于本地/私有环境。

## 环境变量

### Backend

backend 使用 `ADX_COLLECTOR_` 前缀的设置项。

- `ADX_COLLECTOR_DATABASE_URL`：SQLAlchemy 连接串。Compose 默认使用 `postgresql+psycopg://adx:adx@postgres:5432/adx_collector`
- `ADX_COLLECTOR_APP_ENV`：环境标签，例如 `development` 或 `docker`
- `ADX_COLLECTOR_SQL_ECHO`：可选的 SQLAlchemy 日志开关，默认为 `False`
- `ADX_COLLECTOR_APP_NAME`：可选的 FastAPI 应用标题

### Collector

collector 完全由环境变量驱动，并且执行一次 runtime pass 后退出。

- `CONTROL_PLANE_BASE_URL`：backend 基础地址，例如在 Compose 中是 `http://backend:8000`
- `COLLECTOR_INSTANCE_TOKEN`：通过 operator API 创建 collector 实例时得到的 bearer token
- `COLLECTOR_EGRESS_CHECK_URL`：可选的公网 IP 检查地址，默认是 `https://api.ipify.org`
- `COLLECTOR_REQUEST_TIMEOUT_SECONDS`：可选 HTTP 超时，默认 `30`

其余执行任务所需信息全部来自 runtime-config 路由，包括：

- 代理协议、host、port、username、password
- 预期出口 IP
- fetch mode
- Ad Manager network code
- Google OAuth client id
- Google OAuth client secret
- Google OAuth refresh token

## 首次手工同步流程

发送示例请求前，请把所有大写占位符，例如 `ACCOUNT_ID`、`INSTANCE_ID`、`OAUTH_APP_ID`，都替换成真实值。

### 1. 创建账号

在这个 phase-1 MVP 里，`external_account_id` 用来存储 Google Ad Manager network code。

```bash
curl -X POST http://localhost:8000/api/v1/operator/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Example Account",
    "status": "active",
    "external_account_id": "1234567"
  }'
```

把返回的 `id` 记录为 `ACCOUNT_ID`。

### 2. 创建 OAuth 应用配置

```bash
curl -X POST http://localhost:8000/api/v1/operator/oauth-apps \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "client_id": "google-client-id",
    "client_secret": "google-client-secret",
    "redirect_uri": "http://localhost:8000/api/v1/oauth/google/callback",
    "scopes": "https://www.googleapis.com/auth/dfp",
    "app_status": "active",
    "verification_status": "pending"
  }'
```

把返回的 `id` 记录为 `OAUTH_APP_ID`。

### 3. 生成授权 URL

```bash
curl -X POST http://localhost:8000/api/v1/operator/oauth-apps/1/authorization-url
```

在浏览器中打开返回的 `authorization_url`，完成授权，并允许 Google 回调到：

```text
http://localhost:8000/api/v1/oauth/google/callback
```

回调成功后，backend 应将该 OAuth 应用标记为：

- `authorization_status = authorized`
- `refresh_token_present = true`

验证：

```bash
curl http://localhost:8000/api/v1/operator/oauth-apps
```

### 4. 创建 collector 实例

```bash
curl -X POST http://localhost:8000/api/v1/operator/instances \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "name": "local-collector-1",
    "status": "provisioning",
    "expected_egress_ip": "203.0.113.10"
  }'
```

需要记录：

- `INSTANCE_ID`
- `instance_token`

当前 MVP 中，`instance_token` 只会在创建时返回一次，请立即保存。这个 token 是 collector 拉取 runtime-config 和访问 `/api/v1/collector/*` 路由的 bearer 凭据。

### 5. 创建代理绑定

```bash
curl -X POST http://localhost:8000/api/v1/operator/proxies \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "collector_instance_id": 1,
    "provider_name": "manual-local-proxy",
    "protocol": "socks5",
    "host": "proxy.example.internal",
    "port": 1080,
    "username": "proxy-user",
    "password": "proxy-password",
    "expected_egress_ip": "203.0.113.10",
    "status": "active"
  }'
```

### 6. 创建手工同步任务

```bash
curl -X POST http://localhost:8000/api/v1/operator/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "collector_instance_id": 1,
    "task_type": "report_fetch",
    "report_date": "2026-05-21",
    "status": "pending",
    "external_request_id": "manual-local-run-001"
  }'
```

### 7. 查看 collector runtime config

这一步可选，但在第一次运行前非常有帮助。

```bash
curl http://localhost:8000/api/v1/collector/runtime-config \
  -H "Authorization: Bearer <instance-token>"
```

你应该看到：

- 来自代理绑定的代理字段
- `expected_egress_ip`
- `google.fetch_mode = admanager_soap`
- 账号 `external_account_id` 中的 Ad Manager network code

如果 OAuth 应用尚未完全授权，或者账号没有 network code，这个路由会返回 `409`。

### 8. 运行 collector

使用刚才保存的 token。collector 会从 backend 拉取其余所有 runtime 设置。

```bash
docker compose -f deploy/docker-compose.yml run --rm \
  -e COLLECTOR_INSTANCE_TOKEN=<instance-token> \
  collector-example
```

预期运行行为：

1. collector 从 control plane 请求 runtime config
2. collector 通过配置的代理检查自己观察到的公网 IP
3. 如果观察到的 IP 和预期 egress IP 不一致，它会回传一个 `blocked` heartbeat，并以退出码 `2` 退出
4. 如果 IP 匹配，它会回传一个 `ready` heartbeat，领取一条 pending 任务，执行 fetcher，上传 0 个或多个 batch，并将任务标记为终态

### 9. 查看任务和实例状态

```bash
curl http://localhost:8000/api/v1/operator/tasks
curl http://localhost:8000/api/v1/operator/instances
curl http://localhost:8000/api/v1/operator/oauth-apps
```

你应该看到任务从 `pending` -> `in_progress` -> `succeeded`，同时实例的 `last_heartbeat_at` 被写入。

## Phase-1 Ad Manager Fetcher 说明

当前真实 collector fetcher 走的是 Ad Manager SOAP `ReportService`，作为独立 MVP 的真实数据链路。

当前已验证可用的报表定义是站点级 AdX 数据，并且可以投影进现有的行结构：

- 维度：`DATE_PT`、`SITE_NAME`
- 指标：
  - `AD_EXCHANGE_RESPONSES_SERVED`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`
- 时区：`PACIFIC`
- 日期范围：每个任务固定一天

每一页返回数据都会被归一化成以下 staging 字段：

- `report_date`
- `url_id`
- `url`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

这些行会先落到 control plane 侧的 `collector_ingestion_batches.payload_json` 里，作为一个可持久化的中间层，再进入最终业务表。

backend 当前也会继续把这些 staging 行投影到最终查询表：

- `site_daily_reports`
- `account_daily_reports`

你可以通过下面接口查看：

```bash
curl "http://localhost:8000/api/v1/operator/reports/site-daily?account_id=1&report_date=2026-05-21"
curl "http://localhost:8000/api/v1/operator/reports/account-daily?account_id=1&report_date=2026-05-21"
```

## VPS 触发链路

VPS 部署路径使用：

- 公网 PHP 触发器：`GET /ke/fetch.php`
- 本机 Python API：`POST http://127.0.0.1:9100/internal/fetch`
- 公网 PHP 读数接口：`GET /ke/report.php`
- 本机 Python 读数 API：`GET http://127.0.0.1:9100/internal/reports/site-daily`
- 结果存储表：
  - `adx_accounts`
  - `adx_account_proxies`
  - `adx_fetch_runs`
  - `adx_site_daily_reports`

常用运行检查命令：

```bash
sudo systemctl status adx-fetch-api --no-pager
sudo journalctl -u adx-fetch-api -n 100 --no-pager
curl http://127.0.0.1:9100/health
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT id, account_id, report_date, status, row_count, request_id, error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT account_id, report_date, site_name, responses_served, impressions, clicks, revenue, ecpm FROM adx_site_daily_reports ORDER BY id DESC LIMIT 20;"
curl "https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me"
```

公网触发与轮询建议按下面顺序执行：

```bash
curl "https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me"
curl "https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me"
```

当前 `report.php` 的状态语义为：

- `has_run=false`：该日期还没有成功结果快照
- `run_status=success` 且 `row_count=0`：最近一次成功结果存在，但该天无数据
- `run_status=success` 且 `row_count>0`：最近一次成功结果存在，且可直接读取 `items`
- `run_status=null`：当前没有可返回的成功结果
- `error_message`：当前固定为 `null`，不再透传最新失败任务的错误

中台集成时，应将：

- `fetch.php` 视为“提交任务接口”
- `report.php` 视为“读取最新成功结果快照接口”

不要仅根据 `row_count` 判断结果，必须结合 `has_run` 与 `run_status` 一起解释：

- `has_run=false` 下的 `row_count=0` 只表示“当前没有成功结果”
- 只有 `has_run=true` 且 `run_status=success` 时，`row_count` 才表示真实结果行数

当前生产化路径仍然使用我们已经验证通过的站点级 SOAP 报表语义：

- `DATE_PT`
- `SITE_NAME`
- `AD_EXCHANGE_RESPONSES_SERVED`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`

## 当前限制与注意事项

- Compose 文件中的 `COLLECTOR_INSTANCE_TOKEN` 是占位用的，不要指望 `collector-example` 开箱即用。
- 不推荐第一次就直接 `docker compose up` 全部服务，因为 collector 依赖真实 instance token 和完整 backend 配置。
- 当前 MVP 的 operator 路由没有鉴权，请只在本地环境使用。
- PostgreSQL 数据会保存在 `postgres-data` 命名卷里，除非你手动删除。
- 为了 MVP 迭代速度，OAuth 密钥和 refresh token 当前仍以原始形式保存在 backend 数据库中。这是已知后续项，不是生产级设计。
- 当前触发 token 按用户决定继续沿用，不在本阶段轮换。这是显式接受的运行风险。

## 前端控制台说明

项目当前还包含一个轻量级前端 control plane，位于 `frontend/`。

本地启动方式：

```bash
cd frontend
npm install
npm run dev
```

默认 API 目标：

- `http://127.0.0.1:8000`

如果你在本地验证时 backend 使用了其他端口：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

phase 1 的 UI 故意保持很窄：

- `Operations`：创建账号、OAuth 应用、实例、代理和任务
- `Reports`：查看 `site_daily` 和 `account_daily`
- `OAuth callback`：在前端路由 `/oauth/google/callback` 中完成 Google 授权回调

如果你想让本地 OAuth 流程更顺，建议把 OAuth 应用回调地址设为前端回调 URL，例如：

```text
http://127.0.0.1:4173/oauth/google/callback
```

这样前端回调页会再去调用 backend 的 `/api/v1/oauth/google/callback` 完成 token 交换，并展示更友好的结果页。

当前最快的 backend/collector 路径验证方式仍然是：

```bash
python scripts/virtual_flow.py
```

前端的作用是替代常见的手工 operator API 调用，不是为了替代当前终端里的 demo 脚本。

## VPS cron 自动拉数

当前 cron 策略固定为：
- 每天北京时间 09:00 触发一次
- 每天北京时间 21:00 再触发一次
- 两次都默认拉取“昨天”的数据

当前策略只保证“受理触发”，即脚本成功标准是 `fetch.php` 返回 `ok=true` 且 `status=accepted`。
脚本本身不轮询 `report.php`，也不自动重试；如需确认最终结果，请再查询 `report.php` 或检查 `adx_fetch_runs`。

补跑范围时：
- 脚本会按天逐个调用现有 `fetch.php`
- 某一天失败不会中断后续日期
- 执行结束后会输出 success/failed 汇总
- 只要范围内存在失败日期，脚本整体 exit code 就是非 0
