/**
 * Page themes — one look for the studio, the phone shell, the launcher and the web app (docs/STUDIO_UI.md § Page
 * themes). Separate from light / dark (lib/theme.ts): every page theme has both, and the switch keeps working.
 * Separate from the casino's table themes too: while the casino view is open (`html[data-cz]`) the table owns the page.
 *
 *   - the pick lives on the engine (`GET/POST /api/theme`, `state.settings.page_theme`), so every device shows the
 *     same theme; this browser keeps a copy (`localStorage deskdot.pageTheme`) as the fallback and for first paint;
 *   - `PAGE_THEMES` mirrors src/deskdot/gfx/themes.py (tests/test_page_themes.py keeps them equal): only seeds — an
 *     accent for dark, an optional accent for ivory, a metal, a tint and a texture motif. Everything else (washes,
 *     wells, gold leaf, focus rings, on-accent ink) is derived here, AA-checked, in both light and dark;
 *   - the CSS is one constructed stylesheet (`document.adoptedStyleSheets`, CSP-proof; a <style> where unsupported)
 *     scoped to `:root[data-page-theme="…"]:not([data-cz])`. The default theme ("ember") emits nothing: the
 *     stylesheets are its look. The CSS is cached (`deskdot.pageThemeCss`) so index.html / launcher.html /
 *     webapp/host.js paint it before the first frame — no flash;
 *   - a change cross-fades: the View Transitions API where there is one, else the `html.theme-fade` transitions.
 */
import { useSyncExternalStore } from "react";

export type PageThemeSeed = {
  id: string;
  name: string;
  description: string;
  accent: string; // the accent on dark surfaces
  accent_light: string; // the accent on ivory ("" = derived until it reads AA)
  metal: string; // the second ("metal") accent
  tint: string; // the chassis / wash hue ("" = untinted)
  pattern: string; // the page texture: gradients only ("" = the dot grid)
  pattern_size: string;
};

export const DEFAULT_PAGE_THEME = "ember";
export const PAGE_THEME_KEY = "deskdot.pageTheme";
export const PAGE_THEME_CSS_KEY = "deskdot.pageThemeCss";

