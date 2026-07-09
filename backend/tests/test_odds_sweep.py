from datetime import datetime, timedelta, timezone

import pytest

from app import config, db
from app.fetch import odds_api


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


KICKOFF = datetime.now(timezone.utc) + timedelta(hours=24)  # inside btts window


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(odds_api, "ODDS_API_KEY", "test-key")
    monkeypatch.setattr(odds_api.time, "sleep", lambda s: None)
    c = db.bootstrap(path)
    c.execute(
        """INSERT INTO events (id, competition, home_name, away_name, kickoff_utc, status)
           VALUES (700001, 'eng.1', 'Manchester United', 'Arsenal', ?, 'SCHEDULED'),
                  (700002, 'eng.1', 'Real Betis', 'Valencia', ?, 'SCHEDULED'),
                  (700003, 'esp.1', 'Real Betis', 'Valencia', ?, 'SCHEDULED')""",
        (_iso(KICKOFF), _iso(KICKOFF), _iso(KICKOFF)))
    c.commit()
    yield c
    c.close()


def _provider_event(pid, home, away, commence=None):
    return {"id": pid, "home_team": home, "away_team": away,
            "commence_time": _iso(commence or KICKOFF)}


def _book(market, outcomes):
    return {"title": "TestBook", "markets": [{"key": market, "outcomes": outcomes}]}


# ---- name matching --------------------------------------------------------------

def test_match_exact_and_swapped(conn):
    ev = _provider_event("x", "Manchester United", "Arsenal")
    assert odds_api.match_fixture(conn, "eng.1", ev) == (700001, 0)
    ev = _provider_event("x", "Arsenal", "Manchester United")
    assert odds_api.match_fixture(conn, "eng.1", ev) == (700001, 1)


def test_match_alias_and_token_subset(conn):
    # alias map: "Man United" -> manchester united
    ev = _provider_event("x", "Man United", "Arsenal")
    assert odds_api.match_fixture(conn, "eng.1", ev) == (700001, 0)
    # subset: "Betis" ⊆ "Real Betis" — unique in window, matches
    ev = _provider_event("x", "Betis", "Valencia")
    assert odds_api.match_fixture(conn, "eng.1", ev) == (700002, 0)


def test_match_respects_competition_boundary(conn):
    # same fixture name exists in esp.1 — the eng.1 sweep must not claim it
    ev = _provider_event("x", "Betis", "Valencia")
    assert odds_api.match_fixture(conn, "esp.1", ev) == (700003, 0)


def test_match_ambiguous_subset_refuses(conn):
    conn.execute(
        """INSERT INTO events (id, competition, home_name, away_name, kickoff_utc, status)
           VALUES (700004, 'eng.1', 'Real Betis B', 'Valencia', ?, 'SCHEDULED')""",
        (_iso(KICKOFF),))
    conn.commit()
    ev = _provider_event("x", "Betis", "Valencia")  # ⊆ both 700002 and 700004
    assert odds_api.match_fixture(conn, "eng.1", ev) is None


# ---- sweep ----------------------------------------------------------------------

def _fake_get(responses):
    """responses: {path-suffix: payload}. Falls through to None. Suffix (not
    substring) matching: '…/events/prov1/odds' must not hit the '…/events'
    fixture-list entry."""
    calls = []

    def fake(conn, path, label, params=None):
        calls.append(path)
        for frag, payload in responses.items():
            if path.endswith(frag):
                return payload
        return None

    fake.calls = calls
    return fake


def test_sweep_bulk_and_btts_once_ever(conn, monkeypatch):
    ev = _provider_event("prov1", "Manchester United", "Arsenal")
    responses = {
        "/events/prov1/odds": {**ev, "bookmakers": [_book("btts", [
            {"name": "Yes", "price": 1.9}, {"name": "No", "price": 1.9}])]},
        "sports/soccer_epl/events": [ev],
        "sports/soccer_epl/odds": [{**ev, "bookmakers": [_book("h2h", [
            {"name": "Manchester United", "price": 2.1},
            {"name": "Draw", "price": 3.4},
            {"name": "Arsenal", "price": 3.5}])]}],
    }
    fake = _fake_get(responses)
    monkeypatch.setattr(odds_api, "_get", fake)

    report = odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert report["matched"] == 1
    assert report["bulk"] == 3          # home/draw/away rows
    assert report["btts_events"] == 1
    sels = {(r["market"], r["selection"]) for r in
            conn.execute("SELECT market, selection FROM market_odds WHERE event_id=700001")}
    assert ("h2h", "home") in sels and ("btts", "yes") in sels

    # second sweep: btts already stored -> no per-event call spent
    fake.calls.clear()
    report2 = odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert report2["btts_events"] == 0
    assert not any("/events/prov1/odds" in p for p in fake.calls)


def test_sweep_unmatched_reported(conn, monkeypatch):
    ev = _provider_event("prov9", "Narnia FC", "Mordor United")
    monkeypatch.setattr(odds_api, "_get", _fake_get({
        "sports/soccer_epl/events": [ev]}))
    report = odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert report["matched"] == 0
    assert report["unmatched"] == ["Narnia FC v Mordor United"]


def test_sweep_credit_floor_blocks_all(conn, monkeypatch):
    conn.execute("INSERT OR REPLACE INTO meta (key, value)"
                 " VALUES ('odds_api:remaining', '10')")
    conn.commit()
    monkeypatch.setattr(odds_api, "_get", _fake_get({}))
    report = odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert report == {"skipped": "credit floor", "remaining": 10.0}


