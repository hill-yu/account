## Goal

Upgrade the current single-account VPS execution node so that AdX fetches can run only through the account's bound fixed proxy and verified fixed egress IP, while keeping `fetch.php`, `report.php`, and cron behavior unchanged.

## Scope

- Keep the deployment model as one node, one account, one proxy.
- Reuse the existing `AdxAccountProxy`, `ProxyResolver`, `ProxyConfig`, and `EgressChecker` abstractions.
- Do not add new public interfaces.
- Do not introduce multi-account scheduling, proxy failover, or shared proxy pools.

## Work Items

### 1. Lock the behavior with tests first

- Add service tests for:
  - configured proxy routes are passed into the report service builder
  - configured proxy routes trigger an egress IP check before fetch
  - egress mismatch fails the run and persists the failure message
  - proxy config errors still fail cleanly without creating inconsistent rows
- Add lower-level tests for:
  - converting a VPS proxy route into `googleads.common.ProxyConfig`
  - passing `proxy_config` into the SOAP OAuth and service client layers

### 2. Add proxy-aware report service construction

- Extend `AdxReportService` so it can accept an optional proxy config for downstream SOAP calls.
- Extend `AdManagerSoapClient` so it can build:
  - `googleads.common.ProxyConfig`
  - `oauth2.GoogleRefreshTokenClient(..., proxy_config=...)`
  - `ad_manager.AdManagerClient(..., proxy_config=...)`
- Keep direct mode working exactly as it does now.

### 3. Add VPS-side egress validation

- Reuse `app.proxy.ProxyConfig` and `app.egress.EgressChecker`.
- In configured proxy mode:
  - build proxy config from the resolved proxy route
  - check observed egress IP before building the AdX SOAP client
  - fail fast if observed IP != expected egress IP
- Do not silently fall back to direct mode.

### 4. Preserve run semantics and observability

- On proxy validation failure or proxy transport failure:
  - mark `adx_fetch_runs.status = failed`
  - persist a clear `error_message`
- Keep `fetch.php` returning `accepted` and `report.php` returning the latest successful snapshot.
- Add worker-side logging where proxy execution fails before a run can complete.

### 5. Update operator documentation

- Document how to configure a node-level fixed proxy in `adx_account_proxies`.
- Document the new failure modes:
  - invalid proxy binding
  - proxy transport failure
  - egress IP mismatch
- Keep the deployment and cron calling contract unchanged.

## Verification

- Run targeted Python tests for the updated service, SOAP client, and proxy handling.
- Verify no regressions in existing VPS API/report tests.
- If practical, keep the final runtime check deployable to the current VPS without changing the PHP contract.
