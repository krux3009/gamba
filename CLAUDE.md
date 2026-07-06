# CLAUDE.md — Gamba

Play-money multi-sport betting site. Live: https://gamba.kruxqlyz.com · API
https://gamba-p1pk.onrender.com · repo github.com/krux3009/gamba. Spun out of
pitchside 2026-07-06. Architecture + data sources: `README.md`.

## Session start

**Check `handoffs/` for the most recent doc and read it** — current task, open
follow-ups, constraints not in the code.

## Commands

```bash
cd backend && .venv/bin/python -m pytest tests/   # test suite (uv venv, Python 3.12)
.venv/bin/uvicorn app.main:app --reload           # local API on :8000
cd frontend && npm run dev                        # local UI on :5173
# deploy = git push (Render auto-builds API; GH Action FTPs SPA to Hostinger)
```

## Hard rules

- Free tiers only. ESPN = no quota; The Odds API = 500 credits/mo SHARED with
  pitchside — the btts once-per-event guard and per-competition sweep gates in
  `fetch/odds_api.py` + `fetch/refresh.py` are the budget; don't loosen them.
- Render disk is ephemeral: events/odds re-fetch on boot; `gamba_accounts` is
  USER data — durability is the private Hostinger FTP mirror (`app/store.py`),
  NEVER the public repo.
- The sync blob shape `{bets, drips, resetAt, carry, onboardingSeen}` and the
  GB code format are FROZEN — they're the migration contract with accounts
  minted on pitchside.
- `events.id` = ESPN event id, never re-keyed: client bets reference it, and a
  re-seeded id space would orphan open bets on redeploy.
- Gambling disclaimer on every surface showing odds. No model, no EV lesson,
  no School page — dropped by explicit decision, don't re-add.
- Plain sqlite3 + handwritten SQL, no ORM. Recruiters read this repo.
- `HOSTINGER_GAMBA_DIR` stays on `gamba_accounts_staging` until cutover (after
  WC final Jul 19); flipping it to `gamba_accounts` IS the account migration.
