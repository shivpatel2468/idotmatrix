/**
 * Recently shown apps (newest first, per browser in localStorage `deskdot.recent`) — the phone Panel tab's
 * "Recent" row. Fed by the state stream: every time the app on the panel changes, it moves to the front.
 */
import { useSyncExternalStore } from "react";
import { useStore } from "./store";

const KEY = "deskdot.recent";
const MAX = 16;

function load(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

let recent = load();
const listeners = new Set<() => void>();

function push(id: string) {
  if (recent[0] === id) return;
  recent = [id, ...recent.filter((x) => x !== id)].slice(0, MAX);
  try {
    localStorage.setItem(KEY, JSON.stringify(recent));
  } catch {
    /* private mode: this session only */
  }
  listeners.forEach((l) => l());
}

let installed = false;
/** Start following the app on the panel (once; App.tsx). */
export function installRecent() {
  if (installed) return;
  installed = true;
  let last: string | undefined;
  useStore.subscribe((s) => {
    const id = s.state?.engine.current?.app;
    if (id && id !== last) {
      last = id;
      push(id);
    }
  });
}

const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));
/** The recent app ids, newest first (a stable array between changes). */
export const useRecent = () => useSyncExternalStore(subscribe, () => recent, () => recent);
