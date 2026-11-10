/**
 * Liquid Glass after Glisse — the phone app's glass (docs/STUDIO_UI.md § Liquid Glass; CSS: index.css § "Glisse").
 *
 * Adapted from Glisse by Kelvin Zhang (https://github.com/0kzh/glisse, MIT licence: docs/licenses/glisse.txt,
 * THIRD_PARTY_NOTICES.md): its rim light (`rimMap`) and its backdrop lens (`lensMap` and the SVG filter graph), as
 * plain TypeScript — the same code as the website's (site/main.js § 5).
 *
 *   rim   a thin white line lit from the top left, drawn once per size into a PNG and set as `--lg-rim-over` on the
 *         element ([data-rim]); index.css shows it in the element's ::after ring. Static: costs nothing per frame.
 *         Its strength is `--lg-rim-shine` (light and dark differ); repainted when the theme changes.
 *   lens  near the rim the glass shows the backdrop from further in, by the slope of a shallow dome, as a thick pane
 *         does: a displacement map per size and an SVG filter, set as `--lg-bend: url(#…)` ([data-bent]) for the
 *         element's backdrop-filter. `backdrop-filter: url()` is Chromium only (Chrome, Edge, the Android app's
 *         WebView); elsewhere nothing is set and the glass keeps its blur. `split` adds Glisse's colour split (three
 *         rays, red bending a little further than blue: six displacement passes) — only on small glass, the tab
 *         bar's bubble; wide bars bend with one ray (two passes), which measured as cheap as no lens while
 *         scrolling (the website's numbers: site/main.js § 5).
 *
 * Maps are drawn when the page is idle and again when the element changes size; nothing runs per frame. Reduced
 * transparency: the CSS turns the lens off (and the maps are never needed).
 */

export interface Shape {
  w: number;
  h: number;
  r: number;
}

const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));

/** Signed distance to a rounded rectangle centred on the origin; negative inside. */
export function dist(x: number, y: number, hw: number, hh: number, r: number): number {
  const qx = Math.abs(x) - hw + r;
  const qy = Math.abs(y) - hh + r;
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
}

const RIM = 1.22;

/** Glisse's rim light as RGBA (white, alpha = light): brightest at the edge, gone 1.2 px in; the top and left sides
 *  lit and the bottom and right by reflection, fading out over the top-right and bottom-left corners. */
export function rimPixels({ w, h, r }: Shape, shine: number, d: number): { cols: number; rows: number; data: Uint8ClampedArray } {
  const cols = Math.max(1, Math.round(w * d));
  const rows = Math.max(1, Math.round(h * d));
  const data = new Uint8ClampedArray(cols * rows * 4);
  const hw = w / 2;
  const hh = h / 2;
  const c = clamp(r, 0, Math.min(hw, hh));
  const half = 0.5 / d;
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const x = ((col + 0.5) / cols) * w - hw;
      const y = ((row + 0.5) / rows) * h - hh;
      const depth = -dist(x, y, hw, hh, c);
      if (depth < -half || depth > 2 * RIM) continue;
      const qx = Math.abs(x) - hw + c;
      const qy = Math.abs(y) - hh + c;
      let nx = 0;
      let ny = 0;
      if (qx > 0 && qy > 0) {
        const l = Math.hypot(qx, qy);
        nx = (Math.sign(x) * qx) / l;
        ny = (Math.sign(y) * qy) / l;
      } else if (qx > qy) nx = Math.sign(x);
      else ny = Math.sign(y);
      const facing = Math.abs(nx + ny);
      const along = Math.max(0, depth) / (RIM * Math.sqrt(Math.max(1, facing)));
      const cover = clamp((depth + half) * d, 0, 1);
      const light = along < 1 ? shine * Math.min(1, facing) ** 1.5 * (1 - along ** 1.5) * cover : 0;
      if (light <= 0) continue;
      const i = (row * cols + col) * 4;
      data[i] = data[i + 1] = data[i + 2] = 255;
      data[i + 3] = Math.round(255 * light);
    }
  }
  return { cols, rows, data };
}

