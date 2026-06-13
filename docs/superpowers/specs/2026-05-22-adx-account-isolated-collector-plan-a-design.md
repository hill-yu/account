# ADX Account-Isolated Collector Plan A Design

**Date:** 2026-05-22  
**Status:** Approved for MVP planning  
**Owner:** Codex + user discussion output

---

## 1. Background And Goal

The target is not a conventional shared multi-tenant AdX ingestion platform. The target is an **account-isolated collector architecture** where each AdX account has its own identity, execution unit, and outbound network path.

The required invariants are:

- One AdX account maps to one dedicated OAuth application.
- One AdX account maps to one dedicated collector instance.
- One AdX account maps to one fixed commercial proxy and one fixed egress IP.
- The collector instance only authorizes, fetches, and reports data for its own account.
- A central backend acts as the control plane, ingestion endpoint, audit surface, and reporting surface.

This design exists to separate:

- Identity isolation: no shared OAuth app across accounts.
- Execution isolation: no shared runtime worker across accounts.
- Egress isolation: no shared proxy/IP across accounts.
- Reporting isolation: collection happens at the edge; centralized reporting happens after ingestion.

The implementation target is a **standalone collector platform repository**. It must not be mixed into the current `adxmanager` codebase. The existing reporting system can later consume synchronized outputs, but the collector MVP should own its own backend, runtime, deployment files, and docs from day one.

The first phase is not a scale phase. It is a **chain validation phase** for:

`control plane task creation -> designated collector execution -> fixed proxy egress verification -> AdX fetch -> active callback -> idempotent central ingestion`

---

## 2. Scope Definition

### 2.1 In Scope

The phase 1 scope includes:

- Dedicated OAuth app configuration per AdX account.
- Dedicated collector instance per AdX account.
- Fixed proxy binding per AdX account.
- Collector-side AdX API access through the bound proxy only.
- Active result callback from collector to control plane.
- Central control plane management for accounts, instances, proxies, tasks, and sync state.
- Central ingestion and write into the standalone platform reporting tables, with a future adapter point for export into downstream systems.
- Minimal audit, heartbeat, proxy verification, and failure classification.

### 2.2 Out Of Scope

The phase 1 scope explicitly excludes:

- Automatic proxy failover
- Shared instance across multiple accounts
- Shared proxy across multiple accounts
- Automatic schedules
- Automatic gap detection or automatic backfill
- Customer self-service onboarding
- Advanced BI and cross-account operating dashboards
- Dynamic autoscaling and full orchestrator automation
- AdX write/configuration operations

### 2.3 MVP Positioning

Phase 1 is an **architecture validation MVP**, not a production-complete multi-account operating platform.

---

## 3. Architecture Overview

The system contains five core components.

### 3.0 Standalone Project Boundary

The platform is implemented as its own project tree with these top-level slices:

- `backend/`: control plane API, persistence, ingestion, operator APIs, and status views
- `collector/`: account-scoped runtime process that polls for directed work, verifies proxy egress, fetches AdX data, and actively callbacks
- `deploy/`: Dockerfiles, Compose examples, and local deployment notes
- `docs/`: design, implementation plans, and operator runbooks

This boundary is intentional. It keeps collector credentials, proxy routing, and rollout concerns isolated from the existing analytics application.

### 3.1 Control Plane

The control plane is the only global coordination surface. It is responsible for:

- account onboarding records
- OAuth app configuration records
- collector instance lifecycle records
- proxy binding records
- sync task creation and tracking
- callback reception
- audit and state display
- normalized reporting display

It is not responsible for centrally executing AdX fetches on behalf of every account, and it is not implemented inside the existing `adxmanager` service tree.

### 3.2 Collector Instance

Each account gets a dedicated collector instance. A collector is responsible for:

- reading its own account-scoped configuration
- using only its bound proxy
- verifying actual egress IP
- fetching AdX data for its own account only
- posting result metadata and data batches back to the control plane

It is not responsible for cross-account operations, centralized reporting, or shared orchestration logic.

