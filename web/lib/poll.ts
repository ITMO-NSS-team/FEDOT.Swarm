import { useCallback, useEffect, useRef, useState } from "preact/hooks";

/** Polls a JSON endpoint while `active`, one request in flight at a time, and once more
 * after it turns inactive so the final state lands. A response from an older url or a
 * cancelled cycle is dropped rather than applied out of order. */
export function usePoll<T>(
  url: string | null,
  active: boolean,
  intervalMs = 2000,
): { data: T | null; error: string | null; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const cycle = useRef(0);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!url) return;
    const mine = ++cycle.current;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;

    const pull = async () => {
      if (busy) return;
      busy = true;
      try {
        const response = await fetch(url, { signal: controller.signal });
        const text = await response.text();
        let body: unknown = null;
        try {
          body = JSON.parse(text);
        } catch {
          throw new Error(`Unexpected reply (${response.status})`);
        }
        if (!response.ok) {
          const detail = (body as { error?: string })?.error;
          throw new Error(detail ?? `Request failed (${response.status})`);
        }
        if (mine === cycle.current) {
          setData(body as T);
          setError(null);
        }
      } catch (failure) {
        if (controller.signal.aborted || mine !== cycle.current) return;
        setError(
          failure instanceof Error ? failure.message : "The run is unreachable",
        );
      } finally {
        busy = false;
        if (active && mine === cycle.current && !controller.signal.aborted) {
          timer = setTimeout(pull, intervalMs);
        }
      }
    };
    pull();
    return () => {
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [url, active, intervalMs, nonce]);

  return { data, error, refresh };
}
