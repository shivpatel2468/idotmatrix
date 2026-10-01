import { useEffect, useState } from "react";
import type { AppMeta, Meta } from "./types";
import { api } from "./api";
import { captureKey, keyboardMap, seatFor } from "./controls";
import { EMPTY_LIST, toast, useStore } from "./store";
import { sendInput } from "./ws";

/**
 * Game input: one controller for keyboards, gamepads and touch, for every local player.
 *
 * A key sends once on press, then — only for keys where holding makes sense — auto-repeats on our own timer
 * (initial delay, then a steady rate) instead of the OS key-repeat, which is slow to start and varies per machine.
 * Inputs go straight over the WebSocket (`sendInput`), never through React state. A key is held per
 * (player, key): two sources driving the same player (keyboard + pad, stick + d-pad) never double-send.
 */
export type GameKey = "up" | "down" | "left" | "right" | "a" | "b";
/** [initial delay ms, repeat interval ms]; a key without an entry sends once per press. */
type Repeat = [number, number];
type Profile = Partial<Record<GameKey, Repeat>>;

const ARROWS: Repeat = [170, 65];
const DEFAULT_PROFILE: Profile = { up: ARROWS, down: ARROWS, left: ARROWS, right: ARROWS };
const PADDLE: Repeat = [90, 45];
const CURSOR: Repeat = [240, 115];
const FIRE: Repeat = [220, 190];

/** Per-game feel. Rotate / jump / hard-drop / turn keys never repeat: one press, one action. */
const PROFILES: Record<string, Profile> = {
  arcade: {}, // Snake: a held arrow just keeps the heading
  maze: {},
  g2048: {}, // one slide per press
  flappy: {},
  dino: {},
  tetris: { left: [150, 50], right: [150, 50], down: [110, 40] },
  racer: { left: [240, 160], right: [240, 160] },
  tictactoe: { up: CURSOR, down: CURSOR, left: CURSOR, right: CURSOR },
  mines: { up: CURSOR, down: CURSOR, left: CURSOR, right: CURSOR },
  invaders: { left: [110, 55], right: [110, 55], a: FIRE },
  starship: { left: [110, 55], right: [110, 55], a: FIRE },
  asteroids: { left: [90, 45], right: [90, 45], up: [90, 70], a: FIRE },
  pong: { up: PADDLE, down: PADDLE },
  breakout: { left: PADDLE, right: PADDLE },
  infinity: { up: PADDLE, down: PADDLE, a: PADDLE, b: PADDLE },
};
const MENU_FLOWS = new Set(["home", "teams", "intro", "outro"]);
export const repeatFor = (app: string, key: GameKey): Repeat | null => (PROFILES[app] ?? DEFAULT_PROFILE)[key] ?? null;

/** A game you can actually play (base class GameApp: restart + autoplay actions), not e.g. Game Deals. */
export const isPlayable = (a: AppMeta | null | undefined) =>
  !!a && (a.id === "arcade" || (a.category === "games" && a.actions.some((x) => x.id === "demo")));

let cachedMeta: Meta | null = null;
let cachedGames: readonly AppMeta[] = EMPTY_LIST;
/** Playable games in library order. Stable reference per `meta`, so it is safe inside zustand selectors. */
export function playableGames(meta: Meta | null): readonly AppMeta[] {
  if (meta !== cachedMeta) {
    cachedMeta = meta;
    cachedGames = meta ? meta.apps.filter(isPlayable).sort((x, y) => x.name.localeCompare(y.name)) : EMPTY_LIST;
  }
  return cachedGames;
}

/**
 * Enter Play mode: on the game that's showing, else `id`, else the last game played, else the first one.
 * Pauses a running playlist (activating an app does), so the game isn't rotated away mid-play.
 */
export async function openPlay(id?: string) {
  const s = useStore.getState();
  const games = playableGames(s.meta);
  const cur = s.state?.engine.current?.app;
  const target = id ?? (games.some((g) => g.id === cur) ? cur : (games.find((g) => g.id === s.lastGame) ?? games[0])?.id);
  if (!target) {
    toast("No games are installed", "error");
    return;
  }
  useStore.setState({ playMode: true, palette: false, drawer: null });
  if (target !== cur || s.state?.engine.mode === "playlist") await api.activate(target).catch(() => {});
}

// ------------------------------------------------------------------ controller
/** Games where a deeper stick deflection repeats faster: how much faster at full tilt (racers most, paddles a bit). */
const ANALOG: Record<string, number> = { racer: 0.5, streetsurge: 0.5, neonheat: 0.5, pong: 0.3, breakout: 0.3 };

type Held = {
  app: string;
  seat: number;
  sources: Set<string>;
  timer: ReturnType<typeof setTimeout> | null;
  since: number;
  depth: number; // 0..1 past the stick threshold (0 for keys and buttons)
};
const held = new Map<string, Held>(); // `${player}:${key}`
const lit = new Map<number, Set<GameKey>>(); // what each player's on-screen pad / keycaps show as pressed
const listeners = new Set<() => void>();
const unlight = new Map<string, ReturnType<typeof setTimeout>>();
const MIN_LIT_MS = 90; // a quick tap still visibly depresses the key
const hk = (player: number, key: GameKey) => `${player}:${key}`;
const emit = () => listeners.forEach((l) => l());

// "last input" lights in the Controls panel: listeners hear every send (press and repeat) per player
const inputListeners = new Set<(player: number) => void>();
const sent = (player: number) => inputListeners.forEach((l) => l(player));
export function onPlayerInput(l: (player: number) => void) {
  inputListeners.add(l);
  return () => void inputListeners.delete(l);
}