// prettier-ignore
export const PAGE_THEMES: PageThemeSeed[] = [
  {
    "id": "ember",
    "name": "DeskDot",
    "description": "The original: graphite and ember in the dark, porcelain and rose in the light, gold for metal.",
    "accent": "#ff4818",
    "accent_light": "#b81f4b",
    "metal": "#ffcc33",
    "tint": "",
    "pattern": "",
    "pattern_size": ""
  },
  {
    "id": "graphite",
    "name": "Graphite & ice",
    "description": "Brushed steel and ice blue: a calm, almost monochrome instrument.",
    "accent": "#8ab8ff",
    "accent_light": "#2c5a96",
    "metal": "#c3ccd8",
    "tint": "#56657a",
    "pattern": "repeating-linear-gradient(0deg, rgba(160, 180, 210, 0.035) 0 1px, transparent 1px 4px)",
    "pattern_size": "auto"
  },
  {
    "id": "sunset",
    "name": "Sunset coral",
    "description": "Coral light sliding into violet dusk, with a warm amber rim.",
    "accent": "#ff7a59",
    "accent_light": "",
    "metal": "#c58bff",
    "tint": "#5a2a48",
    "pattern": "radial-gradient(circle at 1px 1px, rgba(255, 140, 110, 0.05) 1px, transparent 0)",
    "pattern_size": "18px 18px"
  },
  {
    "id": "citrus",
    "name": "Citrus",
    "description": "Lime zest and lemon on a dark leaf: bright, fresh and loud.",
    "accent": "#b6f23a",
    "accent_light": "",
    "metal": "#ffd84a",
    "tint": "#34461a",
    "pattern": "repeating-linear-gradient(60deg, rgba(182, 242, 58, 0.03) 0 1px, transparent 1px 12px)",
    "pattern_size": "auto"
  },
  {
    "id": "royal",
    "name": "Royal blue",
    "description": "Deep palace blue under a fine gold lattice.",
    "accent": "#6b97ff",
    "accent_light": "",
    "metal": "#ffcc33",
    "tint": "#1b4aa8",
    "pattern": "repeating-linear-gradient(45deg, rgba(255, 204, 51, 0.045) 0 1px, transparent 1px 22px), repeating-linear-gradient(-45deg, rgba(255, 204, 51, 0.045) 0 1px, transparent 1px 22px)",
    "pattern_size": "auto, auto"
  },
  {
    "id": "crimson",
    "name": "Crimson velvet",
    "description": "Red velvet and brass: an old-world salon.",
    "accent": "#ff4d6d",
    "accent_light": "",
    "metal": "#e8b04a",
    "tint": "#8c1a2e",
    "pattern": "radial-gradient(circle at 50% 50%, rgba(232, 176, 74, 0.05) 0 2px, transparent 3px)",
    "pattern_size": "26px 26px"
  },
  {
    "id": "midnight",
    "name": "Midnight neon",
    "description": "After-hours violet with faint neon scan lines and a cyan glint.",
    "accent": "#c77dff",
    "accent_light": "",
    "metal": "#59e3ff",
    "tint": "#3a1d72",
    "pattern": "repeating-linear-gradient(0deg, rgba(199, 125, 255, 0.035) 0 1px, transparent 1px 5px)",
    "pattern_size": "auto"
  },
  {
    "id": "strip",
    "name": "Neon strip",
    "description": "Hot-pink boulevard neon with cyan sparks.",
    "accent": "#ff4fb8",
    "accent_light": "",
    "metal": "#3fe0ff",
    "tint": "#5a1260",
    "pattern": "repeating-linear-gradient(135deg, rgba(255, 63, 176, 0.035) 0 2px, transparent 2px 16px)",
    "pattern_size": "auto"
  },
  {
    "id": "emerald",
    "name": "Emerald & champagne",
    "description": "Dark emerald with champagne trim: the high-limit room.",
    "accent": "#2fd59a",
    "accent_light": "",
    "metal": "#f1dca0",
    "tint": "#0b5a43",
    "pattern": "repeating-linear-gradient(45deg, rgba(241, 220, 160, 0.03) 0 10px, transparent 10px 20px)",
    "pattern_size": "auto"
  },
  {
    "id": "noir",
    "name": "Riviera noir",
    "description": "Black lacquer, silver rails and champagne pinstripes.",
    "accent": "#e8d7a8",
    "accent_light": "#6e5a2a",
    "metal": "#c0c6d0",
    "tint": "#3a3c44",
    "pattern": "repeating-linear-gradient(90deg, rgba(232, 215, 168, 0.03) 0 1px, transparent 1px 18px)",
    "pattern_size": "auto"
  },
  {
    "id": "jade",
    "name": "Imperial jade",
    "description": "Deep jade with red-gold trim and rolling clouds.",
    "accent": "#2fd3b0",
    "accent_light": "",
    "metal": "#f2c14e",
    "tint": "#0c6655",
    "pattern": "radial-gradient(circle at 50% 100%, transparent 9px, rgba(242, 193, 78, 0.045) 10px, transparent 11px)",
    "pattern_size": "24px 14px"
  },
  {
    "id": "deco",
    "name": "Gilded deco",
    "description": "Jazz-age black lacquer with gold sunburst fans.",
    "accent": "#e9c46a",
    "accent_light": "",
    "metal": "#e9c46a",
    "tint": "#4a3f2a",
    "pattern": "repeating-conic-gradient(from 0deg at 50% 100%, rgba(233, 196, 106, 0.04) 0 6deg, transparent 6deg 18deg)",
    "pattern_size": "48px 24px"
  },
  {
    "id": "marigold",
    "name": "Marigold masala",
    "description": "Saffron gold on magenta silk with a scatter of paisley buds.",
    "accent": "#ffa21f",
    "accent_light": "",
    "metal": "#ff5fae",
    "tint": "#7c1452",
    "pattern": "radial-gradient(ellipse 3px 5px at 50% 50%, rgba(255, 162, 31, 0.06) 0 100%, transparent 100%)",
    "pattern_size": "20px 20px"
  },
  {
    "id": "cyber",
    "name": "Cyber grid",
    "description": "Graphite traced with a teal circuit grid and magenta nodes.",
    "accent": "#2ff3e0",
    "accent_light": "",
    "metal": "#ff4fd8",
    "tint": "#1f3a44",
    "pattern": "linear-gradient(rgba(47, 243, 224, 0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(47, 243, 224, 0.035) 1px, transparent 1px)",
    "pattern_size": "24px 24px, 24px 24px"
  },
  {
    "id": "arcade",
    "name": "Pixel arcade",
    "description": "Cabinet black on a neon-green pixel grid with coin-yellow trim.",
    "accent": "#39ff6a",
    "accent_light": "",
    "metal": "#ffd60a",
    "tint": "#1e3a26",
    "pattern": "linear-gradient(rgba(57, 255, 106, 0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(57, 255, 106, 0.03) 1px, transparent 1px)",
    "pattern_size": "8px 8px, 8px 8px"
  },
  {
    "id": "sakura",
    "name": "Sakura night",
    "description": "Indigo dusk under drifting blossom-pink petals.",
    "accent": "#ffa3c7",
    "accent_light": "",
    "metal": "#b9c3ff",
    "tint": "#26306e",
    "pattern": "radial-gradient(ellipse 2px 3px at 50% 50%, rgba(255, 163, 199, 0.07) 0 100%, transparent 100%)",
    "pattern_size": "28px 28px"
  },
  {
    "id": "glacier",
    "name": "Glacier",
    "description": "Glacier blue and silver frost, like a desk carved in ice.",
    "accent": "#8fd8ff",
    "accent_light": "",
    "metal": "#d8ecf6",
    "tint": "#164e6c",
    "pattern": "repeating-linear-gradient(60deg, rgba(216, 236, 246, 0.03) 0 1px, transparent 1px 14px), repeating-linear-gradient(-60deg, rgba(216, 236, 246, 0.03) 0 1px, transparent 1px 14px)",
    "pattern_size": "auto, auto"
  },
  {
    "id": "oasis",
    "name": "Desert oasis",
    "description": "Turquoise pool framed in sand gold and star tiles.",
    "accent": "#3fe0d6",
    "accent_light": "",
    "metal": "#f0cf8e",
    "tint": "#0d5c63",
    "pattern": "repeating-linear-gradient(45deg, rgba(240, 207, 142, 0.035) 0 1px, transparent 1px 16px), repeating-linear-gradient(-45deg, rgba(240, 207, 142, 0.035) 0 1px, transparent 1px 16px)",
    "pattern_size": "auto, auto"
  },
  {
    "id": "abyss",
    "name": "Ocean abyss",
    "description": "Deep-sea teal with bioluminescent aqua sparks.",
    "accent": "#5cf2ff",
    "accent_light": "",
    "metal": "#8af5d0",
    "tint": "#08424f",
    "pattern": "radial-gradient(circle at 50% 50%, rgba(92, 242, 255, 0.07) 0 1px, transparent 2px)",
    "pattern_size": "30px 30px"
  },
  {
    "id": "volcano",
    "name": "Volcano",
    "description": "Charcoal basalt split by glowing lava seams.",
    "accent": "#ff6a1f",
    "accent_light": "",
    "metal": "#ffb347",
    "tint": "#4a2a1c",
    "pattern": "repeating-linear-gradient(120deg, rgba(255, 106, 31, 0.035) 0 1px, transparent 1px 26px)",
    "pattern_size": "auto"
  },
  {
    "id": "galaxy",
    "name": "Galaxy",
    "description": "Deep-space purple scattered with a cyan starfield.",
    "accent": "#59e3ff",
    "accent_light": "",
    "metal": "#c9a7ff",
    "tint": "#2a1a55",
    "pattern": "radial-gradient(circle at 30% 40%, rgba(89, 227, 255, 0.12) 0 1px, transparent 1.5px), radial-gradient(circle at 70% 80%, rgba(201, 167, 255, 0.09) 0 1px, transparent 1.5px)",
    "pattern_size": "37px 37px, 53px 53px"
  }
];

