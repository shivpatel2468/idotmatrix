/**
 * Chip flights for the host's own seat (RightWing → Play) — the same feel as the phones (casino.html "chip flights"):
 * a chip flies on an arc from the rack to the spot and the stack squashes when it lands, undo / clear / take-back fly
 * the chips home, rebet flies them out, a chip dragged from the rack follows the pointer (a ghost) and the spot under
 * it lights up, a stack dragged off its spot gets a red ✕. Other players' chips drop onto their spot in their colour.
 * Web Animations on transform / opacity only (60 fps), in a fixed layer on <body>; nothing at all with reduced motion.
 */
import type { PointerEvent as ReactPointerEvent } from "react";
import { chipColor } from "./bits";
import { short } from "./state";

export type Pt = [number, number];

export const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** When the host's own chips last moved here: sounds.ts skips its "the totals went up" clack right after (no doubles). */
export let localChipAt = -1e9;

let fx: HTMLDivElement | null = null;
function layer(): HTMLDivElement {
  if (fx && fx.isConnected) return fx;
  fx = document.createElement("div");
  fx.className = "cz-fx";
  fx.setAttribute("aria-hidden", "true");
  document.body.append(fx);
  return fx;
}

/** The theme's accent (the ghost's ring), read from the casino view so the layer on <body> matches it. */
function accent(): string {
  const cz = document.querySelector(".cz");
  return (cz && getComputedStyle(cz).getPropertyValue("--gold").trim()) || "#ffcc33";
}

/** How tall a stack of `n` looks: one edge per chip it takes (greedy, at most 6 under the top one) — as on the phones. */
export function stackShadow(n: number): string {
  let left = Math.max(0, Math.round(Number(n) || 0));
  let k = 0;
  for (const c of [500, 100, 25, 5, 1]) while (left >= c && k < 7) { left -= c; k++; }
  const edges: string[] = [];
  for (let i = 1; i < Math.min(7, Math.max(1, k)); i++) edges.push(`0 ${i * 2}px 0 ${i % 2 ? "rgba(255,255,255,.55)" : "rgba(0,0,0,.35)"}`);
  return [...edges, `0 ${Math.max(1, k - 1) * 2 + 2}px 0 rgba(0,0,0,.5)`].join(",");
}

/** One flying chip element: a value chip, or a player's colour (`color`) for someone else's chip. */
export function chipEl(amount: number | "all", opts: { color?: string; ghost?: boolean } = {}): HTMLDivElement {
  const e = document.createElement("div");
  e.className = opts.ghost ? "cz-flychip cz-flychip-ghost" : "cz-flychip";
  const col = opts.color ?? chipColor(amount === "all" ? "all" : amount);
  e.style.setProperty("--chip", col);
  if (col === chipColor(1)) e.dataset.light = "1"; // the white 1-chip: dark numerals
  if (opts.ghost) e.style.setProperty("--ring", accent());
  const b = document.createElement("b");
  b.textContent = amount === "all" ? "ALL" : short(amount);
  e.append(b);
  layer().append(e);
  return e;
}

export const centerOf = (el: Element | null | undefined): Pt | null => {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width || r.height ? [r.left + r.width / 2, r.top + r.height / 2] : null;
};

/** Put a ghost chip a little above the pointer (so the spot under it stays visible). */
export function placeGhost(g: HTMLElement, x: number, y: number) {
  g.style.transform = `translate(${x}px,${y - 26}px)`;
}

/** A chip flies on an arc from `from` to `to` (client coords). */
export function fly(amount: number | "all", from: Pt | null, to: Pt | null,
  o: { s0?: number; s1?: number; fade?: boolean; ms?: number; color?: string; local?: boolean; done?: () => void } = {}) {
  if (o.local !== false) localChipAt = performance.now();
  if (!from || !to || reducedMotion()) { o.done?.(); return; }
  const e = chipEl(amount, { color: o.color });
  const [x0, y0] = from, [x1, y1] = to, dx = x1 - x0, dy = y1 - y0, dist = Math.hypot(dx, dy);
  const lift = Math.min(110, 30 + dist * 0.28), s0 = o.s0 ?? 1, s1 = o.s1 ?? 1;
  const kf: Keyframe[] = [];
  for (let i = 0; i <= 10; i++) {
    const k = i / 10, x = x0 + dx * k, y = y0 + dy * k - lift * 4 * k * (1 - k), sc = s0 + (s1 - s0) * k + 0.16 * Math.sin(Math.PI * k);
    kf.push({ transform: `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) scale(${sc.toFixed(3)})`, opacity: o.fade && k > 0.8 ? (1 - k) / 0.2 : 1 });
  }
  const an = e.animate(kf, { duration: o.ms ?? Math.min(560, Math.max(260, 240 + dist * 0.4)), easing: "cubic-bezier(.35,.1,.35,1)" });
  let fin = false;
  const end = () => { if (fin) return; fin = true; e.remove(); o.done?.(); };
  an.onfinish = end;
  an.oncancel = end;
  window.setTimeout(end, 1200);
}

/** Someone else's chip drops onto a spot in their colour (from a little above it). */
export function drop(color: string, amount: number, to: Pt | null, done?: () => void) {
  if (!to) return;
  fly(amount, [to[0], to[1] - 70], to, { s0: 1.35, s1: 0.75, ms: 360, color, local: false, done });
}

/** A stack squashes and springs back when a chip lands on it. */
export function bump(el: Element | null | undefined) {
  if (!el || reducedMotion() || !(el as HTMLElement).animate) return;
  (el as HTMLElement).animate(
    [{ transform: "none" }, { transform: "translateY(3px) scale(1.16,.82)" }, { transform: "translateY(-5px) scale(.95,1.06)" }, { transform: "none" }],
    { duration: 320, easing: "ease-out" },
  );
}

/** pointermove at most once per frame: the newest event wins. */
export function perFrame<E>(fn: (e: E) => void): (e: E) => void {
  let ev: E | null = null, id = 0;
  return (e: E) => {
    ev = e;
    if (!id) id = requestAnimationFrame(() => { id = 0; const x = ev; ev = null; if (x) fn(x); });
  };
}

/** A bet gesture starts only with the primary button / a finger / a pen tip. */
export const primary = (e: PointerEvent | ReactPointerEvent) => e.isPrimary !== false && (e.pointerType !== "mouse" || e.button === 0);
