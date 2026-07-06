"""Privileged operational endpoints, key-gated.

PR2 adds /api/internal/refresh (the cron-pinger target) alongside the fetch
modules; until then the only privileged op is the account-restore trigger used
during cutover.
"""
import hmac
import threading

from fastapi import APIRouter, HTTPException

from .. import store
from ..config import REFRESH_KEY

router = APIRouter()

# Fail closed: if REFRESH_KEY is unset or still the documented placeholder, every
# privileged /api/internal/* route stays locked rather than authorizing on the
# default everyone can read in config.py. A real deploy MUST set REFRESH_KEY.
_KEY_IS_SECURE = bool(REFRESH_KEY) and REFRESH_KEY != "change-me"


def _check(key: str):
    # compare_digest avoids leaking the key length/prefix via timing on the only
    # auth gate in the app.
    if not _KEY_IS_SECURE or not hmac.compare_digest(key, REFRESH_KEY):
        raise HTTPException(403, "bad key")


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
