import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, store
from .config import ALLOWED_ORIGINS
from .fetch import refresh
from .routes import accounts, events, internal, odds

LIVE_TICK_SECONDS = 75    # refresh cadence while a match is in play
IDLE_CHECK_SECONDS = 120  # how often to peek at the schedule otherwise


def _live_loop():
    """Fast refresh while a match is in play. The external pinger only fires
    every ~10 minutes — fine between matchdays, glacial mid-match. Shares the
    pinger's cycle lock, so ticks collapse instead of stacking. It lives only
    while the instance is awake; the pinger stays the heartbeat that keeps
    Render's free tier from sleeping through a match."""
    while True:
        hot = False
        try:
            conn = db.connect()
            try:
                hot = refresh.live_window_open(conn)
            finally:
                conn.close()
            if hot:
                internal.refresh_locked()
        except Exception:
            pass  # never let a bad tick kill the loop; next tick retries
        time.sleep(LIVE_TICK_SECONDS if hot else IDLE_CHECK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.bootstrap()
    needs_catchup = conn.execute(
        "SELECT 1 FROM meta WHERE key='last_refresh'"
    ).fetchone() is None
    conn.close()
    # a redeploy wiped the disk: re-fetch fixtures/scores in the background
    if needs_catchup:
        threading.Thread(target=internal.refresh_locked, daemon=True).start()
    threading.Thread(target=_live_loop, daemon=True).start()
    # re-insert sync accounts the redeploy dropped (user data — the one table
    # that can't be re-fetched); never blocks serving
    threading.Thread(target=store.restore, daemon=True).start()
    yield


app = FastAPI(title="Gamba API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT"],  # POST/PUT: account sync writes only
    allow_headers=["*"],
)

for module in (accounts, events, internal, odds):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    conn = db.connect()
    try:
        n_accounts = conn.execute(
            "SELECT COUNT(*) AS n FROM gamba_accounts"
        ).fetchone()["n"]
        n_events = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        last_refresh = conn.execute(
            "SELECT value FROM meta WHERE key = 'last_refresh'"
        ).fetchone()
    finally:
        conn.close()
    return {
        "status": "ok",
        "db_accounts": n_accounts,   # cutover check: compare with the FTP dir count
        "db_events": n_events,
        "last_refresh": last_refresh["value"] if last_refresh else None,
    }
