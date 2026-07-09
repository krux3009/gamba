# Handoff — review fixes applied: 30 of 33 findings closed, cutover unblocked

**Date:** 2026-07-09
**Repo:** main, 5 commits ahead of origin (`Review batch 1..5`) — **NOT pushed**.
Pushing deploys (Render API + GH Action SPA), so push when ready to ship.
**Prev handoff:** `2026-07-08-code-review-findings.md` (the findings list; keep
for reference — numbering below matches it).

## What this session did

Fixed the code-review findings in 5 batch commits. All 39 backend tests pass
(`cd backend && .venv/bin/python -m pytest tests/`), frontend builds, and
`cd frontend && npm run check` runs a new framework-free settlement self-check.

- **Batch 1 (pre-cutover critical, findings 1-5 + 16):** restore() now reads
  `HOSTINGER_GAMBA_LEGACY_DIRS` too and re-uploads legacy-only accounts to the
  primary dir (that IS the staging→prod merge); per-blob guards; FTP reads
  finish before the insert txn opens; sync code moved to `X-Sync-Code` header
  on `/api/accounts/me` (old path routes kept for cached SPAs); FTPS is
  fail-closed; pushes coalesce through one drainer; account sqlite runs in the
  threadpool.
- **Batch 2 (settlement, 6-8):** ESPN `post` maps to FT only when
  `completed=True`; canceled/abandoned → `CANCELED` status which the client
  VOIDS (stake back); postponed stays SCHEDULED; one-per-boot 90-day score
  backfill so wiped FT events reappear in /api/events; engine.js voids unknown
  markets instead of confiscating.
- **Batch 3 (odds budget, 9-11):** btts "once per event ever" is a durable
  ledger (meta + FTP mirror `btts_attempted.meta`, restored on cold boot,
  marked on ATTEMPT); `_ingest` clears a re-fetched market even when empty and
  clears matched events absent from a successful bulk; 12h odds gate stamps
  only on a sweep that ran.
- **Batch 4 (reliability, 12-15):** non-JSON 200s = fetch failure; WAL;
  /api/odds joins live events + caches the doc keyed on `last_refresh`
  (generated_at IS the stamp); `/api/internal/refresh` defaults `async=1`;
  restore endpoint is fire-and-forget.
- **Batch 5 (plausibles + cleanup):** kickoff `astimezone(utc)`; stale-day
  pass 6h-gated + skips CANCELED; dead `format` column and `label` keys
  dropped; shared `log_fetch`/`utc_now_z`/`meta_get`/`meta_set`; frontend
  shared `request()`, useApi skips setState on byte-identical polls, Ticket
  uses `localKickoff`.

Deliberately NOT fixed: UCL alias normalizer (design task — warning comment
sits on the commented-out config entry), btts kickoff re-query micro-opt,
React.memo on MarketCard (useApi compare already stops the re-renders).

## CUTOVER RECIPE (after WC final Jul 19) — now unblocked

1. Push this branch, let it deploy, sanity-check /api/health + a sync.
2. On Render: set `HOSTINGER_GAMBA_DIR=gamba_accounts` **and**
   `HOSTINGER_GAMBA_LEGACY_DIRS=gamba_accounts_staging`, redeploy.
3. Boot restore merges both dirs (newer `updated_at` wins) and re-uploads
   staging-window accounts to `gamba_accounts`. Verify: `db_accounts` on
   /api/health ≥ count of blobs in either FTP dir.
4. Weeks later, once staging blobs are all mirrored (or stale), unset
   `HOSTINGER_GAMBA_LEGACY_DIRS`.

## Still open (human steps, carried over)

1. **Push + deploy** the 5 commits (see above — not done, deploy = publish).
2. **Cron pinger** still not set up (`/api/internal/refresh?key=…` every
   10 min on cron-job.org; async is now the default so the 30s timeout is fine).
3. **Key-check curl** `…/api/internal/odds?key=…` to confirm ODDS_API_KEY +
   remaining credits — never verified.
4. **Esports research report** (deep-research) — didn't land on 2026-07-08
   either; re-run if esports phase 2 is still wanted.
5. Post-cutover: "Gamba has moved" banner on pitchside /gamba (other repo).
6. Later: remove the legacy `/api/accounts/{code}` path routes once cached
   SPAs have rolled over (they still leak codes into access logs while used).

## Watch after deploy

- First boot after this deploy re-buys nothing: btts ledger starts empty
  locally but `market_odds` presence still guards until the FTP mirror seeds.
- `restore()` now aborts (rather than half-continues) if the FTP connection
  dies mid-listing — it retries on next boot or via /api/internal/restore.
- generated_at semantics changed: it's the last refresh stamp, not request
  time. Anything comparing it to "now" would misread (nothing does today).
