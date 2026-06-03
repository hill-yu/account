# Operator Notes

These notes describe the local phase-1 operator flow for the standalone MVP after the real Google OAuth and runtime-config handshake were added.

## Services And Startup Order

## Fastest Virtual Demo

If you want the fastest possible local体验 and do not need real Google OAuth yet, run:

```bash
python scripts/virtual_flow.py
```

That script performs a full local round-trip with:

- a temporary SQLite database
- a real backend process
- a real collector process
- stub site data

It prints a JSON summary including:

- collector exit code
- final task status
- projected `site_daily` row count
- first site URL
- final account-level `responses_served`
- final account-level `revenue`

Recommended startup order:

1. Start PostgreSQL.
2. Start the backend and wait for `/health` to return `{"status":"ok"}`.
3. Create the account, OAuth app, collector instance, proxy binding, and first sync task.
4. Complete Google OAuth authorization for that account.
5. Run the example collector with the real instance token.

Commands:

```bash
docker compose -f deploy/docker-compose.yml up -d postgres
docker compose -f deploy/docker-compose.yml up -d backend
curl http://localhost:8000/health
```

The backend container runs `alembic upgrade head` before starting Uvicorn, so schema bootstrapping is part of normal startup.

## Runtime Boundary

The collector no longer receives proxy settings and Google OAuth secrets directly from Compose.

Instead:

1. the operator creates account, OAuth, instance, and proxy records through operator routes
2. the collector authenticates with its `instance_token`
3. the collector fetches `GET /api/v1/collector/runtime-config`
4. the backend returns the proxy binding plus Google runtime credentials for that instance

This is still a local MVP. Secrets are currently stored in the backend database in raw form and then returned to the authenticated collector instance. That is acceptable only for this phase and only for a local/private environment.

## Environment Variables

### Backend

The backend reads `ADX_COLLECTOR_`-prefixed settings.

- `ADX_COLLECTOR_DATABASE_URL`: SQLAlchemy connection string. Compose uses `postgresql+psycopg://adx:adx@postgres:5432/adx_collector`.
- `ADX_COLLECTOR_APP_ENV`: free-form environment label such as `development` or `docker`.
- `ADX_COLLECTOR_SQL_ECHO`: optional SQLAlchemy SQL logging flag, defaults to `False`.
- `ADX_COLLECTOR_APP_NAME`: optional FastAPI app title.

### Collector

The collector is env-only and exits after one runtime pass.

- `CONTROL_PLANE_BASE_URL`: base URL for the backend, for example `http://backend:8000` inside Compose.
- `COLLECTOR_INSTANCE_TOKEN`: bearer token for the collector instance created through the operator API.
- `COLLECTOR_EGRESS_CHECK_URL`: optional public IP endpoint, defaults to `https://api.ipify.org`.
- `COLLECTOR_REQUEST_TIMEOUT_SECONDS`: optional HTTP timeout, defaults to `30`.

Everything else needed to execute a task now comes from the runtime-config route:

- proxy protocol, host, port, username, password
- expected egress IP
- fetch mode
- Ad Manager network code
- Google OAuth client id
- Google OAuth client secret
- Google OAuth refresh token

## First Manual Sync Flow

Replace every all-caps placeholder such as `ACCOUNT_ID`, `INSTANCE_ID`, and `OAUTH_APP_ID` before sending the example requests.

### 1. Create an account

Use `external_account_id` to store the Google Ad Manager network code in this phase-1 MVP.

```bash
curl -X POST http://localhost:8000/api/v1/operator/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Example Account",
    "status": "active",
    "external_account_id": "1234567"
  }'
```

Record the returned `id` as `ACCOUNT_ID`.

### 2. Create the OAuth app config

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

Record the returned `id` as `OAUTH_APP_ID`.

### 3. Generate the authorization URL

```bash
curl -X POST http://localhost:8000/api/v1/operator/oauth-apps/1/authorization-url
```

Open the returned `authorization_url` in a browser, complete consent, and allow Google to redirect back to:

```text
http://localhost:8000/api/v1/oauth/google/callback
```

After callback succeeds, the backend should mark the OAuth app as:

- `authorization_status = authorized`
- `refresh_token_present = true`

Verify:

```bash
curl http://localhost:8000/api/v1/operator/oauth-apps
```

### 4. Create a collector instance

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

Record:

- `INSTANCE_ID`
- `instance_token`

