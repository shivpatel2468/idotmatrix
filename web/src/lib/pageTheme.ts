/**
 * Page themes — the casino's 21 table themes, worn by the studio, the phone shell, the launcher and the web app
 * (docs/STUDIO_UI.md § Page themes). Separate from light / dark (lib/theme.ts): every page theme has both, and the
 * switch keeps working. While the casino view is open (`html[data-cz]`) the table on screen owns the page instead.
 *
 *   - the pick lives on the engine (`GET/POST /api/theme`, `state.settings.page_theme`), so every device shows the
 *     same theme; this browser keeps a copy (`localStorage deskdot.pageTheme`) as the fallback and for first paint.
 *     In the web app (idotmatrix.com/app/) the website's own pick (`deskdot.siteTheme`, same origin) leads, so the app
 *     opens in the table the site was showing, and a pick here is written back for the site;
 *   - the themes are generated from src/deskdot/gfx/tables.py TABLE_THEMES by scripts/gen_page_themes.py
 *     (`pageThemes.gen.ts`: names, swatch colours and each theme's stylesheet; tests keep it current), so the studio,
 *     the casino and the website can't drift. Ids from before 3.9 map to the nearest table (`LEGACY_PAGE_THEMES`);
 *   - the CSS is one constructed stylesheet (`document.adoptedStyleSheets`, CSP-proof; a <style> where unsupported)
 *     scoped to `:root[data-page-theme="…"]:not([data-cz])`. The default (Cyber grid) is also in the studio's own
 *     stylesheet (`pageTheme.default.gen.css`), so a first visit paints it before any script. The CSS is cached
 *     (`deskdot.pageThemeCss`) so index.html / launcher.html / webapp/host.js / controller.html paint it first — no flash;
 *   - a change cross-fades: the View Transitions API where there is one, else the `html.theme-fade` transitions.
 */
import { useSyncExternalStore } from "react";
import { DEFAULT_PAGE_THEME, LEGACY_PAGE_THEMES, PAGE_THEMES, type PageThemeDef } from "./pageThemes.gen";

export { DEFAULT_PAGE_THEME, PAGE_THEMES };
export type { PageThemeDef };

export const PAGE_THEME_KEY = "deskdot.pageTheme";
export const PAGE_THEME_CSS_KEY = "deskdot.pageThemeCss";
/** idotmatrix.com's theme menu (the website copy's scripts/site_theme.py): the same table ids. */
export const SITE_THEME_KEY = "deskdot.siteTheme";
/** The browser build at idotmatrix.com/app/ (scripts/build_webapp.py builds it with base /app/). */
const WEB_APP = import.meta.env.BASE_URL !== "/";

// ------------------------------------------------------------------ the table
const byId = (id: string | null | undefined) => {
  const k = id ? (LEGACY_PAGE_THEMES[id] ?? id) : id;
  return PAGE_THEMES.find((t) => t.id === k);
};
/** The theme for an id (an old id maps to its table), else the default. */
export const pageThemeDef = (id: string | null | undefined): PageThemeDef => byId(id) ?? byId(DEFAULT_PAGE_THEME)!;

function stored(): string {
  try {
    if (WEB_APP) {
      const site = byId(localStorage.getItem(SITE_THEME_KEY));
      if (site) return site.id;
    }
    return byId(localStorage.getItem(PAGE_THEME_KEY))?.id ?? DEFAULT_PAGE_THEME;
  } catch {
    return DEFAULT_PAGE_THEME;
  }
}

// ------------------------------------------------------------------ applying it
let current = typeof document !== "undefined" ? stored() : DEFAULT_PAGE_THEME;
const listeners = new Set<() => void>();
let sheet: CSSStyleSheet | null = null;

/** Put the CSS on the page: one constructed stylesheet (CSP can't block it), else a <style>. */
function install(css: string) {
  const doc = document as Document & { adoptedStyleSheets?: CSSStyleSheet[] };
  if (doc.adoptedStyleSheets && typeof CSSStyleSheet !== "undefined" && "replaceSync" in CSSStyleSheet.prototype) {
    try {
      if (!sheet) {
        sheet = new CSSStyleSheet();
        doc.adoptedStyleSheets = [...doc.adoptedStyleSheets, sheet];
      }
      sheet.replaceSync(css);
      document.getElementById("dd-page-theme")?.remove(); // the first-paint copy (index.html): the live one took over
      return;
    } catch {
      /* fall through to a <style> */
    }
  }
  let el = document.getElementById("dd-page-theme");
  if (!el) {
    el = document.createElement("style");
    el.id = "dd-page-theme";
    document.head.appendChild(el);
  }
  el.textContent = css;
}

