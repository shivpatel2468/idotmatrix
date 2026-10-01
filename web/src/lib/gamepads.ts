import { create } from "zustand";
import { api } from "./api";
import { MAX_SEATS, useControls } from "./controls";
import { type GameKey, isPlayable, pressKey, releaseKey, setHoldDepth } from "./gameInput";
import { appMeta, toast, useStore } from "./store";

/**
 * Gamepads on this computer (USB or Bluetooth) through the Gamepad API — localhost is a secure context.
 *
 * Standard mapping: d-pad (12–15) and the left stick → directions (dead zone from the Controls panel, dominant
 * axis with a little hysteresis), bottom face button (A / ✕) → a, right (B / ○) → b, X / Y / shoulders / triggers
 * as alternates, Start → restart, Select / View / Share → let the AI play. Pads that report no standard mapping
 * get the same indices plus axes 6/7 as a d-pad, which covers most generic pads.
 *
 * The rAF poll runs only while Play mode is open *and* a pad is connected; otherwise a 1 s scan (plus the
 * connect events) notices new pads. A pad is remembered by id (+ position among identical pads), so it gets its
 * player back when it's plugged in again. An unknown pad joins on its first button press.
 */
export type Brand = "xbox" | "playstation" | "nintendo" | "generic";
export type PadInfo = { key: string; index: number; id: string; name: string; brand: Brand; standard: boolean; rumble: boolean };

export const GLYPHS: Record<Brand, { a: string; b: string; x: string; y: string; start: string; select: string; note?: string }> = {
  xbox: { a: "A", b: "B", x: "X", y: "Y", start: "Menu", select: "View" },
  playstation: { a: "✕", b: "○", x: "□", y: "△", start: "Options", select: "Create" },
  nintendo: {
    a: "B", b: "A", x: "Y", y: "X", start: "+", select: "−",
    note: "Nintendo layout: buttons work by position — the bottom button (labelled B) is the game's A.",
  },
  generic: { a: "Bottom", b: "Right", x: "Left", y: "Top", start: "Start", select: "Select" },
};

export function brandOf(id: string): Brand {
  const s = id.toLowerCase();
  if (/xbox|xinput|x-box|vendor: 045e|045e-/.test(s)) return "xbox";
  if (/playstation|dualshock|dualsense|vendor: 054c|054c-|wireless controller/.test(s)) return "playstation";
  if (/nintendo|pro controller|joy-con|vendor: 057e|057e-/.test(s)) return "nintendo";
  return "generic";
}

/** "Xbox 360 Controller (XInput STANDARD GAMEPAD)" → "Xbox 360 Controller"; "054c-0ce6-Wireless Controller" → … */
export function padName(id: string): string {
  const n = id.replace(/\(.*\)\s*$/, "").replace(/^[0-9a-f]{4}-[0-9a-f]{4}-/i, "").trim();
  return n || "Gamepad";
}

type Pads = { pads: readonly PadInfo[] };
const NO_PADS: readonly PadInfo[] = [];
/** Connected pads (reference-stable until the list changes). */
export const usePads = create<Pads>(() => ({ pads: NO_PADS }));

// per-pad activity lights in the Controls panel
const activity = new Set<(key: string) => void>();
export function onPadActivity(l: (key: string) => void) {
  activity.add(l);
  return () => void activity.delete(l);
}

const read = (): Gamepad[] => {
  try {
    return [...(navigator.getGamepads?.() ?? [])].filter((p): p is Gamepad => !!p && p.connected !== false);
  } catch {
    return [];
  }
};

function keysOf(list: Gamepad[]): string[] {
  const seen = new Map<string, number>();
  return list.map((p) => {
    const n = seen.get(p.id) ?? 0;
    seen.set(p.id, n + 1);
    return `${p.id}#${n}`;
  });
}

function scan(): Gamepad[] {
  const list = read();
  const keys = keysOf(list);
  const infos = list.map((p, i) => ({
    key: keys[i], index: p.index, id: p.id, name: padName(p.id), brand: brandOf(p.id), standard: p.mapping === "standard",
    rumble: !!(p as Gamepad & { vibrationActuator?: unknown }).vibrationActuator,
  }));
  const prev = usePads.getState().pads;
  if (JSON.stringify(prev) !== JSON.stringify(infos)) usePads.setState({ pads: infos.length ? infos : NO_PADS });
  return list;
}

