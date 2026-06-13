# ADX Report Service Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the current single-account AdX SOAP fetch logic into a reusable Python service module that both the collector and standalone scripts can call directly.

**Architecture:** Keep the low-level SOAP client and CSV parsing in `admanager_soap.py`, add a business-facing `adx_report_service.py` module with typed credentials, typed rows, range helpers, and batch compatibility helpers, then refactor the collector fetcher into a thin wrapper over that service.

**Tech Stack:** Python 3.11, googleads, pytest, dataclasses

---

## File Structure

### Files to create

- `collector/app/adx_report_service.py`
  - reusable single-account AdX report service
- `collector/tests/test_adx_report_service.py`
  - unit tests for service-level behavior

### Files to modify

- `collector/app/fetcher.py`
  - refactor SOAP fetcher to use the new service
- `collector/tests/test_runtime.py`
  - keep runtime coverage aligned with the thinner fetcher layer
- `docs/2026-06-03-project-handover-soap-update.md`
  - note the new reusable module entrypoint

---

### Task 1: Create service-level tests first

**Files:**
- Create: `collector/tests/test_adx_report_service.py`

- [ ] **Step 1: Write the failing service tests**

Create tests for:
- single-day fetch returns typed rows
- range fetch aggregates rows across days
- dict compatibility output matches current collector row shape
- batch helper returns `FetchBatch`

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```powershell
python -m pytest tests\test_adx_report_service.py -q
```

Expected:

- FAIL because the module does not exist yet

---

### Task 2: Implement the reusable service module

**Files:**
- Create: `collector/app/adx_report_service.py`
- Test: `collector/tests/test_adx_report_service.py`

- [ ] **Step 1: Add minimal data models and service implementation**

Implement:
- `AdxApiCredentials`
- `AdxReportRow`
- `AdxReportService`
- `fetch_site_daily_report`
- `fetch_site_daily_range`
- `fetch_site_daily_rows_as_dicts`
- `build_fetch_batch`

- [ ] **Step 2: Run the service tests**

Run:

```powershell
python -m pytest tests\test_adx_report_service.py -q
```

Expected:

- PASS

---

### Task 3: Refactor the collector fetcher to use the service

**Files:**
- Modify: `collector/app/fetcher.py`
- Modify: `collector/tests/test_runtime.py`

- [ ] **Step 1: Update the SOAP fetcher to delegate to the service**

Replace direct SOAP-client usage in `AdManagerSoapReportFetcher` with:
- service construction from runtime credentials
- conversion through `build_fetch_batch`

- [ ] **Step 2: Add or update the targeted fetcher/runtime tests**

Ensure tests still cover:
- `admanager_soap` fetcher construction
- runtime success path with batch upload shape

- [ ] **Step 3: Run the targeted collector tests**

Run:

```powershell
python -m pytest tests\test_adx_report_service.py tests\test_runtime.py -q
```

Expected:

- PASS

---

### Task 4: Verify reusable entrypoints and real-account behavior

**Files:**
- Modify: `docs/2026-06-03-project-handover-soap-update.md`

- [ ] **Step 1: Run backend compatibility tests**

Run:

```powershell
python -m pytest tests\test_ingestion_service.py -q
```

from `backend/`

Expected:

- PASS

- [ ] **Step 2: Run a real-account service verification**

Call the new service module directly for account `23347208010` and confirm it returns rows for `2026-05-14`.

- [ ] **Step 3: Update the handover addendum**

Document the new reusable module entrypoints and the fact that both collector and standalone scripts should call the same service layer.

---

## Self-Review

- Spec coverage:
  - reusable Python module: covered by Tasks 1-2
  - collector compatibility: covered by Task 3
  - standalone/backend direct use: covered by Task 4 real-account verification
- Placeholder scan:
  - no TODO/TBD placeholders remain
- Type consistency:
  - credentials, row objects, dict compatibility, and batch compatibility use one consistent single-account service boundary
