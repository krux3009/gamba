import { canBet } from "../lib/engine";
import { compLabel } from "../lib/competitions";
import { useLang } from "../lib/i18n";
import { localKickoff } from "../lib/format";

// One match's markets — real bookmaker consensus only. Tapping a price starts
// a ticket, which settles at the BEST book's price.
export default function MarketCard({ m, pick, onPick }) {
  const { t, lang, dateLocale } = useLang();
  const open = canBet(m);

  const base = {
    matchId: m.id,
    homeName: m.home_name, awayName: m.away_name,
    homeId: m.home_id, awayId: m.away_id,
  };
  const isOn = (sel) =>
    pick && pick.matchId === m.id && pick.market === sel.market &&
    pick.selection === sel.selection && pick.line === sel.line;

  // real-book button: settles at the BEST price
  const rb = (market, selection, entry, label, line = 0) => (
    <button
      key={`${market}:${selection}:${line}`}
      className={`g-price${isOn({ market, selection, line }) ? " on" : ""}`}
      disabled={!open}
      onClick={() => {
        const sel = { market, selection, line, price: entry.best, oddsSource: "real" };
        onPick(isOn(sel) ? null : { ...base, ...sel, match: m });
      }}
    >
      <span className="g-price__sel">{label}</span>
      <span className="g-price__odds">{entry.best.toFixed(2)}</span>
      <span className="g-price__real">
        {t("gamba.market.median")} {entry.median?.toFixed(2)} · {entry.n}
      </span>
    </button>
  );

  const real = m.real;
  const codes = { home: "1", draw: "X", away: "2" };

  return (
    <article className="g-card g-match">
      <div className="g-match__head">
        <span className="g-match__teams">{m.home_name} v {m.away_name}</span>
        <span className="g-match__meta">
          {compLabel(m.competition, lang)} · {localKickoff(m.kickoff_utc, dateLocale)}
          {!open && ` · ${t("gamba.board.closed")}`}
        </span>
      </div>

      {!real?.h2h && (
        <div className="g-locked">{t("gamba.board.noOdds")}</div>
      )}

      {real?.h2h && (
        <>
          <div className="g-market">
            <div className="g-market__label">
              {t("gamba.market.h2h")}
              <span className="g-badge">{t("gamba.market.realBook")}</span>
            </div>
            <div className="g-prices">
              {["home", "draw", "away"].map((s) => real.h2h[s] &&
                rb("h2h", s, real.h2h[s],
                   s === "draw" ? t("gamba.sel.draw") : codes[s]))}
            </div>
          </div>

          {real.totals?.length > 0 && (
            <div className="g-market">
              <div className="g-market__label">
                {t("gamba.market.totals")}
                <span className="g-badge">{t("gamba.market.realBook")}</span>
              </div>
              {real.totals.map((tl) => (
                <div className="g-prices" key={tl.line} style={{ marginBottom: 6 }}>
                  {tl.over && rb("totals", "over", tl.over,
                    `${t("gamba.sel.over")} ${tl.line}`, tl.line)}
                  {tl.under && rb("totals", "under", tl.under,
                    `${t("gamba.sel.under")} ${tl.line}`, tl.line)}
                </div>
              ))}
            </div>
          )}

          {real.btts && (
            <div className="g-market">
              <div className="g-market__label">
                {t("gamba.market.btts")}
                <span className="g-badge">{t("gamba.market.realBook")}</span>
              </div>
              <div className="g-prices">
                {real.btts.yes && rb("btts", "yes", real.btts.yes, t("gamba.sel.yes"))}
                {real.btts.no && rb("btts", "no", real.btts.no, t("gamba.sel.no"))}
              </div>
            </div>
          )}
        </>
      )}
    </article>
  );
}
