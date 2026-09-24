"""One-time migration: set default timezone on existing data."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def migrate_control_plane(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    ensure_column(conn, "accounts", "timezone", "timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles'")
    conn.execute("UPDATE accounts SET timezone = 'America/Los_Angeles' WHERE timezone IS NULL OR timezone = ''")
    conn.commit()
    count = conn.total_changes
    conn.close()
    print(f"  control_plane.db: updated {count} accounts")


def migrate_user_system(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    ensure_column(
        conn,
        "managed_accounts",
        "timezone",
        "timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles'",
    )
    conn.execute(
        "UPDATE managed_accounts SET timezone = 'America/Los_Angeles' WHERE timezone IS NULL OR timezone = ''"
    )
    conn.commit()
    count = conn.total_changes
    conn.close()
    print(f"  user_system.db: updated {count} managed_accounts")


def main() -> None:
    base = Path(__file__).resolve().parents[1]
    print("Migrating control plane...")
    migrate_control_plane(str(base / "backend" / "control_plane.db"))
    print("Migrating user system...")
    migrate_user_system(str(base / "user_system" / "backend" / "user_system.db"))
    print("Migration complete.")


if __name__ == "__main__":
    main()
