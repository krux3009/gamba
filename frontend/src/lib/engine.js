// Gamba settlement engine — pure functions, no React, no storage.
//
// Every market settles on the final score from /api/events (league soccer has
// no extra time, so this is simply the FT score). Settlement never reads
// /api/odds — the odds document can lag or vanish without touching balances.
//
// Bet shape (frozen at placement):
//   {id, matchId, market, selection, line, price, stake, placedAt, oddsSource,
//    homeName, awayName, homeId, awayId, listedScores?,
//    status: 'open'|'won'|'lost'|'void', returns?, settledAt?, result?}

export const START_BALANCE = 500;
export const MIN_STAKE = 10;
export const DRIP_AMOUNT = 200;
export const DRIP_BELOW = 200;

// ---- money ------------------------------------------------------------------

// ₲ = "Gamba credits". Whole numbers stay whole; fractional returns show 2dp.
export function fmtG(n) {
  const v = Math.round((n ?? 0) * 100) / 100;
  return "₲ " + v.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: Number.isInteger(v) ? 0 : 2,
  });
}

// ---- settlement --------------------------------------------------------------

function outcome(bet, h, a) {
  switch (bet.market) {
    case "h2h": {
      const winner = h > a ? "home" : h < a ? "away" : "draw";
      return bet.selection === winner;
    }
    case "totals":
      return bet.selection === "over" ? h + a > bet.line : h + a < bet.line;
    case "btts":
      return bet.selection === "yes" ? h >= 1 && a >= 1 : !(h >= 1 && a >= 1);
    case "correct_score": {
      const final = `${h}-${a}`;
      if (bet.selection === "other")
        return !(bet.listedScores || []).includes(final);
      return bet.selection === final;
    }
    default:
      // unknown market — a newer SPA placed it; guessing here would
      // confiscate the stake, so signal "can't judge" and let settleBet void
      return null;
  }
}

// One bet against one event row from /api/events.
// Returns the settled bet, or null when it can't settle yet.
export function settleBet(bet, match) {
  if (!match) return null;
  const settledAt = new Date().toISOString();
  // canceled/abandoned fixture: the bet's premise is gone — stake back
  if (match.status === "CANCELED") {
    return { ...bet, status: "void", returns: bet.stake, settledAt };
  }
  if (match.status !== "FT") return null;
  const h = match.home_goals_90;
  const a = match.away_goals_90;
  // void (stake back): no final score recorded, or the fixture's teams changed
  // after placement — the bet's premise is gone
  const teamsChanged =
    (bet.homeId != null && match.home_id !== bet.homeId) ||
    (bet.awayId != null && match.away_id !== bet.awayId);
  if (h == null || a == null || teamsChanged) {
    return { ...bet, status: "void", returns: bet.stake, settledAt };
  }
  const won = outcome(bet, h, a);
  if (won == null) {
    return { ...bet, status: "void", returns: bet.stake, settledAt };
  }
  return {
    ...bet,
    status: won ? "won" : "lost",
    returns: won ? Math.round(bet.stake * bet.price * 100) / 100 : 0,
    result: `${h}-${a}`,
    settledAt,
  };
}

// All open bets against the events feed. Returns {bets, credit, settled}:
// the full updated list, the total to add to the balance, and just the
// newly settled bets (for the stamp-toast).
export function settleAll(bets, matches) {
  const byId = new Map((matches || []).map((m) => [m.id, m]));
  const settled = [];
  const next = bets.map((bet) => {
    if (bet.status !== "open") return bet;
    const done = settleBet(bet, byId.get(bet.matchId));
    if (done) settled.push(done);
    return done || bet;
  });
  const credit = settled.reduce((s, b) => s + b.returns, 0);
  return { bets: next, credit, settled };
}

// Betting is open only before kickoff on a still-scheduled match.
export const canBet = (match, now = Date.now()) =>
  match?.status === "SCHEDULED" && now < new Date(match.kickoff_utc).getTime();

// Human line for a pick/ticket: "Arsenal to win @ 2.10", "Over 2.5", "BTTS: yes".
export function selectionText(bet, t) {
  switch (bet.market) {
    case "h2h":
      return bet.selection === "draw"
        ? t("gamba.sel.draw")
        : t("gamba.sel.toWin", {
            team: bet.selection === "home" ? bet.homeName : bet.awayName,
          });
    case "totals":
      return `${t(`gamba.sel.${bet.selection}`)} ${bet.line}`;
    case "btts":
      return `${t("gamba.market.btts")}: ${t(`gamba.sel.${bet.selection}`)}`;
    case "correct_score":
      return bet.selection === "other"
        ? t("gamba.sel.otherScore")
        : t("gamba.sel.exactScore", { score: bet.selection });
    default:
      return bet.selection;
  }
}

// ---- balance (derived, never stored — the same rule as the ledger) -----------
//
// v2 state stops storing the balance: it's recomputed from what happened, so
// storage can't drift and a cross-device merge can't double-credit. `carry` is
// the one opaque number — a residual from pitchside's v1 migration, preserved
// because migrated accounts sync in with it. Everything before the last reset
// is inert: bets by full timestamp, drips by day — except the reset-day drip,
// which stays in the array so the once-a-day guard holds, but pays nothing.
export function deriveBalance({ bets, drips, resetAt, carry }) {
  const resetDay = (resetAt || "").slice(0, 10);
  const activeBets = bets.filter((b) => !resetAt || b.placedAt > resetAt);
  const activeDrips = drips.filter((d) => !resetAt || d > resetDay);
  const returned = activeBets.reduce(
    (s, b) => s + (b.status !== "open" ? b.returns || 0 : 0), 0);
  const staked = activeBets.reduce((s, b) => s + b.stake, 0);
  return Math.round(
    (START_BALANCE + carry + DRIP_AMOUNT * activeDrips.length + returned - staked)
    * 100) / 100;
}

// ---- lifetime ledger (derived, never stored — storage can't drift) -----------

export function ledger(bets) {
  const settledBets = bets.filter((b) => b.status !== "open");
  const nonVoid = settledBets.filter((b) => b.status !== "void");
  const staked = nonVoid.reduce((s, b) => s + b.stake, 0);
  const returned = nonVoid.reduce((s, b) => s + (b.returns || 0), 0);
  return {
    nBets: bets.length,
    nSettled: settledBets.length,
    staked,
    returned,
    net: returned - staked,
    roi: staked > 0 ? (returned - staked) / staked : 0,
  };
}
