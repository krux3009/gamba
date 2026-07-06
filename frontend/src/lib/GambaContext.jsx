// Gamba account state — one context, one localStorage key, a memoised value.
// Fake credits only; editing localStorage is minting Monopoly money (and yes,
// syncing spreads it — same trust model), so there's defensive parsing and
// nothing more — honest simplicity over security theater.
//
// The balance is DERIVED (engine.deriveBalance), never stored, and the account
// can sync across devices through the anonymous blob store in
// backend/app/routes/accounts.py. Reconciliation lives in sync.js; this file
// only wires it up: debounced push after local changes, 60s pull, merge on
// conflict.
import {
  createContext, useContext, useEffect, useMemo, useRef, useState,
} from "react";

import {
  DRIP_BELOW, MIN_STAKE, canBet, deriveBalance, settleAll,
} from "./engine";
import {
  fetchAccount, merge, mintAccount, normalizeCode, pushAccount, syncableOf,
} from "./sync";

// fresh origin, fresh slot — pitchside accounts migrate via sync codes, never
// via localStorage (it doesn't cross origins). The `version` field inside is
// the schema version, kept at 2 = the frozen sync-blob contract.
const STORAGE_KEY = "gamba.v1";

const FRESH = {
  version: 2,
  code: null,        // sync code (null = this device is offline-only)
  rev: 0,            // last server revision this device has seen
  bets: [],
  drips: [],         // ISO dates ('2026-07-05') of every mercy drip claimed
  resetAt: null,     // ISO timestamp of the last account reset
  carry: 0,          // migration residual from pitchside v1 accounts — see deriveBalance
  onboardingSeen: false,
};

function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (!raw || !Array.isArray(raw.bets)) return FRESH;
    if (raw.version === 2 && Array.isArray(raw.drips)) return { ...FRESH, ...raw };
    return FRESH;
  } catch {
    return FRESH;
  }
}

const GambaContext = createContext(null);

