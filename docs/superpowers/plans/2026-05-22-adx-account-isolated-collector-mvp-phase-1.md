# ADX Account-Isolated Collector MVP Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute this plan task-by-task in the current session.

**Goal:** Build a standalone phase 1 MVP where 2-3 real AdX accounts each run through a dedicated collector instance, dedicated OAuth app config, and dedicated fixed proxy, then actively callback task results and report rows into a central control plane.

**Architecture:** This plan targets a new standalone project, not the existing `adxmanager` repo. The project contains:

- `backend/`: FastAPI control plane for account onboarding, instance registration, heartbeat, directed task polling, callback ingestion, and operator status APIs.
- `collector/`: Python runtime process that is scoped to one account, verifies its fixed egress IP, fetches report data through its bound proxy, and actively posts callback batches.
- `deploy/`: Dockerfiles and Compose examples for local MVP rollout.
- `docs/`: design docs, plans, and operator notes.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis (optional for later phases; not required for phase 1 runtime path), pytest, httpx, Docker Compose.

---

## File Structure

### Files to create

- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/database.py`
- `backend/app/models/__init__.py`
- `backend/app/models/account.py`
- `backend/app/models/oauth_app_config.py`
- `backend/app/models/collector_instance.py`
- `backend/app/models/proxy_binding.py`
- `backend/app/models/collector_sync_task.py`
- `backend/app/models/collector_sync_log.py`
- `backend/app/models/collector_ingestion_batch.py`
- `backend/app/collectors/__init__.py`
- `backend/app/collectors/schemas.py`
- `backend/app/collectors/security.py`
- `backend/app/collectors/service.py`
- `backend/app/collectors/router.py`
- `backend/app/collectors/ingestion_service.py`
- `backend/alembic.ini`
- `backend/alembic/env.py`
- `backend/alembic/script.py.mako`
- `backend/alembic/versions/20260522_0001_phase1_foundation.py`
- `backend/requirements.txt`
- `backend/tests/conftest.py`
- `backend/tests/test_models.py`
- `backend/tests/test_collector_router.py`
- `backend/tests/test_ingestion_service.py`
- `collector/app/__init__.py`
- `collector/app/config.py`
- `collector/app/models.py`
- `collector/app/proxy.py`
- `collector/app/egress.py`
- `collector/app/control_plane_client.py`
- `collector/app/fetcher.py`
- `collector/app/runtime.py`
- `collector/app/main.py`
- `collector/requirements.txt`
- `collector/tests/test_runtime.py`
- `collector/tests/test_proxy.py`
- `deploy/backend/Dockerfile`
- `deploy/collector/Dockerfile`
- `deploy/docker-compose.yml`
- `deploy/README.md`
- `README.md`
- `docs/operator-notes.md`

---

## Task 1: Bootstrap Standalone Control Plane Foundation

**Outcome:** A standalone backend exists with config, SQLAlchemy base/session, core models, FastAPI app boot, and initial Alembic migration.

### Acceptance criteria
- Backend app starts and responds on `/health`.
- SQLAlchemy models exist for accounts, OAuth apps, instances, proxy bindings, sync tasks, sync logs, and ingestion batches.
- Alembic can upgrade an empty database to the initial schema.
- Pytest covers model import and basic table creation.

### Verification
- `cd backend && python -m pytest tests/test_models.py -q`
- `cd backend && python -m alembic upgrade head`

---

## Task 2: Build Control Plane APIs For Registration, Heartbeat, Task Polling, And Callback Ingestion

**Outcome:** The backend exposes the minimum directed-control and ingestion APIs needed by one collector instance.

### Acceptance criteria
- Operator-facing API can create/list accounts, instances, proxy bindings, and sync tasks.
- Collector-facing API supports:
  - instance heartbeat
  - directed task polling
  - task status callback
  - batch ingestion callback
- Callback auth uses an instance-scoped shared token.
- Ingestion is idempotent by `task_id` + batch identity.
- Tests cover happy path and auth failure path.

### Verification
- `cd backend && python -m pytest tests/test_collector_router.py tests/test_ingestion_service.py -q`

---

## Task 3: Build Account-Scoped Collector Runtime

**Outcome:** A standalone collector runtime can verify egress IP, poll the control plane for one task, fetch report rows from a pluggable fetcher, and callback results.

### Acceptance criteria
- Runtime is configured by env vars only.
- Proxy configuration is explicit and validated.
- Egress IP verification runs before execution.
- Runtime handles one task execution loop cleanly.
- Fetch path is abstracted so phase 1 can use a stub or fake provider in tests.
- Tests cover proxy config validation, egress mismatch blocking, and successful callback flow with mocks.

### Verification
- `cd collector && python -m pytest tests/test_proxy.py tests/test_runtime.py -q`

---

## Task 4: Add Local Deployment Assets And Operator Notes

**Outcome:** The MVP can be run locally with a backend container, a database, and one example collector container.

### Acceptance criteria
- Dockerfiles exist for backend and collector.
- Compose file wires backend + postgres + one example collector instance.
- Operator notes explain env vars, startup order, and the first manual sync flow.
- Project README explains purpose, layout, and MVP limits.

### Verification
- `docker compose -f deploy/docker-compose.yml config`

---

## Suggested Execution Order

1. Task 1: foundation first
2. Task 2: control plane APIs next
3. Task 3: collector runtime after API contracts exist
4. Task 4: deployment and notes after both runtimes pass tests

---

## MVP Done Definition

Phase 1 is complete when all of the following are true:

1. The standalone project boots without depending on the old `adxmanager` repository.
2. The backend schema can be created via Alembic.
3. A control-plane operator can create an account, instance, proxy binding, and a manual single-day sync task.
4. A collector instance can verify its expected egress IP before work.
5. A collector instance can poll a directed task and callback status + batch results.
6. The control plane stores callback metadata and ingested rows idempotently.
7. Tests for backend and collector pass locally.
8. Local deployment docs are sufficient for a human to run the MVP.
