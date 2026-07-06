# GAMBA 🎲

A play-money sports betting game on **real bookmaker odds**. Fake credits (₲),
never real money — nothing can be deposited, withdrawn, or purchased.

Live: https://gamba.kruxqlyz.com · API on Render · spun out of
[pitchside](https://github.com/krux3009/pitchside) (World Cup 2026 analytics),
where Gamba started as a mode.

## What's interesting here

A tiny real-money-shaped system, built honest:

- **Client-side deterministic settlement** — the server never touches a
  balance. `frontend/src/lib/engine.js` settles every ticket from the scores
  feed; the balance is *derived* from history, never stored, so storage can't
  drift and a sync merge can't double-credit.
- **CRDT state sync over a dumb blob store** — cross-device accounts with no
  auth, no users table. `frontend/src/lib/sync.js` is a commutative,
  associative, idempotent merge; `backend/app/routes/accounts.py` is ~170
  lines of compare-and-swap blob storage keyed by an unguessable bearer code
  (2^49.6 entropy — the right trust level for Monopoly money).
- **Everything rebuildable on an ephemeral disk** — Render wipes the disk on
  every deploy. Fixtures and odds re-fetch on boot; user accounts restore from
  a private FTP mirror (`backend/app/store.py`).
- **Credit-budgeted ingestion** — The Odds API free tier is 500 credits/month.
  The sweep is gated, floored, and skips what it already has.
- Plain `sqlite3` + handwritten SQL. No ORM.

## Sports

Soccer at launch: Premier League + La Liga (The Odds API for prices, ESPN for
fixtures/scores). Adding a competition is one line in
`backend/app/config.py::COMPETITIONS`. Esports (Valorant/CS2) is a researched
maybe — the schema carries `sport`/`format` for it.

## Commands

```bash
cd backend && .venv/bin/python -m pytest tests/   # test suite
.venv/bin/uvicorn app.main:app --reload           # local API on :8000
cd frontend && npm run dev                        # local UI on :5173
# deploy: git push — Render builds the API; a GitHub Action FTPs the SPA
# build to Hostinger (gamba.kruxqlyz.com)
```

## Disclaimer

The odds shown are real bookmaker prices, displayed for realism. Nothing on
this site is betting advice. Real betting loses money in the long run by
construction — the prices carry the house's margin.
