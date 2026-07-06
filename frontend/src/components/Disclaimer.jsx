import { useLang } from "../lib/i18n";

export default function Disclaimer({ expanded = false }) {
  const { t } = useLang();
  return (
    <p style={styles.note}>
      <strong>{t("disclaimer.ps")}</strong> {t("disclaimer.base")}
      {expanded ? t("disclaimer.expanded") : t("disclaimer.short")}
    </p>
  );
}

const styles = {
  note: {
    color: "var(--g-ink-soft)",
    fontSize: 12,
    lineHeight: 1.5,
    borderLeft: "3px solid var(--g-line)",
    paddingLeft: 10,
    margin: "12px 0 0",
  },
};
