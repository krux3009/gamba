"""Fetch sources (ESPN, The Odds API) + the refresh orchestrator."""
from .. import db


def log_fetch(conn, source: str, endpoint: str, params: str, status: int) -> None:
    """Budget ledger: one fetch_log row per external HTTP request."""
    conn.execute(
        "INSERT INTO fetch_log (fetched_at, source, endpoint, params, status)"
        " VALUES (?,?,?,?,?)",
        (db.utc_now_z(), source, endpoint, params, status),
    )
    conn.commit()
