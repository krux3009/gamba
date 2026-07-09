"""Betting-market document: real bookmaker consensus for every not-yet-
finished event.

Settlement deliberately does NOT use this endpoint — the frontend settles bets
against /api/events scores — so this document can lag or vanish without
corrupting anyone's (fake) balance.
"""
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

# only rows for still-listed events: FT rows are never pruned, so a bare
# SELECT * would grow all season and rebuild thousands of dead rows per poll
ODDS_SQL = """
  SELECT market_odds.* FROM market_odds
  JOIN events ON events.id = market_odds.event_id
 WHERE events.status NOT IN ('FT', 'CANCELED')
"""

# The document only changes when a refresh cycle writes, but every open tab
# polls it each 60s — cache the built doc keyed on the last_refresh stamp.
# generated_at IS that stamp, so identical content stays byte-identical and
# the client can skip re-renders with a plain string compare.
_cache = {"stamp": None, "doc": None}


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
        stamp = db.meta_get(conn, "last_refresh")
        if stamp is not None and stamp == _cache["stamp"]:
            return _cache["doc"]
        rows = conn.execute(LIST_SQL).fetchall()
        odds_rows = conn.execute(ODDS_SQL).fetchall()
    finally:
        conn.close()

    real_by_event = {}
    for r in odds_rows:
        real_by_event.setdefault(r["event_id"], []).append(r)

    doc = {
        "generated_at": stamp or db.utc_now_z(),
        "matches": [
            {**m, "real": _real_book(real_by_event.get(m["id"], []))}
            for m in rows
        ],
    }
    if stamp is not None:  # pre-first-refresh docs are never cached
        _cache.update(stamp=stamp, doc=doc)
    return doc
