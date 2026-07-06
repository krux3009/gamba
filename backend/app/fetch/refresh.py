"""Refresh orchestrator: fixtures + scores per competition, meta-gated.

Called from the external cron pinger (/api/internal/refresh) every ~10 min and
from main.py's in-app live loop every 75s while a match is in play. Everything
here must be cheap and idempotent: ESPN has no quota but gets one scoreboard
call per competition per pass at most, and every write is an upsert keyed on
the ESPN event id — the one identifier that survives Render's disk wipes
(client-side bets reference it as matchId).

The odds sweep (The Odds API, credit-budgeted) slots in after the fixture
pass — lands with PR3.
"""
from datetime import datetime, timedelta, timezone

from ..config import COMPETITIONS, ODDS_REFRESH_HOURS
from . import espn, odds_api

FIXTURE_HORIZON_DAYS = 14
FIXTURE_REFRESH_HOURS = 24


def _now():
    return datetime.now(timezone.utc)


def _stamp(conn, key: str):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, _now().isoformat()),
    )
    conn.commit()


def _stale(conn, key: str, hours: float) -> bool:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return True
    then = datetime.fromisoformat(row["value"])
    return _now() - then >= timedelta(hours=hours)


def ingest_scoreboard(conn, slug: str, payload: dict) -> int:
    """Upsert every event in a scoreboard payload. Returns rows touched.

    Upsert-by-ESPN-id makes postponements and reschedules self-heal: the feed
    is the truth for kickoff, names, and status. Scores are written only once
    the match has started — a 'pre' event carries a placeholder '0' that must
    not look like a real 0-0.

    Note for future cup competitions: the scoreboard score after extra time is
    the full ET score, not the 90' score. Fine for leagues (no ET); revisit
    settlement convention before adding UCL knockouts.
    """
    sport = COMPETITIONS.get(slug, {}).get("sport", "soccer")
    n = 0
    for event in payload.get("events", []):
        try:
            # normalize ESPN's "2026-08-15T14:00Z" to full seconds form — every
            # kickoff comparison in the app (BETWEEN windows, btts horizon) is a
            # string compare, so one canonical format keeps them all honest
            kickoff = datetime.fromisoformat(
                event["date"].replace("Z", "+00:00")
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            comp = event["competitions"][0]
            sides = {c["homeAway"]: c for c in comp["competitors"]}
            home, away = sides["home"], sides["away"]
            state = ((comp.get("status") or event.get("status") or {})
                     .get("type") or {}).get("state")
            status = {"pre": "SCHEDULED", "in": "LIVE", "post": "FT"}.get(state)
            if status is None:
                continue
            started = status != "SCHEDULED"
            conn.execute(
                """INSERT INTO events (id, sport, competition, home_name, away_name,
                     home_ext_id, away_ext_id, kickoff_utc, status, home_score, away_score)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     home_name = excluded.home_name,
                     away_name = excluded.away_name,
                     home_ext_id = excluded.home_ext_id,
                     away_ext_id = excluded.away_ext_id,
                     kickoff_utc = excluded.kickoff_utc,
                     status = excluded.status,
                     home_score = COALESCE(excluded.home_score, events.home_score),
                     away_score = COALESCE(excluded.away_score, events.away_score)""",
                (int(event["id"]), sport, slug,
                 home["team"]["displayName"], away["team"]["displayName"],
                 str(home["team"]["id"]), str(away["team"]["id"]),
                 kickoff,
                 status,
                 int(home["score"]) if started and home.get("score") is not None else None,
                 int(away["score"]) if started and away.get("score") is not None else None),
            )
            n += 1
        except (KeyError, IndexError, TypeError, ValueError):
            continue  # one malformed event must not sink the pass
    conn.commit()
    return n


def _needs_scores(conn, slug: str) -> bool:
    """Skip the score call when nothing recent is undecided — during the
    off-season and between matchdays this keeps the loop to zero ESPN calls."""
    return conn.execute(
        """SELECT 1 FROM events
           WHERE competition = ? AND status != 'FT'
             AND datetime(kickoff_utc) <= datetime('now', '+12 hours')
             AND datetime(kickoff_utc) >= datetime('now', '-2 days')
           LIMIT 1""",
        (slug,),
    ).fetchone() is not None


def run(conn) -> dict:
    report = {}
    today = _now().date()
    for slug in COMPETITIONS:
        entry = {}
        # 1. fixture horizon, once per 24h per competition
        if _stale(conn, f"last_fetch:fixtures:{slug}", FIXTURE_REFRESH_HOURS):
            dates = f"{today:%Y%m%d}-{today + timedelta(days=FIXTURE_HORIZON_DAYS):%Y%m%d}"
            payload = espn.scoreboard(conn, slug, dates)
            if payload is not None:
                entry["fixtures"] = ingest_scoreboard(conn, slug, payload)
                _stamp(conn, f"last_fetch:fixtures:{slug}")
        # 2. scores for anything undecided in the recent window
        if _needs_scores(conn, slug):
            dates = f"{today - timedelta(days=1):%Y%m%d}-{today:%Y%m%d}"
            payload = espn.scoreboard(conn, slug, dates)
            if payload is not None:
                entry["scores"] = ingest_scoreboard(conn, slug, payload)
        # 3. stale-day pass: an event still not FT long after kickoff was
        # postponed or abandoned — re-fetch its day so the feed's correction
        # (new date or final score) lands. Bounded to a handful of days.
        stale_days = [r["d"] for r in conn.execute(
            """SELECT DISTINCT date(kickoff_utc) AS d FROM events
               WHERE competition = ? AND status != 'FT'
                 AND datetime(kickoff_utc) < datetime('now', '-6 hours')
               ORDER BY d LIMIT 5""", (slug,))]
        for d in stale_days:
            payload = espn.scoreboard(conn, slug, d.replace("-", ""))
            if payload is not None:
                entry.setdefault("stale", 0)
                entry["stale"] += ingest_scoreboard(conn, slug, payload)
        # 4. odds sweep: meta-gated to 2/day per competition, skipped entirely
        # when nothing is bettable within 8 days (international breaks and the
        # off-season cost zero credits)
        has_upcoming = conn.execute(
            """SELECT 1 FROM events
               WHERE competition = ? AND status = 'SCHEDULED'
                 AND datetime(kickoff_utc) <= datetime('now', '+8 days')
                 AND datetime(kickoff_utc) >= datetime('now')
               LIMIT 1""", (slug,)).fetchone() is not None
        if (odds_api.enabled() and has_upcoming
                and _stale(conn, f"last_fetch:odds:{slug}", ODDS_REFRESH_HOURS)):
            entry["odds"] = odds_api.sweep(
                conn, slug, COMPETITIONS[slug]["odds_key"])
            _stamp(conn, f"last_fetch:odds:{slug}")
        report[slug] = entry
    _stamp(conn, "last_refresh")
    return report


def live_window_open(conn) -> bool:
    """True while a match is in play or kicking off imminently — the signal for
    the in-app fast-refresh loop. A match stays LIVE in our DB until a refresh
    observes the final whistle, so the closing tick still ingests the result."""
    return conn.execute(
        """SELECT 1 FROM events
           WHERE status = 'LIVE'
              OR (status = 'SCHEDULED'
                  AND datetime(kickoff_utc) <= datetime('now', '+5 minutes')
                  AND datetime(kickoff_utc) >= datetime('now', '-30 minutes'))
           LIMIT 1"""
    ).fetchone() is not None
