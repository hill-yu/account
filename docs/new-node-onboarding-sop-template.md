# 新增第三方节点标准 SOP

日期：2026-06-12

这份文档用于后续新增节点时直接复用。当前标准方案是：

`站点 VPS（只做反代） -> 中台 VPS 上的独立 collector 实例 -> 独立 MySQL 库 -> 固定代理 -> Google Ad Manager`

适用范围：

- 单账号单节点
- 单中台 VPS 多节点
- 节点站点和中台分离部署
- 站点侧只暴露 `/ke/fetch.php` 和 `/ke/report.php`

不适用范围：

- 单节点多账号
- 节点本机自带完整采集后端
- 自动批量开通多节点

---

## 1. 标准架构

当前统一采用下面这套结构：

1. 中台 VPS 负责跑多个 collector 实例
2. 每个节点独立：
   - 一个 MySQL 库
   - 一个 `env`
   - 一个 `systemd service`
   - 一个监听端口
   - 一组 cron 配置
3. 站点 VPS 不跑采集逻辑，只做 nginx 反代
4. 中台通过节点域名 `/ke/report.php` 读数
5. cron 通过节点域名 `/ke/fetch.php` 触发拉数

标准链路：

`用户系统/中台 -> 节点域名 /ke/*.php -> nginx 反代 -> 中台 collector 实例 -> 代理 -> Google Ad Manager`

---

## 2. 新增节点前必须收集的信息

每次新增节点，先收齐下面这些值：

### 2.1 账号基础信息

- 节点名称：例如 `jwtnx`
- 站点域名：例如 `https://jwtnx.com`
- `account_key`：例如 `jwtnx`
- `report_token`：例如 `jwtnx`
- 中台实例名：例如 `jwtnx-node`
- Ad Manager `network_code`

### 2.2 Google OAuth 信息

- `client_id`
- `client_secret`
- OAuth 回调地址
- 授权完成后的 callback URL
- 最终 `refresh_token`

### 2.3 代理信息

- `proxy_type`，目前统一优先用 `socks5`
- `proxy_host`
- `proxy_port`
- `proxy_username`
- `proxy_password`
- `expected_egress_ip`

### 2.4 服务器信息

- 中台 VPS IP、账号、密码
- 站点 VPS IP、账号、密码
- 站点是否由宝塔管理 nginx
- 站点 nginx 配置文件位置

---

## 3. 命名规范

新增节点时统一按下面的规则命名：

- `account_key`: 节点短名，例如 `jwtnx`
- 数据库名：`adx_data_<account_key>`
- env 文件：`/srv/adx-account-isolated-collector/deploy/vps/env/adx-fetch-api-<account_key>.env`
- service 名：`adx-fetch-api-<account_key>.service`
- cron env：`/srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron-<account_key>.env`
- 日志文件：`/var/log/adx-fetch-cron-<account_key>.log`
- 站点 nginx 反代片段：`/www/server/panel/vhost/nginx/extension/<site>/adx-node-proxy.conf`

端口分配规则：

- 已有节点端口不改
- 新节点取下一个空闲端口，例如 `9103`、`9104`、`9105`
- 中台防火墙只对白名单站点 VPS 放行对应端口

---

## 4. 标准接入顺序

每次新增节点，严格按这个顺序做。

### 步骤 1：确认 control plane 基础记录

先确认中台 `control_plane.db` 里已经有：

1. `accounts`
2. `oauth_app_configs`
3. `collector_instances`
4. `proxy_bindings`

至少要核对这些字段：

- `accounts.external_account_id = network_code`
- `collector_instances.report_base_url`
- `collector_instances.report_account_key`
- `collector_instances.report_token`
- `proxy_bindings.protocol/host/port/username/password/expected_egress_ip`

如果缺记录，先补记录，再继续。

### 步骤 2：完成 Google 授权并拿到 refresh token

操作顺序：

1. 打开授权链接
2. 完成 Google 授权
3. 从 callback URL 中拿到 `code`
4. 使用 `client_id/client_secret/redirect_uri/code` 换 token
5. 取出 `refresh_token`
6. 写回中台 `oauth_app_configs.refresh_token`
7. 将 `authorization_status` 改为 `authorized`

注意：

