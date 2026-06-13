# ADX SOAP URL Report MVP Design

**Date:** 2026-06-03  
**Status:** Proposed and user-approved for planning  
**Owner:** Codex + user discussion output

---

## 1. Goal

The immediate goal is to make the standalone `adx-account-isolated-collector` project fetch **real AdX data** and write it into the existing reporting path without changing the current control-plane architecture.

The MVP must satisfy both conditions:

1. the collector fetches real AdX data from Google successfully
2. the fetched data lands in the current backend projection flow and populates the fields used by `site_daily_reports`

For this MVP, the target field semantics remain:

- `report_date`
- `url_id`
- `url`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

The user requirement is strict: this MVP must not fall back to site-level-only semantics. It must target URL-level AdX data.

---

## 2. Current State

The current standalone project already has these working parts:

- backend control plane for accounts, OAuth apps, instances, proxies, tasks, runtime-config, batch ingestion, and report querying
- collector runtime that authenticates with `instance_token`, verifies egress IP, claims tasks, runs a fetcher, submits batches, and marks task status
- frontend operator console that supports the current MVP workflow
- green backend, collector, and frontend test suites
- a green stub end-to-end virtual flow

The current blocker is isolated to the real fetcher path:

- current real fetcher uses **Ad Manager API (Beta) REST reports**
- current report definition uses **`AD_SERVER_*` metrics**
- real OAuth works
- REST report creation and execution work
- `fetchRows` succeeds but returns `0 rows`

This means the technical transport path works, but the business reporting semantics are wrong for the required AdX data.

---

## 3. Design Decision

The real fetcher path will be changed from:

- Ad Manager API (Beta) REST reports

to:

- **Ad Manager SOAP `ReportService`**

This is the selected direction because:

- the official AdX migration guidance aligns better with Ad Manager SOAP reporting
- the current REST implementation has already been validated as technically reachable but semantically wrong for the required data
- an older internal project, `D:\code\adsense\adxmanager`, already proves a working SOAP client setup using `googleads` and `ReportService`

The project will keep the current control-plane and collector architecture. Only the real fetcher implementation path will be changed.

---

## 4. MVP Scope

### 4.1 In Scope

- add a new SOAP-based real fetcher to the collector
- fetch real AdX URL-level rows for one task date
- normalize SOAP result rows into the existing batch schema
- submit one or more batches back to the control plane
- project those batches into:
  - `site_daily_reports`
  - `account_daily_reports`
- keep the stub fetcher and current runtime flow intact

### 4.2 Out Of Scope

- redesigning backend task, OAuth, or proxy models
- changing frontend workflow or UI structure
- broad support for multiple report definitions in the first pass
- fallback to site-level-only data for this MVP
- changing the final backend report table contract
- replacing the collector runtime with the older `adxmanager` architecture

---

## 5. Implementation Approach

### 5.1 Fetcher Strategy

The collector will support a new fetch mode:

- `stub`
- `admanager_rest` (legacy, retained temporarily for compatibility)
- `admanager_soap` (new target real mode)

The backend runtime-config should return `admanager_soap` for authorized real accounts once the new fetcher is ready.

### 5.2 Code Boundary

The new fetcher should be isolated behind a dedicated collector module, rather than mixing SOAP logic into the current REST implementation.

Recommended file boundaries:

- `collector/app/fetcher.py`
  - keep `StubFetcher`
  - keep or temporarily retain `AdManagerRestReportFetcher`
  - add `AdManagerSoapReportFetcher`
  - update `build_fetcher()`
- `collector/app/admanager_soap.py`
  - new SOAP-specific report definition, client setup, polling, download, CSV parsing, and row normalization
- `collector/app/models.py`
  - allow `admanager_soap` in runtime settings and runtime-config models
- `backend/app/collectors/schemas.py`
  - allow `admanager_soap` in runtime-config schema
- `backend/app/collectors/service.py`
  - return `admanager_soap` for real authorized runtime-config

This keeps the collector architecture stable:

- runtime decides which fetcher to build
- fetcher yields normalized `FetchBatch` objects
- control plane callback and backend projection remain unchanged

---

## 6. SOAP Client Source Of Truth

The current project should reuse the proven client pattern from the older `adxmanager` project conceptually, but not copy its business semantics blindly.

Useful proven pieces from `adxmanager`:

- OAuth refresh-token usage pattern
- `googleads` Ad Manager client setup
- `ReportService` initialization
- `WaitForReport(...)`
- `DownloadReportToFile(...)`
- CSV parsing flow