function paint(id: string) {
  const t = pageThemeDef(id);
  install(t.css);
  document.documentElement.dataset.pageTheme = t.id;
  try {
    localStorage.setItem(PAGE_THEME_KEY, t.id);
    localStorage.setItem(PAGE_THEME_CSS_KEY, t.css);
    if (WEB_APP) localStorage.setItem(SITE_THEME_KEY, t.id); // the website shows the same table
  } catch {
    /* private mode: this tab only */
  }
  current = t.id;
  listeners.forEach((l) => l());
}

/** Show a theme on this page (no engine call). `animate` cross-fades; first paint never does. */
export function applyPageTheme(id: string, animate = true) {
  const next = pageThemeDef(id).id;
  if (next === current && document.documentElement.dataset.pageTheme === next) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const doc = document as Document & { startViewTransition?: (cb: () => void) => { finished?: Promise<void> } };
  if (animate && !reduce && typeof doc.startViewTransition === "function") {
    // one snapshot cross-fade of the whole page: gradients and washes too, which CSS transitions can't animate
    const root = document.documentElement;
    root.classList.add("page-theme-vt");
    const done = () => root.classList.remove("page-theme-vt");
    try {
      const vt = doc.startViewTransition(() => paint(next));
      if (vt?.finished) vt.finished.then(done, done);
      else done();
    } catch {
      done();
      paint(next);
    }
    return;
  }
  if (animate && !reduce) {
    const root = document.documentElement;
    root.classList.add("theme-fade");
    window.setTimeout(() => root.classList.remove("theme-fade"), 450);
  }
  paint(next);
}

/** Pick a theme: this page at once, then the engine (every other device follows from its state push). The local
 *  pick stays if the engine can't be reached or is older than page themes. */
let picked = { id: "", at: 0 }; // this page's last pick: older state pushes must not flip it back meanwhile

const post = async (id: string) => {
  try {
    const r = await fetch("/api/theme", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id }) });
    return r.ok;
  } catch {
    return false;
  }
};

export async function setPageTheme(id: string): Promise<boolean> {
  picked = { id: pageThemeDef(id).id, at: Date.now() };
  applyPageTheme(id, true);
  return post(picked.id);
}

/** The engine's state said `id` (another device picked it, or this page just loaded): follow it. In the web app the
 *  website's pick leads once: the browser engine is told this page's theme instead of overriding it. */
let firstPush = true;
export function syncPageTheme(id: string | null | undefined) {
  if (!id) return;
  const t = byId(id);
  if (!t) return;
  if (firstPush) {
    firstPush = false;
    if (WEB_APP && t.id !== current) {
      picked = { id: current, at: Date.now() };
      void post(current);
      return;
    }
  }
  if (t.id === current) return;
  if (Date.now() - picked.at < 4000 && t.id !== picked.id) return; // a push from before this page's own pick
  applyPageTheme(t.id, true);
}

/** At start-up: re-derive from this build (the first-paint copy may be from an older one) and keep other tabs in step. */
export function installPageTheme() {
  paint(current);
  window.addEventListener("storage", (e) => {
    const watch = e.key === PAGE_THEME_KEY || (WEB_APP && e.key === SITE_THEME_KEY);
    if (watch && e.newValue && pageThemeDef(e.newValue).id !== current) applyPageTheme(e.newValue, true);
  });
}

/** Called whenever the theme changes (lib/theme.ts re-paints the browser / Android bars). */
export const onPageTheme = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));
export const getPageTheme = () => current;
export const usePageTheme = () => useSyncExternalStore(onPageTheme, getPageTheme, getPageTheme);

/** The page / header / tab-bar colours of the current page theme (`meta[name=theme-color]`, the Android bars). */
export function pageBars(mode: "light" | "dark"): { status: string; nav: string; page: string } {
  const d = pageThemeDef(current)[mode];
  return { status: d.c1, nav: d.glass, page: d.c0 };
}