// ------------------------------------------------------------------ polling
type PadState = {
  buttons: Set<number>; keys: Set<GameKey>; stick: GameKey | null; player: number; app: string | null;
  swallow: Set<number>; // buttons held since the join press: ignored until released
};
const state = new Map<string, PadState>();
const BTN: Partial<Record<number, GameKey>> = { 0: "a", 1: "b", 2: "a", 3: "b", 4: "b", 5: "a", 6: "b", 7: "a" };
const DPAD: Partial<Record<number, GameKey>> = { 12: "up", 13: "down", 14: "left", 15: "right" };
const START = 9;
const SELECT = 8;

function currentApp(): string | null {
  const app = useStore.getState().state?.engine.current?.app;
  return app && isPlayable(appMeta(app)) ? app : null;
}

/** The lowest player (1..4) that no connected pad drives yet. */
function nextFreePlayer(keys: string[]): number {
  const pads = useControls.getState().pads;
  const taken = new Set(keys.map((k) => pads[k]).filter((p) => p > 0));
  for (let p = 1; p <= MAX_SEATS; p++) if (!taken.has(p)) return p;
  return 0;
}

function stickDir(x: number, y: number, dz: number, prev: GameKey | null): { key: GameKey | null; depth: number } {
  const mag = Math.min(1, Math.hypot(x, y));
  if (mag < dz) return { key: null, depth: 0 };
  const depth = (mag - dz) / Math.max(0.05, 1 - dz);
  const horiz: GameKey = x < 0 ? "left" : "right";
  const vert: GameKey = y < 0 ? "up" : "down";
  const ax = Math.abs(x);
  const ay = Math.abs(y);
  // hysteresis: keep the held direction until the other axis clearly wins (no flicker on the diagonal)
  if (prev === horiz && ax >= ay * 0.75) return { key: horiz, depth };
  if (prev === vert && ay >= ax * 0.75) return { key: vert, depth };
  return { key: ax >= ay ? horiz : vert, depth };
}

function frame() {
  const list = scan();
  const keys = keysOf(list);
  const app = currentApp();
  const cfg = useControls.getState();
  const live = new Set(keys);
  list.forEach((p, i) => {
    const key = keys[i];
    const st = state.get(key) ?? { buttons: new Set<number>(), keys: new Set<GameKey>(), stick: null, player: 0, app: null, swallow: new Set<number>() };
    state.set(key, st);
    const down = new Set<number>();
    p.buttons.forEach((b, n) => {
      if (b.pressed || b.value > 0.5) down.add(n);
    });
    const edges = [...down].filter((n) => !st.buttons.has(n));
    st.buttons = down;
    st.swallow.forEach((n) => !down.has(n) && st.swallow.delete(n));
    st.swallow.forEach((n) => down.delete(n));
    let player = cfg.pads[key];
    if (player === undefined) {
      if (!edges.length) return;
      player = nextFreePlayer(keys);
      useControls.getState().set({ pads: { ...cfg.pads, [key]: player } });
      toast(player ? `${padName(p.id)} joined as player ${player}` : `${padName(p.id)} connected — all players have a pad`, "ok");
      pulse(key, 0.35, 90);
      st.swallow = new Set(down);
      return; // the join press doesn't also fire into the game
    }
    // player changed (reassigned in the panel) or game switched: let go of everything first
    if (st.player !== player || st.app !== app) {
      st.keys.forEach((k) => releaseKey(k, `gp:${key}`, st.player));
      st.keys = new Set();
      st.stick = null;
      st.player = player;
      st.app = app;
    }
    if (!player || !app) return;
    // directions: d-pad buttons, a non-standard pad's axes 6/7, and the left stick
    const want = new Set<GameKey>();
    down.forEach((n) => {
      const k = DPAD[n] ?? BTN[n];
      if (k) want.add(k);
    });
    if (p.mapping !== "standard" && p.axes.length >= 8) {
      if (p.axes[6] < -0.5) want.add("left");
      if (p.axes[6] > 0.5) want.add("right");
      if (p.axes[7] < -0.5) want.add("up");
      if (p.axes[7] > 0.5) want.add("down");
    }
    const s = stickDir(p.axes[0] ?? 0, p.axes[1] ?? 0, cfg.deadzone, st.stick);
    st.stick = s.key;
    if (s.key) want.add(s.key);
    let moved = edges.length > 0;
    want.forEach((k) => {
      if (!st.keys.has(k)) {
        pressKey(k, `gp:${key}`, app, player, k === s.key ? s.depth : 0);
        moved = true;
      } else if (k === s.key) setHoldDepth(k, player, s.depth);
    });
    st.keys.forEach((k) => {
      if (!want.has(k)) releaseKey(k, `gp:${key}`, player);
    });
    st.keys = want;
    if (edges.includes(START)) api.action(app, "restart");
    if (edges.includes(SELECT) && !useStore.getState().lobby) api.action(app, "demo");
    if (moved || want.size) activity.forEach((l) => l(key)); // lit while anything is held
  });
  // unplugged: release what it held
  for (const [key, st] of state) {
    if (live.has(key)) continue;
    st.keys.forEach((k) => releaseKey(k, `gp:${key}`, st.player));
    state.delete(key);
  }
  return list.length;
}

