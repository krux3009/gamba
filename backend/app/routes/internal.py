"""Privileged operational endpoints, key-gated."""
import hmac
import threading

from fastapi import APIRouter, HTTPException, Query

from .. import db, store
from ..config import REFRESH_KEY
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
def refresh(key: str = "", async_: int = Query(0, alias="async")):
    _check(key)
    if async_:
        # Pinger path: run the refresh in a background thread and return an
        # instant, tiny 200 — cron-job.org has a ~30s timeout, and the quick
        # request keeps the Render free instance warm.
        threading.Thread(target=refresh_locked, daemon=True).start()
        return {"started": True}
    report = refresh_locked()
    return report if report is not None else {"skipped": "cycle already running"}


@router.get("/api/internal/restore")
def restore(key: str = ""):
    """Re-run the FTP account restore. Cutover tool: picks up blobs written by
    pitchside after this instance last booted (stragglers still playing there)."""
    _check(key)
    done = threading.Event()
    result: dict = {}

    def _run():
        result["inserted"] = store.restore()
        done.set()

    threading.Thread(target=_run, daemon=True).start()
    # restore is bounded (MAX_ACCOUNTS blobs) but FTP can be slow; give the
    # caller a quick answer if it finishes fast, else let it run detached.
    finished = done.wait(timeout=20)
    return {"finished": finished, "inserted": result.get("inserted")}
