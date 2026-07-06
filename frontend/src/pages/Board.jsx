import { useState } from "react";

import BetSlip from "../components/BetSlip";
import MarketCard from "../components/MarketCard";
import { compLabel } from "../lib/competitions";
import { localDateHeading, localDayKey } from "../lib/format";
import { useLang } from "../lib/i18n";
import { useApi } from "../lib/useApi";

export default function Board() {
  const { t, lang, dateLocale } = useLang();
  const { data, loading, error } = useApi("/api/odds", { pollMs: 60_000 });
  const [pick, setPick] = useState(null);
  const [comp, setComp] = useState("all");

  const all = data?.matches ?? [];
  // pills are derived from the data, so a new backend competition appears here
  // without a frontend change
  const comps = [...new Set(all.map((m) => m.competition))].sort();
  const matches = comp === "all" ? all : all.filter((m) => m.competition === comp);

  const days = new Map();
  for (const m of matches) {
    const key = localDayKey(m.kickoff_utc);
    if (!days.has(key)) days.set(key, []);
    days.get(key).push(m);
  }

  return (
    <>
      <h1 className="gamba-page-title">{t("gamba.board.title")}</h1>
      <p className="gamba-sub">{t("gamba.board.sub")}</p>

      {comps.length > 1 && (
        <div className="g-comps" role="tablist" aria-label="competition filter">
          {["all", ...comps].map((c) => (
            <button key={c} role="tab" aria-selected={comp === c}
              className={`g-comp${comp === c ? " on" : ""}`}
              onClick={() => setComp(c)}>
              {c === "all" ? t("gamba.comp.all") : compLabel(c, lang)}
            </button>
          ))}
        </div>
      )}

      <div className="gamba-board">
        <div>
          {loading && <div className="g-slip__empty">…</div>}
          {error && <div className="g-slip__empty">{t("gamba.board.error")}</div>}
          {!loading && !error && matches.length === 0 && (
            <div className="g-locked" style={{ marginTop: 20 }}>
              {t("gamba.board.empty")}
            </div>
          )}
          {[...days.entries()].map(([day, ms]) => (
            <section key={day}>
              <h2 className="g-h">{localDateHeading(day, dateLocale)}</h2>
              {ms.map((m) => (
                <MarketCard key={m.id} m={m} pick={pick} onPick={setPick} />
              ))}
            </section>
          ))}
        </div>
        <aside className="gamba-board__rail">
          <BetSlip pick={pick} onClear={() => setPick(null)} />
        </aside>
      </div>
    </>
  );
}
