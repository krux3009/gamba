import { Component, StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { LanguageProvider, useLang } from "./lib/i18n";

// One boundary around the whole app: a render throw anywhere becomes a reload
// prompt instead of a white screen. Class component — React still has no hook
// for error boundaries.
class ErrorBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <ErrorFallback /> : this.props.children;
  }
}

function ErrorFallback() {
  const { t } = useLang();
  return (
    <div style={{ maxWidth: 420, margin: "80px auto", padding: 24, textAlign: "center" }}>
      <h1>{t("error.title")}</h1>
      <p>{t("error.body")}</p>
      <button
        onClick={() => window.location.reload()}
        style={{
          padding: "8px 20px", borderRadius: 3, cursor: "pointer",
          background: "#2e4c8c", color: "#fff3e1", border: "none", fontWeight: 600,
        }}
      >
        {t("error.reload")}
      </button>
    </div>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <LanguageProvider>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </LanguageProvider>
  </StrictMode>
);
