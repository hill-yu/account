# 2026-06-03 SOAP Fetcher Update

This addendum records the current real-fetch direction for the standalone collector MVP.

## Active Implementation

- Authorized real accounts now receive `fetch_mode = admanager_soap` from runtime-config.
- The collector runtime now supports an `AdManagerSoapReportFetcher` path alongside `stub` and `admanager_rest`.
- The SOAP client implementation uses Ad Manager `ReportService` through the `googleads` library.

## Site-Level AdX Report Definition

The current minimum report definition targets the existing `site_daily_reports` schema:

- dimensions: `DATE_PT`, `SITE_NAME`
- columns:
  - `AD_EXCHANGE_RESPONSES_SERVED`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`
- time zone type: `PACIFIC`

Normalized rows remain aligned with the current staging and projection flow:

- `report_date`
- `url_id`
- `url`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

## Validation Status

- SOAP report-definition tests are passing.
- SOAP downloader orchestration is covered with a fake downloader test.
- Collector runtime tests confirm `admanager_soap` fetcher selection.
- Batch ingestion and final table projection remain compatible with the normalized row schema.
- SOAP `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE` and `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM` are now normalized from micros into 6-decimal strings before batch upload.

## Important Guardrails

- CSV parsing now fails fast on missing required columns.
- CSV parsing now fails on truncated required cells instead of silently substituting zero values.
- Non-finite numeric values such as `NaN` are rejected during normalization.

## Remaining Real-Account Dependency

Local implementation is ready for real-account validation, and the current real account now returns rows for this `SITE_NAME`-based AdX SOAP definition. Revenue and eCPM unit normalization remains the next follow-up step.
