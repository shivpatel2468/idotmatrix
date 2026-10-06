/** The studio's intro / outro theme: a per-browser choice (it plays before the engine is even reachable). */
export type IntroTheme = "sunset" | "circuit" | "coin" | "og" | "off";

export const INTRO_THEMES: { id: IntroTheme; name: string; hint: string }[] = [
  { id: "sunset", name: "Sunset", hint: "Warm retro-synthwave: striped sun, neon grid, film grain; the doors glide apart 50/50" },
  { id: "circuit", name: "Circuit", hint: "A sealed LED-matrix face with circuit traces and a power-surge ring" },
  { id: "coin", name: "Coin Gate", hint: "An arcade cabinet: drop a silver coin, CREDIT 1, and the heavy toothed gate rolls open" },
  { id: "og", name: "OG", hint: "The original: LEDs fly in and glide into the wordmark — clean and glare-free" },
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
