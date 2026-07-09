"""Environment configuration. Loaded once at import time."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

REFRESH_KEY = os.getenv("REFRESH_KEY", "change-me")
DB_PATH = Path(os.getenv("DB_PATH") or DATA_DIR / "gamba.db")
# comma-separated list, e.g. "https://gamba.kruxqlyz.com,http://localhost:5173"
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGIN", "http://localhost:5173").split(",")
    if o.strip()
]

# Competitions we ingest. Key = ESPN league slug (canonical competition id in
# the events table); odds_key = The Odds API sport key. Adding a competition
# is one line here — fixtures, scores, and odds all key off this dict.
COMPETITIONS = {
    "eng.1": {"sport": "soccer", "odds_key": "soccer_epl"},
    "esp.1": {"sport": "soccer", "odds_key": "soccer_spain_la_liga"},
    # Sept: "uefa.champions": {"sport": "soccer", "odds_key": "soccer_uefa_champs_league"},
    # ^ before enabling: the flat ALIASES map in fetch/odds_api.py can't handle
    #   UCL's multilingual club names (Inter/Internazionale, Bayern/München…) —
    #   build a per-competition alias table first or marquee ties show no odds.
}

# Hostinger FTP — account-blob durability (store.py). Home-relative and
# deliberately OUTSIDE domains/kruxqlyz.com/public_html: the FTP account
# chroots to its home dir and only public_html is web-served, so account data
# is never reachable over HTTP. Empty creds => store is inert.
HOSTINGER_FTP_HOST = os.getenv("HOSTINGER_FTP_HOST", "")
HOSTINGER_FTP_USER = os.getenv("HOSTINGER_FTP_USER", "")
HOSTINGER_FTP_PASSWORD = os.getenv("HOSTINGER_FTP_PASSWORD", "")
# Points at the SAME dir pitchside writes ("gamba_accounts") after cutover —
# that shared dir is the account migration path. Keep it on a staging dir
# ("gamba_accounts_staging") until the WC final has settled.
HOSTINGER_GAMBA_DIR = os.getenv("HOSTINGER_GAMBA_DIR", "gamba_accounts_staging")
# Retired dirs restore() ALSO reads (never writes). Cutover recipe: flip
# HOSTINGER_GAMBA_DIR to "gamba_accounts" AND set this to
# "gamba_accounts_staging" — accounts minted during the staging window are
# adopted and re-uploaded to the primary dir instead of stranded. Unset once
# /api/health shows the counts merged.
HOSTINGER_GAMBA_LEGACY_DIRS = [
    d.strip()
    for d in os.getenv("HOSTINGER_GAMBA_LEGACY_DIRS", "").split(",")
    if d.strip()
]

# The Odds API. Free tier = 500 credits/month shared with pitchside (whose WC
# sweeps self-stop after the final). Budget model: 2 sweeps/day x 2 comps x 2cr
# = 240/mo bulk + btts once per event (~76/mo) ~= 316 of ~450 usable.
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_REFRESH_HOURS = 12         # 2 sweeps/day per competition
ODDS_BTTS_WINDOW_HOURS = 48     # per-event BTTS only this close to kickoff
ODDS_API_CREDIT_FLOOR = 50      # refuse to spend below this many credits left
