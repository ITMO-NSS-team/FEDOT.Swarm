import { useEffect } from "preact/hooks";

/** Reloads the Runs page while any run is still going, so its states and scores move
 * without a hand on the refresh key. */
export function RunsRefresh({ active }: { active: boolean }) {
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => location.reload(), 5000);
    return () => clearTimeout(timer);
  }, [active]);
  return null;
}
