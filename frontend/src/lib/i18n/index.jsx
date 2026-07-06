// Hand-rolled i18n: a context, two dictionaries, one helper.
// Deliberately not react-i18next — ~100 keys don't justify a dependency.
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { EN } from "./en";
import { ZH } from "./zh";

const DICTS = { en: EN, zh: ZH };
const STORAGE_KEY = "gamba.lang";

const LanguageContext = createContext(null);

function initialLang() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "en" || saved === "zh") return saved;
  return navigator.language?.startsWith("zh") ? "zh" : "en";
}

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(initialLang);

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const value = useMemo(() => {
    const setLang = (next) => {
      localStorage.setItem(STORAGE_KEY, next);
      setLangState(next);
    };
    // missing zh keys degrade to English, never to a raw key on screen
    const t = (key, vars) => {
      const entry = DICTS[lang][key] ?? DICTS.en[key] ?? key;
      return typeof entry === "function" ? entry(vars ?? {}) : entry;
    };
    return {
      lang, setLang, t,
      dateLocale: lang === "zh" ? "zh-CN" : undefined,
    };
  }, [lang]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLang() {
  return useContext(LanguageContext);
}