// ------------------------------------------------------------------ colour maths (sRGB, like the casino's _css())
type RGB = [number, number, number];
const rgb = (h: string): RGB => {
  const x = h.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(x.slice(i, i + 2), 16)) as RGB;
};
const hex = (c: RGB) => "#" + c.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
/** `a` moved `t` of the way to `b`. */
export const mix = (a: string, b: string, t: number) => {
  const x = rgb(a), y = rgb(b);
  return hex([0, 1, 2].map((i) => x[i] + (y[i] - x[i]) * t) as RGB);
};
const rgba = (h: string, a: number) => `rgba(${rgb(h).join(", ")}, ${a})`;
const lum = (h: string) => {
  const c = rgb(h).map((v) => v / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
/** WCAG 2 contrast ratio. */
export const contrast = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
};
/** Move `c` toward `to` in 4 % steps until it reaches `ratio` against `bg`. */
const until = (c: string, to: string, bg: string, ratio: number) => {
  for (let k = 0; k <= 25; k++) {
    const x = mix(c, to, k * 0.04);
    if (contrast(x, bg) >= ratio) return x;
  }
  return mix(c, to, 1);
};

const DARK = { c0: "#08080a", c1: "#0f0f13", c2: "#16161b", c3: "#1e1e25", c4: "#27272f", line: "#25252d", line2: "#33333d", glass: "#0e0e12" };
const LIGHT = { c0: "#f4f0e8", c1: "#fbf9f5", c2: "#ffffff", c3: "#f0ebe2", c4: "#e6e0d5", line: "#e7e1d6", line2: "#d8d0c2" };

/** Every colour a theme paints with, per mode (also used by the swatches and the Android bars). */
export function derive(t: PageThemeSeed) {
  const A = until(t.accent, "#ffffff", DARK.c1, 4.5); // the accent as text on graphite
  const M = t.metal;
  const tint = (base: string, k: number) => (t.tint ? mix(base, t.tint, k) : base);
  const dark = {
    accent: A,
    accent2: mix(A, "#ffffff", 0.28),
    deep: mix(A, DARK.c0, 0.84),
    line: mix(A, DARK.c0, 0.58),
    on: contrast(A, "#111111") >= 4.5 ? mix(A, "#000000", 0.9) : "#ffffff",
    metal: M,
    metal2: mix(M, "#ffffff", 0.45),
    metalText: until(M, "#ffffff", DARK.c1, 7),
    c0: tint(DARK.c0, 0.07), c1: tint(DARK.c1, 0.07), c2: tint(DARK.c2, 0.07), c3: tint(DARK.c3, 0.08), c4: tint(DARK.c4, 0.09),
    lineA: tint(DARK.line, 0.12), lineB: tint(DARK.line2, 0.14), glass: tint(DARK.glass, 0.07),
  };
  const AL = t.accent_light || until(t.accent, "#16101a", LIGHT.c0, 4.8); // AA as text on porcelain, and white on it
  const ML = until(M, "#3a2a10", LIGHT.c1, 2.6); // antique metal: rims and rules, never body text
  const light = {
    accent: AL,
    accent2: mix(AL, "#ffffff", 0.18),
    deep: mix(AL, "#ffffff", 0.9),
    line: mix(AL, "#ffffff", 0.68),
    on: "#ffffff",
    metal: ML,
    metal2: mix(M, "#ffffff", 0.4),
    metalText: until(M, "#2a1c08", LIGHT.c1, 4.8),
    c0: tint(LIGHT.c0, 0.06), c1: LIGHT.c1, c2: LIGHT.c2, c3: tint(LIGHT.c3, 0.06), c4: tint(LIGHT.c4, 0.08),
    lineA: tint(LIGHT.line, 0.08), lineB: tint(LIGHT.line2, 0.1), glass: LIGHT.c1,
  };
  return { dark, light };
}

/** The motif re-inked for porcelain: the same gradients in the theme's ivory accent, a touch stronger. */
const inkPattern = (p: string, ink: string) =>
  p.replace(/rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([0-9.]+)\s*\)/g, (_m, a) => rgba(ink, Math.min(0.12, Number(a) * 1.5)));

