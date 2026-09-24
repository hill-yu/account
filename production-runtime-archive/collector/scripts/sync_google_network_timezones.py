from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TimezoneFetcher = Callable[[str], str]


def sync_network_timezones(
    db: sqlite3.Connection,
    *,
    account_keys: Sequence[str],
    fetch_timezone: TimezoneFetcher,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for account_key in account_keys:
        row = db.execute(
            """
            select a.id, a.timezone
            from accounts a
            join collector_instances ci on ci.account_id = a.id
            where ci.report_account_key = ?
            """,
            (account_key,),
        ).fetchone()
        if row is None:
            results.append({"account_key": account_key, "status": "failed", "message": "account not found"})
            continue

        try:
            network_timezone = fetch_timezone(account_key).strip()
            _validate_iana_timezone(network_timezone)
        except Exception as exc:
            results.append({"account_key": account_key, "status": "failed", "message": str(exc)})
            continue

        old_timezone = str(row[1])
        db.execute(
            "update accounts set timezone = ?, updated_at = CURRENT_TIMESTAMP where id = ?",
            (network_timezone, int(row[0])),
        )
        results.append(
            {
                "account_key": account_key,
                "status": "updated",
                "old_timezone": old_timezone,
                "network_timezone": network_timezone,
            }
        )
    db.commit()
    return results


def build_local_node_fetcher(*, env_dir: Path, timeout_seconds: int) -> TimezoneFetcher:
    def fetch(account_key: str) -> str:
        env_path = _resolve_node_env_path(env_dir=env_dir, account_key=account_key)
        env = _read_env_file(env_path)
        port = env.get("ADX_VPS_BIND_PORT")
        if port is None or not port.isdigit():
            raise ValueError(f"missing ADX_VPS_BIND_PORT in {env_path.name}")
        query = urlencode({"account_key": account_key})
        with urlopen(
            f"http://127.0.0.1:{port}/internal/network-timezone?{query}",
            timeout=timeout_seconds,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        timezone_name = payload.get("network_timezone")
        if not isinstance(timezone_name, str):
            raise ValueError("node response did not include network_timezone")
        return timezone_name

    return fetch


def _validate_iana_timezone(timezone_name: str) -> None:
    if timezone_name != "UTC" and "/" not in timezone_name:
        raise ValueError(f"Google Network timezone is not an IANA timezone: {timezone_name!r}")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Google Network timezone is not an IANA timezone: {timezone_name!r}") from exc


def _resolve_node_env_path(*, env_dir: Path, account_key: str) -> Path:
    aliases = [account_key]
    if account_key.endswith("-a1"):
        aliases.append(account_key.removesuffix("-a1"))
    for alias in aliases:
        candidate = env_dir / f"adx-fetch-api-{alias}.env"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"node env file not found for account_key={account_key}")


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Google Ad Manager Network timezones into accounts.timezone")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--env-dir", required=True, type=Path)
    parser.add_argument("--account-key", action="append", required=True, dest="account_keys")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    args = parser.parse_args()

    db = sqlite3.connect(args.database)
    try:
        results = sync_network_timezones(
            db,
            account_keys=args.account_keys,
            fetch_timezone=build_local_node_fetcher(
                env_dir=args.env_dir,
                timeout_seconds=args.timeout_seconds,
            ),
        )
    finally:
        db.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
