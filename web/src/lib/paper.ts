/**
 * The paper panel: how the studio draws the 32×32 panel in light mode (docs/STUDIO_UI.md § Paper panel).
 *
 * The panel is emissive — colours glow on black. On a light page the studio can instead draw it as a "paper panel": the
 * unlit LEDs become a porcelain grid and every lit colour is re-mapped perceptually (OKLab / OKLCH), not inverted:
 *
 *  1. Split a colour into how lit it is (`v` = its brightest channel, 0..1) and its full-drive colour (the same colour
 *     with its brightest channel at 255 — the hue and saturation the app chose).
 *  2. The full-drive colour gets an ink: neutrals become the studio's near-black ink; chromatic colours keep their
 *     OKLCH hue and relative chroma at a lightness chosen for the hue (brighter hues a little lighter, so yellow and
 *     green stay told apart from red and blue), then darkened until it reads at ≥ 4.5:1 on the unlit-LED colour.
 *     Between the two (pastels) it blends by saturation, so a near-white pink becomes a near-black wine.
 *  3. The lit amount places the colour between the unlit LED and its ink — brighter on the panel = darker on paper, so
 *     the order of every app's contrasts is kept (content stays darker than any dim backdrop behind it). Chroma
 *     arrives faster than lightness, so dim colours (trails, glow, a dim red backdrop) stay clearly coloured tints —
 *     except near-black ones (≲ 3 % lit), which stay the plain ground as they look black on the panel.
 *
 * Results are cached per exact colour (frames reuse a few dozen colours), so a frame costs 1 024 Map lookups.
 * Only the studio's drawing changes: the panel itself and the engine's frames are never touched.
 */
import { useSyncExternalStore } from "react";

/** The paper panel's materials. `ground` is an unlit LED (and a black pixel in the Pixel / Glow looks). */
export const PAPER = {
  housing: "#f8f5ef", // the LED look's face between the LEDs, the mask between thumbnail dots
  ground: "#ebe6dc", // an unlit LED
  ink: "#1c1a22", // what full white becomes (the studio's ink-1)
} as const;

/** Minimum contrast of a fully lit colour against an unlit LED (WCAG 2 ratio). */
const MIN_CONTRAST = 4.5;

// ---------------------------------------------------------------- colour maths (sRGB ↔ linear ↔ OKLab)
const toLin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toSrgb = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.max(0, c) ** (1 / 2.4) - 0.055);
type V3 = [number, number, number];

function linToLab(r: number, g: number, b: number): V3 {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}
function labToLin(L: number, a: number, b: number): V3 {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076953058 * s,
  ];
}
const inGamut = ([r, g, b]: V3) => r >= -1e-4 && g >= -1e-4 && b >= -1e-4 && r <= 1.0001 && g <= 1.0001 && b <= 1.0001;
/** The most chroma sRGB can show at lightness L and hue h (radians). */
function maxChroma(L: number, h: number) {
  const ca = Math.cos(h), sa = Math.sin(h);
  let lo = 0, hi = 0.4;
  for (let i = 0; i < 18; i++) {
    const c = (lo + hi) / 2;
    if (inGamut(labToLin(L, c * ca, c * sa))) lo = c;
    else hi = c;
  }
  return lo;
}
/** Relative luminance (WCAG) of a linear-light colour. */
const lum = ([r, g, b]: V3) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
const contrast = (y1: number, y2: number) => (Math.max(y1, y2) + 0.05) / (Math.min(y1, y2) + 0.05);
const hexLin = (hex: string): V3 => [1, 3, 5].map((i) => toLin(parseInt(hex.slice(i, i + 2), 16) / 255)) as V3;
const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

const GROUND_LIN = hexLin(PAPER.ground);
const GROUND = linToLab(...GROUND_LIN);
const GROUND_Y = lum(GROUND_LIN);
const INK = linToLab(...hexLin(PAPER.ink));

/** Pack an OKLab colour into 0xRRGGBB, pulling chroma in (hue and lightness kept) until it fits sRGB. */
function pack(L: number, a: number, b: number): number {
  let lin = labToLin(L, a, b);
  if (!inGamut(lin)) {
    const c = Math.hypot(a, b), h = Math.atan2(b, a);
    const k = c > 0 ? maxChroma(L, h) / c : 0;
    lin = labToLin(L, a * k, b * k);
  }
  const to8 = (x: number) => Math.round(Math.min(1, Math.max(0, toSrgb(x))) * 255);
  return (to8(lin[0]) << 16) | (to8(lin[1]) << 8) | to8(lin[2]);
}

