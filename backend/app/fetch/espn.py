"""ESPN public JSON API — no key, no quota. The only score/fixture source.

One endpoint is all gamba needs:

    .../sports/soccer/{league_slug}/scoreboard?dates=YYYYMMDD[-YYYYMMDD]

The date-range form returns every fixture in the window — that's how a
competition's schedule is bootstrapped (there is no seed database; Render's
disk starts empty on every deploy).
"""
from datetime import datetime, timezone

import httpx

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
TIMEOUT = 25.0


def _log(conn, endpoint: str, params: str, status: int):
    conn.execute(
        "INSERT INTO fetch_log (fetched_at, source, endpoint, params, status)"
        " VALUES (?,?,?,?,?)",
        (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "espn", endpoint, params, status),
    )
    conn.commit()


def scoreboard(conn, slug: str, dates: str) -> dict | None:
    """Fixtures + live scores for one league. dates: 'YYYYMMDD' or a range
    'YYYYMMDD-YYYYMMDD'. Returns the payload, or None on any HTTP failure —
    callers treat a miss as 'try again next tick'."""
    try:
        r = httpx.get(f"{BASE}/{slug}/scoreboard",
                      params={"dates": dates, "limit": 400}, timeout=TIMEOUT)
        _log(conn, f"{slug}/scoreboard", dates, r.status_code)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None
