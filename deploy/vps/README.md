# VPS 触发式部署说明

## Python API

1. 安装 `collector/requirements.txt` 里的 Python 依赖。
2. 将 `deploy/vps/env/adx-fetch-api.env.example` 复制为 `deploy/vps/env/adx-fetch-api.env`。
3. 填写真实的 MySQL 连接串和触发令牌。
4. 运行 `python scripts/init_vps_schema.py` 初始化表结构。  
   Python 设置层会自动读取 `deploy/vps/env/adx-fetch-api.env`。
5. 在 `collector/` 目录下启动 API：

```bash
python -m uvicorn app.vps_api:app --host 127.0.0.1 --port 9100
```

## PHP 触发器

- 将 `deploy/vps/php/fetch.php` 放到对外 API 站点的根目录或对应路由目录下。
- 确保 PHP 已启用 `curl` 扩展。
- 在 PHP-FPM 环境里配置 `ADX_TRIGGER_TOKEN`。

## Cloudflare

- 将 API 子域名解析并代理到你的 VPS 源站。
- Cloudflare 只负责 DNS、HTTPS 和入口代理，不承载拉数逻辑。

## 冒烟测试

部署完成后，可以直接访问：

`https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me`
