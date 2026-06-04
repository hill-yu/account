# AdX VPS PHP Trigger Architecture Design

## Summary

This design defines the first production-style deployment of the AdX data pull flow outside the current local control-plane demo. The target shape is:

- Cloudflare provides DNS, HTTPS, and reverse-proxy ingress
- A VPS hosts the real execution stack
- A public PHP endpoint acts as the trigger entrypoint
- A local Python HTTP service performs AdX data pulls
- MySQL stores account config, fetch runs, proxy bindings, and normalized report rows

The first release is intentionally minimal:

- single-account execution is sufficient
- synchronous trigger -> synchronous fetch -> synchronous response
- the existing Python AdX SOAP module is reused
- proxy-per-account is not required on day one, but the interface and schema are reserved now

## Goals

- Reuse the existing working Python AdX fetch module in a VPS deployment
- Allow a public PHP script to trigger one report pull by account and date
- Persist normalized site-level AdX rows into a VPS-local database
- Return a clear success or failure result to the trigger caller
- Preserve an upgrade path to multi-account fixed-proxy execution later

## Non-Goals

- Rebuild the current local control-plane stack on the VPS
- Support concurrent multi-account scheduling in the first release
- Expose read APIs for the middle platform in the first release
- Implement queue-based or async workers in the first release
- Implement account-specific proxy routing in the first release

## Architecture

### External ingress

Cloudflare is ingress only. It terminates HTTPS, proxies traffic, and routes subdomains to the VPS origin. It does not run the AdX fetch logic.

### Public trigger layer

A PHP script on the VPS exposes a public trigger endpoint such as:

- `https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-06-03`

Responsibilities:

- validate request parameters
- apply simple request authentication
- assign a request id
- call the local Python HTTP service
- return a JSON result to the caller

The PHP layer must stay thin. It is not responsible for OAuth token exchange, SOAP calls, CSV parsing, proxy selection logic, or result normalization.

### Python execution layer

A local Python service runs on the VPS and listens on loopback only, for example:

- `http://127.0.0.1:9100/internal/fetch`

Responsibilities:

- load account configuration
- load proxy binding configuration
- choose connection strategy for the account
- call the existing `AdxReportService`
- normalize and store rows
- persist execution status to the fetch-runs table
- return a machine-readable result to the PHP caller

This service is the execution core and the future extension point for account-specific proxy routing and middle-platform read APIs.

### Data storage layer

MySQL on the VPS stores:

- AdX account credentials and metadata
- optional account-to-proxy bindings
- fetch execution records
- normalized site-level AdX rows

### Future read layer

A future read API will expose stored results to the middle platform. It is intentionally deferred, but the storage model and execution model are designed so this can be added without refactoring the fetch path.

## Data model

### `adx_accounts`

Stores per-account AdX API configuration.

Recommended fields:

- `id`
- `account_key`
- `account_name`
- `network_code`
- `client_id`
- `client_secret`
- `refresh_token`
- `status`
- `created_at`
- `updated_at`

### `adx_account_proxies`

Stores the optional per-account proxy binding. This is an extension point for the later fixed-IP model.

Recommended fields:

- `id`
- `account_id`
- `proxy_type`
- `proxy_host`
- `proxy_port`
- `proxy_username`
- `proxy_password`
- `expected_egress_ip`
- `is_active`
- `created_at`
- `updated_at`

The first release may leave this table empty or store one default proxy. The Python execution layer must still be written against this interface so account-specific routing can be added later without changing callers.

### `adx_fetch_runs`

Stores one row per fetch attempt.

Recommended fields:

- `id`
- `account_id`
- `report_date`
- `trigger_source`
- `request_id`
- `status`
- `row_count`
- `started_at`
- `finished_at`
- `error_message`

This table is the primary operational audit trail.

### `adx_site_daily_reports`

Stores normalized site-level AdX rows returned by the current working report definition.

Recommended fields:

