"""Cross-device sync: an anonymous blob store with compare-and-swap.

The server never interprets an account beyond "JSON object of sane size" —
settlement, merging, and balance math all live client-side
(frontend/src/lib/sync.js). Identity is a bearer sync code whose entropy IS
the security: 10 symbols of a 31-char alphabet ≈ 2^49.6, unguessable at any
rate this instance can serve — the right trust level for Monopoly money.

Protocol and code format are pitchside's gamba store unchanged (only the path
moved, /api/gamba/accounts -> /api/accounts): existing GB- codes keep working,
and the FTP blobs pitchside mirrored restore here verbatim.

POST /api/accounts        {state}      -> 201 {code, rev: 1}
GET  /api/accounts/{code}              -> {rev, state} | 404
PUT  /api/accounts/{code} {rev, state} -> {rev} | 409 {rev, state} | 404
"""
import json
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from .. import db, store

router = APIRouter()

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O/1/I/L lookalikes
CODE_LEN = 10
MAX_STATE_BYTES = 128_000  # ~300 settled bets of headroom; trivial for sqlite/FTP
MAX_ACCOUNTS = 10_000      # bounds DB size and the boot-restore FTP fan-out

# Mint throttle: in-process and wiped on redeploy — a speed bump against
# drive-by scripts, not security (the code entropy is the security).
MINTS_PER_HOUR = 10
_mints: dict[str, list[float]] = {}


def _mint_code() -> str:
    return "GB" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def _display(code: str) -> str:
    """'GB7Q4KMXW2AB' -> 'GB-7Q4KM-XW2AB' for humans; the DB keeps the compact form."""
    return f"{code[:2]}-{code[2:7]}-{code[7:]}"


def _normalize(raw: str) -> str:
    """Forgiving input: dashes, spaces, lowercase all resolve to the compact PK."""
    return "".join(c for c in raw.upper() if c.isalnum())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_ip(request: Request) -> str:
    # Render sits behind a proxy: request.client.host is the proxy, the caller
    # is the first hop in x-forwarded-for.
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "?")


def _throttle_mint(request: Request) -> None:
    now = time.time()
    ip = _client_ip(request)
    fresh = [t for t in _mints.get(ip, []) if now - t < 3600]
    if len(fresh) >= MINTS_PER_HOUR:
        raise HTTPException(429, "mint limit reached — try again later")
    fresh.append(now)
    _mints[ip] = fresh
    if len(_mints) > 1000:  # keep the dict bounded
        for k in [k for k, v in _mints.items() if now - v[-1] >= 3600]:
            del _mints[k]


async def _read_body(request: Request) -> dict:
    """Parse and size-check the JSON body without trusting it.

    Content-Length is checked before parsing so an oversized body is rejected
    without buffering a huge JSON parse; the serialized-state check after it is
    the real gate (Content-Length can lie).
    """
    if int(request.headers.get("content-length") or 0) > MAX_STATE_BYTES + 1024:
        raise HTTPException(413, "state too large")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(422, "body must be JSON")
    if not isinstance(body, dict) or not isinstance(body.get("state"), dict):
        raise HTTPException(422, "missing state object")
    return body


def _state_json(body: dict) -> str:
    state_json = json.dumps(body["state"], ensure_ascii=False, separators=(",", ":"))
    if len(state_json.encode("utf-8")) > MAX_STATE_BYTES:
        raise HTTPException(413, "state too large")
    return state_json


@router.post("/api/accounts", status_code=201)
async def mint(request: Request):
    _throttle_mint(request)
    state_json = _state_json(await _read_body(request))
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM gamba_accounts").fetchone()["n"]
        if n >= MAX_ACCOUNTS:
            raise HTTPException(503, "account store full")
        for _ in range(2):  # collision is ~2^-50 per try; retry once anyway
            code = _mint_code()
            try:
                conn.execute(
                    "INSERT INTO gamba_accounts (code, rev, state, updated_at)"
                    " VALUES (?, 1, ?, ?)",
                    (code, state_json, _now()),
                )
                conn.commit()
                break
            except sqlite3.IntegrityError:
                continue
        else:
            raise HTTPException(500, "could not mint a code")
    finally:
        conn.close()
    store.push_async(code)
    return {"code": _display(code), "rev": 1}


@router.get("/api/accounts/{code}")
def fetch(code: str):
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT rev, state FROM gamba_accounts WHERE code = ?",
            (_normalize(code),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "unknown code")
    return {"rev": row["rev"], "state": json.loads(row["state"])}


@router.put("/api/accounts/{code}")
async def put(code: str, request: Request):
    code = _normalize(code)
    body = await _read_body(request)
    rev = body.get("rev")
    if not isinstance(rev, int):
        raise HTTPException(422, "missing integer rev")
    state_json = _state_json(body)
    conn = db.connect()
    try:
        # compare-and-swap in one atomic statement — no read-modify-write race
        cur = conn.execute(
            "UPDATE gamba_accounts SET rev = rev + 1, state = ?, updated_at = ?"
            " WHERE code = ? AND rev = ?",
            (state_json, _now(), code, rev),
        )
        conn.commit()
        if cur.rowcount != 1:
            row = conn.execute(
                "SELECT rev, state FROM gamba_accounts WHERE code = ?", (code,)
            ).fetchone()
            if row is None:
                # never upsert: a stale device must not be able to fork the
                # account; the client treats this as transient and retries
                raise HTTPException(404, "unknown code")
            raise HTTPException(
                409, detail={"rev": row["rev"], "state": json.loads(row["state"])}
            )
    finally:
        conn.close()
    store.push_async(code)
    return {"rev": rev + 1}