/** How the lens bends: the pull reaches `strength` × the shorter side, in a band `depth` × it wide, along a dome
 *  that sags `dome` × it; red bends `dispersion` / 5 further than blue (Glisse's glass defaults). */
export const LENS = { strength: 0.45, dispersion: 0.4, depth: 0.25, dome: 0.5 };
export type LensShape = typeof LENS;
/** Glisse's tab bar lens (its src/internal/segments.tsx): a narrow band at the rim, no dome, a strong colour split —
 *  it bends what crosses its rim along it and leaves the labels inside it sharp. */
export const TAB_LENS: LensShape = { strength: 0.2, dispersion: 2, depth: 0.08, dome: 0.01 };

const erf = (x: number) => Math.tanh(1.7724538509 * x);

function arc(sag: number, half: number) {
  const radius = (half * half + sag * sag) / (2 * sag);
  let sum = 0;
  for (let i = 0; i <= 200; i++) {
    const x = (i / 200) * half;
    const s = x / Math.sqrt(radius * radius - x * x);
    sum += i === 0 || i === 200 ? s / 2 : s;
  }
  const mean = sum / 200;
  return { radius, scale: mean > 0 ? 0.5 / mean : 1 };
}

function slope(x: number, { radius, scale }: { radius: number; scale: number }) {
  const t = Math.min(x, 0.999 * radius);
  return (t / Math.sqrt(radius * radius - t * t)) * scale;
}

/** The lens's maps as RGBA: `across` / `down` are greys (128 = no pull; lighter pulls from the right / below) and
 *  `mask` covers (alpha) where the rim bends at all, so the middle shows the backdrop exactly. */
export function lensPixels({ w, h, r }: Shape, d: number, L: LensShape = LENS) {
  const hw = w / 2;
  const hh = h / 2;
  const rr = clamp(r, 0, Math.min(hw, hh));
  const cols = Math.max(1, Math.round(w * d));
  const rows = Math.max(1, Math.round(h * d));
  const share = Math.min(w, h);
  const depth = L.depth * share;
  const dome = L.dome * share;
  const iw = Math.max(0, hw - depth);
  const ih = Math.max(0, hh - depth);
  const ir = clamp(rr, 0, Math.min(iw, ih));
  const ramp = depth > 0 ? 1 / (depth * Math.SQRT2) : 1e6;
  const sag = Math.max(0.01, Math.min(dome, Math.min(hw, hh) - 1));
  const ax = arc(sag, hw);
  const ay = arc(sag, hh);
  const n = cols * rows * 4;
  const across = new Uint8ClampedArray(n);
  const down = new Uint8ClampedArray(n);
  const mask = new Uint8ClampedArray(n);
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const i = (row * cols + col) * 4;
      const x = ((col + 0.5) / cols) * w - hw;
      const y = ((row + 0.5) / rows) * h - hh;
      const edge = dist(x, y, hw, hh, rr);
      across[i + 3] = down[i + 3] = 255;
      if (edge >= 0) {
        across[i] = across[i + 1] = across[i + 2] = down[i] = down[i + 1] = down[i + 2] = 128;
        continue;
      }
      const fall = 0.5 * (1 + erf(dist(x, y, iw, ih, ir) * ramp));
      const dx = Math.sign(x) * slope(Math.abs(x), ax);
      const dy = Math.sign(y) * slope(Math.abs(y), ay);
      across[i] = across[i + 1] = across[i + 2] = Math.round((0.5 - 0.5 * dx * fall) * 255);
      down[i] = down[i + 1] = down[i + 2] = Math.round((0.5 - 0.5 * dy * fall) * 255);
      mask[i + 3] = Math.round(255 * Math.min(1, fall * 20, -edge));
    }
  }
  return { cols, rows, across, down, mask };
}

// ------------------------------------------------------------------------------------------------------- the DOM

