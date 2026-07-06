import ftplib
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import config, db, store
from app.routes import accounts

# display form: GB-XXXXX-XXXXX over the lookalike-free alphabet (no 0/O/1/I/L)
CODE_RE = re.compile(r"^GB-[2-9A-HJKMNP-Z]{5}-[2-9A-HJKMNP-Z]{5}$")

STATE = {"version": 2, "bets": [], "drips": [], "resetAt": None, "carry": 0,
         "onboardingSeen": True}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.bootstrap(path)
    # module-level throttle/retry state must not leak between tests
    accounts._mints.clear()
    store._pending.clear()
    from app.main import app

    with TestClient(app) as c:
        yield c


def _mint(client, state=STATE):
    r = client.post("/api/accounts", json={"state": state})
    assert r.status_code == 201
    return r.json()


def test_mint_and_roundtrip(client):
    body = _mint(client)
    assert CODE_RE.match(body["code"])
    assert body["rev"] == 1
    got = client.get(f"/api/accounts/{body['code']}")
    assert got.status_code == 200
    assert got.json() == {"rev": 1, "state": STATE}


def test_mint_rejects_bad_state(client):
    assert client.post("/api/accounts", json={}).status_code == 422
    assert client.post("/api/accounts", json={"state": []}).status_code == 422
    huge = {"x": "a" * (accounts.MAX_STATE_BYTES + 10)}
    assert client.post("/api/accounts", json={"state": huge}).status_code == 413


def test_unknown_code_404_and_no_upsert(client):
    assert client.get("/api/accounts/GB-22222-22222").status_code == 404
    r = client.put("/api/accounts/GB-22222-22222",
                   json={"rev": 1, "state": STATE})
    assert r.status_code == 404
    # the failed PUT must not have created the row
    assert client.get("/api/accounts/GB-22222-22222").status_code == 404


def test_cas_happy_path(client):
    code = _mint(client)["code"]
    newer = {**STATE, "drips": ["2026-07-05"]}
    r = client.put(f"/api/accounts/{code}", json={"rev": 1, "state": newer})
    assert r.status_code == 200
    assert r.json() == {"rev": 2}
    assert client.get(f"/api/accounts/{code}").json() == {"rev": 2, "state": newer}


def test_cas_conflict_returns_current(client):
    code = _mint(client)["code"]
    current = {**STATE, "drips": ["2026-07-05"]}
    assert client.put(f"/api/accounts/{code}",
                      json={"rev": 1, "state": current}).status_code == 200
    # a second device pushing with the stale rev gets the current row back
    stale = client.put(f"/api/accounts/{code}",
                       json={"rev": 1, "state": STATE})
    assert stale.status_code == 409
    assert stale.json()["detail"] == {"rev": 2, "state": current}
    # and the stored state was not touched
    assert client.get(f"/api/accounts/{code}").json()["state"] == current


def test_code_normalization(client):
    code = _mint(client)["code"]           # 'GB-7Q4KM-XW2AB'
    sloppy = code.replace("-", " ").lower()
    assert client.get(f"/api/accounts/{sloppy}").status_code == 200


def test_mint_rate_limit(client, monkeypatch):
    monkeypatch.setattr(accounts, "MINTS_PER_HOUR", 2)
    _mint(client)
    _mint(client)
    r = client.post("/api/accounts", json={"state": STATE})
    assert r.status_code == 429


# ---- FTP durability (store) ----------------------------------------------------

class FakeFTP:
    def __init__(self, files=None, fail_stor=False):
        self.files = dict(files or {})
        self.fail_stor = fail_stor

    def mkd(self, d):
        raise ftplib.error_perm("550 exists")

    def cwd(self, d):
        pass

    def storbinary(self, cmd, bio):
        if self.fail_stor:
            raise ftplib.error_temp("451 nope")
        self.files[cmd.split(" ", 1)[1]] = bio.read()

    def nlst(self):
        return sorted(self.files)

    def retrbinary(self, cmd, cb):
        cb(self.files[cmd.split(" ", 1)[1]])

    def quit(self):
        pass


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.bootstrap(path)
    store._pending.clear()
    # fake creds so store isn't inert; the FTP itself is faked per-test
    monkeypatch.setattr(store, "HOSTINGER_FTP_HOST", "h")
    monkeypatch.setattr(store, "HOSTINGER_FTP_USER", "u")
    monkeypatch.setattr(store, "HOSTINGER_FTP_PASSWORD", "p")
    return path


def _insert(code, rev, state):
    conn = db.connect()
    conn.execute(
        "INSERT INTO gamba_accounts (code, rev, state, updated_at) VALUES (?,?,?,?)",
        (code, rev, json.dumps(state, separators=(",", ":")), "2026-07-05T00:00:00Z"),
    )
    conn.commit()
    conn.close()


def test_push_uploads_current_rev(seeded, monkeypatch):
    _insert("GBAAAAAAAAAA", 3, STATE)
    ftp = FakeFTP()
    monkeypatch.setattr(store, "ftp_connect", lambda: ftp)
    store._push("GBAAAAAAAAAA")
    blob = json.loads(ftp.files["GBAAAAAAAAAA.json"])
    assert blob["rev"] == 3 and blob["state"] == STATE
    assert store._pending == set()


def test_push_failure_retries_on_next_push(seeded, monkeypatch):
    _insert("GBAAAAAAAAAA", 1, STATE)
    _insert("GBBBBBBBBBBB", 1, STATE)
    monkeypatch.setattr(store, "ftp_connect", lambda: FakeFTP(fail_stor=True))
    store._push("GBAAAAAAAAAA")
    assert store._pending == {"GBAAAAAAAAAA"}
    ok = FakeFTP()
    monkeypatch.setattr(store, "ftp_connect", lambda: ok)
    store._push("GBBBBBBBBBBB")  # later write drains the earlier failure too
    assert set(ok.files) == {"GBAAAAAAAAAA.json", "GBBBBBBBBBBB.json"}
    assert store._pending == set()


def test_restore_fills_missing_without_clobbering(seeded, monkeypatch):
    local_state = {**STATE, "drips": ["2026-07-05"]}
    _insert("GBAAAAAAAAAA", 9, local_state)  # local row is newer than the FTP copy
    files = {
        "GBAAAAAAAAAA.json": json.dumps(
            {"code": "GBAAAAAAAAAA", "rev": 1, "state": STATE,
             "updated_at": "old"}).encode(),
        "GBCCCCCCCCCC.json": json.dumps(
            {"code": "GBCCCCCCCCCC", "rev": 4, "state": STATE,
             "updated_at": "old"}).encode(),
    }
    monkeypatch.setattr(store, "ftp_connect", lambda: FakeFTP(files))
    assert store.restore() == 1  # only the missing account came back
    conn = db.connect()
    rows = {r["code"]: r for r in
            conn.execute("SELECT code, rev, state FROM gamba_accounts")}
    conn.close()
    assert rows["GBAAAAAAAAAA"]["rev"] == 9  # INSERT OR IGNORE kept the local row
    assert json.loads(rows["GBAAAAAAAAAA"]["state"]) == local_state
    assert rows["GBCCCCCCCCCC"]["rev"] == 4
