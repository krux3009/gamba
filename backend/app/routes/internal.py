"""Privileged operational endpoints, key-gated."""
import hmac
import threading

from fastapi import APIRouter, HTTPException, Query

from .. import db, store
from ..config import COMPETITIONS, REFRESH_KEY
from ..fetch import odds_api
from ..fetch import refresh as refresh_orchestrator

router = APIRouter()

# one refresh cycle at a time. The external cron pinger fires every ~10 min and
# the in-app live loop every 75s mid-match; a slow ESPN pass must collapse
# overlapping ticks instead of stacking them.
_cycle_lock = threading.Lock()


def refresh_locked() -> dict | None:
    """Run one refresh cycle unless one is already running (then skip)."""
    if not _cycle_lock.acquire(blocking=False):
        return None
    try:
        conn = db.connect()
        try:
            return refresh_orchestrator.run(conn)
        finally:
            conn.close()
    except Exception:
        return None  # fire-and-forget; /api/health surfaces real state
    finally:
        _cycle_lock.release()

# Fail closed: if REFRESH_KEY is unset or still the documented placeholder, every
# privileged /api/internal/* route stays locked rather than authorizing on the
# default everyone can read in config.py. A real deploy MUST set REFRESH_KEY.
_KEY_IS_SECURE = bool(REFRESH_KEY) and REFRESH_KEY != "change-me"


def _check(key: str):
    # compare_digest avoids leaking the key length/prefix via timing on the only
    # auth gate in the app.
    if not _KEY_IS_SECURE or not hmac.compare_digest(key, REFRESH_KEY):
        raise HTTPException(403, "bad key")


@router.get("/api/internal/refresh")
def refresh(key: str = "", async_: int = Query(1, alias="async")):
    """Background refresh by default: a slow ESPN day can take minutes, and a
    30s-timeout cron caller aborting mid-cycle just retries into a hung pile.
    ?async=0 keeps the synchronous report for hands-on ops."""
    _check(key)
    if async_:
        threading.Thread(target=refresh_locked, daemon=True).start()
        return {"started": True}
    report = refresh_locked()
    return report if report is not None else {"skipped": "cycle already running"}


@router.get("/api/internal/odds")
def odds_sweep(key: str = ""):
    """Manual odds sweep, bypassing the 12h gate and the 8-day-upcoming skip
    (but never the credit floor). Ops tool: verify the pipeline the moment
    books start quoting, without waiting for the scheduled pass."""
    _check(key)
    conn = db.connect()
    try:
        report = {}
        for slug, cfg in COMPETITIONS.items():
            report[slug] = odds_api.sweep(conn, slug, cfg["odds_key"])
        return report
    finally:
        conn.close()


@router.get("/api/internal/restore")
def restore(key: str = ""):
    """Re-run the FTP account restore. Cutover tool: picks up blobs written by
    pitchside after this instance last booted (stragglers still playing there).
    Fire-and-forget; watch db_accounts on /api/health for the result."""
    _check(key)
    threading.Thread(target=store.restore, daemon=True).start()
    return {"started": True}
