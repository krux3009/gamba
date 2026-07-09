# Handoff — Gamba code review: 33 verified findings, fix next session

**Date:** 2026-07-08
**Repo:** `Coding Projects/gamba`, main at `3203b99`, clean tree — nothing fixed yet.
**Prev handoff:** `2026-07-06-gamba-standalone-launch.md` (launch state, cutover plan).

## What this session did

High-effort multi-agent `/code-review` over the whole repo (all 5.5k lines
shipped in one session on 2026-07-06). 8 finder angles → 36 candidates → 7
verifier agents. **33 survived** (30 CONFIRMED, 3 PLAUSIBLE, 0 refuted). No
code changed — user chose to log everything here and fix next session.

Esports research spike (`deep-research`) was launched in parallel; its report
is a **separate deliverable** — if it didn't land this session, re-run it
(phase-2 gate, no esports code before source verification).

## FIX ORDER (batches)

Suggested sequencing — pre-cutover safety first, since real pitchside accounts
migrate after the WC final (Jul 19, ~11 days out).

---

### Batch 1 — PRE-CUTOVER CRITICAL (do before Jul 19 flip)

**1. Cutover strands staging-window accounts** — `store.py:116` / `:58`
`restore()` reads only the single dir `HOSTINGER_GAMBA_DIR` points at. Flipping
staging→prod + redeploy wipes local sqlite; no code copies/merges
`gamba_accounts_staging` blobs into `gamba_accounts`. PUT never upserts
(`accounts.py:169-171`), so every account minted on gamba during the ~2-week
staging window 404s on sync after the flip, no self-heal.
→ Fix: a one-time merge step (copy staging blobs into prod dir over FTP before
the flip), OR make restore() read both dirs during a grace window. Decide the
migration mechanism BEFORE flipping. This is *the* account-loss risk in the
whole plan.

**2. restore() aborts on one bad blob** — `store.py:145`
A well-formed-JSON-but-wrong-shape blob (list, or dict missing `code`/`rev`)
raises `KeyError`/`TypeError` at `:145-148`, which sits OUTSIDE the inner try
(catches only `ftplib.all_errors` + `ValueError`; KeyError is not a ValueError)
and outside the outer except (`ftplib.all_errors` only). Loop aborts, single
commit at `:151` never runs → every account alphabetically after the bad blob
silently fails to restore. Inline comment claims "one bad blob must not sink
the restore" — it does.
→ Fix: wrap per-blob body in `try/except Exception: continue`, commit per-row
or ensure partial commit.

**3. restore() transaction freezes the event loop** — `store.py:142`
First INSERT opens the implicit txn, held across the whole multi-blob FTP RETR
loop (30s+ on slow FTP), single commit at `:151`. Concurrent `mint`/`put` are
`async def` doing SYNC sqlite (`accounts.py:104/:148`) → they busy-wait 5s on
the lock (`db.py:19` busy_timeout=5000) ON THE EVENT LOOP, freezing /api/events
+ /api/odds for everyone, then 500. Client marks sync 'error', state not
uploaded — real bet loss if phone wiped before next push. Race is exactly the
boot-restore-vs-returning-device case the docstring anticipates.
→ Fix: commit per blob (releases lock between RETRs), and/or run sqlite writes
off the event loop (`run_in_threadpool` or make routes sync-def).

**SECURITY 4. Sync code logged in plaintext** — `accounts.py:132` (all routes)
The sync code is the SOLE bearer credential (~2^49.6 entropy) and travels in
the URL path (`GET/PUT /api/accounts/{code}`). uvicorn access logs + Render
request logs record full request lines → every active code sits in log storage
in plaintext. Anyone with dashboard/log-drain access greps `GET /api/accounts/GB`
and harvests all codes, then PUTs arbitrary state (no other auth).
→ Fix: move code to an `Authorization` header or request body (access logs
don't capture those). NOTE: blob shape + GB code format are FROZEN (migration
contract) — this changes TRANSPORT only, not the code or blob.

**SECURITY 5. Silent FTPS→plaintext FTP downgrade** — `store.py:49`
`ftp_connect()` falls back to plain `ftplib.FTP` (same creds) on ANY ftplib
error during the TLS attempt (`:49-53`), no logging. A transient TLS failure or
active MITM stripping the handshake → `HOSTINGER_FTP_PASSWORD` + all account
blobs transit cleartext port 21. That password also controls kruxqlyz.com's
public_html (same FTP home) — one captured session compromises hosting + every
account.
→ Fix: don't fall back silently — either require FTPS (fail loud) or at minimum
log the downgrade loudly. Prefer fail-closed given the password's blast radius.

