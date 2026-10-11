import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { DEFAULT_PAGE_THEME, PAGE_THEMES, type PageThemeSeed, derive, pageThemeSeed, setPageTheme, usePageTheme } from "../lib/pageTheme";
import { toast } from "../lib/store";
import { useTheme } from "../lib/theme";

/** The engine's LED palette per theme (GET /api/theme), fetched once: the swatches show what the panel's apps get. */
let ledCache: Record<string, string[]> | null = null;
function useLedPalettes() {
  const [led, setLed] = useState(ledCache);
  useEffect(() => {
    if (ledCache) return;
    let live = true;
    fetch("/api/theme")
      .then((r) => (r.ok ? r.json() : null))
      .then((j: { themes?: { id: string; panel: Record<string, string> }[] } | null) => {
        if (!j?.themes) return;
        ledCache = Object.fromEntries(j.themes.map((t) => [t.id, [t.panel.accent, t.panel.accent2, t.panel.accent3]]));
        if (live) setLed(ledCache);
      })
      .catch(() => {
        /* an older engine: the swatches just skip the LED dots */
      });
    return () => {
      live = false;
    };
  }, []);
  return led;
}

const pick = async (id: string) => {
  if (!(await setPageTheme(id))) toast("Page theme saved on this device only — the engine didn't take it (restart it to share it)", "info");
};

/** A tiny picture of the studio in a page theme, in the light / dark mode on screen. */
function Swatch({ t, mode }: { t: PageThemeSeed; mode: "light" | "dark" }) {
  const c = derive(t)[mode];
  const pat = t.pattern ? t.pattern : `radial-gradient(circle at 1px 1px, ${mode === "dark" ? "rgba(255,255,255,0.08)" : "rgba(64,48,24,0.12)"} 1px, transparent 0)`;
  return (
    <span className="pt-art" aria-hidden
      style={{
        ["--pt-bg" as string]: c.c0, ["--pt-card" as string]: c.c2, ["--pt-line" as string]: c.lineB,
        ["--pt-acc" as string]: c.accent, ["--pt-metal" as string]: c.metal, ["--pt-pat" as string]: pat,
        ["--pt-pat-size" as string]: t.pattern ? t.pattern_size || "auto" : "8px 8px",
      }}>
      <i className="pt-card" />
      <i className="pt-bar" />
      <i className="pt-line1" />
      <i className="pt-line2" />
      <i className="pt-key" />
      <i className="pt-gem" />
    </span>
  );
}

/** Settings → Display & colour → Page theme: every theme as a picture tile, the hovered one described below. */
export function PageThemeGrid() {
  const cur = usePageTheme();
  const mode = useTheme();
  const led = useLedPalettes();
  const [peek, setPeek] = useState<string | null>(null);
  const shown = pageThemeSeed(peek ?? cur);
  return (
    <div className="flex flex-col gap-2.5">
      <div className="pt-grid" role="radiogroup" aria-label="Page theme" onMouseLeave={() => setPeek(null)}>
        {PAGE_THEMES.map((t) => (
          <button key={t.id} className="pt-tile" role="radio" aria-checked={t.id === cur} data-on={t.id === cur || undefined}
            aria-describedby="pt-desc" onClick={() => pick(t.id)}
            onMouseEnter={() => setPeek(t.id)} onFocus={() => setPeek(t.id)} onBlur={() => setPeek(null)}>
            <Swatch t={t} mode={mode} />
            <span className="pt-name">
              {t.name}
              {t.id === cur && <Check size={12} strokeWidth={2.6} className="pt-check" aria-hidden />}
            </span>
            {led?.[t.id] && (
              <span className="pt-leds" aria-hidden title="On the panel">
                {led[t.id].map((c, i) => <i key={i} style={{ background: c, boxShadow: `0 0 6px ${c}` }} />)}
              </span>
            )}
          </button>
        ))}
      </div>
      <p id="pt-desc" className="min-h-[2.9em] text-[11.5px] leading-snug text-ink-3" aria-live="polite">
        <b className="font-[600] text-ink-2">{shown.name}</b>
        {shown.id === DEFAULT_PAGE_THEME ? " (default)" : ""} — {shown.description}
      </p>
    </div>
  );
}

/** A compact row of round swatches (Display menu, phone Quick controls): accent over metal, a ring on the current one. */
export function PageThemeDots({ className = "" }: { className?: string }) {
  const cur = usePageTheme();
  const mode = useTheme();
  return (
    <div className={`pt-dots ${className}`} role="radiogroup" aria-label="Page theme">
      {PAGE_THEMES.map((t) => {
        const c = derive(t)[mode];
        return (
          <button key={t.id} role="radio" aria-checked={t.id === cur} data-on={t.id === cur || undefined} title={t.name} aria-label={t.name}
            className="pt-dot" onClick={() => pick(t.id)}
            style={{ ["--pt-acc" as string]: c.accent, ["--pt-metal" as string]: c.metal, ["--pt-bg" as string]: c.c2 }} />
        );
      })}
    </div>
  );
}
