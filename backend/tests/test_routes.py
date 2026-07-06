import pytest
from fastapi.testclient import TestClient

from app import config, db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    conn = db.bootstrap(path)
    conn.execute(
        """INSERT INTO events (id, sport, competition, home_name, away_name,
             home_ext_id, away_ext_id, kickoff_utc, status, home_score, away_score)
           VALUES (700001, 'soccer', 'eng.1', 'Arsenal', 'Leeds United',
                   '359', '357', '2026-08-15T14:00Z', 'FT', 2, 1)""")
    conn.commit()
    conn.close()
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_events_serves_engine_aliases(client):
    rows = client.get("/api/events").json()
    assert len(rows) == 1
    row = rows[0]
    # the engine settles on these exact names — the aliases ARE the contract
    assert row["id"] == 700001
    assert row["home_goals_90"] == 2 and row["away_goals_90"] == 1
    assert row["home_id"] == "359" and row["away_id"] == "357"
    assert row["status"] == "FT" and row["competition"] == "eng.1"


def test_health_counts(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["db_events"] == 1
    assert h["db_accounts"] == 0


def test_internal_refresh_needs_key(client):
    assert client.get("/api/internal/refresh").status_code == 403
