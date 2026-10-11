import { Monitor, Moon, Sun } from "lucide-react";
import { derive, pageThemeSeed, usePageTheme } from "../lib/pageTheme";
import { THEME_CHOICES, type ThemePref, setThemePref, useThemePref } from "../lib/theme";

const ICON: Record<ThemePref, React.ReactNode> = {
  light: <Sun size={13} />,
  dark: <Moon size={13} />,
  system: <Monitor size={13} />,
};

/** A tiny picture of the studio in each theme (it shows the other theme too), in the current page theme. */
function Swatch({ id }: { id: ThemePref }) {
  const pt = derive(pageThemeSeed(usePageTheme()));
  const room = (bg: string, panel: string, line: string, accent: string, ink: string) => (
    <>
      <i style={{ inset: 0, borderRadius: 0, background: bg }} />
      <i style={{ left: "7%", top: "14%", width: "22%", bottom: "14%", background: panel, boxShadow: `0 0 0 1px ${line}` }} />
      <i style={{ right: "7%", top: "14%", width: "22%", bottom: "14%", background: panel, boxShadow: `0 0 0 1px ${line}` }} />
      <i style={{ left: "36%", right: "36%", top: "22%", bottom: "22%", background: "#0b0b0e", borderRadius: 4, boxShadow: "0 0 0 2px #1c1c22" }} />
      <i style={{ left: "41%", right: "41%", top: "32%", bottom: "32%", borderRadius: 2, background: "radial-gradient(circle, #ff4f7b 0 30%, #ffcc33 60%, transparent 62%)", opacity: 0.85 }} />
      <i style={{ left: "11%", top: "22%", width: "12%", height: 3, background: accent }} />
      <i style={{ left: "11%", top: "32%", width: "14%", height: 2, background: ink, opacity: 0.35 }} />
      <i style={{ left: "11%", top: "39%", width: "10%", height: 2, background: ink, opacity: 0.25 }} />
    </>
  );
  const light = room(pt.light.c0, "#ffffff", pt.light.lineA, pt.light.accent, "#1c1a22");
  const dark = room(pt.dark.c0, pt.dark.c2, pt.dark.lineA, pt.dark.accent, "#efece4");
  return (
    <span className="theme-swatch" aria-hidden>
      {id === "system" ? (
        <>
          <span className="absolute inset-0 [clip-path:polygon(0_0,100%_0,0_100%)]">{light}</span>
          <span className="absolute inset-0 [clip-path:polygon(100%_0,100%_100%,0_100%)]">{dark}</span>
        </>
      ) : id === "light" ? light : dark}
    </span>
  );
}

/** Settings → Display & colour: three picture tiles. */
export function ThemeTiles() {
  const pref = useThemePref();
  return (
    <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Studio theme">
      {THEME_CHOICES.map((t) => (
        <button key={t.id} className="theme-tile" role="radio" aria-checked={pref === t.id} aria-pressed={pref === t.id} onClick={() => setThemePref(t.id)}>
          <Swatch id={t.id} />
          <span className="flex items-center gap-1.5 px-1 text-[12.5px] font-[600] text-ink-1">{ICON[t.id]}{t.name}</span>
          <span className="-mt-1.5 px-1 text-[11px] leading-snug text-ink-3">{t.hint}</span>
        </button>
      ))}
    </div>
  );
}

/** A compact Light · Dark · Auto switch (Display menu, Quick controls). */
export function ThemeSeg({ className = "" }: { className?: string }) {
  const pref = useThemePref();
  return (
    <div className={`seg ${className}`} role="radiogroup" aria-label="Studio theme">
      {THEME_CHOICES.map((t) => (
        <button key={t.id} role="radio" aria-checked={pref === t.id} data-active={pref === t.id} title={t.hint}
          className="inline-flex items-center justify-center gap-1.5" onClick={() => setThemePref(t.id)}>
          {ICON[t.id]}{t.name}
        </button>
      ))}
    </div>
  );
}
