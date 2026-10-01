import { create } from "zustand";

/** One reading of the fruit-fly brain (GET /api/fly; src/dotdeck/fly/brain.py `snapshot`). Studio only:
 *  the panel shows just the game the fly is playing. */
export type FlySnap = {
  active: boolean;
  app: string | null;
  driving?: boolean; // false while a person has taken over
  step?: number;
  eye?: number[]; // 16×16, 0..255
  on?: number[]; // lamina L1 (brightening)
  off?: number[]; // lamina L2 (dimming)
  mh?: number[]; // T4/T5 horizontal motion, -127..127 (+ = right)
  mv?: number[]; // vertical (+ = down)
  hs?: { left: number; right: number; up: number; down: number };
  looming?: number;
  gf?: number;
  dn?: { left: number; right: number; up: number; down: number };
  light?: [number, number];
  spikes?: string[];
  keys?: [number, string][]; // [step, key] recent presses
  world?: { fly: [number, number]; fruit: [number, number][]; shadow: [number, number, number] | null };
};

export type FlyKey = "left" | "right" | "up" | "down" | "a";
export const FLY_KEYS: FlyKey[] = ["left", "up", "down", "right", "a"];
export const KEY_GLYPH: Record<FlyKey, string> = { left: "←", right: "→", up: "↑", down: "↓", a: "A" };
export const KEY_ROLE: Record<FlyKey, string> = {
  left: "DN left", right: "DN right", up: "DN up", down: "DN down", a: "Giant fibre · escape",
};

export type Press = { id: number; key: FlyKey; at: number };

// ------------------------------------------------------------------ graphics settings

export type Quality = "auto" | "low" | "balanced" | "high" | "ultra";
export type ThemeId = "neon" | "bio" | "thermal" | "ice" | "ember";
export type BoardStyle = "midnight" | "rgb" | "retro" | "glass";
export type FlyLook = "wild" | "golden" | "ghost" | "chrome";
export type CameraMode = "orbit" | "front" | "top" | "close";

export type FlyGfx = {
  autoOpen: boolean; // open the Fly view (and close the side drawers) when a fly starts playing
  quality: Quality;
  fpsCap: 30 | 60 | 0; // 0 = display refresh
  bloom: boolean;
  bloomStrength: number; // 0..2.5
  particles: number; // 0..1 density of signal particles, sparks and dust
  trails: boolean; // the wiring between layers
  labels: boolean;
  theme: ThemeId;
  autoRotate: boolean;
  rotateSpeed: number; // 0..2
  camera: CameraMode;
  brainSpread: number; // 0.7..1.4 vertical spacing of the layers
  fly: FlyLook;
  flySize: number; // 0.7..1.4
  wingShimmer: boolean;
  board: BoardStyle;
  hud: boolean; // key log + stats overlay
  showFps: boolean;
  swap: boolean; // keyboard on the left, brain on the right
  shadows: boolean;
};

export const DEFAULT_GFX: FlyGfx = {
  autoOpen: true, quality: "auto", fpsCap: 60, bloom: true, bloomStrength: 1.1, particles: 0.7, trails: true,
  labels: true, theme: "neon", autoRotate: true, rotateSpeed: 0.6, camera: "orbit", brainSpread: 1, fly: "wild",
  flySize: 1, wingShimmer: true, board: "midnight", hud: true, showFps: false, swap: false, shadows: true,
};

export type Theme = {
  name: string;
  bg: string; fog: string;
  eye: string; on: string; off: string; right: string; left: string; up: string; down: string;
  loom: string; gf: string; dn: string; wire: string; accent: string;
};

export const THEMES: Record<ThemeId, Theme> = {
  neon: {
    name: "Neon", bg: "#04050c", fog: "#070a1c", eye: "#3be3ff", on: "#3dffb0", off: "#ff3d9a", right: "#4d8bff",
    left: "#ff5ad2", up: "#5dff7a", down: "#ffd23d", loom: "#c45cff", gf: "#ff6a1a", dn: "#ffe14d", wire: "#2b3d7a",
    accent: "#3be3ff",
  },
  bio: {
    name: "Bioluminescent", bg: "#010a0a", fog: "#02181a", eye: "#5effe1", on: "#a6ff4d", off: "#2bb3ff", right: "#38ffd0",
    left: "#7dffa0", up: "#c8ff6a", down: "#48d6ff", loom: "#9b7bff", gf: "#ff8a3d", dn: "#e9ff7a", wire: "#0f4a48",
    accent: "#5effe1",
  },
  thermal: {
    name: "Thermal", bg: "#080303", fog: "#1a0606", eye: "#ffb13b", on: "#ffe14d", off: "#7a2cff", right: "#ff6a1a",
    left: "#ff2d55", up: "#ffd23d", down: "#ff8f3d", loom: "#ff3df0", gf: "#ffffff", dn: "#ffcf66", wire: "#4a1a10",
    accent: "#ff8f3d",
  },
  ice: {
    name: "Ice", bg: "#03060a", fog: "#0a1420", eye: "#d6f3ff", on: "#9fe8ff", off: "#7d8cff", right: "#bfe6ff",
    left: "#8fb8ff", up: "#e6fbff", down: "#a6c8ff", loom: "#b59bff", gf: "#ffffff", dn: "#f0fbff", wire: "#223650",
    accent: "#bfe6ff",
  },
  ember: {
    name: "Studio ember", bg: "#07060a", fog: "#130a08", eye: "#ff7a4d", on: "#ffb020", off: "#ff3b5c", right: "#ff4818",
    left: "#ff7a4d", up: "#ffd28a", down: "#ff9a5c", loom: "#ff3b5c", gf: "#ffffff", dn: "#ffb020", wire: "#3a1208",
    accent: "#ff4818",
  },
};

