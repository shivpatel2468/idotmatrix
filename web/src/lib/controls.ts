import { create } from "zustand";
import type { GameKey } from "./gameInput";
import { appMeta, useStore } from "./store";

/**
 * Who plays with what: keyboard bindings per player, gamepad → player assignments, on-screen touch controls,
 * dead zone and rumble. Persisted in localStorage (`dotdeck.controls`); a separate small zustand store so the
 * Controls panel re-renders without touching the main store. Every update replaces only what changed, so
 * selectors that pick `s.players` / `s.pads` stay reference-stable (no React #185 loops).
 */
export const GAME_KEYS: readonly GameKey[] = ["up", "down", "left", "right", "a", "b"];
export const MAX_SEATS = 4;

/** `KeyboardEvent.code` values (physical keys: WASD stays WASD on AZERTY) per game key. */
export type Binding = Record<GameKey, string[]>;
export type KbPreset = "arrows" | "wasd" | "ijkl" | "custom" | "none";
export type TouchStyle = "dpad" | "joystick" | "swipe" | "tap";
export const TOUCH_STYLES: readonly TouchStyle[] = ["dpad", "joystick", "swipe", "tap"];

export const PRESETS: Record<Exclude<KbPreset, "custom" | "none">, { label: string; binding: Binding }> = {
  arrows: {
    label: "Arrows + Space / Shift",
    binding: {
      up: ["ArrowUp"], down: ["ArrowDown"], left: ["ArrowLeft"], right: ["ArrowRight"],
      a: ["Space", "Enter"], b: ["ShiftLeft", "ShiftRight"],
    },
  },
  wasd: {
    label: "W A S D + F / G",
    binding: { up: ["KeyW"], down: ["KeyS"], left: ["KeyA"], right: ["KeyD"], a: ["KeyF"], b: ["KeyG"] },
  },
  ijkl: {
    label: "I J K L + H / ;",
    binding: { up: ["KeyI"], down: ["KeyK"], left: ["KeyJ"], right: ["KeyL"], a: ["KeyH"], b: ["Semicolon"] },
  },
};
/** While nobody else is on the keyboard, player 1 on the arrows also gets W A S D (the old studio default). */
const SOLO_ALIAS: Partial<Binding> = { up: ["KeyW"], down: ["KeyS"], left: ["KeyA"], right: ["KeyD"] };
/** Play-mode keys that games can't take without losing the shortcut. */
export const RESERVED: Record<string, string> = {
  KeyR: "Restart", BracketLeft: "Previous game", BracketRight: "Next game", Escape: "Leave Play mode",
};

export type PlayerCfg = {
  kb: KbPreset;
  custom: Binding; // used when kb === "custom" (starts as a copy of the preset it was edited from)
  /** On-screen touch controls for this player: null = automatic (player 1 on touch screens). */
  touch: boolean | null;
};
type Persisted = {
  players: PlayerCfg[]; // index 0 = P1
  pads: Record<string, number>; // pad key (id#n) -> player, 0 = ignored
  deadzone: number; // 0.05–0.6 of full stick travel
  rumble: boolean;
  ways: 4 | 8; // on-screen joystick: 4-way (one direction at a time) or 8-way (diagonals press two)
  touchStyle: Record<string, TouchStyle>; // per game; missing = the game's first recommended touch controller
};

const blank = (): Binding => ({ up: [], down: [], left: [], right: [], a: [], b: [] });
const copy = (b: Binding): Binding => Object.fromEntries(GAME_KEYS.map((k) => [k, [...(b[k] ?? [])]])) as Binding;
const DEFAULTS: Persisted = {
  players: [
    { kb: "arrows", custom: copy(PRESETS.arrows.binding), touch: null },
    { kb: "none", custom: blank(), touch: false },
    { kb: "none", custom: blank(), touch: false },
    { kb: "none", custom: blank(), touch: false },
  ],
  pads: {},
  deadzone: 0.25,
  rumble: true,
  ways: 4,
  touchStyle: {},
};

