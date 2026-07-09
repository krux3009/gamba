"""SQLite helpers. The database is a rebuildable cache except gamba_accounts."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import BASE_DIR, DB_PATH


def utc_now_z() -> str:
    """Canonical timestamp: second precision, literal Z suffix. Kickoff windows
    and cache stamps are string compares, so every writer must use this format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def meta_get(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    # default resolved at call time so tests can repoint DB_PATH
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA foreign_keys = ON")
    # the boot catch-up thread and a cron refresh can overlap briefly; wait for
    # the writer instead of raising "database is locked"
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def bootstrap(db_path: Path | None = None) -> sqlite3.Connection:
    """Apply the schema. No seed database — all state is fetch-on-boot."""
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    # WAL persists in the db file: refresh-thread commits stop blocking readers
    # (clients polling /api/events mid-ingest saw 5s busy-waits under the
    # default rollback journal)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript((BASE_DIR / "schema.sql").read_text())
    conn.commit()
    return conn