function loadGfx(): FlyGfx {
  try {
    return { ...DEFAULT_GFX, ...JSON.parse(localStorage.getItem("dotdeck.fly") ?? "{}") };
  } catch {
    return { ...DEFAULT_GFX };
  }
}

// ------------------------------------------------------------------ store

type FlyStore = {
  snap: FlySnap;
  /** Every key the fly pressed since the view opened, newest last (capped). */
  presses: Press[];
  counts: Record<FlyKey, number>;
  gfx: FlyGfx;
  /** The person closed the Fly view for this app; it reopens when another fly app starts. */
  dismissedFor: string | null;
  /** The person opened the Fly view by hand (even with auto-open off). */
  forced: boolean;
  settingsOpen: boolean;
  setGfx: (p: Partial<FlyGfx>) => void;
  set: (p: Partial<FlyStore>) => void;
};

const ZERO: Record<FlyKey, number> = { left: 0, right: 0, up: 0, down: 0, a: 0 };

export const useFly = create<FlyStore>((set, get) => ({
  snap: { active: false, app: null },
  presses: [],
  counts: { ...ZERO },
  gfx: loadGfx(),
  dismissedFor: null,
  forced: false,
  settingsOpen: false,
  set: (p) => set(p),
  setGfx: (p) => {
    const gfx = { ...get().gfx, ...p };
    set({ gfx });
    try {
      localStorage.setItem("dotdeck.fly", JSON.stringify(gfx));
    } catch {
      /* private mode: settings just won't persist */
    }
  },
}));

/** Is the Fly view showing (side drawers closed, 3D wings beside the panel)? */
export function useFlyView(): boolean {
  return useFly((s) => {
    if (!s.snap.active) return false;
    if (s.forced) return true;
    return s.gfx.autoOpen && s.dismissedFor !== s.snap.app;
  });
}

export function closeFlyView() {
  const s = useFly.getState();
  s.set({ dismissedFor: s.snap.app, forced: false, settingsOpen: false });
}

export function openFlyView() {
  useFly.getState().set({ forced: true, dismissedFor: null });
}

// ------------------------------------------------------------------ live events (for the 3D scenes)

type PressListener = (p: Press) => void;
const pressListeners = new Set<PressListener>();
export function onPress(l: PressListener) {
  pressListeners.add(l);
  return () => void pressListeners.delete(l);
}

let lastStep = -1;
let lastApp: string | null = null;
let seen = new Set<string>();
let pressId = 0;

function ingest(snap: FlySnap) {
  const s = useFly.getState();
  if (snap.app !== lastApp) {
    lastApp = snap.app;
    lastStep = -1;
    seen = new Set();
    useFly.setState({ presses: [], counts: { ...ZERO }, dismissedFor: s.dismissedFor === snap.app ? s.dismissedFor : null, forced: false });
  }
  const step = snap.step ?? 0;
  if (step < lastStep) seen = new Set(); // a baked loop wrapped around: its steps start again
  lastStep = step;
  const fresh = (snap.keys ?? []).filter(([n, k]) => !seen.has(`${n}:${k}`));
  if (!fresh.length) return void useFly.setState({ snap });
  for (const [n, k] of fresh) seen.add(`${n}:${k}`);
  if (seen.size > 400) seen = new Set([...seen].slice(-200));
  // spread a burst over the poll interval so the keyboard animates every press, not one big thump
  const now = performance.now();
  const add: Press[] = fresh.map(([, k], i) => ({ id: ++pressId, key: k as FlyKey, at: now + i * 55 }));
  const counts = { ...useFly.getState().counts };
  for (const p of add) counts[p.key] = (counts[p.key] ?? 0) + 1;
  useFly.setState({ snap, counts, presses: [...useFly.getState().presses, ...add].slice(-60) });
  add.forEach((p, i) => setTimeout(() => pressListeners.forEach((l) => l(p)), i * 55));
}

let timer: ReturnType<typeof setTimeout> | undefined;

/** Poll the engine: ~12 Hz while a fly plays and the tab is visible, otherwise every 1.5 s. */
export function startFlyPolling() {
  if (timer) return;
  const tick = async () => {
    let active = false;
    if (document.visibilityState === "visible") {
      try {
        const r = await fetch("/api/fly");
        if (r.ok) {
          const snap = (await r.json()) as FlySnap;
          active = snap.active;
          ingest(snap);
        }
      } catch {
        /* engine restarting */
      }
    }
    timer = setTimeout(tick, active ? 80 : 1500);
  };
  tick();
}

// ------------------------------------------------------------------ quality

export type Level = { pixelRatio: number; bloom: boolean; shadows: boolean; particles: number; segments: number; aa: boolean };

export function level(q: Exclude<Quality, "auto">, gfx: FlyGfx): Level {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const base: Record<Exclude<Quality, "auto">, Level> = {
    low: { pixelRatio: Math.min(dpr, 0.85), bloom: false, shadows: false, particles: 0.35, segments: 10, aa: false },
    balanced: { pixelRatio: Math.min(dpr, 1.15), bloom: true, shadows: false, particles: 0.7, segments: 16, aa: true },
    high: { pixelRatio: Math.min(dpr, 1.5), bloom: true, shadows: true, particles: 1, segments: 24, aa: true },
    ultra: { pixelRatio: dpr, bloom: true, shadows: true, particles: 1.5, segments: 36, aa: true },
  };
  const l = { ...base[q] };
  l.bloom = l.bloom && gfx.bloom;
  l.shadows = l.shadows && gfx.shadows;
  l.particles *= gfx.particles;
  return l;
}
