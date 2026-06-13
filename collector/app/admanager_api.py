from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import time
from typing import Any

import requests

from app.models import CollectorTask


ADMANAGER_API_BASE_URL = "https://admanager.googleapis.com/v1"


def _google_date(value: date) -> dict[str, int]:
    return {"year": value.year, "month": value.month, "day": value.day}


@dataclass(frozen=True)
class ReportDefinition:
    dimensions: tuple[str, ...] = ("URL_ID", "URL")
    metrics: tuple[str, ...] = (
        "AD_SERVER_RESPONSES_SERVED",
        "AD_SERVER_IMPRESSIONS",
        "AD_SERVER_CLICKS",
        "AD_SERVER_REVENUE_WITHOUT_CPD",
        "AD_SERVER_AVERAGE_ECPM_WITHOUT_CPD",
    )
    report_type: str = "HISTORICAL"
    schema_version: str = "admanager_site_core_v1"

    def build_create_payload(self, task: CollectorTask) -> dict[str, Any]:
        return {
            "displayName": f"collector-task-{task.id}-{task.report_date.isoformat()}",
            "reportDefinition": {
                "dimensions": list(self.dimensions),
                "metrics": list(self.metrics),
                "dateRange": {
                    "fixed": {
                        "startDate": _google_date(task.report_date),
                        "endDate": _google_date(task.report_date),
                    }
                },
                "reportType": self.report_type,
            },
        }

    def normalize_rows(self, rows: list[dict[str, Any]], report_date: date) -> list[dict[str, Any]]:
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized_rows.append(self.normalize_row(row, report_date))
        return normalized_rows

    def normalize_row(self, row: dict[str, Any], report_date: date) -> dict[str, Any]:
        dimension_values = row.get("dimensionValues")
        metric_value_groups = row.get("metricValueGroups")
        if not isinstance(dimension_values, list) or len(dimension_values) != len(self.dimensions):
            raise ValueError("Ad Manager row dimensions did not match requested report definition")
        if not isinstance(metric_value_groups, list) or not metric_value_groups:
            raise ValueError("Ad Manager row did not include metricValueGroups")
        primary_values = metric_value_groups[0].get("primaryValues")
        if not isinstance(primary_values, list) or len(primary_values) != len(self.metrics):
            raise ValueError("Ad Manager row metrics did not match requested report definition")

        return {
            "report_date": report_date.isoformat(),
            "url_id": _cell_string(dimension_values[0]),
            "url": _cell_string(dimension_values[1]),
            "responses_served": _cell_int(primary_values[0]),
            "impressions": _cell_int(primary_values[1]),
            "clicks": _cell_int(primary_values[2]),
            "revenue": _cell_decimal_string(primary_values[3]),
            "ecpm": _cell_decimal_string(primary_values[4]),
        }


class AdManagerApiClient:
    def __init__(
        self,
        *,
        network_code: str,
        access_token: str,
        timeout_seconds: int,
        session: requests.Session | Any | None = None,
        poll_interval_seconds: float = 1.0,
        page_size: int = 500,
        report_definition: ReportDefinition | None = None,
    ) -> None:
        self._network_code = network_code
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._poll_interval_seconds = poll_interval_seconds
        self._page_size = page_size
        self._report_definition = report_definition or ReportDefinition()

    @property
    def report_definition(self) -> ReportDefinition:
        return self._report_definition

    def iter_report_rows(self, task: CollectorTask):
        report_name = self.create_report(task)
        operation_name = self.run_report(report_name)
        report_result_name = self.wait_for_report_result(operation_name)
        for rows in self.fetch_result_pages(report_result_name):
            yield self._report_definition.normalize_rows(rows, task.report_date)

    def create_report(self, task: CollectorTask) -> str:
        response = self._session.post(
            f"{ADMANAGER_API_BASE_URL}/networks/{self._network_code}/reports",
            headers=self._headers,
            json=self._report_definition.build_create_payload(task),
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        report_name = payload.get("name")
        if not isinstance(report_name, str) or not report_name:
            raise ValueError("Ad Manager create report response did not include report name")
        return report_name

    def run_report(self, report_name: str) -> str:
        response = self._session.post(
            f"{ADMANAGER_API_BASE_URL}/{report_name}:run",
            headers=self._headers,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        operation_name = payload.get("name")
        if not isinstance(operation_name, str) or not operation_name:
            raise ValueError("Ad Manager run report response did not include operation name")
        return operation_name

    def wait_for_report_result(self, operation_name: str) -> str:
        while True:
            response = self._session.get(
                f"{ADMANAGER_API_BASE_URL}/{operation_name}",
                headers=self._headers,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("done") is True:
                operation_response = payload.get("response")
                if not isinstance(operation_response, dict):
                    raise ValueError("Completed Ad Manager operation did not include a response body")
                report_result = operation_response.get("reportResult")
                if not isinstance(report_result, str) or not report_result:
                    raise ValueError("Completed Ad Manager operation did not include reportResult")
                return report_result
            if self._poll_interval_seconds > 0:
                time.sleep(self._poll_interval_seconds)

    def fetch_result_pages(self, report_result_name: str):
        next_page_token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": self._page_size}
            if next_page_token is not None:
                params["pageToken"] = next_page_token
            response = self._session.get(
                f"{ADMANAGER_API_BASE_URL}/{report_result_name}:fetchRows",
                headers=self._headers,
                params=params,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("rows", [])
            if not isinstance(rows, list):
                raise ValueError("Ad Manager fetchRows response rows field must be a list")
            if rows:
                yield rows
            next_page_token = payload.get("nextPageToken")
            if not isinstance(next_page_token, str) or not next_page_token:
                break


def _cell_string(cell: Any) -> str:
    if not isinstance(cell, dict):
        raise ValueError("Ad Manager cell must be an object")
    for key in ("stringValue", "displayValue", "value"):
        value = cell.get(key)
        if isinstance(value, str):
            return value
    int_value = cell.get("intValue")
    if int_value is not None:
        return str(int_value)
    raise ValueError("Ad Manager cell did not contain a readable string value")


def _cell_int(cell: Any) -> int:
    if not isinstance(cell, dict):
        raise ValueError("Ad Manager cell must be an object")
    for key in ("intValue", "value", "displayValue", "stringValue"):
        value = cell.get(key)
        if value is None:
            continue
        try:
            return int(str(value).replace(",", "").strip())
        except ValueError:
            continue
    raise ValueError("Ad Manager cell did not contain an integer value")


def _cell_decimal_string(cell: Any) -> str:
    if not isinstance(cell, dict):
        raise ValueError("Ad Manager cell must be an object")
    for key in ("value", "doubleValue", "microsValue", "displayValue", "stringValue"):
        value = cell.get(key)
        if value is None:
            continue
        text = str(value).replace(",", "").strip()
        if text == "":
            continue
        try:
            if key == "microsValue":
                decimal_value = (Decimal(text) / Decimal("1000000")).quantize(Decimal("0.000001"))
            else:
                decimal_value = Decimal(text).quantize(Decimal("0.000001"))
            return format(decimal_value, "f")
        except InvalidOperation:
            continue
    raise ValueError("Ad Manager cell did not contain a decimal value")