---

### Batch 2 — SETTLEMENT CORRECTNESS (wrong balances on real accounts)

**6. Postponed/canceled matches settle as FT 0-0** — `refresh.py:70`
LIVE-VERIFIED against ESPN: a canceled fixture returns `state='post'`,
`name='STATUS_CANCELED'`, `completed=False`, scores `'0','0'`. `refresh.py:70`
maps any `'post'`→FT with no `completed`/type-name check; `:92-93` writes the
0-0 since `started=True`. engine.js settles h2h draws + unders as WINS, rest as
losses, on a match never played. Sync merge propagates to all devices. Stale-day
pass (selects `status != 'FT'`) can never heal it. EPL postpones every season.
→ Fix: gate FT on `completed==True` AND type name in a FINAL set; map
postponed/canceled to a non-settling status (or void).

**7. Disk wipe orphans FT events > 1 day old** — `refresh.py:122`
Boot catch-up (`main.py:41-47` → `refresh.run()`) backfills fixtures
[today,+14d] + scores [yesterday,today] only; stale-day pass queries the
freshly-wiped empty table. FT events older than ~1 day never re-ingested → their
event id never reappears in /api/events → `settleBet` returns null for the
missing match → open bet stranded forever. Every redeploy risks this; /api/events
docstring promises a device unopened for weeks still finds its events.
→ Fix: on cold boot, backfill scores back far enough to cover the max open-bet
horizon (or persist a "last settled through" watermark and re-fetch the gap).

**8. Unknown market settles as LOST, not void** — `engine.js:46`
`outcome()` `default: return false` → `settleBet` (`:66-73`) marks any market
the client doesn't recognize as LOST (returns 0, stake confiscated) once
status=='FT'. Only void paths are null-score + teamsChanged. No
sport/format/capability descriptor reaches the client to refuse unknown markets
(schema `format` column is written by nothing — see cleanup). Phase-2 landmine:
new market from an updated SPA + a stale cached SPA on device B → wrongful loss,
and sync merge (`sync.js:69-71`, settled-beats-open, earlier-settledAt-wins)
lets the stale device's wrong loss win permanently.
→ Fix: `default:` should VOID (return stake) or leave open, never confiscate.
Fix before phase 2 ships any new market.

---

### Batch 3 — ODDS BUDGET / GATES (burns shared 500cr/mo pool; matchday no-odds)

**9. btts "once per event EVER" guard is neither durable nor set on empty** — `odds_api.py:275` + `:285`
Two defects in one guard:
(a) Guard = presence of btts rows in `market_odds`, which lives on the ephemeral
disk (wiped every push). Boot re-buys 1 credit per event in the 48h window
(~15-20/matchweek deploy).
(b) Credit spent on the HTTP call, but `_ingest` writes nothing when no book
quotes btts (returns 0) and no "attempted" marker is written → same unquoted
event re-bought every 12h sweep for the life of the window.
Both silently blow the ~316-of-450cr/mo budget model shared with pitchside.
→ Fix: persist the "btts fetched for event X" marker durably (meta table is same
DB = also wiped; needs the FTP mirror or a rederivable signal) AND write the
marker on ATTEMPT, not just on rows-written.

**10. _ingest wholesale-replace broken both directions** — `odds_api.py:205`
(a) `if not rows: return 0` runs BEFORE the DELETE → when books pull all quotes
(team news), stale day-old odds survive and are served as live/bettable
(`canBet` checks only status/kickoff). (b) DELETE spans every market in
`markets` but re-inserts only those present → an h2h-only response (all totals
lines quarter-line-filtered) wipes previously-valid totals rows → over/under
prices vanish from UI.
→ Fix: DELETE only the markets actually re-fetched, and delete-before-insert per
market even when the fresh set is empty (so pulled markets clear rather than go
stale). Reconcile with schema.sql:27 "closing snapshot" contract.

