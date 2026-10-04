import { useEffect, useState } from "react";

/** Live `matchMedia` state. */
export function useMedia(query: string) {
  const [on, setOn] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const update = () => setOn(m.matches);
    update();
    m.addEventListener("change", update);
    return () => m.removeEventListener("change", update);
  }, [query]);
  return on;
}

/** Phone layout (bottom tabs) below the `md` breakpoint — the same line as `isPhone()` in lib/store. */
export const usePhone = () => useMedia("(max-width: 767.98px)");
