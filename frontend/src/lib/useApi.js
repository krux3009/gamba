import { useEffect, useState } from "react";

import { apiGet } from "./api";

// pollMs (optional): re-fetch on an interval, bypassing the in-memory cache so a
// poll actually hits the network. A failed poll keeps the data already on screen
// rather than flipping to an error — only the initial load can surface an error.
export function useApi(path, { pollMs } = {}) {
  const [state, setState] = useState({ data: null, loading: true, error: null });

  useEffect(() => {
    let alive = true;
    const load = (bypassCache = false) =>
      apiGet(path, { bypassCache })
        .then((data) => alive && setState({ data, loading: false, error: null }))
        .catch((error) =>
          alive && setState((s) => (s.data ? s : { data: null, loading: false, error })));

    setState({ data: null, loading: true, error: null });
    load();
    const id = pollMs ? setInterval(() => load(true), pollMs) : null;
    return () => {
      alive = false;
      if (id) clearInterval(id);
    };
  }, [path, pollMs]);

  return state;
}