const KEY = "dotdeck.controls";
function load(): Persisted {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Persisted>;
    const players = DEFAULTS.players.map((d, i) => {
      const p = raw.players?.[i];
      if (!p) return d;
      const kb = (["arrows", "wasd", "ijkl", "custom", "none"] as const).includes(p.kb) ? p.kb : d.kb;
      const custom = blank();
      for (const k of GAME_KEYS) custom[k] = Array.isArray(p.custom?.[k]) ? p.custom[k].filter((c) => typeof c === "string") : [];
      return { kb, custom, touch: typeof p.touch === "boolean" ? p.touch : d.touch };
    });
    return {
      players,
      pads: raw.pads && typeof raw.pads === "object" ? raw.pads : {},
      deadzone: typeof raw.deadzone === "number" ? Math.min(0.6, Math.max(0.05, raw.deadzone)) : DEFAULTS.deadzone,
      rumble: typeof raw.rumble === "boolean" ? raw.rumble : DEFAULTS.rumble,
      ways: raw.ways === 8 ? 8 : 4,
      touchStyle: raw.touchStyle && typeof raw.touchStyle === "object" ? raw.touchStyle : {},
    };
  } catch {
    return DEFAULTS;
  }
}

type ControlsStore = Persisted & {
  /** Custom remap in progress: the next key press is bound here. */
  capture: { player: number; key: GameKey } | null;
  set: (p: Partial<Persisted>) => void;
  setPlayer: (player: number, p: Partial<PlayerCfg>) => void;
};

export const useControls = create<ControlsStore>((set, get) => ({
  ...load(),
  capture: null,
  set: (p) => {
    set(p);
    save(get());
  },
  setPlayer: (player, p) => {
    const players = get().players.map((x, i) => (i === player - 1 ? { ...x, ...p } : x));
    set({ players });
    save(get());
  },
}));

function save(s: Persisted) {
  const keep: Persisted = { players: s.players, pads: s.pads, deadzone: s.deadzone, rumble: s.rumble, ways: s.ways, touchStyle: s.touchStyle };
  try {
    localStorage.setItem(KEY, JSON.stringify(keep));
  } catch {
    /* private mode: bindings just won't persist */
  }
}

// ------------------------------------------------------------------ keyboard
/** The binding a player's keyboard preset stands for (empty for "none"). */
export function bindingOf(p: PlayerCfg): Binding {
  if (p.kb === "none") return blank();
  if (p.kb === "custom") return p.custom;
  return PRESETS[p.kb].binding;
}

export type KeyTarget = { player: number; key: GameKey };
let cachedPlayers: PlayerCfg[] | null = null;
let cachedMap = new Map<string, KeyTarget[]>();
/** code -> who it drives. The first owner wins when a key is bound twice (the panel shows the conflict). */
export function keyboardMap(players: PlayerCfg[] = useControls.getState().players): Map<string, KeyTarget[]> {
  if (players === cachedPlayers) return cachedMap;
  const m = new Map<string, KeyTarget[]>();
  const add = (code: string, t: KeyTarget) => m.set(code, [...(m.get(code) ?? []), t]);
  players.forEach((p, i) => {
    const b = bindingOf(p);
    for (const k of GAME_KEYS) for (const c of b[k]) add(c, { player: i + 1, key: k });
  });
  const others = players.slice(1).some((p) => p.kb !== "none");
  if (players[0].kb === "arrows" && !others)
    for (const k of GAME_KEYS) for (const c of SOLO_ALIAS[k] ?? []) if (!m.has(c)) add(c, { player: 1, key: k });
  cachedPlayers = players;
  cachedMap = m;
  return m;
}

/** Keys bound to more than one thing, and game keys that shadow a Play-mode shortcut. */
export function conflicts(players: PlayerCfg[]): Map<string, string> {
  const out = new Map<string, string>();
  const owners = new Map<string, KeyTarget[]>();
  players.forEach((p, i) => {
    const b = bindingOf(p);
    for (const k of GAME_KEYS) for (const c of b[k]) owners.set(c, [...(owners.get(c) ?? []), { player: i + 1, key: k }]);
  });
  owners.forEach((ts, code) => {
    if (ts.length > 1) out.set(code, `${keyLabel(code)} is bound to ${ts.map((t) => `P${t.player} ${t.key.toUpperCase()}`).join(" and ")}`);
    else if (RESERVED[code]) out.set(code, `${keyLabel(code)} also means “${RESERVED[code]}” — the game key wins`);
  });
  return out;
}

