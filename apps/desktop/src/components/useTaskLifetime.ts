import { useEffect, useRef } from "react";

/** Invalidate async task completions at lock time, before React unmounts. */
export function useTaskLifetime() {
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    const locked = () => { alive.current = false; };
    window.addEventListener("vault-ui-locked", locked);
    return () => { alive.current = false; window.removeEventListener("vault-ui-locked", locked); };
  }, []);
  return alive;
}
