import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useLang } from "../lib/i18n";
import { useApi } from "../lib/useApi";
import { GambaProvider, useGamba } from "../lib/GambaContext";
import { fmtG } from "../lib/engine";
import Disclaimer from "./Disclaimer";
import "../styles/gamba.css";

const tabs = [
  { to: "/", key: "gamba.nav.board", end: true },
  { to: "/bets", key: "gamba.nav.bets" },
];

export default function Layout() {
  return (
    <GambaProvider>
      <Shell />
    </GambaProvider>
  );
}

function Shell() {
  const { lang, setLang, t } = useLang();
  const { balance, settle } = useGamba();
  const [toasts, setToasts] = useState([]);

  // The phone header is static (scrolls away — content first), which used to
  // take the balance with it. Watch the masthead: once it leaves the viewport
  // a small fixed twin of the chip takes over top-right. The desktop header is
  // sticky, so it never leaves view and the twin never renders there.
  const headerRef = useRef(null);
  const [headerAway, setHeaderAway] = useState(false);
  useEffect(() => {
    const el = headerRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return undefined;
    const io = new IntersectionObserver(([e]) => setHeaderAway(!e.isIntersecting));
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // settlement heartbeat: poll the scores feed and stamp any decided tickets.
  // Runs on load + every tick while the tab is open; a closed tab settles on
  // the next visit — fine for a toy.
  const { data: matches } = useApi("/api/events", { pollMs: 60_000 });
  useEffect(() => {
    if (!matches) return;
    const settled = settle(matches);
    if (settled.length) {
      setToasts((ts) => [...ts, ...settled]);
    }
  }, [matches]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!toasts.length) return;
    const id = setTimeout(() => setToasts((ts) => ts.slice(1)), 6000);
    return () => clearTimeout(id);
  }, [toasts]);

  return (
    <div className="gamba">
      <header className="gamba-header" ref={headerRef}>
        <div className="container gamba-header__inner">
          <span className="gamba-brand"><span className="dice">🎲</span> GAMBA</span>
          <nav className="gamba-header__nav" aria-label="Gamba">
            {tabs.map((l) => (
              <NavLink key={l.to} to={l.to} end={l.end}
                className={({ isActive }) => `gamba-tab${isActive ? " active" : ""}`}>
                {t(l.key)}
              </NavLink>
            ))}
            <span className="gamba-chip" title={t("gamba.balance")}>{fmtG(balance)}</span>
            <button
              onClick={() => setLang(lang === "en" ? "zh" : "en")}
              aria-label="切换语言 / switch language"
              className="lang-toggle"
            >
              {lang === "en" ? "中文" : "EN"}
            </button>
          </nav>
        </div>
      </header>

      <div className="gamba-strap" role="note">{t("gamba.strap")}</div>

      {headerAway && (
        // duplicate of the header chip, so hide it from the accessibility tree
        <span className="gamba-chip gamba-chip--float" aria-hidden="true">
          {fmtG(balance)}
        </span>
      )}

      <main id="main" className="container">
        <Outlet />
      </main>

      <footer className="gamba-footer">
        <div className="container">
          <Disclaimer expanded />
          <p style={{ margin: "10px 0 0" }}>{t("gamba.disclaimer")}</p>
        </div>
      </footer>

      {toasts.length > 0 && (
        <div className="g-toasts" aria-live="polite">
          {toasts.map((b) => (
            <div key={b.id} className="g-toast">
              <span className={`g-stamp g-stamp--${b.status}`}>
                {t(`gamba.ticket.${b.status}`)}
              </span>
              <span>
                {t("gamba.toast.settled", {
                  match: `${b.homeName} v ${b.awayName}`,
                  amount: fmtG(b.returns),
                })}
              </span>
            </div>
          ))}
        </div>
      )}

    </div>
  );
}
