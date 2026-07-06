import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, store
from .config import ALLOWED_ORIGINS
from .routes import accounts, internal


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.bootstrap().close()
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

for module in (accounts, internal):
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
