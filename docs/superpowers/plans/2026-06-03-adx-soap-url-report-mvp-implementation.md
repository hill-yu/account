# ADX SOAP URL Report MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current real Ad Manager REST fetch path with a SOAP `ReportService` URL-level AdX fetch path that returns real data and projects it into the existing `site_daily_reports` flow.

**Architecture:** Keep the current standalone control-plane and collector structure intact. Add a SOAP-specific collector fetcher that uses `googleads` to run one URL-level AdX report definition, downloads CSV output, normalizes rows into the existing batch schema, and reuses the current batch callback and backend projection flow.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, pytest, requests, googleads, Google Ad Manager SOAP `ReportService`

---

## File Structure

### Files to modify

- `collector/requirements.txt`
  - add the SOAP client dependency used by the collector runtime
- `collector/app/models.py`
  - allow `admanager_soap` as a runtime fetch mode
- `collector/app/fetcher.py`
  - add the SOAP fetcher and wire `build_fetcher()` to select it
- `backend/app/collectors/schemas.py`
  - allow `admanager_soap` in runtime-config payloads
- `backend/app/collectors/service.py`
  - switch authorized real runtime-config responses from `admanager_rest` to `admanager_soap`
- `collector/tests/test_runtime.py`
  - cover SOAP fetcher selection and runtime integration behavior

### Files to create

- `collector/app/admanager_soap.py`
  - own the SOAP report definition, client construction, report execution, CSV download, and row normalization
- `collector/tests/test_admanager_soap.py`
  - cover report definition construction, CSV parsing, row normalization, and basic client orchestration with fakes

---

### Task 1: Add SOAP fetch mode plumbing

**Files:**
- Modify: `collector/app/models.py`
- Modify: `backend/app/collectors/schemas.py`
- Modify: `backend/app/collectors/service.py`
- Test: `collector/tests/test_runtime.py`

- [ ] **Step 1: Write the failing fetch-mode test in `collector/tests/test_runtime.py`**

Add this test near the existing fetcher-selection tests:

```python
def test_runtime_from_settings_builds_admanager_soap_fetcher() -> None:
    from app.fetcher import AdManagerSoapReportFetcher

    runtime = CollectorRuntime.from_settings(
        RuntimeSettings(
            control_plane_base_url="http://control-plane.test",
            instance_token="instance-token",
            proxy_protocol="http",
            proxy_host="proxy.example.com",
            proxy_port=8080,
            proxy_username="proxy-user",
            proxy_password="proxy-pass",
            expected_egress_ip="203.0.113.10",
            fetch_mode="admanager_soap",
            admanager_network_code="1234567",
            google_oauth_client_id="client-id",
            google_oauth_client_secret="client-secret",
            google_oauth_refresh_token="refresh-token",
        )
    )

    assert isinstance(runtime.fetcher, AdManagerSoapReportFetcher)
```

- [ ] **Step 2: Run the collector test to verify it fails**

Run:

```powershell
python -m pytest tests\test_runtime.py::test_runtime_from_settings_builds_admanager_soap_fetcher -q
```

Expected:

- FAIL with an unsupported fetch mode or missing `AdManagerSoapReportFetcher`

- [ ] **Step 3: Update `collector/app/models.py` to accept `admanager_soap`**

Edit the fetch mode comments and defaults so the dataclasses can represent the new value:

```python
@dataclass(frozen=True)
class RuntimeSettings:
    control_plane_base_url: str
    instance_token: str
    proxy_protocol: str
    proxy_host: str
    proxy_port: int
    proxy_username: str | None
    proxy_password: str | None
    expected_egress_ip: str
    fetch_mode: str = "stub"
    admanager_network_code: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_refresh_token: str | None = None
    egress_check_url: str = "https://api.ipify.org"
    request_timeout_seconds: int = 30
```

No field additions are required in this file, but the new mode must remain valid wherever runtime config is converted to settings.

- [ ] **Step 4: Update `backend/app/collectors/schemas.py` to allow `admanager_soap`**

Change the runtime credential schema literal from:

```python
fetch_mode: Literal["stub", "admanager_rest"]
```

to:

```python
fetch_mode: Literal["stub", "admanager_rest", "admanager_soap"]
```

- [ ] **Step 5: Update `backend/app/collectors/service.py` to return `admanager_soap` for authorized real accounts**

In `build_runtime_config(...)`, change:

