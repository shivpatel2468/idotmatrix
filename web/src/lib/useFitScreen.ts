import { type RefObject, useLayoutEffect } from "react";

/**
 * Keeps a popover on the screen: caps its height to the room between its anchored edge and the window's edge (less
 * `margin`) instead of letting it run off the page (the studio's page itself never scrolls). Make the popover a flex
 * column and let an INNER area scroll (`min-h-0 overflow-y-auto`): `.surface` paints its glass on ::before, which
 * would scroll away (and a backdrop filter on a scrolling area lags). `side` is the way it opens: "down" from a key
 * in the top bar, "up" from one at the bottom. A tighter max-height from its classes still wins. Re-fits when the
 * window or the phone keyboard resizes.
 */
export function useFitScreen(ref: RefObject<HTMLElement | null>, open: boolean, side: "down" | "up" = "down", margin = 12) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!open || !el) return;
    const fit = () => {
      el.style.maxHeight = "";
      const cap = parseFloat(getComputedStyle(el).maxHeight); // "none" → NaN
      const r = el.getBoundingClientRect();
      const h = window.visualViewport?.height ?? window.innerHeight;
      const room = Math.max(120, Math.floor(side === "down" ? h - r.top - margin : r.bottom - margin));
      el.style.maxHeight = `${Number.isNaN(cap) ? room : Math.min(cap, room)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    window.visualViewport?.addEventListener("resize", fit);
    return () => {
      window.removeEventListener("resize", fit);
      window.visualViewport?.removeEventListener("resize", fit);
    };
  }, [ref, open, side, margin]);
}
