import { recentlyPlayed, sfx } from "./sound";
import { useStore } from "./store";

/**
 * The studio's ambient sound wiring (docs/STUDIO_UI.md "Sound"), installed once from main.tsx:
 *  - one delegated click listener: soft ticks for keys, tabs, segmented controls and switches
 *    (opt out with `data-sfx="off"` on an element or an ancestor, or name another effect: `data-sfx="chip"`);
 *  - store watchers: toasts (info / ok / error), the app on the panel changing, and Play mode game flow + score.
 * Casino rounds are voiced by components/casino/sounds.ts; the roaming fly buzzes from RoamingFly.tsx.
 */
let installed = false;
export function installStudioSounds() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  document.addEventListener("click", onClick, true);
  watchStore();
}

function onClick(e: MouseEvent) {
  const el = (e.target as Element | null)?.closest?.("button, [role=button], [role=switch], [role=tab], a.key");
  if (!el || (el as HTMLButtonElement).disabled || el.getAttribute("aria-disabled") === "true") return;
  const own = el.closest("[data-sfx]")?.getAttribute("data-sfx");
  if (own === "off") return;
  if (own) return sfx(own as Parameters<typeof sfx>[0]);
  if (el.getAttribute("role") === "switch") return sfx("toggle");
  if (el.getAttribute("role") === "tab" || el.matches(".tabbar-btn, .seg > button, nav button")) return sfx("tab");
  const label = el.getAttribute("aria-label") ?? "";
  if (label === "Next") return sfx("playlist-next");
  if (label === "Previous") return sfx("playlist-prev");
  sfx("click");
}

function watchStore() {
  let lastToast = 0;
  let app: string | undefined;
  let prev: Record<string, unknown> | undefined;
  useStore.subscribe((s, p) => {
    // toasts: one sound per new toast, by tone
    const t = s.toasts[s.toasts.length - 1];
    if (t && t.id > lastToast && s.toasts !== p.toasts) {
      lastToast = t.id;
      sfx(t.tone === "error" ? "error" : t.tone === "ok" ? "success" : "toast");
    }
    // the app on the panel
    const cur = s.state?.engine.current;
    if (!cur) return;
    if (cur.app !== app) {
      const first = app === undefined;
      app = cur.app;
      prev = cur.status;
      if (!first && !recentlyPlayed("playlist-next", 1500) && !recentlyPlayed("playlist-prev", 1500)) sfx("app-switch");
      return;
    }
    // Play mode: game start / over / score, read from the game's status (lib/gamepads.ts reads the same for rumble)
    const st = cur.status;
    if (st === prev) return;
    const was = prev;
    prev = st;
    if (!s.playMode || !was || !st) return;
    const flow = st.flow;
    if (flow !== was.flow) {
      if (flow === "play") sfx("game-start");
      else if (flow === "outro") sfx("game-over");
    }
    const sc = Number(st.score);
    const ps = Number(was.score);
    if (Number.isFinite(sc) && Number.isFinite(ps)) {
      if (sc > ps) sfx("score");
      else if (ps > 0 && sc === 0 && flow !== "outro" && was.flow !== "outro") sfx("game-over");
    }
  });
}