- `refresh_token` 才是长期可用凭据
- `access_token` 不是最终配置项
- 如果用户重复授权，新的 code 要重新换 token，旧 code 可能失效

### 步骤 3：校验代理出口 IP

先手工验证代理是否真的走到目标出口：

```bash
curl -x socks5://USERNAME:PASSWORD@HOST:PORT http://ipinfo.io
```

或：

```bash
curl -x socks5://USERNAME:PASSWORD@HOST:PORT https://api.ipify.org
```

要求：

- 返回 IP 必须等于 `expected_egress_ip`
- 不一致时，不要继续部署

### 步骤 4：在中台 VPS 上创建独立节点库

标准动作：

1. 创建数据库 `adx_data_<account_key>`
2. 给 `adx_user@localhost` 授权
3. 初始化 VPS collector schema
4. 写入 `adx_accounts`
5. 写入 `adx_account_proxies`

要求：

- 一个节点一套独立库
- 不复用其他节点数据库

### 步骤 5：写入节点运行配置

在中台 VPS 新建：

- env 文件
- systemd service
- cron env

env 典型内容：

```env
ADX_VPS_DATABASE_URL=mysql+pymysql://adx_user:123456789@127.0.0.1:3306/adx_data_xxx
ADX_VPS_SQL_ECHO=false
ADX_VPS_BIND_HOST=0.0.0.0
ADX_VPS_BIND_PORT=9103
ADX_TRIGGER_TOKEN=xxx
ADX_VPS_REQUEST_TIMEOUT_SECONDS=30
ADX_VPS_EGRESS_CHECK_URL=https://api.ipify.org
```

cron env 典型内容：

```env
ADX_FETCH_BASE_URL=https://example.com
ADX_FETCH_ACCOUNT_KEY=xxx
ADX_FETCH_TOKEN=xxx
ADX_FETCH_TIMEZONE=Asia/Shanghai
```

### 步骤 6：启动中台实例

标准动作：

```bash
systemctl daemon-reload
systemctl enable adx-fetch-api-<account_key>.service
systemctl restart adx-fetch-api-<account_key>.service
systemctl status adx-fetch-api-<account_key>.service --no-pager
```

健康检查：

```bash
curl http://127.0.0.1:<port>/health
```

预期：

```json
{"status":"ok"}
```

### 步骤 7：安装 cron

标准策略：

- 北京时间每天两次
- 默认是 `09:00` 和 `21:00`
- 多节点时建议错峰，例如：
  - 节点 A：`00`
  - 节点 B：`05`
  - 节点 C：`10`

示例：

```cron
10 9 * * * ADX_FETCH_ENV_FILE=/srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron-jwtnx.env /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron-jwtnx.log 2>&1
10 21 * * * ADX_FETCH_ENV_FILE=/srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron-jwtnx.env /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron-jwtnx.log 2>&1
```

安装后必须执行：

```bash
crontab -l
```

### 步骤 8：在站点 VPS 上配置 nginx 反代

站点 VPS 只需要把公网路径反代到中台 collector 实例端口。

标准反代配置：

