import { fmtG, selectionText } from "../lib/engine";
import { localKickoff } from "../lib/format";
import { useLang } from "../lib/i18n";

// One bet as a paper ticket stub. Settled stubs get a rotated rubber stamp.
export default function Ticket({ bet }) {
  const { t, dateLocale } = useLang();
  const settled = bet.status !== "open";
  return (
    <article className={`g-ticket${settled ? " g-ticket--settled" : ""}`}>
      <div className="g-ticket__top">
        <span>{t(`gamba.market.${bet.market}`)}
          {bet.oddsSource === "real" ? ` · ${t("gamba.market.realBook")}` : ""}
        </span>
        <span>{localKickoff(bet.placedAt, dateLocale)}</span>
      </div>
      <div className="g-ticket__pick">
        {selectionText(bet, t)} @ {bet.price.toFixed(2)}
      </div>
      <div className="g-ticket__match">
        {bet.homeName ? `${bet.homeName} v ${bet.awayName}` : `#${bet.matchId}`}
        {bet.result ? ` · ${t("gamba.ticket.final", { score: bet.result })}` : ""}
      </div>
      <div className="g-ticket__nums">
        <div>
          <span className="lbl">{t("gamba.slip.stake")}</span>
          <span className="val">{fmtG(bet.stake)}</span>
        </div>
        <div>
          <span className="lbl">{t("gamba.slip.returns")}</span>
          <span className="val">
            {settled ? fmtG(bet.returns) : fmtG(bet.stake * bet.price)}
          </span>
        </div>
      </div>
      {settled && (
        <span className={`g-stamp g-stamp--${bet.status}`}>
          {t(`gamba.ticket.${bet.status}`)}
        </span>
      )}
    </article>
  );
}