let canvas: HTMLCanvasElement | null = null;
function png(cols: number, rows: number, data: Uint8ClampedArray): string {
  canvas ??= document.createElement("canvas");
  canvas.width = cols;
  canvas.height = rows;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  const img = ctx.createImageData(cols, rows);
  img.data.set(data);
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL();
}

const rims = new Map<string, string>();
function rimUrl(s: Shape, shine: number, d: number): string {
  const key = [s.w, s.h, s.r, shine, d].join("|");
  let url = rims.get(key);
  if (!url) {
    const { cols, rows, data } = rimPixels(s, shine, d);
    url = `url("${png(cols, rows, data)}")`;
    rims.set(key, url);
  }
  return url;
}

const NS = "http://www.w3.org/2000/svg";
function node(name: string, attrs: Record<string, string | number> = {}): SVGElement {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
}
let defs: SVGElement | null = null;
function holder(): SVGElement {
  if (defs?.isConnected) return defs;
  const root = node("svg", { width: 0, height: 0, "aria-hidden": "true" });
  root.style.cssText = "position:absolute;width:0;height:0;overflow:hidden;pointer-events:none";
  defs = node("defs");
  root.append(defs);
  document.body.append(root);
  return defs;
}

const CH = ["1 0 0 0 0  0 0 0 0 0  0 0 0 0 0", "0 0 0 0 0  0 1 0 0 0  0 0 0 0 0", "0 0 0 0 0  0 0 0 0 0  0 0 1 0 0"];
let made = 0;

/** Glisse's filter in the glass's own px: each ray is the backdrop pulled across, then down, by its map (each pass
 *  reads one grey and an alpha of one half — no pull — for the other direction); with `split`, three rays a third
 *  each; kept where the mask covers, the backdrop as it was elsewhere. */
function lensFilter(s: Shape, d: number, split: boolean, L: LensShape): SVGElement {
  const { cols, rows, across, down, mask } = lensPixels(s, d, L);
  const box = { x: 0, y: 0, width: s.w, height: s.h };
  const f = node("filter", { id: `lg-bend-${made++}`, ...box, filterUnits: "userSpaceOnUse", primitiveUnits: "userSpaceOnUse", "color-interpolation-filters": "sRGB" });
  const img = (data: Uint8ClampedArray, result: string) => node("feImage", { href: png(cols, rows, data), ...box, preserveAspectRatio: "none", result });
  f.append(img(across, "across"), img(down, "down"), img(mask, "mask"));
  for (const pull of ["across", "down"]) {
    const half = node("feComponentTransfer", { in: pull, result: `${pull}-pull` });
    half.append(node("feFuncA", { type: "linear", slope: 0, intercept: 0.5 }));
    f.append(half);
  }
  const reach = L.strength * Math.min(s.w, s.h);
  const ray = (k: number, i: number, result: string) => [
    node("feDisplacementMap", { in: "SourceGraphic", in2: "across-pull", scale: reach * k, xChannelSelector: "R", yChannelSelector: "A", ...box, result: `a${i}` }),
    node("feDisplacementMap", { in: `a${i}`, in2: "down-pull", scale: reach * k, xChannelSelector: "A", yChannelSelector: "R", result }),
  ];
  if (split) {
    [1 + 0.2 * L.dispersion, 1 + 0.1 * L.dispersion, 1].forEach((k, i) => {
      f.append(...ray(k, i, `ray${i}`), node("feColorMatrix", { in: `ray${i}`, type: "matrix", values: `${CH[i]}  0 0 0 0.3333 0`, result: `l${i}` }));
    });
    f.append(
      node("feComposite", { in: "l0", in2: "l1", operator: "arithmetic", k2: 1, k3: 1, result: "l01" }),
      node("feComposite", { in: "l01", in2: "l2", operator: "arithmetic", k2: 1, k3: 1, result: "spread" }),
      node("feColorMatrix", { in: "spread", type: "matrix", values: "3 0 0 0 0  0 3 0 0 0  0 0 3 0 0  0 0 0 1 0", result: "bent" }),
    );
  } else f.append(...ray(1 + 0.1 * L.dispersion, 0, "bent"));
  f.append(
    node("feComposite", { in: "bent", in2: "mask", operator: "in", result: "inside" }),
    node("feComposite", { in: "SourceGraphic", in2: "mask", operator: "out", result: "outside" }),
    node("feComposite", { in: "inside", in2: "outside", operator: "arithmetic", k2: 1, k3: 1 }),
  );
  holder().append(f);
  return f;
}

