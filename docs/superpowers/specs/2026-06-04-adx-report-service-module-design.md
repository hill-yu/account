# ADX Report Service Module Design

## Goal

Extract the current single-account AdX SOAP fetch capability into a reusable Python service module that can be:

- imported directly by the existing collector runtime
- imported directly by standalone backend or operator scripts

The module should return normalized site-level AdX rows and optionally build the current collector batch shape.

## Scope

First version supports:

- one Ad Manager account per call
- site-level AdX daily report rows
- metrics:
  - `responses_served`
  - `impressions`
  - `clicks`
  - `revenue`
  - `ecpm`
- date range fetching by looping day-by-day
- compatibility helpers for current collector batch upload flow

First version does not support:

- multi-account orchestration
- background scheduling
- database persistence
- HTTP API endpoints
- configurable dimensions beyond the current validated `DATE_PT + SITE_NAME`

## Proposed Module Boundary

Create a new module:

- `collector/app/adx_report_service.py`

This module owns the business-facing fetch interface.

It depends on:

- `collector/app/admanager_soap.py` for SOAP transport, report definition, CSV parsing
- `collector/app/models.py` for `FetchBatch`

It should not depend on:

- `CollectorRuntime`
- `ControlPlaneClient`
- backend database code
- FastAPI routes

## Public Interface

### Data structures

- `AdxApiCredentials`
  - `network_code`
  - `client_id`
  - `client_secret`
  - `refresh_token`

- `AdxReportRow`
  - `report_date`
  - `site_name`
  - `responses_served`
  - `impressions`
  - `clicks`
  - `revenue`
  - `ecpm`

### Service methods

- `fetch_site_daily_report(credentials, report_date) -> list[AdxReportRow]`
  - primary single-day entrypoint

- `fetch_site_daily_range(credentials, start_date, end_date) -> list[AdxReportRow]`
  - loops from `start_date` to `end_date` inclusive

- `fetch_site_daily_rows_as_dicts(credentials, start_date, end_date) -> list[dict[str, object]]`
  - compatibility helper for current collector row schema
  - maps `site_name` into current `url_id` and `url` fields

- `build_fetch_batch(rows, batch_key="page-1") -> FetchBatch | None`
  - compatibility helper for current collector callback flow
  - returns `None` if no rows

## Integration Plan

Keep the collector runtime behavior intact by making `AdManagerSoapReportFetcher` a thin wrapper around the new module:

- build credentials from runtime settings
- call the reusable service
- convert returned rows into a `FetchBatch`

This preserves the existing collector contract while making the fetch logic directly reusable elsewhere.

## Testing Strategy

Add focused unit tests for:

- single-day service fetch using a fake SOAP client
- date-range fetch aggregation
- dict compatibility output
- batch helper output
- collector fetcher using the new service boundary

Reuse the existing real-account verification flow after refactor to confirm the reusable module still returns normalized rows for account `23347208010`.
