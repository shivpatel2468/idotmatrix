import { create } from "zustand";

/**
 * How the live 32×32 preview is drawn on this screen (per browser, remembered):
 *  - "glow":  sharp square pixels + a soft bloom — looks great on a laptop/monitor (default)
 *  - "pixel": sharp square pixels only — pure pixel art, best for games and screenshots
 *  - "led":   a physical LED-matrix replica (round dots, gaps, glow) — to judge how it will look on the panel
 */
export type PanelLook = "glow" | "pixel" | "led";

const KEY = "dotdeck.panelLook";
const LOOKS: PanelLook[] = ["glow", "pixel", "led"];

function load(): PanelLook {
  try {
    const v = localStorage.getItem(KEY) as PanelLook | null;
    return v && LOOKS.includes(v) ? v : "glow";
  } catch {
    return "glow";
  }
}

/**
 * Bloom amount for the "glow" look, 0..1 (0 = crisp, no bloom; 0.5 = the classic glow; 1 = twice as soft).
 * Shown as the "Sharpness" slider in Play mode's Display menu.
 */
const BLOOM_KEY = "dotdeck.panelBloom";
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

export const useLook = create<{ look: PanelLook; bloom: number; setLook: (l: PanelLook) => void; setBloom: (b: number) => void }>((set) => ({
  look: load(),
  bloom: loadBloom(),
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
