/**
 * `window.DeskDotAndroid` — the small bridge the Android app (android/…/MainActivity.kt, `Bridge`) adds to the studio's
 * WebView. Absent everywhere else (desktop browsers, the web app), so every call here is a safe no-op there.
 *
 *   setBars(status, nav, page, lightIcons)  system bar colours + icon contrast for the studio theme on screen
 *   icons() / getIcon() / setIcon(id)       the launcher icon (one <activity-alias> per icon)
 *   display()                               {"hz": now, "max": best, "modes": [...]} — the screen's refresh rate
 *   insets()                                {"top","bottom","left","right"} in CSS px (index.html reads it before paint)
 *   introDone()                             the studio is ready: the app's native LED intro hands over (Boot.tsx)
 * The app also calls `window.__deskdotBack()` on the Back button: true = the studio closed something (a sheet, a menu).
 */
import { pageBars } from "./pageTheme";
import { backStep } from "./backStep";
import { useStore } from "./store";

type Bridge = {
  version(): number;
  setBars(status: string, nav: string, page: string, lightIcons: boolean): void;
  icons(): string;
  getIcon(): string;
  setIcon(id: string): boolean;
  display(): string;
  insets?(): string;
  introDone?(): void;
};

const bridge = (): Bridge | null => {
  const b = (window as unknown as { DeskDotAndroid?: Bridge }).DeskDotAndroid;
  return b && typeof b.setBars === "function" ? b : null;
};

/** True inside the DeskDot Android app. */
export const inAndroidApp = () => bridge() !== null;

/** Paint Android's status and navigation bars (and the window behind the page) for a studio theme: the header
 *  (chassis-1), the tab bar (--m-glass) and the page (chassis-0), as tinted by the page theme (lib/pageTheme.ts). */
export function syncSystemBars(theme: "light" | "dark") {
  const b = bridge();
  if (!b) return;
  const { status, nav, page } = pageBars(theme);
  const lightIcons = theme === "dark";
  try {
    b.setBars(status, nav, page, lightIcons);
  } catch {
    /* an older app without this method: the bars just stay as they are */
  }
}

/** The launcher icon in use, or null outside the app. */
export function currentAppIcon(): string | null {
  try {
    return bridge()?.getIcon() ?? null;
  } catch {
    return null;
  }
}

/** Switch the launcher icon; false if the app refused (unknown id) or isn't there. */
export function setAppIcon(id: string): boolean {
  try {
    return bridge()?.setIcon(id) ?? false;
  } catch {
    return false;
  }
}

/** The ids the installed app knows (an older APK may have fewer icons than the studio shows). */
export function appIconIds(): string[] | null {
  try {
    const raw = bridge()?.icons();
    return raw ? (JSON.parse(raw) as string[]) : null;
  } catch {
    return null;
  }
}

export type ScreenInfo = { hz: number; max: number; modes: number[] };

/** The phone screen's refresh rate now / at best (null outside the app). */
export function screenInfo(): ScreenInfo | null {
  try {
    const raw = bridge()?.display();
    const v = raw ? (JSON.parse(raw) as Partial<ScreenInfo>) : null;
    return v && typeof v.hz === "number" ? { hz: v.hz, max: v.max ?? v.hz, modes: v.modes ?? [] } : null;
  } catch {
    return null;
  }
}

/** True when the app plays its own (native) intro: the studio skips its intro and tells the app when it is ready. */
export function nativeIntro(): boolean {
  const b = bridge();
  return !!b && typeof b.introDone === "function";
}

/** The studio has its engine, its apps and the first state: the app's intro may hand over now. */
export function introDone() {
  try {
    bridge()?.introDone?.();
  } catch {
    /* an older app */
  }
}

/**
 * Android's Back button, innermost first: close whatever is open on top (a sheet, a dialog, a menu) the way Escape
 * does; else, on a tab other than Panel (Apps, Presets, Settings), go back to the Panel tab. Returns false only on
 * the Panel tab with nothing open, so the app then goes to the home screen as before.
 */
export function backAction(): boolean {
  const open = document.querySelector('[aria-modal="true"], [role="dialog"], [role="menu"], [role="listbox"]');
  const step = backStep(open !== null, useStore.getState().mobileTab);
  if (step === "close") {
    const target = (document.activeElement as HTMLElement | null) ?? document.body;
    target.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }));
  } else if (step === "panel") {
    useStore.setState({ mobileTab: "panel" });
  }
  return step !== "leave";
}

export function installBackButton() {
  (window as unknown as { __deskdotBack?: () => boolean }).__deskdotBack = backAction;
}
