/**
 * The phone tab bar's selection bubble (components/TabBar.tsx): the maths, kept pure so tests/js/tab_drag.test.mjs can
 * run it in node. Positions are the bubble's left edge in px inside the bar's padding box; slot = one tab's width.
 *
 *   drag     the bubble follows the finger through a spring (springStep), rubber-banding past the first / last tab
 *   release  it snaps to the tab nearest where it would coast to (releaseTab), and that tab opens
 *   tap      the bubble springs over to the tapped tab: a compositor animation whose easing is the same spring,
 *            sampled into a CSS linear() curve (springEasing), so a heavy tab render never stalls it
 */

/** A spring's state: position and velocity (px, px/s). */
export type Spring = { x: number; v: number };

/** Stiffness and damping per unit mass: lightly under-damped (ζ ≈ 0.75) — a small, quick overshoot. */
export const SPRING = { k: 420, c: 31 };

/** A finger has to travel this far sideways (and more sideways than up) before a press becomes a drag. */
export const DRAG_SLOP = 6;

/** Advance a spring toward `target` by `dt` seconds (semi-implicit Euler, sub-stepped so a long frame stays stable). */
export function springStep(s: Spring, target: number, dt: number, k = SPRING.k, c = SPRING.c): Spring {
  let { x, v } = s;
  let left = Math.max(0, Math.min(dt, 0.064));
  while (left > 1e-6) {
    const h = Math.min(left, 1 / 240);
    v += (-k * (x - target) - c * v) * h;
    x += v * h;
    left -= h;
  }
  return { x, v };
}

/** True once the spring is at rest on its target (within half a pixel, barely moving). */
export const settled = (s: Spring, target: number) => Math.abs(s.x - target) < 0.5 && Math.abs(s.v) < 8;

/** Each tab's width inside a bar `inner` px wide. */
export const slotWidth = (inner: number, count: number) => (count > 0 ? inner / count : 0);

/** The bubble's left edge when it sits on tab `index`. */
export const slotX = (index: number, slot: number) => index * slot;

/** The tab whose slot the bubble (left edge `x`) mostly covers. */
export function nearestTab(x: number, slot: number, count: number): number {
  if (slot <= 0 || count <= 0) return 0;
  return Math.max(0, Math.min(count - 1, Math.round(x / slot)));
}

/** Past an end the bubble follows the finger less and less (iOS-style rubber band), at most `limit` px. */
export function rubber(over: number, limit: number): number {
  if (over === 0 || limit <= 0) return 0;
  const k = limit * (1 - 1 / (Math.abs(over) / limit + 1));
  return Math.sign(over) * k;
}

/** Where the bubble wants to be while a finger at `fingerX` drags it, holding it `grab` px from its left edge. */
export function dragTarget(fingerX: number, grab: number, slot: number, count: number): number {
  const max = slot * (count - 1);
  const x = fingerX - grab;
  if (x < 0) return rubber(x, slot * 0.35);
  if (x > max) return max + rubber(x - max, slot * 0.35);
  return x;
}

/** On release the bubble coasts a little with the finger's velocity (a flick moves one tab further). */
export const releaseTab = (x: number, v: number, slot: number, count: number) => nearestTab(x + v * 0.09, slot, count);

/** A press turns into a drag once the finger moved past the slop, mostly sideways. */
export const isDrag = (dx: number, dy: number) => Math.abs(dx) > DRAG_SLOP && Math.abs(dx) > Math.abs(dy);

/** The liquid squash and stretch at velocity `v` (px/s): wider and flatter the faster it moves (area roughly kept). */
export function stretch(v: number): { sx: number; sy: number } {
  const s = Math.min(0.22, Math.abs(v) / 5200);
  return { sx: 1 + s, sy: 1 - s * 0.55 };
}

/**
 * The spring from 0 to 1 as a CSS `linear()` easing, starting with velocity `v0` (in units of the whole move per second,
 * so a bubble already moving toward the target keeps its speed). Returns the easing and its duration in ms.
 */
export function springEasing(v0 = 0, k = SPRING.k, c = SPRING.c): { easing: string; ms: number } {
  const dt = 1 / 120;
  let s: Spring = { x: 0, v: v0 };
  const pts: number[] = [0];
  let t = 0;
  while (t < 2) {
    s = springStep(s, 1, dt, k, c);
    t += dt;
    pts.push(s.x);
    if (t > 0.1 && Math.abs(1 - s.x) < 0.002 && Math.abs(s.v) < 0.02) break;
  }
  pts[pts.length - 1] = 1;
  // keep it short: every other sample is plenty for a curve this smooth
  const out = pts.filter((_, i) => i % 2 === 0 || i === pts.length - 1).map((p) => +p.toFixed(4));
  return { easing: `linear(${out.join(", ")})`, ms: Math.round(t * 1000) };
}
