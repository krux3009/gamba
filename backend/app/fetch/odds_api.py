"""The Odds API — real bookmaker odds. Free tier: 500 credits/mo, shared with
pitchside (whose WC sweeps self-stop after the final).

    /sports/{sport}/events            FREE     fixture list (id, teams, kickoff)
    /sports/{sport}/odds              2 cr     bulk h2h+totals, all events, eu region
    /sports/{sport}/events/{id}/odds  1 cr     per-event btts (bulk endpoint can't)

Budget model (config.py): 2 sweeps/day x 2 competitions x 2 cr bulk = 240/mo,
plus btts ONCE PER EVENT EVER (~76/mo at league volume) ~= 316 of ~450 usable.
The once-ever guard is the big departure from pitchside, which re-fetched btts
every sweep — fine for 104 WC matches, ruinous for two league seasons.

Mirrors espn.py conventions: httpx, fetch_log rows, None on failure. Inert
without ODDS_API_KEY. Every response's x-requests-remaining header lands in
meta('odds_api:remaining') and sweep() refuses to spend below
ODDS_API_CREDIT_FLOOR, the hard monthly backstop.
"""
import json
import statistics
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import httpx

from .. import db, store
from ..config import ODDS_API_CREDIT_FLOOR, ODDS_API_KEY, ODDS_BTTS_WINDOW_HOURS

BASE = "https://api.the-odds-api.com/v4"
REGIONS = "eu"  # 1x credit multiplier
TIMEOUT = 25.0
KICKOFF_TOLERANCE_H = 3  # provider commence_time vs our kickoff_utc

# Provider names that don't normalize onto ESPN's displayName. Grown from
# fetch_log's unmatched reports — the token-subset fallback below catches most
# short forms ("Betis" ⊂ "Real Betis"), so only genuine renames belong here.
ALIASES = {
    "man united": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "nottm forest": "nottingham forest",
}


def enabled() -> bool:
    return bool(ODDS_API_KEY)


def _log(conn, endpoint: str, params: str, status: int):
    conn.execute(
        "INSERT INTO fetch_log (fetched_at, source, endpoint, params, status)"
        " VALUES (?,?,?,?,?)",
        (db.utc_now_z(), "odds_api", endpoint, params, status),
    )
    conn.commit()


def _get(conn, path: str, label: str, params: dict | None = None) -> list | dict | None:
    try:
        r = httpx.get(f"{BASE}/{path}",
                      params={"apiKey": ODDS_API_KEY, **(params or {})},
                      timeout=TIMEOUT)
        _log(conn, path, label, r.status_code)
        remaining = r.headers.get("x-requests-remaining")
        if remaining is not None:
            db.meta_set(conn, "odds_api:remaining", remaining)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError):
        # ValueError covers a 200 with a non-JSON body — same "try next sweep"
        return None


def remaining_credits(conn) -> float | None:
    try:
        return float(db.meta_get(conn, "odds_api:remaining"))
    except (TypeError, ValueError):
        return None