The `instance_token` is only returned at create time in this MVP. Save it immediately. It is the bearer credential that the collector uses both to pull runtime config and to talk to `/api/v1/collector/*` routes.

### 5. Create the proxy binding

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

### 6. Create a manual sync task

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

### 7. Inspect the collector runtime config

This is optional but useful before the first run.

```bash
curl http://localhost:8000/api/v1/collector/runtime-config \
  -H "Authorization: Bearer <instance-token>"
```

You should see:

- proxy fields from the binding
- `expected_egress_ip`
- `google.fetch_mode = admanager_soap`
- the Ad Manager network code from `external_account_id`

If the OAuth app is not fully authorized or the account has no network code, this route returns `409`.

### 8. Run the collector

Use the generated token. The collector will fetch all other runtime settings from the backend.

```bash
docker compose -f deploy/docker-compose.yml run --rm \
  -e COLLECTOR_INSTANCE_TOKEN=<instance-token> \
  collector-example
```

Expected runtime behavior:

1. The collector requests runtime config from the control plane.
2. The collector checks its observed public IP through the configured proxy.
3. If the observed IP does not match the expected egress IP, it posts a `blocked` heartbeat and exits with code `2`.
4. If the egress IP matches, it posts a `ready` heartbeat, claims one pending task, runs the fetcher, uploads zero or more batches, and marks the task terminal.

### 9. Inspect task and instance state

```bash
curl http://localhost:8000/api/v1/operator/tasks
curl http://localhost:8000/api/v1/operator/instances
curl http://localhost:8000/api/v1/operator/oauth-apps
```

You should see the task move from `pending` to `in_progress` to `succeeded`, and the instance `last_heartbeat_at` should be populated.

## Phase-1 Ad Manager Fetcher Notes

The real collector fetcher now uses Ad Manager SOAP `ReportService` for the standalone MVP real-data path.

The first validated report definition targets site-level AdX data that can be projected through the existing row schema:

- dimensions: `DATE_PT`, `SITE_NAME`
- columns:
  - `AD_EXCHANGE_RESPONSES_SERVED`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`
- time zone type: `PACIFIC`
- date range: one fixed day per task

Each returned page is normalized into staging rows with these fields:

- `report_date`
- `url_id`
- `url`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

Those rows are stored in `collector_ingestion_batches.payload_json` on the control plane side. This gives us a durable staging layer before we wire final business-table mapping.

The backend now also projects those staging rows into final tables:

- `site_daily_reports`
- `account_daily_reports`

You can inspect them through:

```bash
curl "http://localhost:8000/api/v1/operator/reports/site-daily?account_id=1&report_date=2026-05-21"
curl "http://localhost:8000/api/v1/operator/reports/account-daily?account_id=1&report_date=2026-05-21"
```

## Operational Caveats

- The compose file contains a placeholder `COLLECTOR_INSTANCE_TOKEN` by design. Do not expect `collector-example` to work unchanged.
- `docker compose up` for all services at once is not the intended first-run path because the collector requires a real instance token and a fully configured backend record set.
- The backend API is unauthenticated on operator routes in this MVP. Keep the stack local.
- PostgreSQL data persists in the `postgres-data` named volume until you remove it.
- OAuth secrets and refresh tokens are currently stored raw in the backend database for MVP speed. That is a known follow-up item, not a production-ready design.

## Frontend Console Notes

The project now includes a thin frontend control plane in `frontend/`.

Start it locally with:

```bash
cd frontend
npm install
npm run dev
```

Default API target:

- `http://127.0.0.1:8000`

If you are running the backend on another port for local validation:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

The UI is intentionally narrow in phase 1:

- `Operations`: create accounts, OAuth apps, instances, proxies, and tasks
- `Reports`: inspect `site_daily` and `account_daily`
- `OAuth callback`: complete Google authorization back into the frontend route `/oauth/google/callback`

For the smoothest local OAuth experience, set the OAuth app redirect URI to the frontend callback URL, for example:

```text
http://127.0.0.1:4173/oauth/google/callback
```

The frontend callback page will then call the backend `/api/v1/oauth/google/callback` endpoint for the token exchange and show a human-readable result screen.

The fastest way to validate the backend/collector path is still:

```bash
python scripts/virtual_flow.py
```

The frontend is there to replace raw operator API calls for the common manual workflow, not to replace the terminal demo script yet.
