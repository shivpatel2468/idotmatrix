/**
 * The studio theme: light | dark | system (Auto: the OS's prefers-color-scheme). First run: dark (the casino's
 * tables are made for it); a saved choice is kept.
 *
 * Contract shared with every DeskDot page (studio, casino.html, controller.html, join pages, the TV):
 *   - stored in localStorage `deskdot.theme` (pages served by the engine share the origin, so it carries over);
 *   - applied as `<html data-theme="light|dark">` plus `color-scheme`, BEFORE first paint (inline script in
 *     web/index.html — keep it in step with `apply()` below);
 *   - colours come from the tokens in web/src/index.css (`--color-*`, `--m-*`);
 *   - inside the Android app, Android's status / navigation bars follow too (lib/android.ts → DeskDotAndroid.setBars).
 */
import { useSyncExternalStore } from "react";
import { syncSystemBars } from "./android";
import { onPageTheme, pageBars } from "./pageTheme";

export type ThemePref = "light" | "dark" | "system";
export type Theme = "light" | "dark";

export const THEME_KEY = "deskdot.theme";
export const THEME_CHOICES: { id: ThemePref; name: string; hint: string }[] = [
  { id: "light", name: "Light", hint: "Porcelain and ink, rose accents" },
  { id: "dark", name: "Dark", hint: "Graphite instrument panel" },
  { id: "system", name: "Auto", hint: "Follow this device" },
];

/** The browser-bar colour (meta theme-color): the page colour, chassis-0 — tinted by the page theme (lib/pageTheme.ts). */
const bar = (theme: Theme) => pageBars(theme).page;

const media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

export function getThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage blocked: the default */
  }
  return "dark";
}

export const resolveTheme = (pref: ThemePref): Theme => (pref === "system" ? (media?.matches ? "light" : "dark") : pref);

const listeners = new Set<() => void>();
let current: Theme = typeof document !== "undefined" && document.documentElement.dataset.theme === "light" ? "light" : "dark";

function apply(theme: Theme, animate: boolean) {
  const root = document.documentElement;
  if (root.dataset.theme === theme) return;
  if (animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    root.classList.add("theme-fade");
    window.setTimeout(() => root.classList.remove("theme-fade"), 450);
  }
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bar(theme));
  syncSystemBars(theme);
  current = theme;
  listeners.forEach((l) => l());
}

export function setThemePref(pref: ThemePref) {
  try {
    localStorage.setItem(THEME_KEY, pref);
  } catch {
    /* private mode: this session only */
  }
  apply(resolveTheme(pref), true);
  listeners.forEach((l) => l());
}

/** Wire the live updates: the OS switching light/dark (pref = system) and another tab changing the pref. */
export function installTheme() {
  apply(resolveTheme(getThemePref()), false);
  syncSystemBars(current); // index.html already applied the theme (apply() skipped): still tell the Android app
  media?.addEventListener?.("change", () => getThemePref() === "system" && apply(resolveTheme("system"), true));
  window.addEventListener("storage", (e) => e.key === THEME_KEY && apply(resolveTheme(getThemePref()), true));
  // a page theme tints the page: the browser bar and the Android system bars follow it too
  onPageTheme(() => {
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bar(current));
    syncSystemBars(current);
  });
}

const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));

/** The theme on screen now ("light" | "dark"). */
export const useTheme = () => useSyncExternalStore(subscribe, () => current, () => current);
/** One tap: the other theme, as an explicit choice (the floating theme key). */
export const toggleTheme = () => setThemePref(current === "dark" ? "light" : "dark");

/** The stored choice ("light" | "dark" | "system"). */
export const useThemePref = () => useSyncExternalStore(subscribe, getThemePref, getThemePref);