export function GambaProvider({ children }) {
  const [state, setState] = useState(load);
  // idle (unlinked) | pending (local changes not yet acked) | synced | error
  const [syncStatus, setSyncStatus] = useState("idle");
  // canonical JSON of the last blob the server acknowledged (push, pull, mint,
  // or link). A state change that serializes to this came FROM the server —
  // pushing it back would just echo.
  const lastServerJson = useRef(null);
  const pushTimer = useRef(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  // adopt a server copy: merge it into whatever is local right now. Idempotent,
  // so a pull racing a 409 branch is harmless.
  const adoptServer = ({ rev, state: serverBlob }) => {
    lastServerJson.current = JSON.stringify(syncableOf(serverBlob));
    setState((s) => ({ ...s, ...merge(syncableOf(s), serverBlob), rev }));
    setSyncStatus("synced");
    // if local had extra content, the merged result differs from the server
    // blob, so the push effect below re-fires with the fresh rev
  };

  // push: debounced 2s after any local change while linked
  useEffect(() => {
    if (!state.code) return undefined;
    const blob = syncableOf(state);
    const json = JSON.stringify(blob);
    if (json === lastServerJson.current) return undefined;
    setSyncStatus("pending");
    clearTimeout(pushTimer.current);
    pushTimer.current = setTimeout(async () => {
      try {
        const res = await pushAccount(state.code, state.rev, blob);
        if (res.conflict) {
          adoptServer(res.conflict);
        } else {
          lastServerJson.current = json;
          setState((s) => (s.rev === res.rev ? s : { ...s, rev: res.rev }));
          setSyncStatus("synced");
        }
      } catch {
        setSyncStatus("error"); // next mutation or poll tick retries
      }
    }, 2000);
    return () => clearTimeout(pushTimer.current);
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps

  // pull: on mount and every 60s while linked (StrictMode double-fire is fine —
  // adoptServer merges idempotently)
  useEffect(() => {
    if (!state.code) return undefined;
    let stopped = false;
    const pull = async () => {
      try {
        const res = await fetchAccount(state.code);
        // notFound = the deploy's FTP restore hasn't finished — transient
        if (stopped || res === "notFound") return;
        if (res.rev !== stateRef.current.rev) adoptServer(res);
      } catch {
        /* poll again next tick */
      }
    };
    pull();
    const id = setInterval(pull, 60_000);
    return () => { stopped = true; clearInterval(id); };
  }, [state.code]); // eslint-disable-line react-hooks/exhaustive-deps

  const value = useMemo(() => {
    const balance = deriveBalance(state);

    // returns an error key for the UI, or null on success
    const placeBet = (bet, match) => {
      let err = null;
      setState((s) => {
        if (!canBet(match)) { err = "closed"; return s; }
        if (!(bet.stake >= MIN_STAKE)) { err = "min"; return s; }
        if (bet.stake > deriveBalance(s)) { err = "funds"; return s; }
        return {
          ...s,
          bets: [
            { ...bet, id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
              placedAt: new Date().toISOString(), status: "open" },
            ...s.bets,
          ],
        };
      });
      return err;
    };

    // settle open bets against the events feed; returns newly settled bets.
    // Idempotent: a second call finds no open bets, so StrictMode's double
    // effects and overlapping polls can never double-credit. Recomputed inside
    // the updater too, so a sync merge landing mid-settle can't be clobbered.
    const settle = (matches) => {
      const { settled } = settleAll(state.bets, matches);
      if (settled.length) {
        setState((s) => {
          const r = settleAll(s.bets, matches);
          return r.settled.length ? { ...s, bets: r.bets } : s;
        });
      }
      return settled;
    };

    // mercy drip: +₲200 once per day, only while broke — never a top-up
    const today = new Date().toISOString().slice(0, 10);
    const canDrip = balance < DRIP_BELOW && !state.drips.includes(today);
    const claimDrip = () => {
      setState((s) =>
        deriveBalance(s) < DRIP_BELOW && !s.drips.includes(today)
          ? { ...s, drips: [...s.drips, today] }
          : s);
    };

    // reset is account-wide by design: one account, one balance — a linked
    // device drops to ₲500 on its next sync. Pre-reset bets/drips become inert
    // via resetAt (deriveBalance/merge filter on it), so copies merged back in
    // from a device that hadn't heard about the reset stay harmless.
    const resetAccount = () =>
      setState((s) => ({
        ...s,
        bets: [],
        drips: s.drips.filter((d) => d >= today),
        resetAt: new Date().toISOString(),
        carry: 0,
      }));

    // ---- sync actions (all return an error key or null) ----
    const enableSync = async () => {
      try {
        const blob = syncableOf(state);
        const { code, rev } = await mintAccount(blob);
        lastServerJson.current = JSON.stringify(blob);
        setState((s) => ({ ...s, code: normalizeCode(code), rev }));
        setSyncStatus("synced");
        return null;
      } catch (e) {
        return e?.status === 429 ? "limit" : "network";
      }
    };

    // linking REPLACES this device's account with the synced one (the UI
    // confirms first) — two pre-existing diverged accounts don't auto-merge;
    // the user picks the canonical device by enabling sync there.
    const linkWithCode = async (input) => {
      try {
        const res = await fetchAccount(input);
        if (res === "notFound") return "notFound";
        lastServerJson.current = JSON.stringify(syncableOf(res.state));
        setState({
          ...FRESH, ...res.state, code: normalizeCode(input), rev: res.rev,
        });
        setSyncStatus("synced");
        return null;
      } catch {
        return "network";
      }
    };

    // forget the code locally; the state stays on this device
    const unlink = () => {
      setState((s) => ({ ...s, code: null, rev: 0 }));
      setSyncStatus("idle");
    };

    return {
      balance,
      // pre-reset bets merged back from a stale device are inert — never render them
      bets: state.resetAt
        ? state.bets.filter((b) => b.placedAt > state.resetAt)
        : state.bets,
      canDrip,
      syncCode: state.code,
      syncStatus,
      placeBet, settle, claimDrip, resetAccount,
      enableSync, linkWithCode, unlink,
    };
  }, [state, syncStatus]);

  return <GambaContext.Provider value={value}>{children}</GambaContext.Provider>;
}

export function useGamba() {
  return useContext(GambaContext);
}
