# 新账号新站点部署模板

日期：2026-06-08

这份模板用于复制当前已经跑通的执行节点模式：

- 一个站点/API 域名
- 一套 `fetch.php` / `report.php`
- 一套本机 Python API
- 一个 AdX 账号
- 一条固定代理
- 一个固定出口 IP

目标架构：

`Cloudflare -> 站点 fetch.php/report.php -> 本机 Python API -> 固定代理 -> Google AdX -> 本机 MySQL -> 中台读取`

---

## 1. 节点标准

每个新节点都按下面约束部署：

- 一节点一账号
- 一节点一代理
- 一节点一固定出口 IP
- 中台只读该节点结果，不参与 Google 拉数

当前不建议在一个节点里混多个账号。

---

## 2. 需要提前准备的资料

部署一个新节点前，先准备这 8 项：

1. `站点/API 域名`
2. `VPS 公网 IP`
3. `account_key`
4. `account_name`
5. `network_code`
6. `client_id / client_secret / refresh_token`
7. `proxy_type / host / port / username / password`
8. `expected_egress_ip`

建议你在部署前先手工验证代理出口：

```bash
curl -x socks5://USERNAME:PASSWORD@HOST:PORT http://ipinfo.io/ip
```

输出 IP 应等于你要写入库里的 `expected_egress_ip`。

---

## 3. 目录约定

假设这台新节点仍然使用当前项目结构：

- 项目目录：
  - `/srv/adx-account-isolated-collector`
- 站点目录：
  - `/www/wwwroot/API_DOMAIN`
- PHP 入口目录：
  - `/www/wwwroot/API_DOMAIN/ke`

其中：

- `fetch.php` 用于触发拉数
- `report.php` 用于读取最新成功结果快照

---

## 4. Python API 环境文件模板

复制：

```bash
cp /srv/adx-account-isolated-collector/deploy/vps/env/adx-fetch-api.env.example /srv/adx-account-isolated-collector/deploy/vps/env/adx-fetch-api.env
```

填入真实值：

```env
ADX_VPS_DATABASE_URL=mysql+pymysql://adx_user:YOUR_DB_PASSWORD@127.0.0.1:3306/adx_data
ADX_VPS_SQL_ECHO=false
ADX_VPS_BIND_HOST=127.0.0.1
ADX_VPS_BIND_PORT=9100
ADX_VPS_REQUEST_TIMEOUT_SECONDS=30
ADX_VPS_EGRESS_CHECK_URL=https://api.ipify.org
ADX_TRIGGER_TOKEN=YOUR_TRIGGER_TOKEN
```

说明：

- `ADX_VPS_EGRESS_CHECK_URL` 当前保持 `https://api.ipify.org`
- `ADX_TRIGGER_TOKEN` 是 PHP 入口和中台访问用的 token

---

## 5. PHP 站点文件

复制到站点目录：

```bash
mkdir -p /www/wwwroot/API_DOMAIN/ke
cp /srv/adx-account-isolated-collector/deploy/vps/php/fetch.php /www/wwwroot/API_DOMAIN/ke/fetch.php
cp /srv/adx-account-isolated-collector/deploy/vps/php/report.php /www/wwwroot/API_DOMAIN/ke/report.php
```

语法检查：

```bash
php -l /www/wwwroot/API_DOMAIN/ke/fetch.php
php -l /www/wwwroot/API_DOMAIN/ke/report.php
```

---

## 6. PHP-FPM 触发 token

在 PHP-FPM pool 配置里加入：

```ini
env[ADX_TRIGGER_TOKEN] = YOUR_TRIGGER_TOKEN
```

然后重启：

```bash
sudo systemctl restart php8.3-fpm
```

如果你的 PHP 版本不是 `8.3`，按实际版本替换。

---

## 7. 数据库初始化

如果这台节点还是第一次部署，先执行 schema 初始化：

```bash
cd /srv/adx-account-isolated-collector
source collector/.venv/bin/activate
python scripts/init_vps_schema.py
```

---

## 8. 新账号 + 固定代理 SQL 模板

可直接参考：

[deploy/vps/sql/single-account-node-template.sql.example](D:/code/adx-account-isolated-collector/deploy/vps/sql/single-account-node-template.sql.example)

典型执行顺序：

1. 插入 `adx_accounts`
2. 删除该账号旧代理绑定
3. 插入一条新的 `adx_account_proxies`

---

## 9. systemd 服务

安装 service：

```bash
sudo cp /srv/adx-account-isolated-collector/deploy/vps/systemd/adx-fetch-api.service /etc/systemd/system/adx-fetch-api.service
sudo systemctl daemon-reload
sudo systemctl enable adx-fetch-api
sudo systemctl restart adx-fetch-api
sudo systemctl status adx-fetch-api --no-pager
```

健康检查：

```bash
curl http://127.0.0.1:9100/health
```

预期：

```json
{"status":"ok"}
```

---

## 10. Cloudflare 入口

对每个新站点/API 节点，Cloudflare 只负责：

- 域名解析
- HTTPS
- 反向代理入口

它不负责真实拉数。

新节点只需要保证：

- 子域名已指向该 VPS
- `fetch.php` / `report.php` 能通过公网访问

---

## 11. 首轮验收步骤

### 11.1 先检查代理出口

```bash
curl -x socks5://USERNAME:PASSWORD@HOST:PORT http://ipinfo.io/ip
```

确认输出是你配置进库里的 `expected_egress_ip`。

### 11.2 再做公网触发

```bash
curl "https://API_DOMAIN/ke/fetch.php?account_key=ACCOUNT_KEY&report_date=2026-05-14&token=YOUR_TRIGGER_TOKEN"
```

预期：

- `ok = true`
- `status = accepted`

### 11.3 再查结果

```bash
sleep 8
curl "https://API_DOMAIN/ke/report.php?account_key=ACCOUNT_KEY&report_date=2026-05-14&token=YOUR_TRIGGER_TOKEN"
```

预期：

- `has_run = true`
- `run_status = success`
- `row_count > 0`
- `items` 有站点数据

### 11.4 查数据库

```bash
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT id,report_date,status,row_count,request_id,error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
```

成功标准：

- 最新 run 为 `success`
- `error_message` 为空

---

## 12. 常用排查命令

```bash
sudo systemctl status adx-fetch-api --no-pager
sudo journalctl -u adx-fetch-api -n 100 --no-pager
curl http://127.0.0.1:9100/health
```

```bash
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT id,report_date,status,row_count,request_id,error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
```

```bash
curl "https://API_DOMAIN/ke/report.php?account_key=ACCOUNT_KEY&report_date=YYYY-MM-DD&token=YOUR_TRIGGER_TOKEN"
```

---

## 13. 复制新节点时只需要替换的内容

每次复制一个新账号新站点节点，只需要替换这些值：

- `API_DOMAIN`
- `VPS 公网 IP`
- `account_key`
- `account_name`
- `network_code`
- `client_id`
- `client_secret`
- `refresh_token`
- `proxy_type`
- `proxy_host`
- `proxy_port`
- `proxy_username`
- `proxy_password`
- `expected_egress_ip`
- `YOUR_TRIGGER_TOKEN`
- `YOUR_DB_PASSWORD`

---

## 14. 当前契约边界

这个模板当前只保证：

- 单账号节点
- 固定代理出站
- 固定出口 IP 校验
- 公网 `fetch/report` 不变
- cron 可继续复用

当前不在这个模板里解决：

- 单节点多账号
- 多代理自动切换
- 中台跨节点聚合
- 失败告警系统