def test_sweep_credit_floor_halts_btts_midway(conn, monkeypatch):
    ev1 = _provider_event("p1", "Manchester United", "Arsenal")
    ev2 = _provider_event("p2", "Real Betis", "Valencia")

    def fake(c, path, label, params=None):
        if path.endswith("/events"):
            return [ev1, ev2]
        if path.endswith("sports/soccer_epl/odds"):
            return []
        # first per-event btts call succeeds but drops credits under the floor
        c.execute("INSERT OR REPLACE INTO meta (key, value)"
                  " VALUES ('odds_api:remaining', '5')")
        c.commit()
        return {"bookmakers": [_book("btts", [
            {"name": "Yes", "price": 1.9}, {"name": "No", "price": 1.9}])]}

    monkeypatch.setattr(odds_api, "_get", fake)
    report = odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert report["btts_events"] == 1
    assert report["halted"] == "credit floor"


def test_btts_marked_on_attempt_even_when_unquoted(conn, monkeypatch):
    # the credit is spent on the HTTP call; a response with no btts quotes
    # must still count as "bought" or the event re-buys every sweep for 48h
    ev = _provider_event("prov1", "Manchester United", "Arsenal")
    responses = {
        "sports/soccer_epl/events": [ev],
        "sports/soccer_epl/odds": [],
        "/events/prov1/odds": {**ev, "bookmakers": []},  # nobody quotes btts
    }
    fake = _fake_get(responses)
    monkeypatch.setattr(odds_api, "_get", fake)
    report = odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert report["btts_events"] == 0

    fake.calls.clear()
    odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert not any("/events/prov1/odds" in p for p in fake.calls)


def test_btts_ledger_restores_from_ftp_mirror(conn, monkeypatch):
    # cold boot: meta is wiped with the disk; the FTP mirror must stop a re-buy
    monkeypatch.setattr(odds_api.store, "load_meta_blob",
                        lambda name: [700001])
    ev = _provider_event("prov1", "Manchester United", "Arsenal")
    fake = _fake_get({"sports/soccer_epl/events": [ev],
                      "sports/soccer_epl/odds": []})
    monkeypatch.setattr(odds_api, "_get", fake)
    report = odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert report["btts_events"] == 0
    assert not any("/odds" in p and "events/" in p.rsplit("sports/", 1)[-1]
                   for p in fake.calls if p.endswith("prov1/odds"))


def test_pulled_quotes_clear_stale_rows(conn, monkeypatch):
    ev = _provider_event("prov1", "Manchester United", "Arsenal")
    with_odds = {
        "sports/soccer_epl/events": [ev],
        "sports/soccer_epl/odds": [{**ev, "bookmakers": [_book("h2h", [
            {"name": "Manchester United", "price": 2.1},
            {"name": "Draw", "price": 3.4},
            {"name": "Arsenal", "price": 3.5}])]}],
    }
    monkeypatch.setattr(odds_api, "_get", _fake_get(with_odds))
    odds_api.sweep(conn, "eng.1", "soccer_epl")
    n = conn.execute("SELECT COUNT(*) AS n FROM market_odds").fetchone()["n"]
    assert n == 3

    # books pull every quote (team news): the event comes back with no
    # bookmakers — yesterday's prices must not stay bettable
    pulled = {**with_odds,
              "sports/soccer_epl/odds": [{**ev, "bookmakers": []}]}
    monkeypatch.setattr(odds_api, "_get", _fake_get(pulled))
    odds_api.sweep(conn, "eng.1", "soccer_epl")
    n = conn.execute("SELECT COUNT(*) AS n FROM market_odds").fetchone()["n"]
    assert n == 0


def test_event_absent_from_bulk_clears_stale_rows(conn, monkeypatch):
    ev = _provider_event("prov1", "Manchester United", "Arsenal")
    conn.execute(
        """INSERT INTO market_odds (event_id, market, selection, line,
             price_median, price_best, book_best, n_books, fetched_at)
           VALUES (700001, 'h2h', 'home', 0, 2.0, 2.1, 'OldBook', 3,
                   '2026-07-01T00:00:00Z')""")
    conn.commit()
    # bulk succeeds but the event vanished from the odds feed entirely
    monkeypatch.setattr(odds_api, "_get", _fake_get({
        "sports/soccer_epl/events": [ev],
        "sports/soccer_epl/odds": []}))
    odds_api.sweep(conn, "eng.1", "soccer_epl")
    assert conn.execute("SELECT COUNT(*) AS n FROM market_odds"
                        ).fetchone()["n"] == 0


def test_totals_half_lines_only(conn, monkeypatch):
    ev = _provider_event("prov1", "Manchester United", "Arsenal")
    monkeypatch.setattr(odds_api, "_get", _fake_get({
        "sports/soccer_epl/events": [ev],
        "sports/soccer_epl/odds": [{**ev, "bookmakers": [_book("totals", [
            {"name": "Over", "price": 1.9, "point": 2.5},
            {"name": "Under", "price": 1.9, "point": 2.5},
            {"name": "Over", "price": 1.8, "point": 2.0},   # whole line: dropped
            {"name": "Under", "price": 2.0, "point": 2.0},
        ])]}]}))
    odds_api.sweep(conn, "eng.1", "soccer_epl")
    lines = [r["line"] for r in conn.execute(
        "SELECT DISTINCT line FROM market_odds WHERE market='totals'")]
    assert lines == [2.5]
