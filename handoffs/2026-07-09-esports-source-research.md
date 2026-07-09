# Esports phase-2 source research — verdict: NO-GO on free tier (as of 2026-07-09)

The phase-2 gate from `2026-07-06-gamba-standalone-launch.md` ("no esports code
before source verification") ran today: 3 parallel research agents, primary
sources fetched and cited, claims tagged CONFIRMED (official page fetched) vs
SECONDHAND. Full cited findings are in the session transcript; this doc keeps
the decision-relevant facts.

## Verdict

**NO-GO for CS2, Valorant, and LoL.** No free (results source + odds source)
pair exists that satisfies gamba's hard rules — free tiers only, real
bookmaker odds (no model), stable event ids. The odds side fails outright;
the results side only has compromised options.

## Why the odds side fails (two independent kills, both CONFIRMED)

1. **The Odds API has no esports.** Its official covered-sports catalog,
   betting-markets page, and v4 guide list zero esports keys — no CS2, no
   Valorant, no LoL, no Dota 2. (the-odds-api.com/sports-odds-data/sports-apis.html,
   fetched 2026-07-09.) A search snippet claiming esports IDs "17/18/61" in
   The Odds API is a conflation with another vendor — false.
2. **Pinnacle's public API closed 2025-07-23** — the historical free-ish
   sharp-odds route is dead; access is now bespoke commercial/academic only.

Remaining routes, all disqualified:
- **PandaScore odds** — paid (from ~€1,000/mo/game), and its ToS (Art. 2.8 /
  6.4, fetched) bans "odds or odds-related products/services" on free/stats
  plans. A play-money book is plausibly odds-related — ToS risk even for
  fake currency.
- **OpticOdds / OddsJam** — enterprise, sales-gated (~$5k/mo secondhand).
- **OddsPapi** — claims free ~250 req/mo esports odds incl. Pinnacle-derived
  lines. Every source is its own marketing blog: UNVERIFIED. Even if real,
  250 req/mo is below the volume floor (see below).
- **Scraping books/odds-display sites** — prior art (bookie-odds-scraper)
  shows per-site hard-coding that rots on redesign; HLTV is Cloudflare-walled.
  Violates the "boring, stable, free" architecture ethos. No.
- **Model/derived odds** — collides with the explicit "no model" product
  decision and the "real bookmaker consensus" positioning. No.

## Why the results side is compromised (even ignoring odds)

| Source | Free quota | Fatal flaw |
|---|---|---|
| PandaScore (all 3 titles, fixtures+winner+map score) | 1,000 req/hr, no card | ToS bans betting-related use of free plans (CONFIRMED) |
| Liquipedia LPDB (all 3 titles) | **60 req/hr**, custom UA, CC-BY-SA attribution | ToS-clean but quota tight for reboot-refetch; per-match id (`match2id`) stability UNVERIFIED — risks the frozen `events.id` contract |
| lolesports internal API (LoL only) | undocumented, shared public key | Unofficial reverse-engineered Riot backend; key/schema can vanish any day |
| vlr.gg via vlrggapi (Valorant only) | self-host only (hosted instance dead) | Scrape, no data license, stable id not cleanly exposed |
| HLTV (CS2) | n/a | Library unmaintained; Cloudflare IP-bans — fatal for an ephemeral Render box that cold-refetches every reboot |
| GRID Open Access | free but application-gated | CS2+Dota2 only, approval required, betting-grade feed is a separate paid product |
| Abios | 14-day trial only | Not durable |

## Volume reality check

Tier-1 match volume ≈ 30-60/mo (CS2) + 30-40/mo (VCT) + 40-80/mo (LoL) —
hundreds of matches/month in season (derived from confirmed formats, ±30%).
Even a real odds feed at 1 credit/match/fetch would dwarf the ~130 spare
Odds API credits/mo. Esports needs its own budget, not the shared pool.

## What would reopen the gate (watch list)

1. **The Odds API adds esports keys** — check costs nothing: the `/v4/sports`
   list endpoint is 0 credits (CONFIRMED). Glance quarterly or when their
   changelog mentions esports.
2. **OddsPapi's free tier verified real** — a throwaway signup + one CS2
   match odds pull would confirm/refute their marketing in 15 minutes. Even
   then, 250 req/mo caps it at roughly one covered event per month.
3. **Willingness to pay** — PandaScore odds tier or GRID betting feed makes
   this a design problem instead of a sourcing problem.
4. **Liquipedia REST API opens a free tier** (currently Enterprise-only) —
   would fix the results side cleanly.

## Repo state notes

- `events.format` column was dropped in the 2026-07-09 cleanup — re-add
  (`bo1/bo3/bo5`) if this ever reopens; cache table, no migration cost.
- engine.js already voids unknown markets (review finding 8 fix), so a future
  esports market can't wrongly confiscate stakes on stale clients.
