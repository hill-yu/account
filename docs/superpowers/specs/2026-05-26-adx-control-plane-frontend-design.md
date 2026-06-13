# ADX Control Plane Frontend Design

**Date:** 2026-05-26  
**Status:** Approved for phase 1 frontend planning  
**Owner:** Codex + user discussion output

---

## 1. Background And Goal

The standalone `adx-account-isolated-collector` project already has a working backend control plane, a real collector runtime, a virtual-flow demo script, and final reporting tables for:

- `site_daily_reports`
- `account_daily_reports`

The current gap is not backend capability. The current gap is that the project still behaves like a backend/operator API toolkit instead of a usable control surface.

The frontend goal is therefore not to build a complete production admin system. The goal is to build a **thin internal control plane UI** that makes the existing MVP operable and easy to validate.

The frontend must help an operator:

1. create and inspect accounts
2. create OAuth app configs and generate authorization URLs
3. create instances and capture one-time `instance_token`
4. bind proxies to instances
5. create manual sync tasks
6. inspect recent task and instance state
7. inspect `site_daily` and `account_daily` results

This frontend is a **phase 1 operating console**, not a customer portal, BI suite, or production NOC.

---

## 2. Scope Definition

### 2.1 In Scope

The phase 1 frontend scope includes:

- a standalone frontend app inside this repository
- two top-level pages:
  - `Operations`
  - `Reports`
- operator-facing forms and lists for:
  - accounts
  - OAuth apps
  - instances
  - proxies
  - sync tasks
- report tables for:
  - `site_daily`
  - `account_daily`
- localized Chinese user-facing success/error messages
- compatibility with the current local backend and `scripts/virtual_flow.py`

### 2.2 Out Of Scope

The phase 1 frontend explicitly excludes:

- authentication and user permissions
- customer self-service flows
- delete/edit-heavy object lifecycle management
- charts and dashboards
- websocket/live push state
- bulk operations
- automatic polling orchestration beyond minimal explicit refresh
- advanced filters and saved views
- production-grade theming or design system packaging

### 2.3 MVP Positioning

This frontend is a **workflow-enabling shell** over the existing backend MVP. It should make the system easy to operate without expanding scope into full platform UX.

---

## 3. Product Positioning

This UI should feel like a reliable internal operations console:

- calm
- clear
- tool-oriented
- state-driven
- low-friction

It should not feel like:

- a marketing site
- a BI dashboard wall
- a generic bootstrap admin clone
- an over-themed “AI product” interface

The design must prioritize:

- task completion
- state visibility
- low ambiguity
- explicit next steps when something is missing

---

## 4. Information Architecture

The frontend should use a two-entry structure.

### 4.1 `Operations`

This is the main page and the default landing view.

Its responsibility is to move an account through the operational chain:

`account -> oauth app -> authorization -> instance -> proxy -> task -> status`

It contains five sections:

1. `Accounts`
2. `OAuth Apps`
3. `Instances`
4. `Proxies`
5. `Tasks`

### 4.2 `Reports`

This is the verification page.

Its responsibility is to confirm that collection output has landed correctly.

It contains two report sections:

1. `Site Daily`
2. `Account Daily`

### 4.3 Navigation

Phase 1 should use only two primary navigation targets:

- `Operations`
- `Reports`

No deeper navigation tree is required in phase 1.

---

## 5. Operations Page Design

The `Operations` page is the core operator surface. It should be organized as a sequence of clear sections, each containing:

- a short purpose label
- one minimal creation form
- one current-state list/table

The page should make the workflow obvious even for someone new to the system.

### 5.1 Accounts Section

#### Purpose
Create and inspect account records.

#### Create form fields
- `name`
- `external_account_id`
- `status`

#### List fields
- `id`
- `name`
- `external_account_id`
- `status`
- `created_at`

#### Behavior
- creation success triggers refresh
- duplicate names show Chinese error feedback
- no edit/delete flows in phase 1

### 5.2 OAuth Apps Section

#### Purpose
Attach an OAuth app configuration to an account and expose authorization initiation.

#### Create form fields
- `account_id`
- `client_id`
- `client_secret`
- `redirect_uri`
- `scopes`
- `app_status`
- `verification_status`

#### List fields
- `id`
- `account_id`
- `client_id`
- `redirect_uri`
- `authorization_status`
- `refresh_token_present`
- `access_token_expires_at`

#### Required actions
- `Create OAuth App`
- `Generate Authorization URL`

#### Authorization URL behavior
When generated, the UI should:

- display the URL in a read-only field
- provide `Open` action
- provide `Copy` action

Phase 1 should not implement a custom OAuth wizard.

### 5.3 Instances Section

#### Purpose
Create collector instances and expose one-time provisioning token output.

#### Create form fields
- `account_id`
- `name`
- `status`
- `expected_egress_ip`

#### List fields
- `id`
- `account_id`
- `name`
- `status`
- `expected_egress_ip`
- `last_heartbeat_at`

#### Special behavior
On successful creation, the UI must prominently display:

- `instance_id`
- `instance_token`

The token must be clearly labeled as one-time output and copyable.

The normal instance list must not include `instance_token`.

### 5.4 Proxies Section

#### Purpose
Bind a fixed proxy to an account/instance pair.

#### Create form fields
- `account_id`
- `collector_instance_id`
- `provider_name`
- `protocol`
- `host`
- `port`
- `username`
- `password`
- `expected_egress_ip`
- `status`