/** The ink a fully lit colour (brightest channel = 1, sRGB 0..1) becomes. OKLab. */
function inkFor(r: number, g: number, b: number): V3 {
  const [Lf, af, bf] = linToLab(toLin(r), toLin(g), toLin(b));
  const cf = Math.hypot(af, bf);
  let h = Math.atan2(bf, af);
  // darkened yellows read olive (the eye sees dark yellow as green-brown): lean them up to 14° toward gold
  const deg = (h * 180) / Math.PI;
  h -= (14 * Math.PI / 180) * smooth(70, 100, deg) * (1 - smooth(110, 135, deg));
  const sat = 1 - Math.min(r, g, b); // HSV saturation (the brightest channel is 1)
  const w = smooth(0, 0.6, sat); // 0 = neutral → ink, 1 = a full colour
  const rel = cf > 1e-4 ? Math.min(1, cf / Math.max(1e-4, maxChroma(Lf, h))) : 0;
  // the hue's lightness on paper: deep for blue / red, a little lighter for green / yellow (kept apart by lightness too)
  let L = 0.47 + 0.15 * smooth(0.45, 0.98, Lf);
  let tgt: V3 = [0, 0, 0];
  for (let i = 0; i < 40; i++) {
    const c = rel * maxChroma(L, h) * w;
    tgt = [INK[0] + (L - INK[0]) * w, INK[1] * (1 - w) + c * Math.cos(h), INK[2] * (1 - w) + c * Math.sin(h)];
    const lin = labToLin(...tgt);
    if (contrast(lum(lin.map((x) => Math.max(0, x)) as V3), GROUND_Y) >= MIN_CONTRAST || tgt[0] < 0.2) break;
    L -= 0.01; // too light to read on the unlit LEDs: darker until it does
  }
  return tgt;
}

/** The paper colour (0xRRGGBB) for an LED colour. Pure; see the file comment for the rules. */
export function paperColor(r: number, g: number, b: number): number {
  const v = Math.max(r, g, b) / 255;
  if (v < 3 / 255) return (parseInt(PAPER.ground.slice(1), 16));
  const t = inkFor(r / 255 / v, g / 255 / v, b / 255 / v);
  const a = 1 - (1 - v) ** 2; // how far toward the ink: brighter on the panel = darker on paper
  // colour arrives before darkness, so dim colours stay clearly coloured — but not near-black ones: a backdrop at 2 %
  // reads black on the panel and must stay (almost) the plain ground, whatever its hue
  const ac = a ** (1 - 0.45 * smooth(0.03, 0.2, v));
  return pack(GROUND[0] + (t[0] - GROUND[0]) * a, GROUND[1] + (t[1] - GROUND[1]) * ac, GROUND[2] + (t[2] - GROUND[2]) * ac);
}

// ---------------------------------------------------------------- the cache (a Map on exact colours)
const cache = new Map<number, number>();
/** Cached `paperColor` on a packed 0xRRGGBB. */
export function paperOf(rgb: number): number {
  let v = cache.get(rgb);
  if (v === undefined) {
    if (cache.size > 65536) cache.clear(); // photos / gradients: never let it grow without bound
    v = paperColor(rgb >> 16, (rgb >> 8) & 255, rgb & 255);
    cache.set(rgb, v);
  }
  return v;
}
/** `#rrggbb` → its paper `#rrggbb`. */
export const paperHex = (hex: string) => "#" + paperOf(parseInt(hex.replace("#", "").slice(0, 6), 16)).toString(16).padStart(6, "0");

/** Map an RGB frame (3 bytes per pixel) into `out` (same layout). Unlit pixels get the ground colour. */
export function paperFrame(src: Uint8Array, out: Uint8Array): Uint8Array {
  for (let i = 0; i < src.length; i += 3) {
    const p = paperOf((src[i] << 16) | (src[i + 1] << 8) | src[i + 2]);
    out[i] = p >> 16;
    out[i + 1] = (p >> 8) & 255;
    out[i + 2] = p & 255;
  }
  return out;
}

