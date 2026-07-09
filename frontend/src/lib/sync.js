// Cross-device sync — pure merge + tiny fetch helpers, no React.
//
// The server (backend/app/routes/accounts.py) is a dumb blob store with a
// compare-and-swap rev; ALL reconciliation happens here. merge() is a
// state-CRDT — commutative, associative, idempotent — so any interleaving of
// pushes and pulls converges:
//
//  - same-day drip claimed on two offline devices → the date-set union pays it
//    once, not twice
//  - both devices settle the same bet off the same /api/events feed →
//    identical outcome (settlement is deterministic), only the settledAt stamp
//    differs, and the tie-break makes even the bytes converge
//  - a reset beats concurrent activity by wall clock: bets placed before the
//    reset instant die (even merged in later from a device that hadn't heard),
//    bets placed after it survive against the fresh ₲500
//  - total server loss: any device's push recreates the account at rev 1 and
//    every other device union-merges its superset back in — nothing is lost
//    while one device still holds the state
//
// Blobs always travel through syncableOf(), which applies the same canonical
// ordering as merge(), so "did anything change" is a plain string compare.
//
// The blob shape {bets, drips, resetAt, carry, onboardingSeen} is FROZEN: it
// is the migration contract with the accounts pitchside mirrored to FTP.

import { request } from "./api";

// ---- codes --------------------------------------------------------------------

export function normalizeCode(raw) {
  return (raw || "").toUpperCase().replace(/[^0-9A-Z]/g, "");
}

export function displayCode(code) {
  const c = normalizeCode(code);
  return c.length === 12 ? `${c.slice(0, 2)}-${c.slice(2, 7)}-${c.slice(7)}` : c;
}

// ---- canonical blob -------------------------------------------------------------

// newest first, matching the UI's prepend order; id breaks placedAt ties
const betOrder = (a, b) =>
  a.placedAt < b.placedAt ? 1 : a.placedAt > b.placedAt ? -1
    : a.id < b.id ? 1 : a.id > b.id ? -1 : 0;

// the slice of state that syncs — code/rev are per-device envelope, never cargo
export function syncableOf(state) {
  return {
    bets: [...state.bets].sort(betOrder),
    drips: [...state.drips].sort(),
    resetAt: state.resetAt ?? null,
    carry: state.carry ?? 0,
    onboardingSeen: !!state.onboardingSeen,
  };
}

// ---- merge ----------------------------------------------------------------------

// Two copies of the same bet id, one from each device. Pick the winner:
//   1. a settled ticket beats an open one (settlement is deterministic — it
//      never has to be undone);
//   2. both settled: the earlier settledAt wins (outcomes are identical, this
//      only converges the timestamp bytes);
//   3. still tied: smaller JSON.stringify wins — arbitrary but deterministic,
//      so both devices resolve the same way.
function pickBet(x, y) {
  const settledX = x.status !== "open";
  const settledY = y.status !== "open";
  if (settledX !== settledY) return settledX ? x : y;
  if (settledX && x.settledAt !== y.settledAt)
    return x.settledAt < y.settledAt ? x : y;
  return JSON.stringify(x) <= JSON.stringify(y) ? x : y;
}

function pickCarry(a, b, resetAt) {
  // the most recent resetter zeroed carry — its side is authoritative. Equal
  // resetAt (the normal linked case) means equal carry by construction:
  // linking replaces local state, and carry only changes at migration (before
  // linking) or reset (handled here). min() is a deterministic fallback.
  if ((a.resetAt ?? null) === (b.resetAt ?? null)) return Math.min(a.carry, b.carry);
  return a.resetAt === resetAt ? a.carry : b.carry;
}

export function merge(a, b) {
  const resetAt =
    (a.resetAt || "") > (b.resetAt || "") ? a.resetAt : b.resetAt || null;
  const resetDay = (resetAt || "").slice(0, 10);
  const byId = new Map();
  for (const bet of [...a.bets, ...b.bets]) {
    const prev = byId.get(bet.id);
    byId.set(bet.id, prev ? pickBet(prev, bet) : bet);
  }
  return {
    bets: [...byId.values()]
      .filter((bet) => !resetAt || bet.placedAt > resetAt)
      .sort(betOrder),
    // keep the reset-day drip: it pays nothing (deriveBalance) but still blocks
    // a second claim that day
    drips: [...new Set([...a.drips, ...b.drips])]
      .filter((d) => !resetAt || d >= resetDay)
      .sort(),
    resetAt,
    carry: pickCarry(a, b, resetAt),
    onboardingSeen: a.onboardingSeen || b.onboardingSeen,
  };
}

// ---- server ---------------------------------------------------------------------

// request() comes from api.js (same 25s cold-start timeout); no retry loops,
// the 60s poll in GambaContext is the retry.
//
// The sync code travels in the X-Sync-Code header, never the URL path — it is
// the sole credential, and path segments land verbatim in server access logs.

export async function mintAccount(state) {
  const res = await request("/api/accounts", {
    method: "POST",
    body: JSON.stringify({ state }),
  });
  if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
  return res.json(); // {code, rev}
}

// -> {rev, state} | "notFound" (404 is expected while a fresh deploy is still
// restoring accounts from FTP — the caller treats it as transient)
export async function fetchAccount(code) {
  const res = await request("/api/accounts/me", {
    headers: { "X-Sync-Code": normalizeCode(code) },
  });
  if (res.status === 404) return "notFound";
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// -> {rev} on success | {conflict: {rev, state}} on a lost CAS race
export async function pushAccount(code, rev, state) {
  const res = await request("/api/accounts/me", {
    method: "PUT",
    headers: { "X-Sync-Code": normalizeCode(code) },
    body: JSON.stringify({ rev, state }),
  });
  if (res.status === 409) return { conflict: (await res.json()).detail };
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