```python
google_runtime = schemas.CollectorGoogleRuntimeCredentials(
    fetch_mode="admanager_rest",
    admanager_network_code=account.external_account_id,
    google_oauth_client_id=oauth_app.client_id,
    google_oauth_client_secret=oauth_app.client_secret,
    google_oauth_refresh_token=oauth_app.refresh_token,
)
```

to:

```python
google_runtime = schemas.CollectorGoogleRuntimeCredentials(
    fetch_mode="admanager_soap",
    admanager_network_code=account.external_account_id,
    google_oauth_client_id=oauth_app.client_id,
    google_oauth_client_secret=oauth_app.client_secret,
    google_oauth_refresh_token=oauth_app.refresh_token,
)
```

- [ ] **Step 6: Run the targeted collector test again**

Run:

```powershell
python -m pytest tests\test_runtime.py::test_runtime_from_settings_builds_admanager_soap_fetcher -q
```

Expected:

- still FAIL because the fetcher class and `build_fetcher()` support do not exist yet

- [ ] **Step 7: Commit the fetch-mode plumbing changes**

```powershell
git add collector/app/models.py backend/app/collectors/schemas.py backend/app/collectors/service.py collector/tests/test_runtime.py
git commit -m "feat: add admanager soap runtime mode plumbing"
```

---

### Task 2: Add the SOAP report definition and CSV normalization module

**Files:**
- Create: `collector/app/admanager_soap.py`
- Test: `collector/tests/test_admanager_soap.py`

- [ ] **Step 1: Write the failing SOAP normalization tests in `collector/tests/test_admanager_soap.py`**

Create the new test file with these tests:

```python
from __future__ import annotations

from datetime import date

from app.admanager_soap import SoapReportDefinition, parse_report_csv


def test_soap_report_definition_builds_expected_query() -> None:
    definition = SoapReportDefinition()

    query = definition.build_report_query(task_id=7, report_date=date(2026, 6, 3))

    assert query == {
        "dimensions": ["DATE_PT", "URL_ID", "URL_NAME"],
        "columns": [
            "AD_EXCHANGE_RESPONSES_SERVED",
            "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
            "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
            "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
            "AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
        ],
        "dateRangeType": "CUSTOM_DATE",
        "startDate": {"year": 2026, "month": 6, "day": 3},
        "endDate": {"year": 2026, "month": 6, "day": 3},
        "reportType": "HISTORICAL",
        "timeZoneType": "PACIFIC",
    }


def test_parse_report_csv_normalizes_adx_url_rows() -> None:
    raw_csv = \"\"\"Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM
2026-06-03,2001,https://example.com/a,1000,950,15,12.345678,12.995450
2026-06-03,2002,https://example.com/b,800,760,8,4.250000,5.592105
\"\"\"

    rows = parse_report_csv(raw_csv, report_date=date(2026, 6, 3))

    assert rows == [
        {
            "report_date": "2026-06-03",
            "url_id": "2001",
            "url": "https://example.com/a",
            "responses_served": 1000,
            "impressions": 950,
            "clicks": 15,
            "revenue": "12.345678",
            "ecpm": "12.995450",
        },
        {
            "report_date": "2026-06-03",
            "url_id": "2002",
            "url": "https://example.com/b",
            "responses_served": 800,
            "impressions": 760,
            "clicks": 8,
            "revenue": "4.250000",
            "ecpm": "5.592105",
        },
    ]
```

- [ ] **Step 2: Run the new SOAP tests to verify they fail**

Run:

```powershell
python -m pytest tests\test_admanager_soap.py -q
```

Expected:

- FAIL because `app.admanager_soap` does not exist yet

- [ ] **Step 3: Create `collector/app/admanager_soap.py` with the report definition and parser**

Create this file:

