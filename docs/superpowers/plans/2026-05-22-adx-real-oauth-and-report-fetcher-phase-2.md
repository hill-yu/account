# ADX Real OAuth And Report Fetcher Phase 2 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real Google Ad Manager OAuth authorization handling, a real Ad Manager REST report fetcher, and a local end-to-end integration path on top of the standalone collector MVP.

**Architecture:** Keep the existing standalone project boundary. Extend the control plane to manage OAuth app configs, authorization URLs, callback exchange, and authorization state. Extend the collector runtime with an Ad Manager REST fetcher that uses OAuth2 refresh tokens to create access tokens, then runs reports and pages through `fetchRows`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest, requests, Google OAuth2 token endpoint, Google Ad Manager API (Beta) REST.

---

## Tasks

### Task 5: Add OAuth App Management And Authorization Callback Flow

**Files:**
- Modify: `backend/app/models/oauth_app_config.py`
- Modify: `backend/alembic/versions/20260522_0001_phase1_foundation.py` or add a follow-up migration if safer
- Create/Modify: `backend/app/collectors/oauth_service.py`
- Modify: `backend/app/collectors/schemas.py`
- Modify: `backend/app/collectors/router.py`
- Create: `backend/tests/test_oauth_service.py`
- Modify: `backend/tests/test_collector_router.py`

**Outcome:**
- Control plane can create/list OAuth app configs.
- Control plane can generate an authorization URL for an account-scoped web app.
- OAuth callback exchanges `code` for tokens via Google OAuth2 token endpoint.
- Authorization state is stored with token metadata and timestamps.

### Task 6: Add Real Ad Manager REST Fetcher

**Files:**
- Modify: `collector/app/models.py`
- Modify: `collector/app/config.py`
- Create: `collector/app/oauth.py`
- Create: `collector/app/admanager_api.py`
- Modify: `collector/app/fetcher.py`
- Modify: `collector/app/runtime.py`
- Create: `collector/tests/test_oauth.py`
- Modify: `collector/tests/test_runtime.py`

**Outcome:**
- Collector can refresh an OAuth access token from a refresh token.
- Collector can create/run a report against Ad Manager API (Beta) REST.
- Collector can page through `fetchRows` and convert pages into callback batches.
- Runtime can switch between `stub` and `admanager_rest` fetch modes via env.

### Task 7: Wire Local End-To-End Integration And Docs

**Files:**
- Modify: `deploy/docker-compose.yml`
- Modify: `deploy/README.md`
- Modify: `docs/operator-notes.md`
- Modify: `README.md`

**Outcome:**
- Local docs explain how to create an OAuth app config, complete callback auth, export collector env vars, and run one real report task.
- Compose/docs reflect the new fetcher mode and required Google credentials.
- Verification commands are documented even if live Google creds are not available in this session.
