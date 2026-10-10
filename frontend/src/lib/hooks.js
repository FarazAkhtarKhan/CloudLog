import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

export const LiveContext = createContext({ live: true, session: null, pulse: null });
export const useLive = () => useContext(LiveContext);

/**
 * Fetch on mount, whenever `deps` change, and every `intervalMs` while live.
 * Keeps the previous data while refreshing so the screen never flashes empty.
 */
export function usePoll(fetcher, deps, intervalMs) {
  // Callers pass primitive values (filters, IDs), so a string key captures every change.
  const depsKey = JSON.stringify(deps);
  const [state, setState] = useState({ data: null, error: null, key: null });
  const latest = useRef({ fetcher, depsKey });
  useEffect(() => {
    latest.current = { fetcher, depsKey };
  });

  const reload = useCallback(async () => {
    const { fetcher: fetchNow, depsKey: key } = latest.current;
    try {
      const data = await fetchNow();
      setState({ data, error: null, key });
      return data;
    } catch (error) {
      setState((s) => ({ ...s, error, key }));
      return null;
    }
  }, []);

  useEffect(() => {
    reload();
  }, [depsKey, reload]);

  useEffect(() => {
    if (!intervalMs) return undefined;
    const timer = setInterval(reload, intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs, reload]);

  // Loading until a response for the *current* filters has arrived.
  return { data: state.data, error: state.error, loading: state.key !== depsKey, reload };
}

/** Re-render every `ms` so relative times ("12s ago") stay fresh. */
export function useTick(ms = 5000) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), ms);
    return () => clearInterval(t);
  }, [ms]);
}