#### List fields
- `id`
- `account_id`
- `collector_instance_id`
- `provider_name`
- `protocol`
- `host`
- `port`
- `expected_egress_ip`
- `status`

#### UX note
This section should include a static hint that proxy egress mismatch will block task execution.

### 5.5 Tasks Section

#### Purpose
Create manual sync tasks and inspect recent execution state.

#### Create form fields
- `account_id`
- `collector_instance_id`
- `report_date`
- `task_type`
- `status`
- `external_request_id`

#### List fields
- `id`
- `account_id`
- `collector_instance_id`
- `task_type`
- `report_date`
- `status`
- `started_at`
- `finished_at`
- `external_request_id`

#### Status display
At minimum, visually distinguish:

- `pending`
- `in_progress`
- `succeeded`
- `failed`
- `blocked`
- `cancelled`

---

## 6. Reports Page Design

The `Reports` page exists to verify the currently collected output.

### 6.1 Filters

Phase 1 should support only:

- `account_id`
- `report_date`

These filters should be shared by both report tables.

### 6.2 Site Daily Table

This table maps to `GET /api/v1/operator/reports/site-daily`.

#### Fields
- `url`
- `url_id`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

### 6.3 Account Daily Table

This table maps to `GET /api/v1/operator/reports/account-daily`.

#### Fields
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

### 6.4 Empty States

When reports are empty, the UI should not show blank tables. It should show clear next-step guidance such as:

- no data yet
- create a sync task and run the collector

---

## 7. Interaction Rules

### 7.1 Form And List Pattern

Every operational section should use the same interaction model:

- create form
- submit action
- current records list
- refresh after success

Consistency is more important than UI novelty.

### 7.2 Loading States

All submission buttons must show loading state while requests are in-flight.

Initial section loads should provide at least a lightweight loading indicator.

### 7.3 Success Feedback

Use short Chinese success toasts/messages. They should be informational, not verbose.

### 7.4 Failure Feedback

All end-user error messages must be Chinese. The UI should not expose internal English exceptions, stack details, or raw backend field names unless they are already human-readable.

### 7.5 Data Preservation On Error

On submission failure, form values should remain in place so the operator can fix and retry.

### 7.6 Explicit Refresh

Phase 1 should favor explicit refresh or submission-triggered refresh over aggressive live polling.

---

## 8. API Integration Contract

The frontend must consume existing backend APIs without requiring new backend endpoints for phase 1.

### 8.1 Operations APIs

- `POST /api/v1/operator/accounts`
- `GET /api/v1/operator/accounts`
- `POST /api/v1/operator/oauth-apps`
- `GET /api/v1/operator/oauth-apps`
- `POST /api/v1/operator/oauth-apps/{oauth_app_id}/authorization-url`
- `POST /api/v1/operator/instances`
- `GET /api/v1/operator/instances`
- `POST /api/v1/operator/proxies`
- `GET /api/v1/operator/proxies`
- `POST /api/v1/operator/tasks`
- `GET /api/v1/operator/tasks`

### 8.2 Reports APIs

- `GET /api/v1/operator/reports/site-daily`
- `GET /api/v1/operator/reports/account-daily`

### 8.3 Phase 1 Assumption

The frontend is allowed to assume a trusted local or internal environment and does not need to handle login/session flows yet.

---

## 9. Technical Approach

### 9.1 Stack

Recommended stack:

- React
- Vite
- TypeScript
- React Router

### 9.2 State Management

Phase 1 should avoid heavy global state solutions. Local component state plus lightweight shared API helpers is sufficient.

### 9.3 Data Fetching

Use simple request wrappers around `fetch`. No advanced caching or data synchronization framework is required in phase 1.

### 9.4 UI Components

The UI should remain light:

- tabs/navigation
- cards/sections
- tables
- forms
- toast feedback
- copy/open affordances

A full admin template or heavy component system is not required.

### 9.5 Config

The frontend should point to the standalone backend base URL via a single environment-backed API base setting.

---

## 10. Visual Direction

The visual direction should be:

- light background
- dark readable text
- strong section hierarchy
- restrained color usage
- state colors only where they add clarity

Recommended mood:

- calm
- sharp
- internal-tools oriented

Not recommended:

- purple-heavy AI styling
- dark neon dashboards
- large decorative hero layouts
- dense card-wall admin templates

---

## 11. Explicit Non-Goals

The frontend phase 1 must not drift into:

- permission management
- account deletion flows
- charting
- websocket real-time coordination
- customer-facing onboarding
- advanced search/filter systems
- configuration editing for every object type
- mobile-app-like polish work

The value of this phase comes from operational clarity, not feature breadth.

---

## 12. Completion Criteria

The frontend phase 1 is complete when all of the following are true:

1. The app boots locally and connects to the standalone backend.
2. The `Operations` page supports creating accounts, OAuth apps, instances, proxies, and tasks.
3. The OAuth app section can generate and expose authorization URLs.
4. The instance creation flow exposes the one-time `instance_token` clearly.
5. The task list reflects backend task status correctly.
6. The `Reports` page can load `site_daily` and `account_daily` for a chosen account/date.
7. All primary feedback shown to users is in Chinese.
8. The frontend can be demonstrated successfully against `python scripts/virtual_flow.py`.

---

## 13. Final Position

The correct first frontend for this project is not a full admin platform. It is a **thin, reliable operator console** that makes the existing backend/collector MVP usable without expanding product scope prematurely.

The design should therefore stay focused on:

- clear operational flow
- low-friction status visibility
- minimal but complete result verification
- lightweight implementation choices that do not slow down MVP iteration
