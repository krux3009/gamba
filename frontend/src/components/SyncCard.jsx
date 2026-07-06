// Cross-device sync card (My bets page). Two states: unlinked — enable sync or
// link with a code someone minted elsewhere; linked — show the code (it IS the
// account) and the live sync status.
import { useState } from "react";

import { useGamba } from "../lib/GambaContext";
import { displayCode } from "../lib/sync";
import { useLang } from "../lib/i18n";

export default function SyncCard() {
  const { t } = useLang();
  const { syncCode, syncStatus, enableSync, linkWithCode, unlink } = useGamba();
  const [input, setInput] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  if (syncCode) {
    const dot = syncStatus === "error" ? "err" : syncStatus === "pending" ? "pending" : "ok";
    return (
      <div className="g-sync">
        <div className="g-sync__head">
          <span className="lbl">{t("gamba.sync.codeLabel")}</span>
          <span className={`g-sync__dot g-sync__dot--${dot}`} />
          <span className="g-sync__status">
            {t(`gamba.sync.status.${dot === "ok" ? "synced" : dot === "pending" ? "pending" : "error"}`)}
          </span>
        </div>
        <div className="g-sync__code">{displayCode(syncCode)}</div>
        <div className="g-sync__row">
          <button
            className="g-btn"
            onClick={() => {
              navigator.clipboard?.writeText(displayCode(syncCode));
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
          >
            {copied ? t("gamba.sync.copied") : t("gamba.sync.copy")}
          </button>
          <button
            className="g-btn g-btn--danger"
            onClick={() => window.confirm(t("gamba.sync.unlinkConfirm")) && unlink()}
          >
            {t("gamba.sync.unlink")}
          </button>
        </div>
      </div>
    );
  }

  const run = async (action) => {
    setBusy(true);
    setErr(null);
    const e = await action();
    setBusy(false);
    if (e) setErr(e);
  };

  const submitLink = () => {
    if (!input.trim() || busy) return;
    if (!window.confirm(t("gamba.sync.linkConfirm"))) return;
    run(() => linkWithCode(input));
  };

  return (
    <div className="g-sync">
      <div className="g-sync__head">
        <span className="lbl">{t("gamba.sync.title")}</span>
      </div>
      <p className="g-sync__blurb">{t("gamba.sync.blurb")}</p>
      <div className="g-sync__row">
        <button className="g-btn" disabled={busy} onClick={() => run(enableSync)}>
          {t("gamba.sync.enable")}
        </button>
      </div>
      <div className="g-sync__row">
        <span className="g-sync__or">{t("gamba.sync.haveCode")}</span>
        <input
          className="g-sync__input"
          value={input}
          placeholder={t("gamba.sync.codePlaceholder")}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && submitLink()}
        />
        <button className="g-btn" disabled={busy || !input.trim()} onClick={submitLink}>
          {t("gamba.sync.link")}
        </button>
      </div>
      {err && <p className="g-sync__err">{t(`gamba.sync.err.${err}`)}</p>}
    </div>
  );
}