**11. Odds gate stamps on failure** — `refresh.py:159`
`_stamp('last_fetch:odds:{slug}')` fires unconditionally after `sweep()`, even
when sweep returned `{'error':...}` / `{'skipped':'credit floor'}` / matched 0
(all zero-credit). Locks the 12h gate → a failed Saturday-morning sweep means
the 3pm slate shows no odds till evening. Fixture gate 3 lines up stamps only on
`payload is not None` — opposite philosophy for the same failure class.
→ Fix: stamp only when sweep actually succeeded (inspect the report).

---

### Batch 4 — RELIABILITY / EFFICIENCY

**12. 200-with-HTML aborts the whole refresh pass** — `espn.py:38` (+ `odds_api.py:74`)
`return r.json()` guarded only by `except httpx.HTTPError`. `json.JSONDecodeError`
subclasses `ValueError`, not `httpx.HTTPError` → a 200 with a maintenance-HTML
body propagates out of `scoreboard()` through `run()`'s per-competition loop,
aborting remaining competitions + the `last_refresh` stamp; `internal.py:30-31`
`except Exception: return None` swallows it with zero logging.
→ Fix: catch `ValueError`/`JSONDecodeError` in the fetch wrappers, treat as
fetch failure (return None), log it.

**13. No WAL mode** — `db.py:19`
Only `foreign_keys` + `busy_timeout=5000` set; no `journal_mode=WAL`. Default
rollback journal → refresh-thread commits (fetch_log row per HTTP call, ingests,
meta stamps) block readers up to 5s. During live windows clients polling
/api/events + /api/odds hit routine 5s stalls or "database is locked" 500s on
the single free-tier instance.
→ Fix: `PRAGMA journal_mode=WAL` once in bootstrap (persists in the db file).
Cheapest high-value fix in the whole review.

**14. /api/odds rebuilds from unfiltered SELECT \*** — `routes/odds.py:57`
`SELECT * FROM market_odds` loads every row ever ingested (FT rows never pruned →
grows all season, ~7-8k rows by May), rebuilds the full JSON doc per request, and
`generated_at = now()` per call defeats any ETag/304/CDN caching for a payload
that only changes 2×/day/competition. N open tabs = N full rebuilds+transfers/min.
→ Fix: JOIN to non-FT events (or delete rows when events go FT), cache the built
doc keyed on the last-refresh meta stamp, derive `generated_at` from that so
ETags work.

**15. Sync refresh path blocks minutes in-request** — `internal.py:57`
`async_=0` runs the whole orchestrator in-request (threadpool thread): N blocking
ESPN calls × 25s timeout + `time.sleep(1.0)` per btts event, holding `_cycle_lock`.
A slow ESPN day → 1-5 min request; a 30s-timeout cron caller aborts + retries,
hanging connections while the 75s live loop was already going to do the work.
→ Fix: make async the default/only behavior; return the last report from meta.

**16. Per-push FTPS handshake, thread-per-push** — `store.py:113`
`push_async` spawns a thread per call; `_push` opens a fresh
connect/TLS/login/quit per invocation under `_lock`. Matchday burst (20 linked
devices settling) = 20 serialized full handshakes (~1-2s each, ~4s+ when TLS
fails to plain) = 30-80s of FTP churn for 20 tiny blobs.
→ Fix: one long-lived worker draining a queue over a kept-alive connection, or
debounce pushes so a burst coalesces into one connection.

---

### Batch 5 — PLAUSIBLE (real mechanism, trigger depends on provider/future)

- **ALIASES structural gap (pre-UCL)** — `odds_api.py:35`. Flat 5-entry EPL-only
  dict; token-subset match structurally can't handle exonyms/transliterations
  (Inter Milan vs Internazionale, Bayern Munich vs München, Sporting Lisbon vs
  Sporting CP). UCL in Sept adds ~36 multilingual clubs → marquee fixtures show
  no odds. Not reachable yet (uefa.champions commented out). Cross-league
  mis-alias mostly guarded by competition+kickoff-scoped candidate query.
  → Design a proper normalizer/alias-per-competition before enabling UCL.
- **Stale-day retry-forever** — `refresh.py:136`. No meta gate + no terminal
  state; an event ESPN drops from its day feed re-qualifies as stale every cycle
  (incl. 75s live loop), can saturate LIMIT 5 slots. Endgame depends on ESPN
  re-keying/removal; canceled events currently get marked FT (finding 6) and
  leave the set. Fixing 6 partly mitigates. Add a meta gate + give-up counter.
