/**
 * Liquid Glass — how much glass this device gets (docs/STUDIO_UI.md § Liquid Glass; the CSS is in index.css).
 *
 *   <html data-glass="liquid | frosted | solid">   + html.lg-lens (the SVG edge lens, Chromium with a fine pointer)
 *
 * The inline script in web/index.html (and launcher.html) picks the first mode before first paint with the same rules
 * as `autoMode()` below minus the hardware probe; `installGlass()` refines it, injects the lens filter and wires the
 * specular highlight (pointer on desktops, tilt on phones). The Display menu can force a mode per browser
 * (`localStorage["deskdot.glass"]` = auto | liquid | frosted | solid).
 *
 * Rules: reduced transparency → solid. No backdrop-filter, the Android app's WebView (its blur let content show through
 * translucent bars — the bars must never be see-through there), or a low-end device (≤ 4 GB or ≤ 4 cores) → frosted:
 * a near-opaque fill, so text never sits on raw content. Otherwise liquid.
 */
import { useSyncExternalStore } from "react";

export type GlassPref = "auto" | "liquid" | "frosted" | "solid";
export type GlassMode = Exclude<GlassPref, "auto">;
export const GLASS_KEY = "deskdot.glass";
export const GLASS_CHOICES: { id: GlassPref; name: string; hint: string }[] = [
  { id: "auto", name: "Auto", hint: "Clear glass where this device draws it smoothly, frosted where it can't" },
  { id: "liquid", name: "Clear", hint: "Liquid Glass: bars and panels blur and bend what's behind them" },
  { id: "frosted", name: "Frosted", hint: "Glass without the blur: nearly opaque, lightest on the battery" },
  { id: "solid", name: "Solid", hint: "No transparency at all (also what Reduce transparency gives you)" },
];

const listeners = new Set<() => void>();
const media = (q: string) => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q) : null);
const reducedTransparency = media("(prefers-reduced-transparency: reduce)");
const finePointer = media("(pointer: fine)");

export function getGlassPref(): GlassPref {
  try {
    const v = localStorage.getItem(GLASS_KEY);
    if (v === "liquid" || v === "frosted" || v === "solid" || v === "auto") return v;
  } catch {
    /* storage blocked */
  }
  return "auto";
}

const supportsBlur = () =>
  typeof CSS !== "undefined" && (CSS.supports("backdrop-filter", "blur(1px)") || CSS.supports("-webkit-backdrop-filter", "blur(1px)"));
const inAndroid = () => !!(window as unknown as { DeskDotAndroid?: unknown }).DeskDotAndroid;
const lowEnd = () => {
  const nav = navigator as Navigator & { deviceMemory?: number };
  return (nav.deviceMemory !== undefined && nav.deviceMemory < 4) || (navigator.hardwareConcurrency || 8) <= 4;
};
const chromium = () => {
  const brands = (navigator as Navigator & { userAgentData?: { brands?: { brand: string }[] } }).userAgentData?.brands;
  return !!brands?.some((b) => /Chromium/i.test(b.brand));
};

/** The mode Auto picks on this device. */
export function autoMode(): GlassMode {
  if (reducedTransparency?.matches) return "solid";
  if (!supportsBlur() || inAndroid() || lowEnd()) return "frosted";
  return "liquid";
}

export const resolveGlass = (pref: GlassPref = getGlassPref()): GlassMode =>
  reducedTransparency?.matches ? "solid" : pref === "auto" ? autoMode() : pref === "liquid" && !supportsBlur() ? "frosted" : pref;

let current: GlassMode = "liquid";

function apply() {
  const root = document.documentElement;
  current = resolveGlass();
  root.dataset.glass = current;
  // the edge lens: Chromium renders `backdrop-filter: url(#svg)`; a fine pointer = a desktop with GPU headroom
  root.classList.toggle("lg-lens", current === "liquid" && chromium() && !!finePointer?.matches);
  listeners.forEach((l) => l());
}

export function setGlassPref(pref: GlassPref) {
  try {
    if (pref === "auto") localStorage.removeItem(GLASS_KEY);
    else localStorage.setItem(GLASS_KEY, pref);
  } catch {
    /* this session only */
  }
  apply();
}

