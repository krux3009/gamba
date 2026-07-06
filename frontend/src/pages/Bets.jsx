import { Link } from "react-router-dom";

import SyncCard from "../components/SyncCard";
import Ticket from "../components/Ticket";
import { useGamba } from "../lib/GambaContext";
import { fmtG, ledger } from "../lib/engine";
import { useLang } from "../lib/i18n";

export default function Bets() {
  const { t } = useLang();
  const { bets, canDrip, claimDrip, resetAccount } = useGamba();
  const open = bets.filter((b) => b.status === "open");
  const settled = bets.filter((b) => b.status !== "open");
  const lg = ledger(bets);

  return (
    <>
      <h1 className="gamba-page-title">{t("gamba.bets.title")}</h1>

      <div className="g-stats">
        <div className="g-stat">
          <span className="lbl">{t("gamba.bets.staked")}</span>
          <span className="val">{fmtG(lg.staked)}</span>
        </div>
        <div className="g-stat">
          <span className="lbl">{t("gamba.bets.returned")}</span>
          <span className="val">{fmtG(lg.returned)}</span>
        </div>
        <div className="g-stat">
          <span className="lbl">{t("gamba.bets.net")}</span>
          <span className={`val ${lg.net < 0 ? "neg" : lg.net > 0 ? "pos" : ""}`}>
            {lg.net >= 0 ? "+" : "−"}{fmtG(Math.abs(lg.net))}
          </span>
        </div>
        <div className="g-stat">
          <span className="lbl">{t("gamba.bets.roi")}</span>
          <span className={`val ${lg.roi < 0 ? "neg" : lg.roi > 0 ? "pos" : ""}`}>
            {(lg.roi * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      <SyncCard />

      <div style={{ display: "flex", gap: 8, margin: "10px 0 4px", flexWrap: "wrap" }}>
        {canDrip && (
          <button className="g-btn" onClick={claimDrip}>{t("gamba.drip")}</button>
        )}
        <button
          className="g-btn g-btn--danger"
          onClick={() => window.confirm(t("gamba.reset.confirm")) && resetAccount()}
        >
          {t("gamba.reset")}
        </button>
      </div>

      {bets.length === 0 && (
        <div className="g-locked" style={{ marginTop: 20 }}>
          {t("gamba.bets.none")}{" "}
          <Link to="/" style={{ textDecoration: "underline" }}>
            {t("gamba.nav.board")}
          </Link>
        </div>
      )}

      {open.length > 0 && (
        <>
          <h2 className="g-h">{t("gamba.bets.open")}</h2>
          {open.map((b) => <Ticket key={b.id} bet={b} />)}
        </>
      )}
      {settled.length > 0 && (
        <>
          <h2 className="g-h">{t("gamba.bets.settled")}</h2>
          {settled.map((b) => <Ticket key={b.id} bet={b} />)}
        </>
      )}
    </>
  );
}
