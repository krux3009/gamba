// Smallest runnable check for the settlement money path: `npm run check`.
// No framework on purpose — engine.js is pure, node + assert is enough.
import assert from "node:assert/strict";

import { deriveBalance, settleBet } from "../src/lib/engine.js";

const bet = (over = {}) => ({
  id: "b1", matchId: 1, market: "h2h", selection: "home", line: 0,
  price: 2.0, stake: 100, placedAt: "2026-07-01T00:00:00Z",
  homeId: "10", awayId: "20", status: "open", ...over,
});
const match = (over = {}) => ({
  id: 1, status: "FT", home_goals_90: 2, away_goals_90: 1,
  home_id: "10", away_id: "20", ...over,
});

// win pays stake*price; loss pays 0
assert.equal(settleBet(bet(), match()).status, "won");
assert.equal(settleBet(bet(), match()).returns, 200);
assert.equal(settleBet(bet({ selection: "away" }), match()).returns, 0);

// not-yet-final match: no settlement
assert.equal(settleBet(bet(), match({ status: "LIVE" })), null);
assert.equal(settleBet(bet(), match({ status: "SCHEDULED" })), null);

// canceled fixture voids — stake back, never a 0-0 settlement
let v = settleBet(bet(), match({
  status: "CANCELED", home_goals_90: null, away_goals_90: null,
}));
assert.equal(v.status, "void");
assert.equal(v.returns, 100);

// unknown market (newer SPA placed it) voids, never confiscates
v = settleBet(bet({ market: "first_scorer" }), match());
assert.equal(v.status, "void");
assert.equal(v.returns, 100);

// FT but no score recorded: void
assert.equal(settleBet(bet(), match({ home_goals_90: null })).status, "void");

// a void round-trips the balance exactly
const base = deriveBalance({ bets: [], drips: [], resetAt: null, carry: 0 });
const voided = settleBet(bet({ market: "first_scorer" }), match());
assert.equal(
  deriveBalance({ bets: [voided], drips: [], resetAt: null, carry: 0 }),
  base,
);

console.log("engine.check: ok");