- **Non-UTC offset mislabeled as Z** — `refresh.py:62`. `fromisoformat().strftime('...Z')`
  with no `.astimezone(timezone.utc)`; a non-UTC offset from ESPN would stamp
  local wall-clock + Z → all string-compare windows off by the offset. ESPN
  observed emitting Z-form UTC; trigger is provider behavior. One-line defensive
  fix: `.astimezone(timezone.utc)` before strftime.

---

## CLEANUP BATCH (16 confirmed; do in a sweep, low risk, recruiters read this repo)

Highest-value first:
- **WAL** (`db.py:19`) — see finding 13, already in Batch 4.
- **/api/odds SELECT \*** (`routes/odds.py:57`) — finding 14.
- **Four divergent `_now()`** — `accounts.py:54` returns `isoformat()`
  (`+00:00`, microseconds) while `odds_api.py:48`, `espn.py:23`,
  `routes/odds.py:66` all `strftime('%Y-%m-%dT%H:%M:%SZ')`. Kickoff comparisons
  are STRING compares on the Z format — grabbing the isoformat one for any
  events/odds code silently breaks windows. → one `utc_now_z()` helper in db.py.
- **Dead `format` column** (`schema.sql:21`) — written/read by nothing
  (grep-confirmed). Drop it; re-add when esports lands (cache table, no migration
  cost). Note it's the same descriptor finding 8 wants for the client — decide
  together.
- **Unread `label` key** (`config.py:25`) — never read; frontend has its own
  `COMP_LABEL`. Drop or comment.
- **Duplicated `_log()`** (`odds_api.py:52` == `espn.py:19`) — byte-identical
  but source string. → shared `log_fetch()` in the empty `fetch/__init__.py`.
- **Duplicated meta upsert** (`odds_api.py:70` INSERT OR REPLACE vs `refresh.py:27`
  ON CONFLICT) + 3 scattered raw SELECTs → `db.meta_get/meta_set`.
- **`.replace('Z','+00:00')`** (`refresh.py:63`, `odds_api.py:113`) — unnecessary
  on Python 3.12 (`fromisoformat` parses Z natively). Drop both.
- **Duplicated ftp connect block** (`store.py:44`) — collapse TLS + plain
  branches to a loop over `(FTP_TLS, FTP)`. (Coordinate with security finding 5 —
  the plain branch may go away entirely.)
- **btts per-event kickoff re-query** (`odds_api.py:271`) — `match_fixture`
  already selected those rows; add kickoff_utc to its projection, drop the loop
  query + can't-happen null check.
- **Over-built `/api/internal/restore`** (`internal.py:83`) — threading.Event +
  shared dict + daemon + 20s wait for an operator curl endpoint; use the existing
  `async=1` fire-and-forget pattern or a plain sync call.
- **Frontend re-render every poll** (`useApi.js:15`) — unconditional setState of
  fresh object + `generated_at` differs per call → Board re-renders all unmemoized
  MarketCards every 60s on byte-identical data. Compare raw text (excluding
  generated_at) before setState + `React.memo` on MarketCard. (Ties to finding
  14's caching.)
- **Ticket.jsx inline date fmt** (`Ticket.jsx:14`) — re-implements `format.js`
  `localKickoff` minus weekday. Use the shared helper.
- **sync.js req() dup** (`sync.js:113`) — re-implements `api.js` fetch wrapper +
  25s timeout constant. Share the low-level `request()`/constant (keep apiGet's
  cache/retry out of sync).

## Carried over from prev handoff (NOT this review — still open human steps)

1. **Cron pinger** — user chose to SKIP for now (`/api/internal/refresh` every
   10 min on cron-job.org). Still not set up.
2. **Key-check curl** — `curl …/api/internal/odds?key=…` to prove ODDS_API_KEY +
   see remaining credits. Not confirmed.
3. **CUTOVER (after Jul 19)** — flip `HOSTINGER_GAMBA_DIR` staging→`gamba_accounts`.
   ⚠ Now blocked on finding 1 (staging-window merge) — resolve that FIRST or real
   accounts minted on gamba during staging are lost.
4. Post-cutover: "Gamba has moved" banner on pitchside /gamba (out of repo scope).

## Method note

Findings are ranked by severity, correctness over cleanup. Verifiers ran
recall-biased (PLAUSIBLE by default, REFUTED only when disprovable from code).
0 candidates refuted — the finder pool was accurate. Full verdicts with
file:line citations are in this session's transcript if a specific one needs
re-checking.