function delay(app: string, rep: Repeat, depth: number, first: boolean) {
  const ms = first ? rep[0] : rep[1];
  const k = ANALOG[app] ?? 0;
  return k && depth > 0 ? ms * (1 - k * Math.min(1, depth)) : ms;
}

/**
 * Start holding `key` for local `player` from `source` (a keyboard key, a pointer, a gamepad). Sends immediately.
 * `depth` (0..1) is how far past the threshold a stick is pushed — in racers and paddle games it speeds up repeat.
 */
export function pressKey(key: GameKey, source: string, app: string, player = 1, depth = 0) {
  const seat = seatFor(app, player);
  if (seat == null) return; // e.g. player 3 in a 2-player game
  const id = hk(player, key);
  const h = held.get(id);
  if (h) {
    h.sources.add(source); // e.g. ArrowUp and the pad's d-pad held together: still one press
    h.depth = Math.max(h.depth, depth);
    return;
  }
  sendInput(app, key, seat);
  sent(player);
  const entry: Held = { app, seat, sources: new Set([source]), timer: null, since: performance.now(), depth };
  // on the game's own screens (home menu, side select, results) one press = one step: no auto-repeat
  const flow = useStore.getState().state?.engine.current?.status?.flow;
  const rep = typeof flow === "string" && MENU_FLOWS.has(flow) ? null : repeatFor(app, key);
  if (rep) {
    const tick = () => {
      sendInput(entry.app, key, entry.seat);
      sent(player);
      entry.timer = setTimeout(tick, delay(entry.app, rep, entry.depth, false));
    };
    entry.timer = setTimeout(tick, delay(app, rep, depth, true));
  }
  held.set(id, entry);
  clearTimeout(unlight.get(id));
  unlight.delete(id);
  const set = lit.get(player) ?? new Set<GameKey>();
  lit.set(player, set);
  set.add(key);
  emit();
}

/** A held stick direction moved deeper or shallower: the next repeat uses the new speed. */
export function setHoldDepth(key: GameKey, player: number, depth: number) {
  const h = held.get(hk(player, key));
  if (h) h.depth = depth;
}

/** Stop holding `key` from `source` (the key stays held while another source still holds it). */
export function releaseKey(key: GameKey, source: string, player = 1) {
  const id = hk(player, key);
  const h = held.get(id);
  if (!h) return;
  h.sources.delete(source);
  if (h.sources.size) return;
  if (h.timer) clearTimeout(h.timer);
  held.delete(id);
  const wait = Math.max(0, MIN_LIT_MS - (performance.now() - h.since));
  unlight.set(id, setTimeout(() => {
    unlight.delete(id);
    if (!held.has(id)) {
      lit.get(player)?.delete(key);
      emit();
    }
  }, wait));
}

export function releaseAll() {
  for (const h of held.values()) if (h.timer) clearTimeout(h.timer);
  held.clear();
  pressedCodes.clear();
  unlight.forEach((t) => clearTimeout(t));
  unlight.clear();
  if ([...lit.values()].some((x) => x.size)) {
    lit.clear();
    emit();
  }
}

/** Keyboard codes held right now -> what they pressed (a remap mid-hold still releases the right key). */
const pressedCodes = new Map<string, { player: number; key: GameKey }>();

/**
 * Keyboard: call from a keydown handler. Returns true (and prevents the default — no page scroll, no button
 * activation) when the key is a game key for any local player. OS auto-repeat events are swallowed: our own
 * timer repeats. A Custom-remap capture in progress takes the key first.
 */
export function gameKeyDown(e: KeyboardEvent, app: string): boolean {
  if (captureKey(e)) return true;
  const t = keyboardMap().get(e.code)?.[0]; // a doubly-bound key drives its first owner (the panel flags it)
  if (!t) return false;
  e.preventDefault();
  if (e.repeat || pressedCodes.has(e.code)) return true;
  pressedCodes.set(e.code, t);
  pressKey(t.key, `kb:${e.code}`, app, t.player);
  return true;
}

if (typeof window !== "undefined") {
  window.addEventListener("keyup", (e) => {
    const t = pressedCodes.get(e.code);
    if (!t) return;
    pressedCodes.delete(e.code);
    e.preventDefault(); // Space/Enter keyup must not click a focused button mid-game
    releaseKey(t.key, `kb:${e.code}`, t.player);
  }, true);
  window.addEventListener("blur", releaseAll);
  document.addEventListener("visibilitychange", () => document.hidden && releaseAll());
  // a different app took over (playlist, autopilot, game switch): stop repeating into the old one
  let lastApp: string | undefined;
  useStore.subscribe((s) => {
    const a = s.state?.engine.current?.app;
    if (a !== lastApp) {
      lastApp = a;
      releaseAll();
    }
  });
}

const NONE: ReadonlySet<GameKey> = new Set();
/** React: the game keys currently shown as pressed for `player`. */
export function usePressedKeys(player = 1): ReadonlySet<GameKey> {
  const [keys, setKeys] = useState<ReadonlySet<GameKey>>(() => new Set(lit.get(player) ?? NONE));
  useEffect(() => {
    let last: string | null = null;
    const on = () => {
      const cur = lit.get(player) ?? NONE;
      const sig = [...cur].sort().join();
      if (sig === last) return;
      last = sig;
      setKeys(new Set(cur));
    };
    on();
    listeners.add(on);
    return () => void listeners.delete(on);
  }, [player]);
  return keys;
}

/** React: true for ~160 ms after `player` sent an input (the Controls panel's activity light). */
export function useInputFlash(player: number): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = onPlayerInput((p) => {
      if (p !== player) return;
      setOn(true);
      clearTimeout(t);
      t = setTimeout(() => setOn(false), 160);
    });
    return () => {
      off();
      clearTimeout(t);
    };
  }, [player]);
  return on;
}
