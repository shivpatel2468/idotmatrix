import clsx from "clsx";
import { ChevronRight, Monitor, RotateCcw, Settings2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import {
  LOOK_HINT, LOOK_LABEL, LOOK_SHORT, LOOKS, MATCHES, MATCH_HINT, MATCH_LABEL, isDefaultLook, useLook,
} from "../lib/look";
import { openSettings, type SettingsTab } from "../lib/store";
import { usePhone } from "../lib/useMedia";
import { LedPanel } from "./LedPanel";
import { Sheet } from "./Sheet";
import { ThemeSeg } from "./ThemePicker";

/** The panel's own settings, one tap further: they live in Settings → Display & colour. */
const LINKS: [SettingsTab, string, string][] = [
  ["display", "Brightness, night mode, rotate", "Also sounds and the intro"],
  ["calibrate", "Colour calibration", "Match the panel's colours to your screen"],
  ["transfer", "Smooth motion", "Fix judder or stutter on the panel"],
];

/**
 * The Display menu: how the live preview is drawn on this screen (per browser, lib/look.ts) plus a way into the
 * panel's settings. One glance for the common case — three picture tiles (each a tiny live preview) and, for Glow,
 * one slider; the rest sits under "More". A popover on wide screens, a bottom sheet on phones.
 *
 *  - `trigger="settings"`: the gear key in the top bar, just left of the power guard.
 *  - `trigger="look"`: Play mode's header key (shows the current look's name).
 * `open` / `setOpen` are optional (Play mode drives them so its own Esc handling can close the menu first).
 * `beforeSettings` runs before Settings opens (Play mode leaves itself, since Settings sits underneath it).
 */
export function DisplayMenu({ trigger, open: openProp, setOpen: setOpenProp, beforeSettings }: {
  trigger: "settings" | "look";
  open?: boolean;
  setOpen?: (o: boolean) => void;
  beforeSettings?: () => void;
}) {
  const [own, setOwn] = useState(false);
  const open = openProp ?? own;
  const setOpen = setOpenProp ?? setOwn;
  const phone = usePhone();
  const look = useLook((s) => s.look);
  const key = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(open);

  // opening: focus the chosen tile; closing (any way — Esc, a click outside, Play mode): focus goes back to the key
  useEffect(() => {
    if (open && !phone) requestAnimationFrame(() => panel.current?.querySelector<HTMLElement>("[aria-pressed=true]")?.focus());
    if (!open && wasOpen.current) {
      const a = document.activeElement;
      if (!a || a === document.body) key.current?.focus({ preventScroll: true });
    }
    wasOpen.current = open;
  }, [open, phone]);

  // Esc closes the popover wherever focus is (the phone sheet handles its own; Play mode's handler runs first)
  useEffect(() => {
    if (!open || phone) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, phone, setOpen]);

  const close = () => setOpen(false);
  const goSettings = (t: SettingsTab) => {
    setOpen(false);
    beforeSettings?.();
    openSettings(t);
  };

  return (
    <div className="relative">
      {trigger === "settings" ? (
        <button ref={key} className="key key-icon" title="Display & settings" aria-label="Display and settings"
          aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>
          <Settings2 size={15} />
        </button>
      ) : (
        <button ref={key} className="key" onMouseDown={(e) => e.preventDefault()} onClick={() => setOpen(!open)}
          aria-haspopup="dialog" aria-expanded={open} aria-label={`Display: ${LOOK_LABEL[look]} look`} title="How the panel looks on this screen">
          <Monitor size={14} /> <span className="hidden sm:inline">{LOOK_LABEL[look]}</span>
        </button>
      )}
      {open && phone && (
        <Sheet open onClose={close} title="Display">
          <DisplayBody goSettings={goSettings} />
        </Sheet>
      )}
      {open && !phone && (
        <>
          <div className="fixed inset-0 z-40" onClick={close} aria-hidden />
          <div ref={panel} role="dialog" aria-label="Display"
            className="surface absolute right-0 top-full z-50 mt-2 w-[min(340px,calc(100vw-24px))] p-4 animate-rise">
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <span className="font-display text-[15px] font-[640] tracking-[-0.01em] text-ink-1">Display</span>
              <span className="text-[11px] text-ink-4">Saved in this browser</span>
            </div>
            <DisplayBody goSettings={goSettings} />
          </div>
        </>
      )}
    </div>
  );
}

function DisplayBody({ goSettings }: { goSettings: (t: SettingsTab) => void }) {
  const look = useLook((s) => s.look);
  const bloom = useLook((s) => s.bloom);
  const match = useLook((s) => s.match);
  const setLook = useLook((s) => s.setLook);
  const setBloom = useLook((s) => s.setBloom);
  const setMatch = useLook((s) => s.setMatch);
  const reset = useLook((s) => s.reset);
  const atDefault = isDefaultLook({ look, bloom, match });
  const [more, setMore] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const ids = useId();
  const pct = Math.round(bloom * 100);
  useEffect(() => { if (atDefault) setConfirm(false); }, [atDefault]);

  return (
    <div className="flex flex-col gap-4">
      {/* 1 · the look: three picture tiles, each drawing the live frame in that look */}
      <section aria-labelledby={`${ids}-look`}>
        <h3 id={`${ids}-look`} className="mb-2 text-[12.5px] font-[560] text-ink-2">How the panel looks on this screen</h3>
        <div role="group" aria-labelledby={`${ids}-look`} className="grid grid-cols-3 gap-2">
          {LOOKS.map((l) => (
            <button key={l} type="button" aria-pressed={look === l} title={LOOK_HINT[l]} onClick={() => setLook(l)}
              onMouseDown={(e) => e.preventDefault()}
              className={clsx("flex min-w-0 flex-col items-center gap-1 rounded-[10px] border p-1.5 pb-2 text-center transition",
                look === l ? "border-ember bg-ember-deep/40" : "border-line hover:border-line-2 hover:bg-chassis-2/60")}>
              <span className="grid aspect-square w-full place-items-center overflow-hidden rounded-[6px] bg-black theme-dark" aria-hidden>
                <LedPanel size={72} look={l} lookSwitch={false} className="grid place-items-center" />
              </span>
              <span className="mt-0.5 text-[13px] font-[600] text-ink-1">{LOOK_LABEL[l]}</span>
              <span className="text-[10.5px] leading-tight text-ink-3">{LOOK_SHORT[l]}</span>
            </button>
          ))}
        </div>
        <p className="mt-2 text-[11.5px] leading-snug text-ink-3" aria-live="polite">{LOOK_HINT[look]}.</p>
      </section>

      {/* 2 · the one slider, only where it does something */}
      {look === "glow" && (
        <section className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between">
            <label htmlFor={`${ids}-glow`} className="text-[12.5px] font-[560] text-ink-1">Glow</label>
            <span className="font-mono text-[11px] tabular-nums text-ink-2">{pct === 0 ? "None" : `${pct}%`}</span>
          </div>
          <input id={`${ids}-glow`} type="range" min={0} max={1} step={0.05} value={bloom} className="fader w-full"
            aria-valuetext={pct === 0 ? "No glow, crisp pixels" : `${pct}% glow`} style={{ ["--fill" as string]: `${pct}%` }}
            onChange={(e) => setBloom(+e.target.value)}
            // hand the keys back to Play mode's game once the thumb is let go
            onMouseUp={(e) => e.currentTarget.blur()} onTouchEnd={(e) => e.currentTarget.blur()} />
          <div className="flex justify-between text-[10.5px] text-ink-3" aria-hidden>
            <span>Crisp</span>
            <span>Soft</span>
          </div>
        </section>
      )}

      {/* the studio around the panel: light · dark · auto (lib/theme.ts) */}
      <section className="flex flex-col gap-1.5">
        <span className="text-[12.5px] font-[560] text-ink-1">Studio theme</span>
        <ThemeSeg className="!p-1 [&>button]:!h-8" />
      </section>

      {/* 3 · everything else, behind one disclosure */}
      <section className="border-t border-line pt-3">
        <button type="button" aria-expanded={more} aria-controls={`${ids}-more`} onClick={() => setMore((m) => !m)}
          className="flex w-full items-center gap-2 rounded-lg py-1 text-left text-[12.5px] font-[560] text-ink-2 hover:text-ink-1">
          <ChevronRight size={14} className={clsx("shrink-0 transition", more && "rotate-90")} />
          More
          {!more && <span className="ml-auto truncate text-[11px] font-normal text-ink-4">colours, panel settings</span>}
        </button>
        {more && (
          <div id={`${ids}-more`} className="mt-2 flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <span id={`${ids}-match`} className="text-[12.5px] font-[560] text-ink-1">Show my colour calibration</span>
              <div className="seg !p-1" role="group" aria-labelledby={`${ids}-match`}>
                {MATCHES.map((m) => (
                  <button key={m} type="button" aria-pressed={match === m} data-active={match === m} className="!h-8"
                    onMouseDown={(e) => e.preventDefault()} onClick={() => setMatch(m)}>{MATCH_LABEL[m]}</button>
                ))}
              </div>
              <p className="text-[11px] leading-snug text-ink-3">{MATCH_HINT[match]}.</p>
            </div>
            <div className="flex flex-col">
              <span className="mb-1 text-[11px] text-ink-4">The panel itself — in Settings</span>
              {LINKS.map(([tab, label, hint]) => (
                <button key={tab} type="button" onClick={() => goSettings(tab)}
                  className="flex items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-chassis-2/60">
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] text-ink-1">{label}</span>
                    <span className="block text-[11px] leading-snug text-ink-3">{hint}</span>
                  </span>
                  <ChevronRight size={14} className="shrink-0 text-ink-4" />
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* footer: reset (confirms inline) and the way to every setting */}
      <div className="flex flex-wrap items-center gap-2">
        {confirm ? (
          <span className="flex flex-wrap items-center gap-2 text-[12px] text-ink-2" role="group" aria-label="Reset the display to default?">
            Back to Glow, normal glow?
            <button type="button" className="key !h-8" onClick={() => { reset(); setConfirm(false); }}>Reset</button>
            <button type="button" className="key key-ghost !h-8" onClick={() => setConfirm(false)}>Keep</button>
          </span>
        ) : (
          <button type="button" className="key key-ghost !h-8" disabled={atDefault} onClick={() => setConfirm(true)}
            title={atDefault ? "Already at the default" : "Glow look, normal glow, calibration in the LED look only"}>
            <RotateCcw size={13} /> Reset to default
          </button>
        )}
        <button type="button" className="key !h-8 ml-auto" onClick={() => goSettings("display")}>
          <Settings2 size={13} /> All settings
        </button>
      </div>
    </div>
  );
}
