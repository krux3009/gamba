-- Gamba: everything here is a rebuildable cache EXCEPT gamba_accounts.
-- Render's disk is wiped on every deploy: events and odds re-fetch on boot
-- (ESPN + The Odds API), accounts restore from the private Hostinger FTP dir
-- (store.py). There is no seed database.

-- One row per fixture, any sport. id IS the ESPN event id — stable across
-- rebuilds, which matters because client-side bets reference it (a re-seeded
-- id space would orphan every open bet on redeploy).
CREATE TABLE IF NOT EXISTS events (
  id            INTEGER PRIMARY KEY,        -- ESPN event id
  sport         TEXT NOT NULL DEFAULT 'soccer',
  competition   TEXT NOT NULL,              -- ESPN slug: 'eng.1' | 'esp.1' | ...
  home_name     TEXT,
  away_name     TEXT,
  home_ext_id   TEXT,                       -- ESPN team ids; the client voids a
  away_ext_id   TEXT,                       -- bet if the fixture's teams change
  kickoff_utc   TEXT NOT NULL,
  status        TEXT DEFAULT 'SCHEDULED',   -- 'SCHEDULED'|'LIVE'|'FT'|'CANCELED'
  home_score    INTEGER,                    -- soccer: FT score (leagues have no
  away_score    INTEGER,                    -- extra time); esports later: maps won
  format        TEXT                        -- NULL for soccer; 'bo1'/'bo3'/'bo5'
);
CREATE INDEX IF NOT EXISTS idx_events_kickoff ON events(kickoff_utc);

-- Real bookmaker odds (The Odds API), consensus rows only — median/best across
-- books, aggregated at ingest. Each sweep replaces an event's rows wholesale;
-- the last pre-kickoff sweep is the closing snapshot. Lost on redeploy by
-- design: the boot catch-up sweeps again within minutes and settlement never
-- reads odds, so balances are untouched.
CREATE TABLE IF NOT EXISTS market_odds (
  event_id      INTEGER NOT NULL REFERENCES events(id),
  market        TEXT NOT NULL,              -- 'h2h' | 'totals' | 'btts'
  selection     TEXT NOT NULL,              -- 'home'|'draw'|'away'|'over'|'under'|'yes'|'no'
  line          REAL NOT NULL DEFAULT 0,    -- totals point (2.5); 0 for h2h/btts
  price_median  REAL,
  price_best    REAL,
  book_best     TEXT,
  n_books       INTEGER,
  fetched_at    TEXT,
  PRIMARY KEY (event_id, market, selection, line)
);

-- Budget ledger: every external request is logged.
CREATE TABLE IF NOT EXISTS fetch_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  fetched_at    TEXT,
  source        TEXT,                       -- 'espn' | 'odds_api'
  endpoint      TEXT,
  params        TEXT,
  status        INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
  key           TEXT PRIMARY KEY,
  value         TEXT
);

-- Sync accounts: opaque client blobs keyed by an anonymous bearer code.
-- Byte-identical to pitchside's table — the FTP blobs written there restore
-- here unchanged (that IS the migration path). The CLIENT owns the state
-- schema; the server never interprets it.
CREATE TABLE IF NOT EXISTS gamba_accounts (
  code          TEXT PRIMARY KEY,           -- compact sync code, e.g. 'GB7Q4KMXW2AB'
  rev           INTEGER NOT NULL,           -- compare-and-swap revision
  state         TEXT NOT NULL,              -- opaque JSON
  updated_at    TEXT NOT NULL
);
