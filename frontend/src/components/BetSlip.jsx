import { useEffect, useRef, useState } from "react";

import { useGamba } from "../lib/GambaContext";
import { MIN_STAKE, canBet, fmtG, selectionText } from "../lib/engine";
import { useLang } from "../lib/i18n";
import Disclaimer from "./Disclaimer";

// Sticky receipt (right rail desktop / bottom sheet mobile): pick, stake,
// returns, place. On phones the sheet minimizes (never closes): drag the grab
// bar down or tap it to dock the ticket as a slim bar; tap the bar to bring it
// back up.
export default function BetSlip({ pick, onClear }) {
  const { t } = useLang();
  const { balance, placeBet, canDrip, claimDrip } = useGamba();
  const [stake, setStake] = useState(50);
  const [err, setErr] = useState(null);
  const [printed, setPrinted] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [dragY, setDragY] = useState(0);
  const drag = useRef(null); // {startY} while the grab bar is held

  useEffect(() => { setErr(null); setMinimized(false); setDragY(0); }, [pick]);
  useEffect(() => {
    if (!printed) return;
    const id = setTimeout(() => setPrinted(false), 2500);
    return () => clearTimeout(id);
  }, [printed]);

  if (!pick) {
    // on phones this renders as nothing at all — the sheet only docks in when
    // it has something to say (printed flash) or offer (the daily drip)
    return (
      <div className={`g-slip g-slip--empty${printed ? " is-printed" : ""}${canDrip ? " has-drip" : ""}`}>
        <div className="g-slip__title">{t("gamba.slip.title")}</div>
        <div className="g-slip__empty">
          {printed ? t("gamba.slip.printed") : t("gamba.slip.empty")}
        </div>
        {canDrip && (
          <button className="g-btn" style={{ width: "100%" }} onClick={claimDrip}>
            {t("gamba.drip")}
          </button>
        )}
        <div className="g-slip__fine">
          <Disclaimer />
        </div>
      </div>
    );
  }

  const stakeNum = Number(stake) || 0;
  const open = canBet(pick.match);

  const place = () => {
    const { match, ...frozen } = pick;
    const e = placeBet({ ...frozen, stake: stakeNum }, match);
    if (e) {
      setErr(e);
    } else {
      setPrinted(true);
      onClear();
    }
  };

  // grab-bar gesture: follow the finger down; past the threshold it docks,
  // otherwise it springs back. A no-move press counts as a tap-to-minimize.
  const onGrabDown = (e) => {
    drag.current = { startY: e.clientY };
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
  };
  const onGrabMove = (e) => {
    if (!drag.current) return;
    drag.current.dy = Math.max(0, e.clientY - drag.current.startY);
    setDragY(drag.current.dy);
  };
  const onGrabUp = () => {
    if (!drag.current) return;
    const dy = drag.current.dy ?? 0;
    drag.current = null;
    if (dy > 70 || dy < 5) setMinimized(true);
    setDragY(0);
  };

  if (minimized) {
    return (
      <button className="g-slip g-slip--min" onClick={() => setMinimized(false)}
              aria-label={t("gamba.slip.expand")}>
        <div className="g-slip__grab" aria-hidden="true" />
        <span className="g-slip__minpick">
          {selectionText(pick, t)} @ {pick.price.toFixed(2)}
        </span>
        <span className="g-slip__mincue" aria-hidden="true">▲</span>
      </button>
    );
  }

  return (
    <div className="g-slip"
         style={dragY ? { transform: `translateY(${dragY}px)`, transition: "none" } : undefined}>
      <button type="button" className="g-slip__dragzone" aria-label={t("gamba.slip.close")}
              onPointerDown={onGrabDown} onPointerMove={onGrabMove}
              onPointerUp={onGrabUp} onPointerCancel={onGrabUp}>
        <div className="g-slip__grab" aria-hidden="true" />
      </button>
      <div className="g-slip__title">{t("gamba.slip.title")}</div>

      <div className="g-slip__pick">
        {selectionText(pick, t)} @ {pick.price.toFixed(2)}
        <span className="g-badge" style={{ marginLeft: 6 }}>
          {t("gamba.market.realBook")}
        </span>
      </div>
      <div className="g-slip__match">
        {pick.homeName} v {pick.awayName}
        {" · "}{t(`gamba.market.${pick.market}`)}
      </div>

      <label htmlFor="g-stake" className="g-slip__row" style={{ display: "block" }}>
        <span style={{ fontSize: 12, color: "var(--g-ink-soft)" }}>
          {t("gamba.slip.stake")}
        </span>
      </label>
      <input
        id="g-stake"
        className="g-stake"
        type="number"
        min={MIN_STAKE}
        max={Math.floor(balance)}
        step="10"
        value={stake}
        onChange={(e) => setStake(e.target.value)}
      />
      <div className="g-chips">
        {[50, 100, 250].map((v) => (
          <button key={v} className="g-chipbtn" onClick={() => setStake(v)}>
            {v}
          </button>
        ))}
        <button className="g-chipbtn" onClick={() => setStake(Math.floor(balance))}>
          MAX
        </button>
      </div>

      <dl className="g-slip__rows">
        <div className="g-slip__row">
          <dt>{t("gamba.slip.returns")}</dt>
          <dd>{fmtG(stakeNum * pick.price)}</dd>
        </div>
      </dl>

      <button className="g-place" onClick={place} disabled={!open}>
        {open ? t("gamba.slip.place") : t("gamba.slip.closed")}
      </button>
      {err && (
        <p className="g-slip__err">
          {t(`gamba.slip.err.${err}`)}
          {err === "funds" && canDrip && (
            <button className="g-btn" style={{ marginLeft: 8 }} onClick={claimDrip}>
              {t("gamba.drip")}
            </button>
          )}
        </p>
      )}

      <div className="g-slip__perf" />
      <Disclaimer />
    </div>
  );
}
