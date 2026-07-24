import { useEffect, useRef, useState } from "react";

/**
 * Polls `fetcher` every `intervalMs` while `shouldContinue(result)` is true.
 * Used for documents stuck in "pending"/"processing" — stops automatically
 * once the backend reports "completed"/"failed".
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  shouldContinue: (result: T | null) => boolean,
  intervalMs = 3000
): { data: T | null; error: Error | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      try {
        const result = await fetcherRef.current();
        if (stopped) return;
        setData(result);
        setError(null);
        if (shouldContinue(result)) {
          timer = setTimeout(tick, intervalMs);
        }
      } catch (err) {
        if (!stopped) setError(err as Error);
      }
    }

    tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return { data, error };
}