```python
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


def _google_date(value: date) -> dict[str, int]:
    return {"year": value.year, "month": value.month, "day": value.day}


@dataclass(frozen=True)
class SoapReportDefinition:
    dimensions: tuple[str, ...] = ("DATE_PT", "URL_ID", "URL_NAME")
    columns: tuple[str, ...] = (
        "AD_EXCHANGE_RESPONSES_SERVED",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM",
    )
    report_type: str = "HISTORICAL"
    time_zone_type: str = "PACIFIC"
    schema_version: str = "admanager_site_core_v1"

    def build_report_query(self, *, task_id: int, report_date: date) -> dict[str, object]:
        return {
            "dimensions": list(self.dimensions),
            "columns": list(self.columns),
            "dateRangeType": "CUSTOM_DATE",
            "startDate": _google_date(report_date),
            "endDate": _google_date(report_date),
            "reportType": self.report_type,
            "timeZoneType": self.time_zone_type,
        }


def parse_report_csv(raw_csv: str, *, report_date: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    reader = csv.DictReader(io.StringIO(raw_csv))
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        row_date = (row.get("Dimension.DATE_PT") or "").strip()
        if row_date != report_date.isoformat():
            continue
        rows.append(
            {
                "report_date": report_date.isoformat(),
                "url_id": (row.get("Dimension.URL_ID") or "").strip(),
                "url": (row.get("Dimension.URL_NAME") or "").strip(),
                "responses_served": _parse_int(row.get("Column.AD_EXCHANGE_RESPONSES_SERVED")),
                "impressions": _parse_int(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS")),
                "clicks": _parse_int(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS")),
                "revenue": _parse_decimal_string(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE")),
                "ecpm": _parse_decimal_string(row.get("Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM")),
            }
        )
    return rows


def _parse_int(value: str | None) -> int:
    text = (value or "").replace(",", "").strip()
    if text == "":
        return 0
    return int(Decimal(text))


def _parse_decimal_string(value: str | None) -> str:
    text = (value or "").replace(",", "").strip()
    if text == "":
        return "0.000000"
    try:
        return format(Decimal(text).quantize(Decimal("0.000001")), "f")
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal cell value: {value}") from exc
```

- [ ] **Step 4: Run the SOAP parser tests to verify they pass**

Run:

```powershell
python -m pytest tests\test_admanager_soap.py -q
```

Expected:

- PASS

- [ ] **Step 5: Commit the SOAP report-definition module**

```powershell
git add collector/app/admanager_soap.py collector/tests/test_admanager_soap.py
git commit -m "feat: add admanager soap report definition and csv parser"
```

---

### Task 3: Implement the SOAP fetcher using `googleads`

**Files:**
- Modify: `collector/requirements.txt`
- Modify: `collector/app/fetcher.py`
- Create: `collector/app/admanager_soap.py`
- Test: `collector/tests/test_admanager_soap.py`
- Test: `collector/tests/test_runtime.py`

- [ ] **Step 1: Add a failing orchestration test to `collector/tests/test_admanager_soap.py`**

Append this test:

```python
from app.admanager_soap import AdManagerSoapClient


class FakeDownloader:
    def __init__(self) -> None:
        self.wait_calls = []
        self.download_calls = []

    def WaitForReport(self, report_job, poll_time_seconds):
        self.wait_calls.append((report_job, poll_time_seconds))
        return 12345

    def DownloadReportToFile(
        self,
        report_job_id,
        export_format,
        outfile,
        include_report_properties,
        include_totals_row,
        use_gzip_compression,
    ):
        self.download_calls.append(
            (
                report_job_id,
                export_format,
                include_report_properties,
                include_totals_row,
                use_gzip_compression,
            )
        )
        outfile.write(
            b"Dimension.DATE_PT,Dimension.URL_ID,Dimension.URL_NAME,Column.AD_EXCHANGE_RESPONSES_SERVED,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM\n"
            b"2026-06-03,2001,https://example.com/a,1000,950,15,12.345678,12.995450\n"
        )


def test_admanager_soap_client_downloads_and_parses_rows() -> None:
    downloader = FakeDownloader()
    client = AdManagerSoapClient(
        network_code="1234567",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        application_name="adx-account-isolated-collector",
        api_version="v202602",
        downloader_factory=lambda: downloader,
    )

    rows = client.fetch_rows(task_id=7, report_date=date(2026, 6, 3))

    assert rows == [
        {
            "report_date": "2026-06-03",
            "url_id": "2001",
            "url": "https://example.com/a",
            "responses_served": 1000,
            "impressions": 950,
            "clicks": 15,
            "revenue": "12.345678",
            "ecpm": "12.995450",
        }
    ]
    assert downloader.wait_calls == [
        (
            {"reportQuery": SoapReportDefinition().build_report_query(task_id=7, report_date=date(2026, 6, 3))},
            2,
        )
    ]
    assert downloader.download_calls == [
        (12345, "CSV_DUMP", False, False, False)
    ]
```

- [ ] **Step 2: Run the orchestration test to verify it fails**

Run:

```powershell
python -m pytest tests\test_admanager_soap.py::test_admanager_soap_client_downloads_and_parses_rows -q
```

Expected:

- FAIL because `AdManagerSoapClient` does not exist yet

- [ ] **Step 3: Add `googleads` to `collector/requirements.txt`**

Append this dependency if not already present:

```text
googleads
```

