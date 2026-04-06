from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MigrationResult:
    db_path: Path
    applied_migrations: list[str]
    user_version: int


def available_migrations() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def initialize_database(db_path: Path) -> MigrationResult:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          migration_name TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )

    applied_names = {
        row[0]
        for row in connection.execute("SELECT migration_name FROM schema_migrations ORDER BY migration_name")
    }

    applied_migrations: list[str] = []
    with connection:
        for migration_path in available_migrations():
            if migration_path.name in applied_names:
                continue
            connection.executescript(migration_path.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (migration_name, applied_at) VALUES (?, ?)",
                (migration_path.name, now_utc_iso()),
            )
            applied_migrations.append(migration_path.name)

    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    connection.close()
    return MigrationResult(
        db_path=db_path,
        applied_migrations=applied_migrations,
        user_version=user_version,
    )
