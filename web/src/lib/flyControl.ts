import { create } from "zustand";
import { api } from "./api";
import { flyCanPilot, flyHandBack, flyTakeOver, useFly } from "./fly";
import { appMeta, toast, useStore } from "./store";
import type { AppMeta, Meta } from "./types";

/**
 * Entering and leaving "the fly plays" from anywhere in the studio: the top bar, Play mode, a game's status bar,
 * the command palette and the F shortcut all go through these helpers (docs/FLY_BRAIN.md).
 */

/** The game picker that opens when "Let the fly play" is pressed while no game is showing. */
export const useFlyPicker = create<{ open: boolean; set: (open: boolean) => void }>((set) => ({
  open: false,
  set: (open) => set({ open }),
}));

let cachedMeta: Meta | null = null;
let cachedGames: AppMeta[] = [];
/** Every app the fly can play (games with the `pilot` setting), by name. Stable per `meta` (safe in selectors). */
export function flyGames(meta: Meta | null): AppMeta[] {
  if (meta !== cachedMeta) {
    cachedMeta = meta;
    cachedGames = (meta?.apps ?? []).filter((a) => !!a.schema?.properties?.pilot).sort((x, y) => x.name.localeCompare(y.name));
  }
  return cachedGames;
}

/** Is the fly playing the game on the panel right now? */
export function useFlyPlaying(): boolean {
  const cur = useStore((s) => s.state?.engine.current);
  const snap = useFly((s) => s.snap);
  if (!cur || !flyCanPilot(cur.app)) return false;
  return cur.status?.player === "fly" || (snap.active && snap.app === cur.app && snap.driving !== false);
}

/** Can the current app be handed to the fly (it's a game)? */
export function useCurrentIsFlyGame(): boolean {
  useStore((s) => s.meta); // re-render once meta arrives
  return flyCanPilot(useStore((s) => s.state?.engine.current?.app));
}

const nameOf = (id: string) => appMeta(id)?.name ?? id;

/** Hand `app` (default: the game on the panel) to the fruit fly. A game that isn't showing is started first. */
export async function letFlyPlay(app?: string) {
  const cur = useStore.getState().state?.engine.current?.app;
  const target = app ?? cur;
  useFlyPicker.getState().set(false);
  if (!target || !flyCanPilot(target)) {
    useFlyPicker.getState().set(true); // nothing playable on the panel: pick a game
    return;
  }
  try {
    if (target === cur) {
      await flyTakeOver();
    } else {
      await api.patchSettings(target, { pilot: "fly" });
      await api.activate(target);
      await api.action(target, "fly").catch(() => undefined); // older engines: it takes over after the idle wait
      await flyTakeOver();
    }
    useStore.getState().prefs({ lastGame: target });
    toast(`The fruit fly is playing ${nameOf(target)}`, "ok");
  } catch {
    toast("The fly couldn't get to the panel", "error");
  }
}

/** Take the game back from the fly: its built-in AI keeps it warm until you press a key. */
export async function takeBackFromFly() {
  const cur = useStore.getState().state?.engine.current?.app;
  try {
    await flyHandBack();
    if (cur && flyCanPilot(cur) && useFly.getState().snap.app !== cur) await api.patchSettings(cur, { pilot: "ai" });
    toast(cur ? `${nameOf(cur)} is yours again — press any game key to play` : "The fly is back to roaming", "ok");
  } catch {
    toast("Couldn't take the game back from the fly", "error");
  }
}

/** One toggle for buttons and the F key. */
export function toggleFly(playing: boolean) {
  return playing ? takeBackFromFly() : letFlyPlay();
}

/** Non-hook check (shortcut, palette) of whether the fly is playing the current game. */
export function flyPlayingNow(): boolean {
  const cur = useStore.getState().state?.engine.current;
  const snap = useFly.getState().snap;
  if (!cur || !flyCanPilot(cur.app)) return false;
  return cur.status?.player === "fly" || (snap.active && snap.app === cur.app && snap.driving !== false);
}
