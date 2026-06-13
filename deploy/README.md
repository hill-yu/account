# Local Deployment Assets

This directory contains the smallest local deployment setup for the phase-1 MVP:

- `backend/Dockerfile`: FastAPI control plane image. The container applies Alembic migrations on boot, then starts Uvicorn.
- `collector/Dockerfile`: one-shot collector runtime image.
- `docker-compose.yml`: local stack with PostgreSQL, the backend API, and one example collector service definition.

The frontend is intentionally kept outside this compose flow for phase 1. Run it from `frontend/` so it can point at whichever local backend you are validating.

## Quick Start

From the repository root:

```bash
docker compose -f deploy/docker-compose.yml up -d postgres backend
```

Check the backend health endpoint:

```bash
curl http://localhost:8000/health
```

When the backend is healthy, follow [operator notes](../docs/operator-notes.md) to:

1. Create an account.
2. Create and authorize an OAuth app for that account.
3. Create a collector instance and save its generated `instance_token` immediately.
4. Create a proxy binding for that instance.
5. Create a manual sync task.
6. Run the example collector with the real instance token.

Example collector run with ad-hoc overrides:

```bash
docker compose -f deploy/docker-compose.yml run --rm \
  -e COLLECTOR_INSTANCE_TOKEN=<instance-token> \
  collector-example
```

## Frontend Run

From the repository root:

```bash
cd frontend
npm install
npm run dev
```

If your backend is not on the default `http://127.0.0.1:8000`, set:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

## Notes

- The compose file is intentionally local-only. It exposes PostgreSQL and FastAPI directly on the host and stores database data in the named volume `postgres-data`.
- `collector-example` is defined in the compose file so the wiring is visible, but the recommended startup flow is to bring up `postgres` and `backend` first, then run the collector manually after an instance token exists.
- The collector now pulls proxy settings and Google OAuth runtime credentials from `GET /api/v1/collector/runtime-config` by authenticating with its instance token.
- Real Ad Manager report fetching requires:
  - the account `external_account_id` to contain the Ad Manager network code
  - an authorized OAuth app on that account
  - a valid proxy binding for the instance
- The current real fetcher uploads normalized staging rows for:
  - `url_id`
  - `url`
  - `responses_served`
  - `impressions`
  - `clicks`
  - `revenue`
  - `ecpm`
- The backend projects those staging rows into final queryable tables:
  - `site_daily_reports`
  - `account_daily_reports`