const metalVars = (m: string, m2: string, light: boolean) => `
  --m-gold-leaf: linear-gradient(135deg, ${mix(m2, "#ffffff", 0.45)} 0%, ${m} 34%, ${mix(m, "#000000", light ? 0.25 : 0.32)} 58%, ${m2} 80%, ${m} 100%);
  --m-brass: linear-gradient(180deg, ${m2}, ${mix(m, "#000000", 0.2)});
  --m-champagne: ${light ? mix(m2, "#ffffff", 0.7) : mix(m, "#08080a", 0.84)};
  --m-rule-gold: linear-gradient(90deg, transparent, ${rgba(m, light ? 0.5 : 0.32)} 22%, ${rgba(m2, light ? 0.85 : 0.32)} 50%, ${rgba(m, light ? 0.5 : 0.32)} 78%, transparent);`;

/** The theme's stylesheet. The default theme is the stylesheets themselves: "". */
export function themeCss(t: PageThemeSeed): string {
  if (t.id === DEFAULT_PAGE_THEME) return "";
  const { dark: d, light: l } = derive(t);
  const sel = `:root[data-page-theme="${t.id}"]:not([data-cz])`;
  const chassis = (c: typeof d) =>
    t.tint
      ? `
  --color-chassis-0: ${c.c0}; --color-chassis-1: ${c.c1}; --color-chassis-2: ${c.c2}; --color-chassis-3: ${c.c3}; --color-chassis-4: ${c.c4};
  --color-line: ${c.lineA}; --color-line-2: ${c.lineB}; --m-glass: ${c.glass};
  --c0: ${c.c0}; --line: ${c.lineA}; --line2: ${c.lineB};`
      : "";
  const accents = (c: typeof d) => `
  --color-ember: ${c.accent}; --color-ember-2: ${c.accent2}; --color-ember-deep: ${c.deep}; --color-ember-line: ${c.line};
  --color-on-ember: ${c.on}; --color-gold: ${c.metal}; --color-gold-2: ${c.metal2}; --color-gold-text: ${c.metalText};
  --ember: ${c.accent}; --ember2: ${c.accent2}; --on-ember: ${c.on}; --rose: ${c.accent}; --tangerine: ${c.accent2}; --gold: ${c.metal};`;
  const darkTexture = t.pattern ? `\n  --m-texture: ${t.pattern}; --m-texture-size: ${t.pattern_size || "auto"};` : "";
  const lightTexture = t.pattern ? `\n  --m-texture: ${inkPattern(t.pattern, l.accent)}; --m-texture-size: ${t.pattern_size || "auto"};` : "";
  return `/* page theme: ${t.name} (lib/pageTheme.ts) */
${sel} {${accents(d)}${chassis(d)}
  --m-page-glow: ${rgba(d.accent, 0.06)};
  --m-wash-b: ${rgba(d.metal, 0.03)};${darkTexture}${metalVars(d.metal, d.metal2, false)}
  --landing-bg: radial-gradient(circle at 50% 0%, ${rgba(d.accent, 0.14)}, transparent 55%), ${rgba(d.c0, 0.92)};
  --card-wash: ${rgba(d.deep, 0.33)}; --tan-line: ${rgba(d.accent2, 0.27)}; --tan-fill: ${rgba(d.accent2, 0.06)}; --tan-sel: ${rgba(d.accent2, 0.33)};
}
${sel}[data-theme="light"] {${accents(l)}${chassis(l)}
  --m-page-glow: ${rgba(l.accent2, 0.05)};
  --m-wash-a: ${rgba(l.accent2, 0.1)};
  --m-wash-b: ${rgba(l.metal, 0.12)};${lightTexture}${metalVars(l.metal, l.metal2, true)}
  --card-wash: ${rgba(l.deep, 0.6)}; --tan-line: ${rgba(l.accent, 0.2)}; --tan-fill: ${rgba(l.accent, 0.05)}; --tan-sel: ${rgba(l.accent, 0.27)};
}
${sel}[data-theme="light"] :is(.theme-dark, .bezel, .fly-wing, .fly-full, .roam-tip) {${accents(d)}
}
`;
}