def _norm(name: str) -> str:
    """lowercase, strip accents, drop punctuation and noise words so
    'Atlético Madrid', 'Brighton & Hove Albion' etc. line up across providers.
    Punctuation becomes a token break (not deletion)."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    tokens = [t for t in
              "".join(c if (c.isascii() and c.isalnum()) else " "
                      for c in s.lower()).split()
              if t not in ("and", "fc", "cf")]
    key = " ".join(tokens)
    return ALIASES.get(key, key)


def _tokens(name: str) -> frozenset:
    return frozenset(_norm(name).split())


def match_fixture(conn, competition: str, event: dict) -> tuple[int, int] | None:
    """(event_id, swapped) for one provider event, or None. Candidate = an
    upcoming fixture in this competition with kickoff within tolerance; names
    then match exactly in either orientation, else by unique token-subset
    ("Man United" ⊆ "Manchester United") — club short forms vary by book."""
    try:
        commence = datetime.fromisoformat(event["commence_time"])
    except (KeyError, ValueError):
        return None
    lo = (commence - timedelta(hours=KICKOFF_TOLERANCE_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (commence + timedelta(hours=KICKOFF_TOLERANCE_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidates = conn.execute(
        """SELECT id, home_name, away_name FROM events
           WHERE competition = ? AND status = 'SCHEDULED'
             AND kickoff_utc BETWEEN ? AND ?""",
        (competition, lo, hi),
    ).fetchall()
    ev_home, ev_away = _norm(event.get("home_team", "")), _norm(event.get("away_team", ""))
    for c in candidates:
        ours = (_norm(c["home_name"]), _norm(c["away_name"]))
        if (ev_home, ev_away) == ours:
            return c["id"], 0
        if (ev_away, ev_home) == ours:
            return c["id"], 1

    # subset fallback: one name's token set contains the other's, both sides,
    # in one orientation, for exactly one candidate — else refuse (ambiguous
    # beats wrong: an unmatched event just means no odds shown).
    def sub(a: frozenset, b: frozenset) -> bool:
        return bool(a) and bool(b) and (a <= b or b <= a)

    eh, ea = _tokens(event.get("home_team", "")), _tokens(event.get("away_team", ""))
    hits = []
    for c in candidates:
        ch, ca = _tokens(c["home_name"]), _tokens(c["away_name"])
        if sub(eh, ch) and sub(ea, ca):
            hits.append((c["id"], 0))
        elif sub(eh, ca) and sub(ea, ch):
            hits.append((c["id"], 1))
    return hits[0] if len(hits) == 1 else None


def _consensus(bookmakers: list) -> dict:
    """{(market, outcome_name, line): {median, best, book, n}} across books."""
    prices = {}  # key -> [(price, book_title)]
    for book in bookmakers or []:
        title = book.get("title") or book.get("key", "?")
        for market in book.get("markets", []):
            for o in market.get("outcomes", []):
                if o.get("price") is None:
                    continue
                line = float(o.get("point") or 0)
                key = (market["key"], o["name"], line)
                prices.setdefault(key, []).append((float(o["price"]), title))
    out = {}
    for key, quotes in prices.items():
        best_price, best_book = max(quotes)
        out[key] = {
            "median": round(statistics.median(p for p, _ in quotes), 3),
            "best": best_price, "book": best_book, "n": len(quotes),
        }
    return out


def _selection(market: str, outcome_name: str, event: dict, swapped: int) -> str | None:
    if market == "h2h":
        if outcome_name == "Draw":
            return "draw"
        if outcome_name == event.get("home_team"):
            return "away" if swapped else "home"
        if outcome_name == event.get("away_team"):
            return "home" if swapped else "away"
        return None
    if market == "totals":
        return {"Over": "over", "Under": "under"}.get(outcome_name)
    if market == "btts":
        return {"Yes": "yes", "No": "no"}.get(outcome_name)
    return None


def _ingest(conn, event_id: int, event: dict, swapped: int,
            bookmakers: list, markets: tuple) -> int:
    """Replace event_id's rows for the given markets with fresh consensus rows.
    An EMPTY fresh set still clears the market: when the books pull their
    quotes (team news), day-old prices must stop being served as bettable.
    Totals keeps half-lines only — quarter/whole lines would need push/half-win
    settlement the fake-credit engine deliberately doesn't model."""
    rows = []
    fetched_at = db.utc_now_z()
    for (market, name, line), agg in _consensus(bookmakers).items():
        if market not in markets:
            continue
        if market == "totals" and (line * 2) % 2 != 1:
            continue
        sel = _selection(market, name, event, swapped)
        if sel is None:
            continue
        rows.append((event_id, market, sel, line if market == "totals" else 0,
                     agg["median"], agg["best"], agg["book"], agg["n"], fetched_at))
    conn.executemany(
        "DELETE FROM market_odds WHERE event_id=? AND market=?",
        [(event_id, mk) for mk in markets],
    )
    if rows:
        conn.executemany(
            """INSERT OR REPLACE INTO market_odds
               (event_id, market, selection, line, price_median, price_best,
                book_best, n_books, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    conn.commit()
    return len(rows)


def _has_btts(conn, event_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM market_odds WHERE event_id=? AND market='btts' LIMIT 1",
        (event_id,),
    ).fetchone() is not None


# The "once per event ever" btts guard must survive Render's disk wipe, or
# every deploy inside the 48h window re-buys the whole matchweek (and events
# no book quotes re-buy every sweep — a credit is spent even when the response
# carries no btts prices). Ledger = event ids in meta, mirrored to the FTP
# store the accounts already use. Ids are ints (~760/season): never pruned.

def _btts_attempted(conn) -> set[int]:
    raw = db.meta_get(conn, "btts:attempted")
    if raw is None:  # cold boot — pull the mirror before spending anything
        ids = store.load_meta_blob("btts_attempted") or []
        db.meta_set(conn, "btts:attempted", json.dumps(ids))
        return set(ids)
    return set(json.loads(raw))


def _mark_btts_attempted(conn, attempted: set[int]) -> None:
    ids = sorted(attempted)
    db.meta_set(conn, "btts:attempted", json.dumps(ids))
    store.save_meta_blob("btts_attempted", ids)


def sweep(conn, competition: str, sport_key: str) -> dict:
    """One odds pass for one competition: free event list -> fixture matching
    -> bulk h2h+totals (2 cr) -> per-event btts near kickoff (1 cr each, once
    per event ever)."""
    if not enabled():
        return {"skipped": "no api key"}
    remaining = remaining_credits(conn)
    if remaining is not None and remaining < ODDS_API_CREDIT_FLOOR:
        return {"skipped": "credit floor", "remaining": remaining}

    report = {"matched": 0, "bulk": 0, "btts_events": 0, "unmatched": []}

    events = _get(conn, f"sports/{sport_key}/events", f"events:{competition}")
    if events is None:
        return {**report, "error": "events fetch failed"}

    mapping = {}  # provider event id -> (our event id, swapped, provider event)
    for ev in events:
        found = match_fixture(conn, competition, ev)
        if not found:
            report["unmatched"].append(
                f"{ev.get('home_team')} v {ev.get('away_team')}")
            continue
        mapping[ev["id"]] = (*found, ev)
    report["matched"] = len(mapping)
    if not mapping:
        return {**report, "remaining": remaining_credits(conn)}

    bulk = _get(conn, f"sports/{sport_key}/odds", f"bulk:{competition}",
                {"regions": REGIONS, "markets": "h2h,totals",
                 "oddsFormat": "decimal"})
    if bulk is not None:
        seen = set()
        for ev in bulk:
            hit = mapping.get(ev.get("id"))
            if hit:
                seen.add(ev["id"])
                event_id, swapped, _ = hit
                report["bulk"] += _ingest(conn, event_id, ev, swapped,
                                          ev.get("bookmakers", []),
                                          ("h2h", "totals"))
        # a matched event the books dropped from the odds feed entirely:
        # clear its stale quotes too — same rule as an empty bookmaker list
        for pid, (event_id, swapped, ev) in mapping.items():
            if pid not in seen:
                _ingest(conn, event_id, ev, swapped, [], ("h2h", "totals"))

    # btts: per-event endpoint only. Spend a credit just once per event EVER
    # (durable ledger), only near kickoff; re-check the floor as the loop spends.
    horizon = (datetime.now(timezone.utc)
               + timedelta(hours=ODDS_BTTS_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    attempted = _btts_attempted(conn)
    dirty = False
    for pid, (event_id, swapped, ev) in mapping.items():
        row = conn.execute(
            "SELECT kickoff_utc FROM events WHERE id=?", (event_id,)).fetchone()
        if not row or not (db.utc_now_z() < row["kickoff_utc"] <= horizon):
            continue
        if event_id in attempted or _has_btts(conn, event_id):
            continue  # once per event ever — the budget depends on this
        left = remaining_credits(conn)
        if left is not None and left < ODDS_API_CREDIT_FLOOR:
            report["halted"] = "credit floor"
            break
        payload = _get(conn, f"sports/{sport_key}/events/{pid}/odds",
                       f"btts:{event_id}",
                       {"regions": REGIONS, "markets": "btts",
                        "oddsFormat": "decimal"})
        if payload is not None:
            # the credit is spent even when no book quotes btts — mark the
            # ATTEMPT, or unquoted events re-buy every sweep for 48 hours
            attempted.add(event_id)
            dirty = True
            report["btts_events"] += bool(
                _ingest(conn, event_id, ev, swapped,
                        payload.get("bookmakers", []), ("btts",)))
        time.sleep(1.0)
    if dirty:
        _mark_btts_attempted(conn, attempted)

    report["remaining"] = remaining_credits(conn)
    if not report["unmatched"]:
        report.pop("unmatched")
    return report