/** The edge lens: a displacement map that is neutral in the middle and bends the backdrop toward the rim near every
 *  edge (red = x, green = y), applied before the blur. objectBoundingBox units: it fits any glass element. */
function injectLens() {
  if (document.getElementById("lg-lens")) return;
  const map =
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100' preserveAspectRatio='none'>" +
    "<linearGradient id='x'><stop offset='0' stop-color='#f00'/><stop offset='.07' stop-color='#800000'/><stop offset='.93' stop-color='#800000'/><stop offset='1' stop-color='#000'/></linearGradient>" +
    "<linearGradient id='y' x2='0' y2='1'><stop offset='0' stop-color='#0f0'/><stop offset='.16' stop-color='#008000'/><stop offset='.84' stop-color='#008000'/><stop offset='1' stop-color='#000'/></linearGradient>" +
    "<rect width='100' height='100' fill='url(#x)'/><rect width='100' height='100' fill='url(#y)' style='mix-blend-mode:screen'/></svg>";
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("width", "0");
  svg.setAttribute("height", "0");
  svg.style.cssText = "position:absolute;width:0;height:0;overflow:hidden;pointer-events:none";
  svg.innerHTML =
    `<filter id="lg-lens" x="0" y="0" width="1" height="1" primitiveUnits="objectBoundingBox" color-interpolation-filters="sRGB">` +
    `<feImage href="data:image/svg+xml,${encodeURIComponent(map)}" x="0" y="0" width="1" height="1" preserveAspectRatio="none" result="map"/>` +
    `<feDisplacementMap in="SourceGraphic" in2="map" scale="0.05" xChannelSelector="R" yChannelSelector="G"/></filter>`;
  document.body.appendChild(svg);
}

const GLASS = ".glass, .glass-thick, .glass-capsule, .surface, .tabbar, .phone-head, .sheet, .theme-fab-menu, .mini-now";

/** The specular spot on the rim follows the pointer over a glass element (desktops) — one delegated listener, at
 *  most one style write per frame, only on the element under the pointer. */
function wirePointer() {
  let el: HTMLElement | null = null;
  let x = 0;
  let y = 0;
  let raf = 0;
  const flush = () => {
    raf = 0;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--lg-x", `${(x - r.left).toFixed(0)}px`);
    el.style.setProperty("--lg-y", `${(y - r.top).toFixed(0)}px`);
  };
  document.addEventListener(
    "pointermove",
    (e) => {
      if (current !== "liquid" || e.pointerType !== "mouse") return;
      const hit = (e.target as Element | null)?.closest?.(GLASS) as HTMLElement | null;
      if (hit !== el) {
        el?.style.removeProperty("--lg-x");
        el?.style.removeProperty("--lg-y");
        el = hit;
      }
      x = e.clientX;
      y = e.clientY;
      if (el && !raf) raf = requestAnimationFrame(flush);
    },
    { passive: true },
  );
}

/** Phones: the light on the bars' rims slides a little as the phone tilts (≤ 15 writes a second, two elements, only
 *  while liquid and motion is allowed; Android Chrome needs no permission, iOS Safari asks — then we just skip it). */
function wireTilt() {
  if (finePointer?.matches || media("(prefers-reduced-motion: reduce)")?.matches || !("DeviceOrientationEvent" in window)) return;
  let last = 0;
  window.addEventListener(
    "deviceorientation",
    (e) => {
      const now = performance.now();
      if (current !== "liquid" || now - last < 66 || e.gamma === null) return;
      last = now;
      const g = Math.max(-30, Math.min(30, e.gamma ?? 0));
      const pos = `${(50 + g * 1.4).toFixed(0)}%`;
      document.querySelectorAll<HTMLElement>(".tabbar, .phone-head").forEach((n) => n.style.setProperty("--lg-x", pos));
    },
    { passive: true },
  );
}

export function installGlass() {
  apply();
  injectLens();
  wirePointer();
  wireTilt();
  reducedTransparency?.addEventListener?.("change", apply);
  finePointer?.addEventListener?.("change", apply);
  window.addEventListener("storage", (e) => e.key === GLASS_KEY && apply());
}

const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));
export const useGlassPref = () => useSyncExternalStore(subscribe, getGlassPref, getGlassPref);
export const useGlassMode = () => useSyncExternalStore(subscribe, () => current, () => current);