- [ ] **Step 4: Expand `collector/app/admanager_soap.py` with the SOAP client**

Add this implementation below the parser code:

```python
from googleads import ad_manager, oauth2
import io


class AdManagerSoapClient:
    def __init__(
        self,
        *,
        network_code: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        application_name: str = "adx-account-isolated-collector",
        api_version: str = "v202602",
        downloader_factory=None,
    ) -> None:
        self._network_code = network_code
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._application_name = application_name
        self._api_version = api_version
        self._report_definition = SoapReportDefinition()
        self._downloader_factory = downloader_factory

    @property
    def report_definition(self) -> SoapReportDefinition:
        return self._report_definition

    def fetch_rows(self, *, task_id: int, report_date: date) -> list[dict[str, object]]:
        downloader = self._build_downloader()
        report_job_id = downloader.WaitForReport(
            {"reportQuery": self._report_definition.build_report_query(task_id=task_id, report_date=report_date)},
            poll_time_seconds=2,
        )
        csv_io = io.BytesIO()
        downloader.DownloadReportToFile(
            report_job_id,
            export_format="CSV_DUMP",
            outfile=csv_io,
            include_report_properties=False,
            include_totals_row=False,
            use_gzip_compression=False,
        )
        return parse_report_csv(csv_io.getvalue().decode("utf-8", errors="ignore"), report_date=report_date)

    def _build_downloader(self):
        if self._downloader_factory is not None:
            return self._downloader_factory()
        oauth2_client = oauth2.GoogleRefreshTokenClient(
            self._client_id,
            self._client_secret,
            self._refresh_token,
        )
        client = ad_manager.AdManagerClient(
            oauth2_client,
            self._application_name,
            network_code=self._network_code,
            cache=None,
        )
        return client.GetDataDownloader(version=self._api_version)
```

- [ ] **Step 5: Add the SOAP fetcher to `collector/app/fetcher.py`**

Update imports and `build_fetcher()`:

```python
from app.admanager_soap import AdManagerSoapClient
```

Add the class:

```python
class AdManagerSoapReportFetcher:
    def __init__(
        self,
        *,
        network_code: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        self._client = AdManagerSoapClient(
            network_code=network_code,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )

    def fetch(self, task: CollectorTask) -> Iterable[FetchBatch]:
        rows = self._client.fetch_rows(task_id=task.id, report_date=task.report_date)
        if not rows:
            return ()
        return (
            FetchBatch(
                batch_key="page-1",
                row_count=len(rows),
                payload_hash=_hash_rows(rows),
                schema_version=self._client.report_definition.schema_version,
                rows=rows,
            ),
        )
```

Update the builder:

```python
def build_fetcher(settings: RuntimeSettings) -> Fetcher:
    if settings.fetch_mode == "stub":
        return StubFetcher()
    if settings.fetch_mode == "admanager_rest":
        return AdManagerRestReportFetcher(
            network_code=_require_setting(settings.admanager_network_code, "admanager_network_code"),
            client_id=_require_setting(settings.google_oauth_client_id, "google_oauth_client_id"),
            client_secret=_require_setting(settings.google_oauth_client_secret, "google_oauth_client_secret"),
            refresh_token=_require_setting(settings.google_oauth_refresh_token, "google_oauth_refresh_token"),
            timeout_seconds=settings.request_timeout_seconds,
        )
    if settings.fetch_mode == "admanager_soap":
        return AdManagerSoapReportFetcher(
            network_code=_require_setting(settings.admanager_network_code, "admanager_network_code"),
            client_id=_require_setting(settings.google_oauth_client_id, "google_oauth_client_id"),
            client_secret=_require_setting(settings.google_oauth_client_secret, "google_oauth_client_secret"),
            refresh_token=_require_setting(settings.google_oauth_refresh_token, "google_oauth_refresh_token"),
        )
    raise ValueError(f"Unsupported fetch mode: {settings.fetch_mode}")
```

- [ ] **Step 6: Run the targeted collector tests**

Run:

```powershell
python -m pytest tests\test_admanager_soap.py tests\test_runtime.py::test_runtime_from_settings_builds_admanager_soap_fetcher -q
```

Expected:

- PASS

- [ ] **Step 7: Commit the SOAP fetcher implementation**

```powershell
git add collector/requirements.txt collector/app/admanager_soap.py collector/app/fetcher.py collector/tests/test_admanager_soap.py collector/tests/test_runtime.py
git commit -m "feat: add admanager soap fetcher"
```

---

### Task 4: Verify end-to-end batch compatibility and real-mode callback flow