### 3.3 OAuth App Configuration Layer

Each account has its own OAuth app configuration object:

- client id
- client secret
- redirect uri
- scopes
- app status
- verification status

This breaks the previous shared-application identity model into account-scoped application identity.

### 3.4 Proxy Resource Layer

Proxy resources are first-class managed objects, not free-form environment strings. This layer is responsible for:

- proxy inventory
- provider metadata
- fixed egress IP metadata
- account binding
- health state
- verification history

### 3.5 Callback / Ingestion Layer

The control plane must expose an ingestion surface that:

- authenticates collector identity
- receives task result metadata
- receives data payloads
- enforces idempotency
- writes callback batches to staging
- writes normalized output to final tables

---

## 4. Account-Instance-Proxy Binding Model

Plan A depends on a strict three-way binding:

- one account -> one collector instance
- one account -> one fixed proxy
- one collector instance -> one account
- one proxy -> one account

### 4.1 Account

The account is the business anchor for all tasks, callbacks, data, and audit records.

### 4.2 Collector Instance

The collector instance is the only permitted execution unit for that account. It may not execute tasks for other accounts.

### 4.3 Proxy

The proxy is a fixed infrastructure resource bound to the account. It is not a temporary runtime selection.

### 4.4 Binding Rules

The following rules are mandatory:

- no instance may serve multiple accounts in phase 1
- no proxy may be bound to multiple accounts in phase 1
- no task may execute without account-instance binding validation
- no fetch may continue when actual egress IP differs from expected egress IP

### 4.5 Binding Changes

Rebinding an account to a new instance or proxy must be explicit and auditable. Silent replacement is not acceptable.

---

## 5. OAuth And Authorization Design

### 5.1 Authorization Flow

Recommended flow:

1. Create an account onboarding record in the control plane.
2. Allocate a dedicated OAuth app config, collector instance, and proxy.
3. Generate an account-scoped authorization entrypoint.
4. Complete OAuth authorization.
5. Store refresh/access token material in collector-scoped secure storage.
6. Store only state, timestamps, and references centrally.

### 5.2 Token Ownership Boundary

The control plane should not become the long-lived shared token execution owner. The preferred boundary is:

- collector instance or collector-scoped secret store owns refresh token material
- control plane owns status and references

### 5.3 Authorization States

At minimum:

- `pending`
- `authorized`
- `expired`
- `revoked`
- `failed`

### 5.4 Authorization Failure Handling

Refresh failures, revoked permissions, scope mismatches, and app misconfiguration must become explicit account state, not hidden sync side effects.

---

## 6. Proxy And Egress Design

Proxy management is a core design layer, not an implementation detail.

### 6.1 Proxy Resource Model

Each proxy record should include:

- proxy id
- provider name
- protocol type
- host
- port
- credentials
- fixed egress IP
- bound account id
- current status
- last health check time
- last health result
- consecutive failure count

### 6.2 Binding Strategy

Phase 1 uses strict fixed binding:

- one proxy per account
- one account per proxy
- no dynamic borrowing
- no dynamic pool rotation

### 6.3 Egress Verification

Each collector must verify egress IP:

- at startup
- before every sync execution

If actual egress IP does not match expected egress IP:

- the collector must not fetch data
- the task must be marked blocked/failed
- the control plane must receive a proxy mismatch event

### 6.4 Proxy Failure Strategy

Phase 1 does not support automatic proxy failover. Proxy failure results in:

- blocked sync
- explicit alert/state
- manual operator intervention

### 6.5 Phase 1 Principle

Clarity and auditability are prioritized over automatic recovery.

---

## 7. Control Flow Design

### 7.1 Control Authority

The control plane is the only task creation authority in phase 1. Collectors do not self-schedule.

### 7.2 Task Creation

Each sync task must identify:

- `account_id`
- `collector_instance_id`
- `sync_type`
- `date_from`
- `date_to`
- `task_id`

Phase 1 should support only:

- manual execution
- single account
- single day

### 7.3 Task Routing

Tasks should be directed to a designated collector, not broadcast to a pool.

