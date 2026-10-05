import { create } from "zustand";
import type { EngineState, LobbyInfo, Meta, Preset } from "./types";

/** Stable fallbacks: zustand v5 selectors must not return fresh objects on every call. */
export const EMPTY_LIST: readonly never[] = [];
export const EMPTY_MAP: Record<string, string> = {};

export type Toast = { id: number; text: string; tone: "info" | "error" | "ok" };
export type Tool = "pencil" | "eraser" | "fill" | "picker";
/** The four settings sections. */
export type SettingsSection = "display" | "alerts" | "playlist" | "device";
/**
 * Where to open settings: a section, or a named block inside one (the sheet scrolls to it).
 * The block names are the old tab ids, so every "open settings at X" link keeps working.
 */
export type SettingsTab =
  | SettingsSection
  | "transfer" | "calibrate" | "notifications" | "autopilot" | "integrations" | "audio" | "weather" | "panel" | "handoff";
export type MobileTab = "panel" | "apps" | "play" | "tune";

/** Per-browser UI preferences (layout sizes, favourites…), persisted in localStorage. */
type Prefs = {
  libraryWidth: number; // px
  inspectorWidth: number; // px
  libraryView: "grid" | "list";
  cardSize: number; // library preview size, px
  favorites: string[];
  category: string; // library filter chip ("all", "fav", or a category id)
  shuffle: boolean; // presets play in random order
  queueOpen: boolean; // playlist editor expanded in the playback dock
  lastGame: string; // the game Play mode opens when nothing playable is showing
  dockHeight: number; // playback dock height in px; 0 = fit its content
};
const DEFAULT_PREFS: Prefs = {
  libraryWidth: 300, inspectorWidth: 340, libraryView: "grid", cardSize: 112, favorites: [], category: "all",
  shuffle: false, queueOpen: false, lastGame: "", dockHeight: 0,
};
export const LIBRARY_MAX = 460;
export const INSPECTOR_MAX = 560;
/** The dock may grow to this share of the window (the panel preview stays the hero). */
export const DOCK_MAX_SHARE = 0.62;
function loadPrefs(): Prefs {
  try {
    const p: Prefs = { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem("deskdot.prefs") ?? localStorage.getItem("dotdeck.prefs") ?? "{}") };
    // the panel preview is the hero: never let a stored rail width crush it
    p.libraryWidth = Math.max(240, Math.min(LIBRARY_MAX, p.libraryWidth));
    p.inspectorWidth = Math.max(300, Math.min(INSPECTOR_MAX, p.inspectorWidth));
    p.dockHeight = Math.max(0, Math.min(Math.round(window.innerHeight * DOCK_MAX_SHARE), p.dockHeight || 0));
    return p;
  } catch {
    return DEFAULT_PREFS;
  }
}

type Store = Prefs & {
  meta: Meta | null;
  state: EngineState | null;
  stateAt: number; // performance.now() when `state` arrived (for local countdowns)
  link: "connecting" | "open" | "closed";
  selected: string | null; // app shown in the inspector
  palette: boolean; // command palette open
  settingsOpen: boolean;
  settingsTab: SettingsTab;
  wizardOpen: boolean;
  notifyOpen: boolean;
  aiOpen: boolean;
  tvOpen: boolean; // the "Show on TV" sheet (docs/TV_VIEW.md)
  playMode: boolean; // focused full-window game view
  lobby: LobbyInfo | null; // open multiplayer lobby (polled while Play mode is open)
  lanReady: boolean; // can phones on the Wi-Fi reach the engine?
  mpGames: Record<string, number> | null; // multiplayer game id -> max players (null until loaded)
  drawer: "library" | "inspector" | null; // slide-overs on tablet-width screens
  mobileTab: MobileTab; // bottom tab bar on phones
  presets: Preset[] | null; // null until loaded
  layerSel: string | null; // Text Studio: selected layer id
  opening: { app: string; since: number } | null; // app being opened (loading overlay)
  toasts: Toast[];
  // canvas painting
  tool: Tool;
  brush: string;
  recent: string[];
  set: (p: Partial<Store>) => void;
  prefs: (p: Partial<Prefs>) => void;
};

export const useStore = create<Store>((set, get) => ({
  ...loadPrefs(),
  meta: null,
  state: null,
  stateAt: 0,
  link: "connecting",
  selected: null,
  palette: false,
  settingsOpen: false,
  settingsTab: "display",
  wizardOpen: false,
  notifyOpen: false,
  aiOpen: false,
  tvOpen: false,
  playMode: false,
  lobby: null,
  lanReady: true,
  mpGames: null,
  drawer: null,
  mobileTab: "panel",
  presets: null,
  layerSel: null,
  opening: null,
  toasts: [],
  tool: "pencil",
  brush: "#ff4818",
  recent: ["#ff4818", "#ffd600", "#00ff8c", "#00dcff", "#8c3cff", "#ffffff"],
  set: (p) => set(p),
  prefs: (p) => {
    set(p);
    const s = get();
    const keep: Prefs = {
      libraryWidth: s.libraryWidth, inspectorWidth: s.inspectorWidth, libraryView: s.libraryView,
      cardSize: s.cardSize, favorites: s.favorites, category: s.category, shuffle: s.shuffle, queueOpen: s.queueOpen,
      lastGame: s.lastGame, dockHeight: s.dockHeight,
    };
    try {
      localStorage.setItem("deskdot.prefs", JSON.stringify(keep));
    } catch {
      /* private mode: preferences just won't persist */
    }
  },
}));

let toastId = 0;
export function toast(text: string, tone: Toast["tone"] = "info") {
  const id = ++toastId;
  useStore.setState((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, tone }] }));
  setTimeout(() => useStore.setState((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 3800);
}

// ---- frames bypass React: LED panels subscribe here and draw on a canvas directly
type FrameListener = (rgb: Uint8Array) => void;
const frameListeners = new Set<FrameListener>();
export let lastFrame: Uint8Array = new Uint8Array(32 * 32 * 3);

export function pushFrame(rgb: Uint8Array) {
  lastFrame = rgb;
  frameListeners.forEach((l) => l(rgb));
}

export function onFrame(l: FrameListener) {
  frameListeners.add(l);
  l(lastFrame);
  return () => void frameListeners.delete(l);
}

export const appMeta = (id: string | null | undefined) =>
  useStore.getState().meta?.apps.find((a) => a.id === id) ?? null;

/** Phone layout (bottom tab bar) — matches Tailwind's `md` breakpoint. */
export const isPhone = () => window.innerWidth < 768;

/** Show an app's settings: the inspector rail, a drawer on tablets, or the Tune tab on phones. */
export function inspect(id: string | null) {
  const w = window.innerWidth;
  if (w < 768) useStore.setState({ selected: id, mobileTab: "tune", drawer: null });
  else useStore.setState({ selected: id, drawer: w < 1280 ? "inspector" : null });
}

export function openSettings(tab: SettingsTab = "display") {
  useStore.setState({ settingsOpen: true, settingsTab: tab });
}
