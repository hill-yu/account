from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
COLLECTOR_DIR = ROOT_DIR / "collector"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _wait_for_backend(base_url: str, backend_proc: subprocess.Popen[str], timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if backend_proc.poll() is not None:
            output = backend_proc.stdout.read() if backend_proc.stdout else ""
            raise RuntimeError(f"backend exited early\n{output}")
        try:
            response = requests.get(f"{base_url}/health", timeout=1)
            if response.status_code == 200:
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("backend did not become healthy in time")


def _create_virtual_entities(base_url: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    account = requests.post(
        f"{base_url}/api/v1/operator/accounts",
        json={
            "name": "process-account-1",
            "status": "active",
            "external_account_id": "1234567",
        },
        timeout=10,
    ).json()

    instance = requests.post(
        f"{base_url}/api/v1/operator/instances",
        json={
            "account_id": account["id"],
            "name": "process-instance-1",
            "instance_token": "process-token-1",
            "status": "ready",
            "expected_egress_ip": "203.0.113.10",
        },
        timeout=10,
    ).json()

    proxy_response = requests.post(
        f"{base_url}/api/v1/operator/proxies",
        json={
            "account_id": account["id"],
            "collector_instance_id": instance["id"],
            "provider_name": "process-proxy",
            "protocol": "http",
            "host": "proxy.invalid",
            "port": 8080,
            "username": "user",
            "password": "pass",
            "expected_egress_ip": "203.0.113.10",
            "status": "active",
        },
        timeout=10,
    )
    proxy_response.raise_for_status()

    task = requests.post(
        f"{base_url}/api/v1/operator/tasks",
        json={
            "account_id": account["id"],
            "collector_instance_id": instance["id"],
            "task_type": "report_fetch",
            "report_date": "2026-05-21",
            "status": "pending",
            "external_request_id": "virtual-flow-script-run-001",
        },
        timeout=10,
    ).json()

    return account, instance, task


def run_virtual_flow() -> dict[str, Any]:
    tmpdir = Path(tempfile.mkdtemp(prefix="adx-virtual-flow-"))
    db_path = tmpdir / "virtual-flow.db"
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    backend_env = os.environ.copy()
    backend_env.update(
        {
            "ADX_COLLECTOR_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
            "ADX_COLLECTOR_COLLECTOR_EGRESS_CHECK_URL": "inline://203.0.113.10",
        }
    )

    migrate = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        env=backend_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if migrate.returncode != 0:
        raise RuntimeError(f"Migration failed\nSTDOUT:\n{migrate.stdout}\nSTDERR:\n{migrate.stderr}")

    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND_DIR),
        env=backend_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_for_backend(base_url, backend_proc)
        account, instance, task = _create_virtual_entities(base_url)

        collector_env = os.environ.copy()
        collector_env.update(
            {
                "CONTROL_PLANE_BASE_URL": base_url,
                "COLLECTOR_INSTANCE_TOKEN": instance["instance_token"],
            }
        )
        collector_run = subprocess.run(
            [sys.executable, "-m", "app.main"],
            cwd=str(COLLECTOR_DIR),
            env=collector_env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        task_after = requests.get(f"{base_url}/api/v1/operator/tasks", timeout=10).json()["items"][0]
        site_daily = requests.get(
            f"{base_url}/api/v1/operator/reports/site-daily",
            params={"account_id": account["id"], "report_date": "2026-05-21"},
            timeout=10,
        ).json()["items"]
        account_daily = requests.get(
            f"{base_url}/api/v1/operator/reports/account-daily",
            params={"account_id": account["id"], "report_date": "2026-05-21"},
            timeout=10,
        ).json()["items"][0]

        return {
            "collector_exit_code": collector_run.returncode,
            "task_status": task_after["status"],
            "site_rows": len(site_daily),
            "first_url": site_daily[0]["url"] if site_daily else None,
            "responses_served": account_daily["responses_served"],
            "revenue": account_daily["revenue"],
            "base_url": base_url,
            "database_path": str(db_path),
        }
    finally:
        if backend_proc.poll() is None:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                backend_proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    summary = run_virtual_flow()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