### 7.4 Collector Preflight Validation

Before execution, the collector must verify:

- task belongs to itself
- task account matches local account binding
- local proxy matches bound proxy
- actual egress IP matches expected egress IP
- authorization/token state is valid

### 7.5 Task State Machine

Recommended base states:

- `pending`
- `running`
- `success`
- `failed`
- `blocked`

`blocked` indicates unmet execution prerequisites, such as token invalidity or proxy mismatch.

---

## 8. Data Flow And Callback Design

### 8.1 Collector Fetch

On execution, the collector:

1. uses its own authorization context
2. uses its own bound proxy
3. fetches AdX data for the requested date range
4. performs minimal field normalization

### 8.2 Active Callback

The collector actively posts results to the control plane. Callback should contain:

- sync metadata
- data payload

### 8.3 Required Metadata

At minimum:

- `task_id`
- `account_id`
- `collector_instance_id`
- `proxy_id`
- `egress_ip`
- `started_at`
- `finished_at`
- `status`
- `records_count`
- `error_message`

### 8.4 Data Payload

At minimum:

- source account identity
- date range
- normalized metrics rows
- dedupe or batch key

### 8.5 Staging First

Control plane should first persist callback batches into a staging/ingestion layer, then write to final reporting tables. This separates:

- fetch success
- callback reception success
- final write success

### 8.6 Idempotency

Each callback must carry a unique task identity. Final ingestion must be idempotent by `task_id`.

---

## 9. Data Model Design

Phase 1 should introduce or formalize the following data objects.

### 9.1 `oauth_app_configs`

- `id`
- `account_id`
- `project_name`
- `client_id`
- `client_secret_encrypted`
- `redirect_uri`
- `scope_json`
- `verification_status`
- `status`

### 9.2 `collector_instances`

- `id`
- `account_id`
- `name`
- `status`
- `version`
- `proxy_id`
- `last_heartbeat_at`
- `last_sync_status`
- `last_egress_ip`

### 9.3 `proxy_bindings`

- `id`
- `account_id`
- `proxy_id`
- `collector_instance_id`
- `bound_at`
- `status`
- `last_verified_ip`

### 9.4 `collector_sync_tasks`

- `id`
- `account_id`
- `collector_instance_id`
- `sync_type`
- `date_from`
- `date_to`
- `status`
- `retry_count`
- `created_at`
- `started_at`
- `finished_at`
- `error_message`

### 9.5 `collector_sync_logs`

- `id`
- `task_id`
- `account_id`
- `collector_instance_id`
- `proxy_id`
- `egress_ip`
- `records_count`
- `response_status`
- `error_code`
- `error_message`
- `created_at`

### 9.6 `collector_ingestion_batches`

- `id`
- `task_id`
- `account_id`
- `collector_instance_id`
- `received_at`
- `payload_checksum`
- `status`
- `records_count`
- `error_message`

### 9.7 Final Tables

Phase 1 should continue using existing:

- `daily_reports`
- `link_daily_reports`

This keeps MVP focus on collection architecture instead of replacing current reporting storage.

---

## 10. Security And Secret Management

### 10.1 Sensitive Assets

At minimum:

- OAuth client secret
- refresh token
- callback authentication token
- proxy credentials

### 10.2 Storage Rules

These assets must be:

- encrypted at rest
- access-restricted by account boundary
- rotatable
- excluded from routine logs

### 10.3 Collector Authentication

The control plane must verify collector identity. At minimum:

- collector id
- collector-scoped callback token or signature secret
- rejection of unknown or mismatched collector submissions

### 10.4 Token Boundary

Refresh token material should not be normalized into a global shared token pool used by the control plane.

---

## 11. State, Monitoring, And Audit

### 11.1 Collector State

The control plane must display:

- online/offline
- last heartbeat
- running version
- latest egress IP
- latest sync result

### 11.2 Proxy State

The control plane must display:

- bound account
- health state
- recent failure state
- failure streak

### 11.3 Task State

The control plane must show:

