"""ESPN public JSON API — no key, no quota. The only score/fixture source.

One endpoint is all gamba needs:

    .../sports/soccer/{league_slug}/scoreboard?dates=YYYYMMDD[-YYYYMMDD]

The date-range form returns every fixture in the window — that's how a
competition's schedule is bootstrapped (there is no seed database; Render's
disk starts empty on every deploy).
"""
import logging

import httpx

from . import log_fetch

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
TIMEOUT = 25.0

log = logging.getLogger(__name__)


def scoreboard(conn, slug: str, dates: str) -> dict | None:
    """Fixtures + live scores for one league. dates: 'YYYYMMDD' or a range
    'YYYYMMDD-YYYYMMDD'. Returns the payload, or None on any HTTP or parse
    failure — callers treat a miss as 'try again next tick'."""
    try:
        r = httpx.get(f"{BASE}/{slug}/scoreboard",
                      params={"dates": dates, "limit": 400}, timeout=TIMEOUT)
        log_fetch(conn, "espn", f"{slug}/scoreboard", dates, r.status_code)
        r.raise_for_status()
        return r.json()
    except ValueError:
        # a 200 with a non-JSON body (maintenance page). Without this catch it
        # would propagate through run()'s loop and abort every remaining
        # competition's pass.
        log.warning("espn %s returned non-JSON for %s", slug, dates)
        return None
    except httpx.HTTPError:
        return None