The new standalone collector must not inherit the old report definition unchanged, because the old implementation is still based on `AD_SERVER_*` columns and an older summary-style query.

The older project is a **transport/reference source**, not the final business definition source.

---

## 7. First Report Definition

The first MVP must validate one minimal URL-level AdX report definition only.

Target query:

- `reportType`: `HISTORICAL`
- `timeZoneType`: `PACIFIC`
- `dimensions`:
  - `DATE_PT`
  - `URL_ID`
  - `URL_NAME`
- `columns`:
  - `AD_EXCHANGE_RESPONSES_SERVED`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`

This design intentionally starts with only one report shape. The goal is not breadth. The goal is to prove that real URL-level AdX data can be fetched and normalized into the current standalone schema.

---

## 8. Normalization Contract

SOAP CSV output must be normalized into the existing collector batch schema so backend ingestion does not need a structural rewrite.

The normalized row contract is:

```json
{
  "report_date": "2026-06-03",
  "url_id": "12345",
  "url": "https://example.com/page",
  "responses_served": 100,
  "impressions": 90,
  "clicks": 3,
  "revenue": "1.234567",
  "ecpm": "13.717411"
}
```

Field mapping:

- `DATE_PT` -> `report_date`
- `URL_ID` -> `url_id`
- `URL_NAME` -> `url`
- `AD_EXCHANGE_RESPONSES_SERVED` -> `responses_served`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS` -> `impressions`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS` -> `clicks`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE` -> `revenue`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM` -> `ecpm`

The fetcher must output these values in the same type style already expected by `admanager_site_core_v1`.

---

## 9. Verification Strategy

This MVP must be verified in progressively harder layers.

### 9.1 Unit Verification

Before using real credentials:

- SOAP CSV parsing must be covered by tests
- report definition construction must be covered by tests
- fetcher selection by `fetch_mode` must be covered by tests
- normalized rows must be validated against the existing batch schema expectations

### 9.2 Local Controlled Verification

With a real authorized account and real instance:

1. create or reuse one pending task for one report date
2. run the collector once
3. confirm the runtime reaches the SOAP fetch path
4. confirm one of these clearly happens:
   - rows returned and batches uploaded
   - a specific SOAP/report-definition error occurs
   - zero rows are returned despite a valid SOAP report

### 9.3 End-to-End Success Criteria

The MVP is considered successful only if all of the following are true:

1. a real collector task completes against the SOAP fetcher
2. `collector_ingestion_batches` gets at least one new row for the task
3. `site_daily_reports` gets real data using the required URL-level semantics
4. `account_daily_reports` is rebuilt from the projected site rows

---

## 10. Failure Handling

The first implementation should distinguish clearly among these failure classes:

- OAuth refresh failure
- SOAP client initialization failure
- invalid dimension/column combination
- incompatible report settings such as time zone or report type
- report execution success but zero rows returned
- CSV download or parsing failure
- batch callback or backend ingestion failure

The collector should continue to use the current task status callback path:

- `failed` for execution failure
- `succeeded` only after all produced batches are submitted successfully

The implementation should preserve enough message detail so the operator can tell whether the failure is:

- credentials
- SOAP transport
- report definition
- empty result set

---

## 11. Risks And Stop Conditions

### 11.1 Main Risk

The chosen URL-level AdX combination may still be unsupported or return no rows for the target account even under SOAP.

### 11.2 What Not To Do

If the first SOAP implementation fails, the next step should not be:

- going back to frontend debugging
- changing backend projection logic first
- continuing REST `AD_SERVER_*` experimentation
- trying many unrelated dimensions and columns at once

### 11.3 Allowed Next Investigation

If the first combination fails, investigation should stay tightly scoped to:

- SOAP report definition compatibility
- AdX URL-level dimension availability on the real account
- exact CSV output column names
- exact Google error responses

---

## 12. Done Definition

This MVP is done when:

1. the standalone collector uses SOAP `ReportService` for real runtime fetches
2. a real account returns actual AdX data through that path
3. the data matches the current URL-level `site_daily_reports` semantics
4. the backend batch ingestion and final projections work without structural redesign
5. tests cover the new SOAP fetcher construction and normalization path

---

## Final Position

The safest path is not to redesign the platform. The safest path is to preserve the current standalone control-plane and collector architecture, replace the real fetcher with a SOAP `ReportService` implementation, and validate one minimal URL-level AdX report definition end-to-end.

If that path succeeds, the current MVP becomes a real account-isolated AdX collector instead of a technically successful but semantically incorrect report runner.
