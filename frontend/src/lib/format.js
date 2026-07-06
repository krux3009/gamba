// Kickoffs are stored UTC; render in the visitor's local time.
// locale: undefined = browser default (English UI), "zh-CN" when 中文 is on —
// toLocaleString natively renders 周五 / 6月12日 forms with the same options.

export function localKickoff(iso, locale) {
  return new Date(iso).toLocaleString(locale, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Which local calendar day a kickoff belongs to (YYYY-MM-DD). Grouping must
// agree with the local times the cards display — keying on the UTC date puts
// a 22:00Z match under "yesterday" for viewers east of Greenwich.
export function localDayKey(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function localDateHeading(isoDate, locale) {
  return new Date(isoDate + "T12:00:00Z").toLocaleDateString(locale, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}