// ------------------------------------------------------------------ applying it
const byId = (id: string | null | undefined) => PAGE_THEMES.find((t) => t.id === id);
export const pageThemeSeed = (id: string | null | undefined) => byId(id) ?? byId(DEFAULT_PAGE_THEME)!;

function stored(): string {
  try {
    return byId(localStorage.getItem(PAGE_THEME_KEY))?.id ?? DEFAULT_PAGE_THEME;
  } catch {
    return DEFAULT_PAGE_THEME;
  }
}

let current = typeof document !== "undefined" ? (byId(document.documentElement.dataset.pageTheme)?.id ?? stored()) : DEFAULT_PAGE_THEME;
const listeners = new Set<() => void>();
let sheet: CSSStyleSheet | null = null;

/** Put the CSS on the page: one constructed stylesheet (CSP can't block it), else a <style>. */
function install(css: string) {
  const doc = document as Document & { adoptedStyleSheets?: CSSStyleSheet[] };
  if (doc.adoptedStyleSheets && typeof CSSStyleSheet !== "undefined" && "replaceSync" in CSSStyleSheet.prototype) {
    try {
      if (!sheet) {
        sheet = new CSSStyleSheet();
        doc.adoptedStyleSheets = [...doc.adoptedStyleSheets, sheet];
      }
      sheet.replaceSync(css);
      document.getElementById("dd-page-theme")?.remove(); // the first-paint copy (index.html): the live one took over
      return;
    } catch {
      /* fall through to a <style> */
    }
  }
  let el = document.getElementById("dd-page-theme");
  if (!el) {
    el = document.createElement("style");
    el.id = "dd-page-theme";
    document.head.appendChild(el);
  }
  el.textContent = css;
}

