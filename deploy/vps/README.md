# VPS Trigger Deployment

## Python API

1. Install Python dependencies from `collector/requirements.txt`.
2. Copy `deploy/vps/env/adx-fetch-api.env.example` to `deploy/vps/env/adx-fetch-api.env`.
3. Set a real MySQL URL and trigger token.
4. Run `python scripts/init_vps_schema.py`. The Python settings layer will read `deploy/vps/env/adx-fetch-api.env` automatically.
5. Start the API from `collector/` with `python -m uvicorn app.vps_api:app --host 127.0.0.1 --port 9100`.

## PHP Trigger

- Place `deploy/vps/php/fetch.php` under the public API site root.
- Ensure PHP has `curl` enabled.
- Set `ADX_TRIGGER_TOKEN` in the PHP-FPM environment.

## Cloudflare

- Point the API subdomain to the VPS origin.
- Keep Cloudflare as DNS/HTTPS ingress only.

## Smoke Test

Call:

`https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me`
