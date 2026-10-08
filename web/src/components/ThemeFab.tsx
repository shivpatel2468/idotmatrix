import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { THEME_CHOICES, type ThemePref, setThemePref, toggleTheme, useTheme, useThemePref } from "../lib/theme";

const ICON: Record<ThemePref, React.ReactNode> = {
  light: <Sun size={15} />,
  dark: <Moon size={15} />,
  system: <Monitor size={15} />,
};

/**
 * Phones: a small round key pinned bottom-left, just above the tab bar. One tap flips light ↔ dark; a long press (or
 * the right-click / context-menu gesture) opens a tiny menu with Auto. The scroll areas leave room for it
 * (`.phone-scroll` / `.phone-panel` bottom padding), so it never sits on top of content you need.
 */
export function ThemeFab({ lift = false }: { lift?: boolean }) {
  const theme = useTheme();
  const pref = useThemePref();
  const [menu, setMenu] = useState(false);
  const timer = useRef(0);
  const longPressed = useRef(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const close = (e: PointerEvent) => !box.current?.contains(e.target as Node) && setMenu(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    window.addEventListener("pointerdown", close, true);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("pointerdown", close, true);
      window.removeEventListener("keydown", esc);
    };
  }, [menu]);

  const down = () => {
    longPressed.current = false;
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      longPressed.current = true;
      setMenu(true);
    }, 450);
  };
  const cancel = () => clearTimeout(timer.current);
  const click = () => {
    cancel();
    if (longPressed.current) return void (longPressed.current = false); // the long press already opened the menu
    if (menu) return setMenu(false);
    toggleTheme();
  };
  const next = theme === "dark" ? "light" : "dark";

  return (
    <div ref={box} className="theme-fab" data-lift={lift}>
      {menu && (
        <div role="menu" aria-label="Studio theme" className="theme-fab-menu">
          {THEME_CHOICES.map((t) => (
            <button key={t.id} role="menuitemradio" aria-checked={pref === t.id}
              onClick={() => { setThemePref(t.id); setMenu(false); }}>
              <span className="theme-fab-ico">{ICON[t.id]}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-[600] text-ink-1">{t.id === "system" ? "Auto" : t.name}</span>
                <span className="block truncate text-[11px] text-ink-3">{t.id === "system" ? "Follow the phone" : t.hint}</span>
              </span>
              {pref === t.id && <Check size={15} className="shrink-0 text-ember" />}
            </button>
          ))}
        </div>
      )}
      <button className="theme-fab-key" data-theme-now={theme}
        aria-label={`Switch to ${next} theme (hold for Auto)`} title={`Switch to ${next} theme — hold for more`}
        aria-haspopup="menu" aria-expanded={menu}
        onPointerDown={down} onPointerUp={cancel} onPointerLeave={cancel} onPointerCancel={cancel}
        onContextMenu={(e) => { e.preventDefault(); cancel(); longPressed.current = true; setMenu(true); }}
        onClick={click}>
        <span className="theme-fab-sun" aria-hidden><Sun size={18} strokeWidth={1.9} /></span>
        <span className="theme-fab-moon" aria-hidden><Moon size={17} strokeWidth={1.9} /></span>
        {pref === "system" && <span className="theme-fab-auto" aria-hidden>A</span>}
      </button>
    </div>
  );
}
