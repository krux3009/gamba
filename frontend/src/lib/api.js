// Data fetch with a tiny in-memory TTL cache and one cold-start retry —
// Render's free tier sleeps; the first request after a nap can take ~20s.

export const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Low-level fetch shared with sync.js: one timeout constant, JSON header when
// a body is present, caller headers merged on top.
export function request(path, opts = {}) {
  const headers = {
    ...(opts.body ? { "Content-Type": "application/json" } : {}),
    ...(opts.headers || {}),
  };
  return fetch(API_BASE + path, {
    signal: AbortSignal.timeout(25_000),
    ...opts,
    headers,
  });
}

const cache = new Map(); // path -> { at, data }
const TTL = 60 * 1000;

export async function apiGet(path, { retry = true, bypassCache = false } = {}) {
  if (!bypassCache) {
    const hit = cache.get(path);
    if (hit && Date.now() - hit.at < TTL) return hit.data;
  }
  try {
    const res = await request(path);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    cache.set(path, { at: Date.now(), data });
    return data;
  } catch (err) {
    if (retry) {
      await new Promise((r) => setTimeout(r, 20_000));
      return apiGet(path, { retry: false });
    }
    throw err;
  }
}