```nginx
location = /ke/fetch.php {
    proxy_pass http://MID_PLATFORM_IP:PORT/public/fetch.php;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /ke/report.php {
    proxy_pass http://MID_PLATFORM_IP:PORT/public/report.php;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

如果站点由宝塔管理，通常放在：

`/www/server/panel/vhost/nginx/extension/<site>/adx-node-proxy.conf`

改完后必须执行：

```bash
/www/server/nginx/sbin/nginx -t
/etc/init.d/nginx reload
```

### 步骤 9：放行中台防火墙

如果中台启用了 `ufw`，必须允许“站点 VPS -> 节点端口”。

例如：

```bash
ufw allow from 104.244.95.68 to any port 9103 proto tcp
```

这一条非常关键。  
如果漏掉，公网 `/ke/fetch.php` 和 `/ke/report.php` 会一直超时。

### 步骤 10：更新 control plane 节点状态

至少确认这几个值正确：

- `report_base_url`
- `report_account_key`
- `report_token`
- `status`

推荐状态：

- 配置完成后改成 `ready`

---

## 5. 标准验收流程

新增节点以后，必须按下面顺序验收。

### 5.1 中台实例健康检查

```bash
curl http://127.0.0.1:<port>/health
```

预期：HTTP 200，返回 `{"status":"ok"}`

### 5.2 站点 VPS 到中台实例连通性

在站点 VPS 上执行：

```bash
curl -o /dev/null -w '%{http_code}' http://MID_PLATFORM_IP:PORT/health
```

预期：`200`

### 5.3 公网 report 检查

```bash
curl "https://DOMAIN/ke/report.php?account_key=ACCOUNT_KEY&report_date=YYYY-MM-DD&token=TOKEN"
```

首次未拉数前，预期通常是：

- `ok = true`
- `has_run = false`

### 5.4 公网 fetch 触发

```bash
curl "https://DOMAIN/ke/fetch.php?account_key=ACCOUNT_KEY&report_date=YYYY-MM-DD&token=TOKEN"
```

预期：

- `ok = true`
- `status = accepted`

### 5.5 轮询 report 结果

```bash
sleep 8
curl "https://DOMAIN/ke/report.php?account_key=ACCOUNT_KEY&report_date=YYYY-MM-DD&token=TOKEN"
```

预期：

- `has_run = true`
- `run_status = success`
- `row_count >= 0`

### 5.6 节点库核验

```bash
mysql -uroot -N -e "USE adx_data_<account_key>; SELECT id, report_date, status, row_count, LEFT(IFNULL(error_message,''),200) FROM adx_fetch_runs ORDER BY id DESC LIMIT 5;"
```

预期：

- 最新 run 状态是 `success`
- `error_message` 为空

---

## 6. 常见故障排查

### 问题 1：公网接口超时

优先检查：

1. nginx 反代是否写对
2. 中台实例端口是否在监听
3. `ufw` 是否已放行站点 VPS 到该端口

关键命令：

```bash
ss -ltnp | grep 9103
ufw status numbered
curl http://127.0.0.1:9103/health
```

### 问题 2：`fetch.php` accepted 了，但一直没数据

优先检查：

1. 后台 worker 是否正常运行
2. 代理出口 IP 是否匹配
3. OAuth refresh token 是否有效
4. `network_code` 是否正确

关键命令：

```bash
journalctl -u adx-fetch-api-<account_key>.service -n 100 --no-pager
mysql -uroot -N -e "USE adx_data_<account_key>; SELECT id, report_date, status, row_count, error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
```

### 问题 3：OAuth 已授权，但仍无法拉数

优先检查：

1. `oauth_app_configs.authorization_status` 是否真的是 `authorized`
2. `refresh_token` 是否已写入
3. `redirect_uri` 是否和授权时一致
4. 当前账号对应的 `network_code` 是否属于这套 OAuth

### 问题 4：站点 VPS 能 reload nginx，但公网还是不通

优先检查：

1. 域名解析是否已到该站点 VPS
2. Cloudflare 是否命中了正确站点
3. 站点 nginx 是否是正确站点配置
4. 是否把配置写到了错误的 extension 目录

---

## 7. 下次新增节点时的执行清单

以后只要你说“按标准流程新增节点”，默认按这张清单执行：

1. 收集节点、域名、OAuth、代理、服务器信息
2. 核对 control plane 记录
3. 完成 OAuth 授权并写入 `refresh_token`
4. 验证代理出口 IP
5. 在中台建独立库并初始化 schema
6. 写入 `adx_accounts` 和 `adx_account_proxies`
7. 创建独立 env、service、cron env
8. 启动 service 并过健康检查
9. 安装 cron
10. 在站点 VPS 配 nginx 反代
11. 放行中台防火墙端口
12. 更新 `collector_instances` 配置和状态
13. 执行公网 `fetch/report` 验收
14. 返回验收结果和已落地配置路径

---

## 8. 当前已验证通过的样板

当前这套 SOP 已经按真实环境验证过，至少覆盖过下面这类节点：

- `loshiny`
- `jwtnx`

`jwtnx` 的真实模式是：

- 中台 VPS：`97.64.83.11`
- 站点 VPS：`104.244.95.68`
- 站点侧仅反代
- 中台实例端口：`9103`
- 中台独立库：`adx_data_jwtnx`
- cron：`09:10` / `21:10`

所以后续第四个、第五个节点，继续按这份 SOP 扩展就行。