/** Chromium draws `backdrop-filter: url()` (Chrome, Edge, Android WebView); Safari and Firefox don't. */
export function bendsBackdrop(): boolean {
  if (typeof navigator === "undefined") return false;
  const brands = (navigator as Navigator & { userAgentData?: { brands?: { brand: string }[] } }).userAgentData?.brands;
  return !!brands?.some((b) => /Chromium/i.test(b.brand)) || /Chrom(?:e|ium)\//.test(navigator.userAgent);
}

export interface GlisseOptions {
  /** Paint the rim light (`--lg-rim-over`, [data-rim]). */
  rim?: boolean;
  /** Bend the backdrop (`--lg-bend`, [data-bent]): one ray, or Glisse's colour split. */
  lens?: false | "ray" | "split";
  /** The lens's shape (default: Glisse's glass lens, `LENS`). */
  shape?: LensShape;
}

const idle = (fn: () => void) =>
  typeof requestIdleCallback === "function" ? requestIdleCallback(fn, { timeout: 500 }) : setTimeout(fn, 60);

/** The glass's box: the element's border box (its ::before / ::after glass is drawn at inset -1px) and corner. */
function shapeOf(el: HTMLElement): Shape | null {
  const w = el.offsetWidth;
  const h = el.offsetHeight;
  if (!w || !h) return null;
  const r = parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0;
  return { w, h, r: Math.min(r, w / 2, h / 2) };
}

/** Gives `el` Glisse's glass and keeps it fitted to its size and the theme; returns the cleanup. */
export function glisse(el: HTMLElement | null, { rim = true, lens = false, shape = LENS }: GlisseOptions = {}): () => void {
  if (!el || typeof ResizeObserver === "undefined") return () => {};
  const bend = lens && bendsBackdrop();
  let key = "";
  let rimKey = "";
  let filter: SVGElement | null = null;
  let pending = false;
  let stopped = false;
  const fit = () => {
    pending = false;
    if (stopped) return;
    const s = shapeOf(el);
    if (!s) return;
    const d = Math.min(window.devicePixelRatio || 1, 2);
    if (rim) {
      const root = getComputedStyle(document.documentElement);
      const shine = clamp(parseFloat(root.getPropertyValue("--lg-rim-shine")) || 0.2, 0, 1);
      const k = [s.w, s.h, s.r, shine, d].join("|");
      if (k !== rimKey) {
        rimKey = k;
        el.style.setProperty("--lg-rim-over", rimUrl(s, shine, d));
        el.setAttribute("data-rim", "");
      }
    }
    if (bend) {
      const k = [s.w, s.h, s.r, d].join("|");
      if (k !== key) {
        key = k;
        const next = lensFilter(s, d, lens === "split", shape);
        filter?.remove();
        filter = next;
        el.style.setProperty("--lg-bend", `url("#${next.id}")`);
        el.setAttribute("data-bent", "");
      }
    }
  };
  const later = () => {
    if (pending) return;
    pending = true;
    idle(fit);
  };
  const ro = new ResizeObserver(later);
  ro.observe(el);
  // the rim's strength follows light / dark
  const mo = rim ? new MutationObserver(later) : null;
  mo?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => {
    stopped = true;
    ro.disconnect();
    mo?.disconnect();
    filter?.remove();
    el.style.removeProperty("--lg-rim-over");
    el.style.removeProperty("--lg-bend");
    el.removeAttribute("data-rim");
    el.removeAttribute("data-bent");
  };
}
