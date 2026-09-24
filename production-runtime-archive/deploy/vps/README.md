# VPS 触发式部署说明

## Python API

1. 安装 `collector/requirements.txt` 里的 Python 依赖。
2. 将 `deploy/vps/env/adx-fetch-api.env.example` 复制为 `deploy/vps/env/adx-fetch-api.env`。
3. 填写真实的 MySQL 连接串和触发令牌。
4. 运行 `python scripts/init_vps_schema.py` 初始化表结构。  
   Python 设置层会自动读取 `deploy/vps/env/adx-fetch-api.env`。
5. 将 `deploy/vps/systemd/adx-fetch-api.service` 安装到 `/etc/systemd/system/`。
6. 使用 `systemctl enable --now adx-fetch-api` 启动常驻服务。
7. 用 `curl http://127.0.0.1:9100/health` 验证服务健康状态。

```bash
sudo cp /srv/adx-account-isolated-collector/deploy/vps/systemd/adx-fetch-api.service /etc/systemd/system/adx-fetch-api.service
sudo systemctl daemon-reload
sudo systemctl enable adx-fetch-api
sudo systemctl restart adx-fetch-api
sudo systemctl status adx-fetch-api --no-pager
curl http://127.0.0.1:9100/health
```

## PHP 触发器

- 将 `deploy/vps/php/fetch.php` 放到对外 API 站点的根目录或对应路由目录下。
- 将 `deploy/vps/php/report.php` 放到同一个公开站点目录下，供中台读取站点日报结果。
- 确保 PHP 已启用 `curl` 扩展。
- 在 PHP-FPM 环境里配置 `ADX_TRIGGER_TOKEN`。

## Cloudflare

- 将 API 子域名解析并代理到你的 VPS 源站。
- Cloudflare 只负责 DNS、HTTPS 和入口代理，不承载拉数逻辑。

## 冒烟测试

部署完成后，建议按下面顺序验证：

1. 先触发拉数，确认返回 `status=accepted`：

`https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me`

2. 等待数秒后轮询读取结果：

`https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me`

`report.php` 的返回语义固定为：

- `has_run=false`：这一天还没有成功结果快照
- `run_status=success`：表示当前已经存在最新成功 run 的结果快照
- `run_status=null`：表示当前还没有可返回的成功结果
- `error_message`：当前固定为 `null`，`report.php` 不再承担失败状态透传

中台接入时建议固定按下面顺序处理：

1. 调 `fetch.php`，只把 `status=accepted` 解释为“任务已受理”
2. 等待数秒后轮询 `report.php`
3. 先看 `ok`
4. 再看 `has_run`
5. 只有在 `has_run=true` 且 `run_status=success` 时才正式读取 `row_count` 和 `items`

不要只根据 `row_count` 判断结果，因为：

- `has_run=false` 时，`row_count=0` 只表示当前没有成功结果快照
- 只有 `has_run=true` 且 `run_status=success` 时，`row_count` 才表示实际结果行数

## 常用检查命令

```bash
sudo systemctl status adx-fetch-api --no-pager
sudo journalctl -u adx-fetch-api -n 100 --no-pager
curl http://127.0.0.1:9100/health
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT id, account_id, report_date, status, row_count, request_id, error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT account_id, report_date, site_name, responses_served, impressions, clicks, revenue, ecpm FROM adx_site_daily_reports ORDER BY id DESC LIMIT 20;"
```

## Cron 自动拉数

1. 复制配置样板：
   `cp /srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env.example /srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env`
2. 填写真值：
   - `ADX_FETCH_BASE_URL`
   - `ADX_FETCH_ACCOUNT_KEY`
   - `ADX_FETCH_TOKEN`
   - `ADX_FETCH_TIMEZONE`
3. 赋予脚本执行权限：
   `chmod +x /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`
4. 手工 smoke test：
   `/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`
5. 安装 crontab：
   `crontab -e`
6. 写入：
   `0 9 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1`
   `0 21 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1`

### 常用检查命令

```bash
tail -n 50 /var/log/adx-fetch-cron.log
crontab -l
curl "https://api.wangmengmeng.fun/ke/report.php?account_key=a1&report_date=$(TZ=Asia/Shanghai date -d 'yesterday' +%F)&token=YOUR_TOKEN"
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT id, account_id, report_date, status, row_count, request_id, error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
```

### 手工补跑示例

拉昨天：

```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh
```

补跑单天：

```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-07
```

补跑范围：

```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-01 2026-06-07
```