**Files:**
- Modify: `collector/tests/test_runtime.py`
- Test: `backend/tests/test_collector_router.py`
- Test: `backend/tests/test_ingestion_service.py`

- [ ] **Step 1: Add a runtime success test that uses the SOAP fetcher output shape**

Add this test to `collector/tests/test_runtime.py`:

```python
def test_runtime_uploads_single_soap_batch_and_marks_task_succeeded() -> None:
    task = CollectorTask(
        id=11,
        account_id=3,
        collector_instance_id=2,
        task_type="report_fetch",
        report_date=date(2026, 6, 3),
        status="in_progress",
    )
    batch = FetchBatch(
        batch_key="page-1",
        row_count=1,
        payload_hash="soap-hash",
        schema_version="admanager_site_core_v1",
        rows=[
            {
                "report_date": "2026-06-03",
                "url_id": "2001",
                "url": "https://example.com/a",
                "responses_served": 1000,
                "impressions": 950,
                "clicks": 15,
                "revenue": "12.345678",
                "ecpm": "12.995450",
            }
        ],
    )
    client = FakeControlPlaneClient(next_task_result=task)
    fetcher = FakeFetcher([batch])
    runtime = CollectorRuntime(
        settings=build_settings(),
        control_plane_client=client,
        egress_checker=FakeEgressChecker("203.0.113.10"),
        fetcher=fetcher,
    )

    result = runtime.run_once()

    assert result.outcome == "succeeded"
    assert client.batch_callbacks == [(11, batch)]
    assert client.status_callbacks == [(11, "succeeded", "uploaded 1 batches")]
```

- [ ] **Step 2: Run the runtime test to verify it passes**

Run:

```powershell
python -m pytest tests\test_runtime.py::test_runtime_uploads_single_soap_batch_and_marks_task_succeeded -q
```

Expected:

- PASS

- [ ] **Step 3: Run the backend ingestion tests to confirm no schema rewrite is required**

Run:

```powershell
python -m pytest tests\test_collector_router.py tests\test_ingestion_service.py -q
```

Expected:

- PASS

- [ ] **Step 4: Commit the compatibility verification changes**

```powershell
git add collector/tests/test_runtime.py
git commit -m "test: verify soap batch callback compatibility"
```

---

### Task 5: Run full local verification and prepare the real-account execution checklist

**Files:**
- Modify: `docs/2026-06-03-project-handover.md`
- Modify: `docs/operator-notes.md`

- [ ] **Step 1: Run the collector test suite**

Run:

```powershell
python -m pytest tests\test_runtime.py tests\test_oauth.py tests\test_proxy.py tests\test_admanager_soap.py -q
```

Expected:

- PASS

- [ ] **Step 2: Run the backend test suite relevant to collector execution**

Run:

```powershell
python -m pytest tests\test_virtual_flow_script.py tests\test_collector_router.py tests\test_ingestion_service.py tests\test_oauth_service.py -q
```

Expected:

- PASS

- [ ] **Step 3: Update `docs/operator-notes.md` to reflect the SOAP real-fetch path**

Add or update the real fetcher notes so they say:

```markdown
The real collector fetcher now uses Ad Manager SOAP `ReportService` for the standalone MVP real-data path.

The first validated report definition targets URL-level AdX data:

- dimensions: `DATE_PT`, `URL_ID`, `URL_NAME`
- columns:
  - `AD_EXCHANGE_RESPONSES_SERVED`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`
```

- [ ] **Step 4: Update `docs/2026-06-03-project-handover.md` with the new real fetcher direction**

Replace the wording that describes the active real fetcher as Beta REST with wording that says the active implementation now targets SOAP `ReportService`, while also noting that real-account validation still depends on the target account returning rows for the chosen URL-level AdX definition.

- [ ] **Step 5: Commit the docs updates**

```powershell
git add docs/operator-notes.md docs/2026-06-03-project-handover.md
git commit -m "docs: update handover for soap report fetcher"
```

---

## Self-Review

- Spec coverage:
  - SOAP fetcher added: covered in Tasks 1-3
  - URL-level AdX report definition: covered in Task 2
  - batch-schema compatibility: covered in Task 4
  - docs and operator guidance: covered in Task 5
- Placeholder scan:
  - no `TODO`, `TBD`, or “implement later” placeholders remain
- Type consistency:
  - fetch mode is consistently `admanager_soap`
  - normalized output consistently uses the existing `admanager_site_core_v1` row shape

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-03-adx-soap-url-report-mvp-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