const NAMES: Record<string, string> = {
  ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→", Space: "Space", Enter: "Enter",
  ShiftLeft: "Shift", ShiftRight: "R Shift", ControlLeft: "Ctrl", ControlRight: "R Ctrl", Semicolon: ";", Quote: "'",
  Comma: ",", Period: ".", Slash: "/", Backslash: "\\", BracketLeft: "[", BracketRight: "]", Minus: "-", Equal: "=",
  Backquote: "`", Tab: "Tab", Backspace: "Bksp", Escape: "Esc", AltLeft: "Alt", AltRight: "AltGr",
};
/** A short keycap label for a `KeyboardEvent.code`. */
export function keyLabel(code: string): string {
  if (NAMES[code]) return NAMES[code];
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  if (code.startsWith("Numpad")) return `Num ${code.slice(6)}`;
  return code;
}

/** Custom remap: bind the pressed key. Returns true when a capture consumed the event. */
export function captureKey(e: KeyboardEvent): boolean {
  const s = useControls.getState();
  if (!s.capture) return false;
  e.preventDefault();
  e.stopPropagation();
  const { player, key } = s.capture;
  if (e.code === "Escape") {
    useControls.setState({ capture: null });
    return true;
  }
  const p = s.players[player - 1];
  const custom = p.kb === "custom" ? copy(p.custom) : copy(bindingOf(p));
  custom[key] = e.code === "Backspace" || e.code === "Delete" ? [] : [e.code];
  useControls.setState({ capture: null });
  s.setPlayer(player, { kb: "custom", custom });
  return true;
}

// ------------------------------------------------------------------ seats & touch
/** How many seats a game has (from /api/meta, else the lobby's list). */
export function maxPlayersOf(app: string | null | undefined): number {
  if (!app) return 1;
  const m = appMeta(app)?.max_players;
  if (typeof m === "number" && m > 0) return m;
  return useStore.getState().mpGames?.[app] ?? 1;
}

/**
 * Where a local player's input goes in `app`: single-player games fold every player onto seat 1 (anyone can play),
 * multiplayer games drop players beyond their seats (null).
 */
export function seatFor(app: string, player: number): number | null {
  const max = maxPlayersOf(app);
  if (max <= 1) return 1;
  return player <= max ? player : null;
}

/** The game's recommended on-screen controller, unless the user picked one for this game. */
export function touchStyleFor(app: string | null, picked: Record<string, TouchStyle>): TouchStyle {
  if (app && picked[app]) return picked[app];
  const rec = (app && appMeta(app)?.controls) || [];
  return (rec.find((c) => (TOUCH_STYLES as readonly string[]).includes(c)) as TouchStyle | undefined) ?? "dpad";
}

export const coarsePointer = () => typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches;
/** Players who get on-screen controls (P1 automatically on touch screens). */
export function touchPlayers(players: PlayerCfg[], coarse: boolean, max: number): number[] {
  const out: number[] = [];
  players.forEach((p, i) => {
    if (i + 1 > Math.max(1, max)) return;
    if (p.touch === true || (p.touch === null && i === 0 && coarse)) out.push(i + 1);
  });
  return out;
}

/** One-click "two players on one keyboard": P1 = W A S D + F/G, P2 = arrows + Space/Shift. */
export function twoOnOneKeyboard() {
  const s = useControls.getState();
  const players = s.players.map((p, i) => (i === 0 ? { ...p, kb: "wasd" as const } : i === 1 ? { ...p, kb: "arrows" as const } : p.kb === "wasd" || p.kb === "arrows" ? { ...p, kb: "none" as const } : p));
  s.set({ players });
}
export function soloKeyboard() {
  const s = useControls.getState();
  s.set({ players: s.players.map((p, i) => (i === 0 ? { ...p, kb: "arrows" as const } : p.kb === "arrows" || p.kb === "wasd" ? { ...p, kb: "none" as const } : p)) });
}
