# ADX Control Plane Frontend Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute this plan task-by-task in the current session.

**Goal:** Build a thin frontend control plane for the standalone `adx-account-isolated-collector` project so an operator can complete the MVP workflow through a browser instead of raw API calls.

**Architecture:** The frontend sits alongside the existing standalone backend and collector. It does not replace current APIs. It provides two pages:

- `Operations`: object creation and sync workflow
- `Reports`: site/account result verification

**Tech Stack:** React, Vite, TypeScript, React Router, lightweight internal API wrapper, minimal shared UI primitives.

---

## File Structure

### New top-level slice

- `frontend/`

### Files to create

- `frontend/package.json`
- `frontend/tsconfig.json`
- `frontend/tsconfig.node.json`
- `frontend/vite.config.ts`
- `frontend/index.html`
- `frontend/.gitignore`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/styles.css`
- `frontend/src/router.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/errorMessages.ts`
- `frontend/src/lib/format.ts`
- `frontend/src/components/layout/AppShell.tsx`
- `frontend/src/components/ui/SectionCard.tsx`
- `frontend/src/components/ui/StatusBadge.tsx`
- `frontend/src/components/ui/Field.tsx`
- `frontend/src/components/ui/CopyButton.tsx`
- `frontend/src/components/ui/ToastProvider.tsx`
- `frontend/src/components/ui/useToast.ts`
- `frontend/src/pages/OperationsPage.tsx`
- `frontend/src/pages/ReportsPage.tsx`
- `frontend/src/features/accounts/AccountsSection.tsx`
- `frontend/src/features/oauth/OAuthAppsSection.tsx`
- `frontend/src/features/instances/InstancesSection.tsx`
- `frontend/src/features/proxies/ProxiesSection.tsx`
- `frontend/src/features/tasks/TasksSection.tsx`
- `frontend/src/features/reports/SiteDailySection.tsx`
- `frontend/src/features/reports/AccountDailySection.tsx`
- `frontend/src/types/api.ts`
- `frontend/src/__tests__/format.test.ts`
- `frontend/src/__tests__/errorMessages.test.ts`

### Existing files to update

- `README.md`
- `docs/operator-notes.md`
- `deploy/README.md`

Optionally later:
- `deploy/docker-compose.yml` (only if we decide to include frontend container in local compose during the same phase)

---

## Task 1: Bootstrap Frontend App Shell

**Outcome:** A standalone frontend app exists and can run locally against the backend.

### Acceptance criteria
- `frontend/` is initialized with Vite + React + TypeScript.
- The app builds successfully.
- A root shell with navigation for `Operations` and `Reports` exists.
- Global styles establish the intended internal-tool visual direction.

### Verification
- `cd frontend && npm install`
- `cd frontend && npm run build`

---

## Task 2: Build Shared UI And API Foundation

**Outcome:** The frontend has a reusable base for API requests, Chinese error handling, toasts, formatting, and status display.

### Acceptance criteria
- API base URL is centralized.
- Request failures map to Chinese user-facing messages.
- Success/error toasts are available to all sections.
- Shared UI primitives exist for:
  - section container
  - status badge
  - field block
  - copy action
- Format helpers exist for dates and nullable values.

### Verification
- `cd frontend && npm run build`
- `cd frontend && npm test` or equivalent lightweight test command if configured

---

## Task 3: Implement Operations Page

**Outcome:** Operators can create and inspect accounts, OAuth apps, instances, proxies, and tasks through one page.

### Acceptance criteria
- `Accounts` section can create and list accounts.
- `OAuth Apps` section can create/list configs and generate authorization URLs.
- `Instances` section can create/list instances and prominently show one-time `instance_token`.
- `Proxies` section can create/list proxy bindings.
- `Tasks` section can create/list manual sync tasks.
- All submit actions show loading states and Chinese feedback.
- Lists refresh after successful actions.

### Verification
- Local manual run against backend
- Confirm object creation and list refresh for all five sections

---

## Task 4: Implement Reports Page

**Outcome:** Operators can inspect final projected results for one account and date.

### Acceptance criteria
- Filters for `account_id` and `report_date` exist.
- `Site Daily` table loads from `/api/v1/operator/reports/site-daily`.
- `Account Daily` table loads from `/api/v1/operator/reports/account-daily`.
- Empty states are explicit and helpful.
- Result fields match the current site-dimension backend schema:
  - `url`
  - `url_id`
  - `responses_served`
  - `impressions`
  - `clicks`
  - `revenue`
  - `ecpm`

### Verification
- Use virtual flow backend state and confirm reports render correctly

---

## Task 5: Validate Against Virtual Flow

**Outcome:** The frontend can be demonstrated end-to-end using the existing virtual demo path.

### Acceptance criteria
- Running `python scripts/virtual_flow.py` still succeeds.
- The frontend can connect to a locally started backend and display:
  - created account/task state
  - final `site_daily`
  - final `account_daily`
- The documented MVP walkthrough no longer requires raw API-only interaction for the common path.

### Verification
- Run backend locally
- Run frontend locally
- Complete manual browser walkthrough:
  1. create account
  2. create instance/proxy/task
  3. run collector or virtual flow
  4. confirm reports display expected rows

---

## Suggested Execution Order

1. Task 1: app shell and routing
2. Task 2: shared API/error/toast foundation
3. Task 3: operations page
4. Task 4: reports page
5. Task 5: virtual-flow validation and docs polish

---

## UX Constraints

These constraints should be preserved during implementation:

- two top-level pages only
- explicit refresh over heavy polling
- Chinese user-visible messaging
- no heavy admin template adoption
- no authentication scope added in this phase
- no charts, websockets, or workflow wizard complexity

---

## Phase 1 Done Definition

The frontend phase 1 is complete when all of the following are true:

1. The frontend app builds successfully.
2. `Operations` and `Reports` pages are both implemented.
3. An operator can create all core objects needed by the backend MVP.
4. The one-time `instance_token` flow is visible and usable.
5. Task state is visible and understandable.
6. `Site Daily` and `Account Daily` render correctly for current site-dimension data.
7. User-facing errors and successes are shown in Chinese.
8. The app can be demonstrated against the existing standalone backend and virtual-flow path.
