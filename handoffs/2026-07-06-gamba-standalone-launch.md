# Handoff — Gamba standalone: built, deployed, self-running to launch

**Date:** 2026-07-06 (one session: grill → plan → PR1/PR2/PR3 all shipped)
**Repo:** `Coding Projects/gamba`, main at `6f63166`, all pushed + deployed.
**Live:** https://gamba.kruxqlyz.com · API https://gamba-p1pk.onrender.com

## What this is

Gamba split out of pitchside into its own repo/site/API per the grilled plan
(decisions table in `~/.claude/plans/gamba-standalone-multi-sport-betting-atomic-taco.md`,
mirrored in project memory `gamba-standalone-deployment`). Key decisions:
EPL + La Liga at launch (UCL = one `COMPETITIONS` line in Sept); esports =
phase 2 gated on a research spike; **education features dropped entirely**
(no model/EV/School — user chose this twice, don't relitigate); pitchside
untouched except a future "moved" banner.

## Shipped

- `0e2a101` PR1: CAS blob store + FTP durability ported verbatim (+tests),
  paper-theme SPA (Board/Bets), deploy pipelines (Render + GH Action→Hostinger).
- `61408fa` PR2: thin ESPN client, refresh orchestrator (24h fixture gate,
  zero-call idle, stale-day self-heal), /api/events w/ engine aliases, live
  loop. Verified vs real ESPN both directions (2026-27 openers SCHEDULED,
  2025-26 final day FT w/ correct scores).
- `6f63166` PR3: odds sweep parameterized per competition, **btts
  once-per-event-ever** (budget-critical), club token-subset matching that
  refuses ambiguity, /api/odds document, /api/internal/odds manual sweep.
  Sport keys verified vs provider list. 28 tests green.

## Timeline (self-running)

- ~Aug 1: fixtures enter the 14-day horizon → board fills
- ~Aug 7: opening matches within 8 days → odds sweeps start spending
  (budget model ≈316 of ~450 usable cr/mo — watch `meta odds_api:remaining`
  in week 1 vs that model)
- Aug 15: EPL + La Liga kick off → launch, no code needed

## Human steps outstanding

1. **Cron pinger** (user): cron-job.org → `/api/internal/refresh?key=…&async=1`
   every 10 min. Was instructed, NOT yet confirmed done.
2. **Key check** (user): `curl …/api/internal/odds?key=…` once — zero-cost,
   proves ODDS_API_KEY wiring, shows remaining credits. Instructed, not confirmed.
3. **CUTOVER (after WC final Jul 19):** flip Render env
   `HOSTINGER_GAMBA_DIR=gamba_accounts_staging` → `gamba_accounts`, redeploy.
   Boot restore() adopts all real pitchside accounts (mechanism already proven
   in prod — staging account survived 3 redeploys today). Verify
   `/api/health db_accounts` vs FTP dir count; link a real code, check balance
   parity; hit `/api/internal/restore?key=` daily ~1wk for stragglers.
4. Post-cutover, touching pitchside (out of this repo's scope): "Gamba has
   moved" banner on its /gamba route.

## Facts a fresh session needs

- Blob shape + GB codes FROZEN (migration contract). `events.id` = ESPN id,
  stable across disk wipes — bets reference it.
- Kickoffs normalized to `%Y-%m-%dT%H:%M:%SZ` at ingest; every window check in
  the app is a string compare. Don't insert other formats.
- Odds sweep skips comps with nothing SCHEDULED within 8 days; btts refetch is
  once-per-event-EVER — loosening either blows the 500cr/mo shared pool.
- Club-name aliases (`odds_api.ALIASES`) grow from `fetch_log` unmatched
  reports in week 1 — check `report["unmatched"]` after first real sweeps.
- Playwright MCP profile on gamba origin holds test account GB-YRHTC-GWQ8J
  (rev 1, empty). The REAL user account lives on the worldcup origin
  (pitchside memory: gamba-state-in-playwright-profile).
- ESPN scoreboard after extra time carries the FULL ET score — fine for
  leagues, must be handled before adding UCL knockouts (see
  refresh.ingest_scoreboard docstring).

## Phase 2 (separate task, not started)

Esports (Valorant/CS2): research spike FIRST — free odds+results source
unverified (The Odds API esports coverage doubtful; PandaScore/Abios quotas
unknown). Schema already carries sport/format/no-draw capability.
