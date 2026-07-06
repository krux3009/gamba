// Display names for the competitions the backend ingests (config.py's
// COMPETITIONS dict is the source of truth for WHAT is fetched; this map only
// labels it). Unknown slugs render as-is, so a new backend competition still
// works before this map learns its name.
const COMP_LABEL = {
  "eng.1": { en: "Premier League", zh: "英超" },
  "esp.1": { en: "La Liga", zh: "西甲" },
  "uefa.champions": { en: "Champions League", zh: "欧冠" },
};

export const compLabel = (slug, lang) =>
  COMP_LABEL[slug]?.[lang] ?? COMP_LABEL[slug]?.en ?? slug;