- task creation
- task execution status
- callback status
- final ingestion status

### 11.4 Auditability

The operator must be able to answer:

- which account
- which collector
- which proxy
- which egress IP
- which task
- which callback batch
- what result

### 11.5 Minimum Alerts

Phase 1 should at least alert on:

- authorization invalid
- proxy unreachable
- egress IP mismatch
- collector heartbeat missing
- callback failure
- final write failure

---

## 12. Failure Classification And Recovery

### 12.1 Authorization Failures

Examples:

- token expired
- refresh failure
- scope mismatch
- app misconfiguration

Handling:

- mark authorization state unhealthy
- block execution
- route to operator intervention

### 12.2 Proxy Failures

Examples:

- connectivity failure
- auth failure
- wrong egress IP

Handling:

- do not execute fetch
- do not auto-switch to another account proxy
- mark account blocked
- require rebind/manual repair

### 12.3 API Fetch Failures

Examples:

- timeout
- throttling
- upstream service failure
- malformed upstream response

Handling:

- mark task failed
- allow bounded retry policy later
- preserve full task context

### 12.4 Callback / Ingestion Failures

Examples:

- control plane unreachable
- callback schema invalid
- idempotency conflict
- final write failed

Handling:

- distinguish fetch success from callback failure
- distinguish callback success from final write failure
- preserve staging state for reprocessing

---

## 13. MVP Scope And Done Definition

### 13.1 MVP Scope

Phase 1 supports only:

- `2-3` real AdX accounts
- dedicated OAuth app per account
- dedicated collector instance per account
- fixed proxy per account
- manual single-day fetch
- active callback
- centralized task and status management

### 13.2 MVP Exclusions

Phase 1 does not support:

- automatic scheduling
- automatic proxy failover
- automatic backfill
- shared collectors
- shared proxies
- self-service onboarding
- advanced analytics

### 13.3 Done Definition

Phase 1 is complete only when all of the following are true:

1. `2-3` real AdX accounts are connected.
2. Each account has its own OAuth app, collector, and fixed proxy.
3. The control plane can create a manual sync task for a specified day.
4. The collector verifies egress IP before fetch.
5. The collector fetches and actively callbacks.
6. The control plane ingests callback data idempotently.
7. The control plane shows account, collector, proxy, egress IP, and latest sync state.
8. At least one real failure has occurred and can be accurately classified.

---

## 14. Risk Signals And Stop Conditions

### 14.1 Positive Signals

The architecture is validated if:

- account/proxy boundaries remain stable
- egress verification is consistently correct
- adding the second and third accounts remains standardized
- callback ingestion stays idempotent
- failures are classifiable by layer

### 14.2 Negative Signals

Scale-out should pause if:

- proxy quality is too unstable to preserve fixed egress
- adding each account requires high manual configuration overhead
- the control plane accumulates too much long-lived credential power
- callback/final-write idempotency is unreliable
- collector state and control plane state diverge often

### 14.3 Stop Principle

If proxy/account/instance isolation cannot be trusted, this plan should not be scaled further until the isolation premise is repaired.

---

## 15. Phased Delivery Recommendation

### Phase 1: Binding Model

- account model
- collector model
- proxy model
- three-way binding rules

### Phase 2: Protocols

- task dispatch protocol
- heartbeat/status protocol
- callback protocol
- idempotency rules

### Phase 3: Collector Execution

- collector startup
- proxy injection
- egress verification
- AdX fetch
- active callback

### Phase 4: Control Plane Ingestion

- task creation
- callback reception
- staging write
- final write
- state display

### Phase 5: Authorization Formalization

- account-scoped OAuth config
- authorization state tracking
- token lifecycle handling

### Phase 6: Operational Enhancements

- proxy health checks
- alerts
- backup proxy policy
- controlled backfill
- collector version management

---

## Final Position

Plan A is technically and architecturally valid for an account-isolated collector model, but only if the account-instance-proxy boundary remains strict and observable. The phase 1 MVP should validate that boundary with real accounts before expanding to larger account counts.