let running = 0; // Play-mode users (StrictMode mounts twice)
let raf = 0;
let scanTimer: ReturnType<typeof setInterval> | undefined;

function loop() {
  raf = 0;
  if (!running) return;
  if (frame() > 0) raf = requestAnimationFrame(loop);
}
const kick = () => {
  if (running && !raf && read().length) raf = requestAnimationFrame(loop);
  else scan();
};

/** Start gamepad input (Play mode mounts this). Returns the stop function. */
export function startGamepads(): () => void {
  running++;
  if (running === 1) {
    window.addEventListener("gamepadconnected", kick);
    window.addEventListener("gamepaddisconnected", kick);
    scanTimer = setInterval(kick, 1000);
    unwatch = watchHits();
  }
  kick();
  return () => {
    running = Math.max(0, running - 1);
    if (running) return;
    window.removeEventListener("gamepadconnected", kick);
    window.removeEventListener("gamepaddisconnected", kick);
    clearInterval(scanTimer);
    cancelAnimationFrame(raf);
    raf = 0;
    unwatch?.();
    for (const [key, st] of state) st.keys.forEach((k) => releaseKey(k, `gp:${key}`, st.player));
    state.clear();
  };
}

// ------------------------------------------------------------------ rumble
type Actuator = { playEffect?: (t: string, p: Record<string, number>) => Promise<unknown> };
function pulse(key: string, strength: number, ms: number) {
  if (!useControls.getState().rumble) return;
  const list = read();
  const keys = keysOf(list);
  const p = list[keys.indexOf(key)] as (Gamepad & { vibrationActuator?: Actuator }) | undefined;
  p?.vibrationActuator?.playEffect?.("dual-rumble", {
    startDelay: 0, duration: ms, strongMagnitude: strength, weakMagnitude: Math.min(1, strength + 0.2),
  })?.catch(() => {});
}
/** Rumble every pad that drives one of `players` (all pads when null). */
export function rumble(players: number[] | null, strength = 0.8, ms = 180) {
  const pads = useControls.getState().pads;
  for (const key of keysOf(read())) {
    const p = pads[key];
    if (p > 0 && (!players || players.includes(p))) pulse(key, strength, ms);
  }
}
export const testRumble = (key: string) => pulse(key, 0.7, 220);

let unwatch: (() => void) | undefined;
/** "A hit": a life lost (per seat where the game reports it), the game ending (score back to 0), a round won. */
function watchHits() {
  let app: string | undefined;
  let prev: Record<string, unknown> | undefined;
  return useStore.subscribe((s) => {
    const cur = s.state?.engine.current;
    const st = cur?.status;
    if (!cur || st === prev) return;
    if (cur.app !== app) {
      app = cur.app;
      prev = st;
      return;
    }
    const was = prev;
    prev = st;
    if (!was || !st) return;
    const lv = st.lives;
    const plv = was.lives;
    if (typeof lv === "number" && typeof plv === "number" && lv < plv) rumble(null, 0.9, 220);
    else if (lv && plv && typeof lv === "object" && typeof plv === "object") {
      const hit = Object.entries(lv as Record<string, number>)
        .filter(([seat, n]) => n < ((plv as Record<string, number>)[seat] ?? n))
        .map(([seat]) => Number(seat));
      if (hit.length) rumble(hit, 0.9, 220);
    }
    if (Number(was.score) > 0 && Number(st.score) === 0) rumble(null, 1, 320);
    const w = st.wins as Record<string, number> | undefined;
    const pw = was.wins as Record<string, number> | undefined;
    if (w && pw && JSON.stringify(w) !== JSON.stringify(pw)) rumble(null, 0.6, 160);
  });
}
