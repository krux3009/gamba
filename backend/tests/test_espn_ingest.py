import pytest

from app import config, db
from app.fetch import refresh


def _event(eid, date="2026-08-15T14:00Z", state="pre", home="Arsenal", away="Leeds United",
           hid="359", aid="357", hscore=None, ascore=None,
           completed=None, name=None):
    def side(ha, team, tid, score):
        d = {"homeAway": ha, "team": {"displayName": team, "id": tid}}
        if score is not None:
            d["score"] = str(score)
        return d
    stype = {"state": state}
    # mirror the live feed: a finished match carries completed=True; canceled/
    # postponed fixtures are 'post' with completed=False and a status name
    if completed is None and state == "post" and name is None:
        completed = True
    if completed is not None:
        stype["completed"] = completed
    if name is not None:
        stype["name"] = name
    return {
        "id": str(eid),
        "date": date,
        "competitions": [{
            "competitors": [side("home", home, hid, hscore), side("away", away, aid, ascore)],
            "status": {"type": stype},
        }],
    }


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    c = db.bootstrap(path)
    yield c
    c.close()


def _row(conn, eid):
    return conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()


def test_ingest_creates_scheduled_event_without_scores(conn):
    # ESPN pads 'pre' events with score "0" — must not read as a real 0-0
    n = refresh.ingest_scoreboard(conn, "eng.1", {"events": [
        _event(700001, hscore=0, ascore=0)]})
    assert n == 1
    row = _row(conn, 700001)
    assert row["status"] == "SCHEDULED"
    assert row["home_score"] is None and row["away_score"] is None
    assert row["competition"] == "eng.1"
    assert row["home_name"] == "Arsenal" and row["away_ext_id"] == "357"


def test_ingest_ft_sets_scores_and_status(conn):
    refresh.ingest_scoreboard(conn, "eng.1", {"events": [_event(700001)]})
    refresh.ingest_scoreboard(conn, "eng.1", {"events": [
        _event(700001, state="post", hscore=2, ascore=1)]})
    row = _row(conn, 700001)
    assert row["status"] == "FT"
    assert (row["home_score"], row["away_score"]) == (2, 1)


def test_ingest_moved_kickoff_updates_in_place(conn):
    refresh.ingest_scoreboard(conn, "eng.1", {"events": [_event(700001)]})
    refresh.ingest_scoreboard(conn, "eng.1", {"events": [
        _event(700001, date="2026-08-17T19:00Z")]})
    assert conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 1
    assert _row(conn, 700001)["kickoff_utc"] == "2026-08-17T19:00:00Z"


def test_ingest_canceled_never_settles_as_ft(conn):
    # LIVE-VERIFIED shape: canceled fixtures come back state='post',
    # completed=False, name='STATUS_CANCELED', with placeholder '0' scores
    refresh.ingest_scoreboard(conn, "eng.1", {"events": [_event(700001)]})
    refresh.ingest_scoreboard(conn, "eng.1", {"events": [
        _event(700001, state="post", completed=False, name="STATUS_CANCELED",
               hscore=0, ascore=0)]})
    row = _row(conn, 700001)
    assert row["status"] == "CANCELED"
    assert row["home_score"] is None and row["away_score"] is None


def test_ingest_postponed_stays_scheduled(conn):
    refresh.ingest_scoreboard(conn, "eng.1", {"events": [
        _event(700001, state="post", completed=False, name="STATUS_POSTPONED",
               hscore=0, ascore=0)]})
    row = _row(conn, 700001)
    assert row["status"] == "SCHEDULED"  # the feed re-dates it later
    assert row["home_score"] is None


def test_ingest_malformed_event_skipped(conn):
    n = refresh.ingest_scoreboard(conn, "eng.1", {"events": [
        {"id": "junk"},                       # no competitions
        _event(700002),
    ]})
    assert n == 1
    assert _row(conn, 700002) is not None


def test_run_fixture_gate_and_report(conn, monkeypatch):
    calls = []

    def fake_scoreboard(c, slug, dates):
        calls.append((slug, dates))
        return {"events": [_event(700000 + len(calls))]}

    monkeypatch.setattr(refresh.espn, "scoreboard", fake_scoreboard)
    report = refresh.run(conn)
    assert set(report) == set(config.COMPETITIONS)
    # two date-range calls per competition: the one-per-boot score backfill
    # plus the 24h fixture horizon
    range_calls = [c for c in calls if "-" in c[1] and len(c[1]) == 17]
    assert len(range_calls) == 2 * len(config.COMPETITIONS)
    # second run inside the 24h gate: no new fixture calls (scores gated off —
    # the seeded kickoffs are outside the recent window)
    calls.clear()
    refresh.run(conn)
    assert all("-" not in d or len(d) != 17 for _, d in calls) or calls == []


def test_live_window_open(conn):
    assert refresh.live_window_open(conn) is False
    conn.execute(
        "INSERT INTO events (id, competition, kickoff_utc, status)"
        " VALUES (1, 'eng.1', '2026-08-15T14:00Z', 'LIVE')")
    conn.commit()
    assert refresh.live_window_open(conn) is True
