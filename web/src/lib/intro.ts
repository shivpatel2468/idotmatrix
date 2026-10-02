/** The studio's intro / outro theme: a per-browser choice (it plays before the engine is even reachable). */
export type IntroTheme = "sunset" | "circuit" | "og" | "off";

export const INTRO_THEMES: { id: IntroTheme; name: string; hint: string }[] = [
  { id: "sunset", name: "Sunset", hint: "Warm retro-synthwave: striped sun, neon grid, film grain; the doors glide apart 50/50" },
  { id: "circuit", name: "Circuit", hint: "A sealed LED-matrix face with circuit traces and a power-surge ring" },
  { id: "og", name: "OG", hint: "The original: LEDs fly in and settle into the wordmark" },
  { id: "off", name: "Off", hint: "No intro: a quick fade" },
];

const KEY = "deskdot.intro";
const listeners = new Set<() => void>();

export function getIntroTheme(): IntroTheme {
  try {
    const v = localStorage.getItem(KEY) as IntroTheme | null;
    return v && INTRO_THEMES.some((t) => t.id === v) ? v : "sunset";
  } catch {
    return "sunset";
  }
}

export function setIntroTheme(v: IntroTheme) {
  try {
    localStorage.setItem(KEY, v);
  } catch {
    /* private mode */
  }
  listeners.forEach((l) => l());
}

/** Play the intro again now (a preview from Settings). */
export function replayIntro() {
  window.dispatchEvent(new Event("deskdot:replay-intro"));
}

export function onIntroTheme(l: () => void) {
  listeners.add(l);
  return () => void listeners.delete(l);
}
