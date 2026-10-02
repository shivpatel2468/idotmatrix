import { create } from "zustand";

/**
 * How the live 32×32 preview is drawn on this screen (per browser, remembered):
 *  - "glow":  sharp square pixels + a soft bloom — looks great on a laptop/monitor (default)
 *  - "pixel": sharp square pixels only — pure pixel art, best for games and screenshots
 *  - "led":   a physical LED-matrix replica (round dots, gaps, glow) — to judge how it will look on the panel
 */
export type PanelLook = "glow" | "pixel" | "led";

const KEY = "deskdot.panelLook";
const LOOKS: PanelLook[] = ["glow", "pixel", "led"];

function load(): PanelLook {
  try {
    const v = (localStorage.getItem(KEY) ?? localStorage.getItem(KEY.replace("deskdot", "dotdeck"))) as PanelLook | null;
    return v && LOOKS.includes(v) ? v : "glow";
  } catch {
    return "glow";
  }
}

/**
 * Bloom amount for the "glow" look, 0..1 (0 = crisp, no bloom; 0.5 = the classic glow; 1 = twice as soft).
 * Shown as the "Sharpness" slider in Play mode's Display menu.
 */
const BLOOM_KEY = "deskdot.panelBloom";
export const DEFAULT_BLOOM = 0.5;
function loadBloom(): number {
  try {
    const v = Number(localStorage.getItem(BLOOM_KEY));
    return localStorage.getItem(BLOOM_KEY) !== null && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : DEFAULT_BLOOM;
  } catch {
    return DEFAULT_BLOOM;
  }
}

function persist(key: string, v: string) {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* private mode: just won't persist */
  }
}

/**
 * Colour match: should the preview show the panel's colour calibration (what the LEDs are actually sent)?
 *  - "led": only in the LED look (default — that look exists to judge the real panel)
 *  - "all": in every look
 *  - "off": never (the preview shows the app's design colours untouched)
 */
export type ColorMatch = "led" | "all" | "off";
const MATCH_KEY = "deskdot.panelMatch";
const MATCHES: ColorMatch[] = ["led", "all", "off"];
function loadMatch(): ColorMatch {
  try {
    const v = localStorage.getItem(MATCH_KEY) as ColorMatch | null;
    return v && MATCHES.includes(v) ? v : "led";
  } catch {
    return "led";
  }
}
export const MATCH_LABEL: Record<ColorMatch, string> = { led: "LED look only", all: "Every look", off: "Off" };
export const MATCH_HINT: Record<ColorMatch, string> = {
  led: "The LED look shows your panel calibration; Glow and Pixel show the design colours",
  all: "Every preview shows the colours exactly as the panel is sent them",
  off: "Previews always show the untouched design colours",
};
export { MATCHES };

/** Does `look` apply the panel calibration under the viewer's colour-match choice? */
export const matchesPanel = (look: PanelLook, match: ColorMatch) => match === "all" || (match === "led" && look === "led");

export const useLook = create<{
  look: PanelLook; bloom: number; match: ColorMatch;
  setLook: (l: PanelLook) => void; setBloom: (b: number) => void; setMatch: (m: ColorMatch) => void;
}>((set) => ({
  look: load(),
  bloom: loadBloom(),
  match: loadMatch(),
  setMatch: (match) => {
    set({ match });
    persist(MATCH_KEY, match);
  },
  setLook: (look) => {
    set({ look });
    persist(KEY, look);
  },
  setBloom: (b) => {
    const bloom = Math.min(1, Math.max(0, b));
    set({ bloom });
    persist(BLOOM_KEY, String(bloom));
  },
}));

export const LOOK_LABEL: Record<PanelLook, string> = { glow: "Glow", pixel: "Pixel", led: "LED" };
export const LOOK_HINT: Record<PanelLook, string> = {
  glow: "Sharp pixels with a soft glow — best on a laptop screen",
  pixel: "Pure sharp pixels — best for games and screenshots",
  led: "Looks like the real LED panel — to check your designs",
};
export { LOOKS };
