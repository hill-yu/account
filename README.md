# ADX Account-Isolated Collector

This repository is a standalone phase-1 MVP for running one collector process per AdX account behind a fixed proxy, while a central FastAPI control plane manages registration, OAuth authorization, runtime config delivery, task assignment, heartbeat updates, and ingestion metadata.

## Purpose

The MVP isolates each AdX account into its own runtime boundary:

- the `backend/` service stores account, instance, proxy, and task state
- the `backend/` service stores OAuth app state and issues per-instance runtime config snapshots
- the `collector/` runtime fetches its config from the control plane, verifies egress IP, polls for one task, and reports status back to the control plane
- the `deploy/` assets provide a simple local stack for manual validation
- the `docs/` directory holds design, planning, and operator documentation

## Repository Layout

- `backend/`: FastAPI app, SQLAlchemy models, and Alembic migrations for the control plane
- `collector/`: one-shot collector runtime and tests
- `frontend/`: React + Vite operator console for the phase-1 control plane
- `deploy/`: Dockerfiles, compose file, and local deployment notes
- `docs/`: operator notes plus project planning artifacts

## MVP Scope

Phase 1 is intentionally narrow:

- one backend service
- one PostgreSQL database
- one example collector instance definition in Compose
- manual operator-driven creation of accounts, OAuth apps, instances, proxy bindings, and sync tasks
- collector execution as a one-shot process

## MVP Limits

These limits are expected for this phase:

- the default local stack is still manual and local-only; it does not include a scheduler or managed secret store
- the collector can run either a stub fetcher or a real Google Ad Manager API (Beta) report fetcher
- the real fetcher currently uses a fixed report shape and relies on runtime credentials supplied by the control plane
- the real fetcher currently normalizes and uploads these core fields per site row:
  - `url_id`
  - `url`
  - `responses_served`
  - `impressions`
  - `clicks`
  - `revenue`
  - `ecpm`
- the control plane stores those row payloads in staging batches and projects them into:
  - `site_daily_reports`
  - `account_daily_reports`
- no scheduler, worker pool, or multi-instance orchestration is included
- no secret management, TLS termination, or production hardening is included
- local deployment uses manual startup steps and an authenticated runtime-config handshake

## Local Run

Use the assets under [deploy/README.md](deploy/README.md) for the local container flow. The operator runbook for the first manual sync is in [docs/operator-notes.md](docs/operator-notes.md).

## Quick Virtual Flow

If you want to experience the end-to-end flow without real Google OAuth or a real proxy yet, run:

```bash
python scripts/virtual_flow.py
```

This script will:

- create a temporary SQLite database
- run Alembic migrations
- start a local backend process
- create a virtual account, instance, proxy, and task
- run the real collector process in `stub` mode
- print a JSON summary of the final `site_daily` and `account_daily` results

## Frontend Control Plane

The frontend now lives under `frontend/` and mirrors the current MVP workflow:

- `Operations`: accounts, OAuth apps, instances, proxies, and tasks
- `Reports`: `site_daily` and `account_daily` verification
- `OAuth callback`: `http://127.0.0.1:4173/oauth/google/callback` for a frontend-complete authorization flow during local development

Run it locally with:

```bash
cd frontend
npm install
npm run dev
```

The default API base URL is `http://127.0.0.1:8000`.

If your backend is on another port, override it before starting Vite:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

When creating a local OAuth app through the UI, keep the redirect URI pointed at the frontend callback route if you want the authorization flow to return to the control plane instead of ending on a raw backend JSON page.

## Second Account Onboarding

If you are adding a second node, do it by creating a second account first. The current MVP keeps a one-account-to-one-node shape.

Use this order:

1. Create the second account.
2. Create the second account's instance.
3. Create the second account's OAuth app.
4. Set `redirect_uri` to the second account website callback.
5. Generate the authorization URL and complete authorization.

Important notes:

- Each account has its own node.
- Each account has its own OAuth app config.
- Different accounts can use different callback websites.
- The current version does not auto-generate the callback URL from node settings.