- `id`
- `account_id`
- `report_date`
- `site_name`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`
- `fetch_run_id`
- `created_at`

Recommended uniqueness constraint:

- unique on `account_id, report_date, site_name`

That allows safe delete-and-replace or upsert behavior for reruns.

## Interfaces

### Public PHP trigger endpoint

Example:

- `GET /ke/fetch.php?account_key=a1&report_date=2026-06-03&token=...`

Input:

- `account_key`
- `report_date`
- trigger auth token or signature

Behavior:

- validate input
- generate `request_id`
- call the local Python API
- return JSON

Example success response:

```json
{
  "ok": true,
  "request_id": "req_20260604_001",
  "run_id": 17,
  "account_key": "a1",
  "report_date": "2026-06-03",
  "row_count": 8,
  "status": "success"
}
```

Example error response:

```json
{
  "ok": false,
  "request_id": "req_20260604_001",
  "error_code": "FETCH_ERROR",
  "message": "Google report download failed"
}
```

### Local Python fetch endpoint

Example:

- `POST /internal/fetch`

Input JSON:

```json
{
  "account_key": "a1",
  "report_date": "2026-06-03",
  "trigger_source": "php_manual",
  "request_id": "req_20260604_001"
}
```

Output JSON:

```json
{
  "ok": true,
  "run_id": 17,
  "account_key": "a1",
  "report_date": "2026-06-03",
  "row_count": 8,
  "status": "success"
}
```

This endpoint is loopback-only and must not be exposed publicly.

## Runtime flow

1. A caller hits the public PHP trigger endpoint.
2. PHP validates the request and generates a `request_id`.
3. PHP calls the local Python fetch endpoint.
4. Python loads the target account from `adx_accounts`.
5. Python loads any active proxy config from `adx_account_proxies`.
6. Python inserts a `running` row into `adx_fetch_runs`.
7. Python executes the existing `AdxReportService` site-level SOAP fetch.
8. Python writes report rows into `adx_site_daily_reports`.
9. Python updates the fetch run to `success` or `failed`.
10. Python returns a structured result to PHP.
11. PHP returns a structured result to the external caller.

## Report semantics

The first release reuses the currently proven working report semantics:

- dimensions:
  - `DATE_PT`
  - `SITE_NAME`
- metrics:
  - `AD_EXCHANGE_RESPONSES_SERVED`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`

The first release stores site-level rows, not URL-level rows. This is acceptable because the required business metrics are available and verified on the real account.

Revenue and eCPM must continue to be normalized from micros before storage.

## Proxy extension design

The architecture explicitly reserves a proxy-selection boundary between the Python execution layer and outbound Google API calls.

The Python service must depend on a small proxy-resolution abstraction with the following responsibilities:

- accept an account id or account key
- return either:
  - direct connection
  - default shared proxy
  - account-specific proxy configuration

The first release may resolve to direct connection or one default proxy, but the Python fetch path must not hardcode this decision inline. The goal is to enable a later second phase where different AdX accounts always use different fixed outbound IPs without changing the public PHP trigger contract.

## Error handling

Errors are grouped into four operational categories.

### `REQUEST_ERROR`

Examples:

- missing `account_key`
- invalid `report_date`
- missing or invalid trigger token

Handled in PHP. Return HTTP 400 or 401.

### `ACCOUNT_CONFIG_ERROR`

Examples:

- unknown account
- missing `network_code`
- missing OAuth credentials

Handled in Python. Return HTTP 422. Persist the failure in `adx_fetch_runs` when a run row already exists.

### `FETCH_ERROR`

Examples:

- refresh token exchange failed
- SOAP report failed
- report download failed
- proxy connection failed

Handled in Python. Return HTTP 502 or 500. Persist detailed message in `adx_fetch_runs.error_message`.

### `STORE_ERROR`

Examples:

- database connection failure
- row upsert failure
- result persistence mismatch

Handled in Python. Return HTTP 500 and persist failure details.

## Deployment model

### Cloudflare

- DNS and HTTPS
- reverse proxy to the VPS origin
- optional WAF/rate limiting later

### VPS services

- nginx or Apache for public PHP handling
- PHP-FPM for `fetch.php`
- MySQL for account config and report data
- a supervised Python HTTP service bound to `127.0.0.1`

The Python process should be managed by `systemd` or `supervisor` so it survives restarts.

## Security

First release minimums:

- the Python API listens on loopback only
- the public PHP endpoint requires a token or request signature
- OAuth secrets are stored server-side only
- PHP never exposes raw Google credentials
- database and application logs must avoid dumping secrets

## Phased rollout

### Phase 1: minimal production replication

- deploy the Python fetch service to the VPS
- connect it to MySQL
- expose the PHP trigger endpoint
- run one account and one date successfully end-to-end

### Phase 2: middle-platform read access

- add a read endpoint over stored report data
- keep the fetch path unchanged

### Phase 3: account-specific fixed-IP execution

- activate `adx_account_proxies`
- implement proxy resolution by account
- optionally add egress verification and operational tooling

## Testing strategy

### Unit tests

- request validation for the Python API
- account lookup and config validation
- proxy resolution behavior
- persistence logic for fetch runs and site rows
- idempotent rerun behavior for the same account/date

### Integration tests

- PHP endpoint calling the Python loopback API
- Python API storing rows into MySQL-backed tables
- one real-account smoke test in the VPS environment

### Operational verification

Success for the first release means:

- public PHP trigger returns success JSON
- Python fetch run is stored with `status=success`
- `adx_site_daily_reports` contains the normalized site rows for the requested date
- rerunning the same date does not create duplicate logical rows

## Recommended implementation order

1. Extract the current reusable Python module behind a VPS-oriented service boundary.
2. Add MySQL persistence for accounts, fetch runs, and site rows.
3. Add the local Python HTTP API.
4. Add the thin PHP trigger endpoint.
5. Deploy behind Cloudflare on the VPS.
6. Add the proxy-resolution abstraction without turning on per-account routing yet.