function paint(id: string) {
  const t = pageThemeSeed(id);
  const css = themeCss(t);
  install(css);
  const root = document.documentElement;
  if (t.id === DEFAULT_PAGE_THEME) delete root.dataset.pageTheme;
  else root.dataset.pageTheme = t.id;
  try {
    localStorage.setItem(PAGE_THEME_KEY, t.id);
    localStorage.setItem(PAGE_THEME_CSS_KEY, css);
  } catch {
    /* private mode: this tab only */
  }
  current = t.id;
  listeners.forEach((l) => l());
}

/** Show a theme on this page (no engine call). `animate` cross-fades; first paint never does. */
export function applyPageTheme(id: string, animate = true) {
  const next = pageThemeSeed(id).id;
  if (next === current) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const doc = document as Document & { startViewTransition?: (cb: () => void) => { finished?: Promise<void> } };
  if (animate && !reduce && typeof doc.startViewTransition === "function") {
    // one snapshot cross-fade of the whole page: gradients and washes too, which CSS transitions can't animate
    const root = document.documentElement;
    root.classList.add("page-theme-vt");
    const done = () => root.classList.remove("page-theme-vt");
    try {
      const vt = doc.startViewTransition(() => paint(next));
      if (vt?.finished) vt.finished.then(done, done);
      else done();
    } catch {
      done();
      paint(next);
    }
    return;
  }
  if (animate && !reduce) {
    const root = document.documentElement;
    root.classList.add("theme-fade");
    window.setTimeout(() => root.classList.remove("theme-fade"), 450);
  }
  paint(next);
}

/** Pick a theme: this page at once, then the engine (every other device follows from its state push). The local
 *  pick stays if the engine can't be reached or is older than page themes. */
let picked = { id: "", at: 0 }; // this page's last pick: older state pushes must not flip it back meanwhile

export async function setPageTheme(id: string): Promise<boolean> {
  picked = { id, at: Date.now() };
  applyPageTheme(id, true);
  try {
    const r = await fetch("/api/theme", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id }) });
    return r.ok;
  } catch {
    return false;
  }
}

/** The engine's state said `id` (another device picked it, or this page just loaded): follow it. */
export function syncPageTheme(id: string | null | undefined) {
  if (!id || !byId(id) || id === current) return;
  if (Date.now() - picked.at < 4000 && id !== picked.id) return; // a push from before this page's own pick
  applyPageTheme(id, true);
}

/** At start-up: re-derive from this build (the first-paint copy may be from an older one) and keep other tabs in step. */
export function installPageTheme() {
  paint(current);
  window.addEventListener("storage", (e) => {
    if (e.key === PAGE_THEME_KEY && e.newValue && e.newValue !== current) applyPageTheme(e.newValue, true);
  });
}

/** Called whenever the theme changes (lib/theme.ts re-paints the browser / Android bars). */
export const onPageTheme = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));
export const getPageTheme = () => current;
export const usePageTheme = () => useSyncExternalStore(onPageTheme, getPageTheme, getPageTheme);

/** The page / header / tab-bar colours of the current page theme (`meta[name=theme-color]`, the Android bars). */
export function pageBars(mode: "light" | "dark"): { status: string; nav: string; page: string } {
  const d = derive(pageThemeSeed(current))[mode];
  return { status: d.c1, nav: d.glass, page: d.c0 };
}
