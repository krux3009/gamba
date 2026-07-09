"""Betting-market document: real bookmaker consensus for every not-yet-
finished event.

Settlement deliberately does NOT use this endpoint — the frontend settles bets
against /api/events scores — so this document can lag or vanish without
corrupting anyone's (fake) balance.
"""
from datetime import datetime, timezone

from fastapi import APIRouter

from .. import db

router = APIRouter()

LIST_SQL = """
  SELECT id, sport, competition, home_name, away_name,
         home_ext_id AS home_id, away_ext_id AS away_id,
         kickoff_utc, status
    FROM events
   WHERE status NOT IN ('FT', 'CANCELED')
   ORDER BY kickoff_utc, id
"""


def _row(r: dict) -> dict:
    return {"median": r["price_median"], "best": r["price_best"],
            "book": r["book_best"], "n": r["n_books"]}


def _real_book(rows: list[dict]) -> dict | None:
    """Group an event's market_odds rows into {h2h, totals[], btts}. Every
    market is optional — The Odds API doesn't guarantee totals/btts per event."""
    if not rows:
        return None
    out = {"fetched_at": max(r["fetched_at"] or "" for r in rows) or None,
           "h2h": None, "totals": [], "btts": None}
    by_line = {}
    for r in rows:
        if r["market"] == "h2h":
            out["h2h"] = out["h2h"] or {}
            out["h2h"][r["selection"]] = _row(r)
        elif r["market"] == "btts":
            out["btts"] = out["btts"] or {}
            out["btts"][r["selection"]] = _row(r)
        elif r["market"] == "totals":
            by_line.setdefault(r["line"], {})[r["selection"]] = _row(r)
    out["totals"] = [{"line": line, **sels} for line, sels in sorted(by_line.items())]
    return out


@router.get("/api/odds")
def list_odds():
    conn = db.connect()
    try:
        rows = conn.execute(LIST_SQL).fetchall()
        odds_rows = conn.execute("SELECT * FROM market_odds").fetchall()
    finally:
        conn.close()

    real_by_event = {}
    for r in odds_rows:
        real_by_event.setdefault(r["event_id"], []).append(r)

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "matches": [
            {**m, "real": _real_book(real_by_event.get(m["id"], []))}
            for m in rows
        ],
    }