/** Map RGBA pixels in place (alpha kept; a transparent pixel is an unlit LED and becomes opaque ground). */
export function paperRgba(px: Uint8ClampedArray | Uint8Array) {
  for (let i = 0; i < px.length; i += 4) {
    const k = px[i + 3] / 255;
    const p = paperOf((Math.round(px[i] * k) << 16) | (Math.round(px[i + 1] * k) << 8) | Math.round(px[i + 2] * k));
    px[i] = p >> 16;
    px[i + 1] = (p >> 8) & 255;
    px[i + 2] = p & 255;
    px[i + 3] = 255;
  }
}

// ---------------------------------------------------------------- the switch: paper (default) or the dark device
/**
 * Panel preview in light mode (Display menu → More): `paper` (default) draws the paper panel while the studio is light;
 * `device` keeps the black LED device in both themes. Per browser, `localStorage["deskdot.panelLight"]`.
 * Active = `<html data-theme="light">` and pref `paper`; mirrored to `<html data-panel="paper|device">` for CSS.
 */
export type PanelLight = "paper" | "device";
export const PANEL_LIGHT_KEY = "deskdot.panelLight";
export const DEFAULT_PANEL_LIGHT: PanelLight = "paper";
export const PANEL_LIGHT_LABEL: Record<PanelLight, string> = { paper: "Paper", device: "Dark device" };
export const PANEL_LIGHT_HINT: Record<PanelLight, string> = {
  paper: "In light mode the preview is drawn like ink on porcelain, its colours re-tuned to read on white",
  device: "The preview stays a black LED panel, also in light mode",
};

function readPref(): PanelLight {
  try {
    return localStorage.getItem(PANEL_LIGHT_KEY) === "device" ? "device" : "paper";
  } catch {
    return DEFAULT_PANEL_LIGHT;
  }
}
let pref: PanelLight = typeof window !== "undefined" ? readPref() : DEFAULT_PANEL_LIGHT;
let paper = false;
let light = false; // <html data-theme="light">, whoever set it
const listeners = new Set<() => void>();

function sync() {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const isLight = root.dataset.theme === "light";
  const next = isLight && pref === "paper";
  root.dataset.panel = next ? "paper" : "device";
  if (next === paper && isLight === light) return;
  paper = next;
  light = isLight;
  listeners.forEach((l) => l());
}

export function setPanelLight(p: PanelLight) {
  pref = p;
  try {
    localStorage.setItem(PANEL_LIGHT_KEY, p);
  } catch {
    /* private mode: this session only */
  }
  sync();
  listeners.forEach((l) => l());
}

let installed = false;
/** Follow `<html data-theme>` (whoever sets it) and other tabs changing the choice. Idempotent. */
export function installPaper() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  sync();
  new MutationObserver(sync).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  window.addEventListener("storage", (e) => {
    if (e.key !== PANEL_LIGHT_KEY) return;
    pref = readPref();
    sync();
    listeners.forEach((l) => l());
  });
}

export const isPaper = () => paper;
export const onPaper = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));
/** Is the paper panel on screen now (light theme + the Paper choice)? */
export const usePaper = () => useSyncExternalStore(onPaper, isPaper, isPaper);
/** The stored choice. */
export const usePanelLight = () => useSyncExternalStore(onPaper, () => pref, () => pref);
/** Is the page light now (`<html data-theme>` as it is on screen — the header logo follows it)? */
export const useLightPage = () => useSyncExternalStore(onPaper, () => light, () => light);

/**
 * Cross-fade a canvas into its next look: `overlay` (an absolutely positioned canvas with the same offset parent as
 * `from`) is laid exactly over `from`, takes a copy of what is on screen now and fades out over ~0.4 s while `from` is
 * redrawn underneath. Instant with reduced motion.
 */
export function crossFade(from: HTMLCanvasElement | null, overlay: HTMLCanvasElement | null) {
  if (!from || !overlay || !from.width || !overlay.animate) return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  Object.assign(overlay.style, {
    left: `${from.offsetLeft}px`, top: `${from.offsetTop}px`, width: `${from.offsetWidth}px`, height: `${from.offsetHeight}px`,
  });
  overlay.width = from.width;
  overlay.height = from.height;
  overlay.getContext("2d")?.drawImage(from, 0, 0);
  overlay.getAnimations().forEach((a) => a.cancel());
  overlay.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 420, easing: "cubic-bezier(0.4, 0, 0.2, 1)", fill: "forwards" });
}
