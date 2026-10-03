import clsx from "clsx";
import { useState } from "react";
import { useFly } from "../lib/fly";
import { useStore } from "../lib/store";
import { flyGames, letFlyPlay, takeBackFromFly, useCurrentIsFlyGame, useFlyPicker, useFlyPlaying } from "../lib/flyControl";
import { Icon } from "./Icon";

/**
 * "Let the fly play" / "Fly playing · Take back": one toggle used in the top bar, Play mode and a game's status bar.
 * When the panel isn't showing a game, it opens a small list of games to start with the fly (`picker`).
 */
export function FlyToggle({ compact = false, picker = false, up = false, className }: {
  compact?: boolean; // icon (+ short label) only — phones and tight bars
  picker?: boolean; // this instance owns the game list pop-over
  up?: boolean; // open the pop-over above the button (bottom of the screen)
  className?: string;
}) {
  const playing = useFlyPlaying();
  const isGame = useCurrentIsFlyGame();
  const open = useFlyPicker((s) => s.open);
  const setOpen = useFlyPicker((s) => s.set);
  const label = playing ? "Fly playing · Take back" : "Let the fly play";
  const title = playing
    ? "A fruit fly is playing — take the game back (F)"
    : isGame
      ? "Hand this game to the fruit-fly brain (F)"
      : "Pick a game for the fruit-fly brain to play (F)";
  const act = () => (playing ? takeBackFromFly() : isGame ? letFlyPlay() : setOpen(!open));
  return (
    <div className={clsx("relative", className)}>
      <button
        className={clsx("flybtn", compact && "flybtn-compact")}
        data-on={playing}
        aria-pressed={playing}
        aria-haspopup={!playing && !isGame ? "menu" : undefined}
        aria-expanded={picker && !playing && !isGame ? open : undefined}
        title={title}
        aria-label={label}
        onMouseDown={(e) => e.preventDefault()} // keep Play mode's keyboard focus
        onClick={act}
      >
        <FlyGlyph />
        {playing ? (
          <>
            <span className="flybtn-dot" aria-hidden />
            {!compact && <span className="flybtn-label">Fly playing</span>}
            <span className="flybtn-back">Take back</span>
          </>
        ) : (
          !compact && <span className="flybtn-label">Let the fly play</span>
        )}
      </button>
      {picker && open && !playing && <FlyGamePicker up={up} onClose={() => setOpen(false)} />}
    </div>
  );
}

/** A tiny fruit fly (wings flutter on hover / while it plays). */
function FlyGlyph() {
  return (
    <svg className="flybtn-fly" viewBox="0 0 24 24" width="18" height="18" aria-hidden>
      <g className="flybtn-wings">
        <ellipse cx="7.2" cy="9" rx="5.2" ry="2.6" transform="rotate(-28 7.2 9)" />
        <ellipse cx="16.8" cy="9" rx="5.2" ry="2.6" transform="rotate(28 16.8 9)" />
      </g>
      <ellipse cx="12" cy="15.2" rx="2.6" ry="4.4" className="flybtn-abdomen" />
      <circle cx="12" cy="9.6" r="2.6" className="flybtn-thorax" />
      <circle cx="10.4" cy="7.4" r="1.25" className="flybtn-eye" />
      <circle cx="13.6" cy="7.4" r="1.25" className="flybtn-eye" />
    </svg>
  );
}

function FlyGamePicker({ onClose, up = false }: { onClose: () => void; up?: boolean }) {
  const meta = useStore((s) => s.meta);
  const lastGame = useStore((s) => s.lastGame);
  const games = flyGames(meta);
  const last = games.find((g) => g.id === lastGame);
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div role="menu" aria-label="Games the fly can play"
        className={clsx("surface absolute right-0 z-50 flex max-h-[min(420px,70vh)] w-[min(280px,86vw)] flex-col overflow-hidden animate-rise", up ? "bottom-11" : "top-11")}
        onKeyDown={(e) => e.key === "Escape" && onClose()}>
        <div className="border-b border-line px-3.5 py-2.5">
          <div className="engrave !text-[8.5px]">Let the fly play</div>
          <div className="mt-0.5 text-[11.5px] leading-snug text-ink-3">It sees only the pixels (and smells its goal). Press any game key to take over.</div>
        </div>
        <div className="min-h-0 overflow-y-auto p-1.5">
          {last && <PickRow id={last.id} name={last.name} icon={last.icon} hint="Last played" autoFocus />}
          {games.filter((g) => g.id !== last?.id).map((g, i) => (
            <PickRow key={g.id} id={g.id} name={g.name} icon={g.icon} autoFocus={!last && i === 0} />
          ))}
          {!games.length && <div className="px-3 py-4 text-center text-[12.5px] text-ink-3">No games are installed</div>}
        </div>
      </div>
    </>
  );
}

function PickRow({ id, name, icon, hint, autoFocus }: { id: string; name: string; icon: string; hint?: string; autoFocus?: boolean }) {
  return (
    <button role="menuitem" autoFocus={autoFocus} onClick={() => letFlyPlay(id)}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] hover:bg-chassis-3 focus:bg-chassis-3 focus:outline-none">
      <Icon name={icon} size={14} className="text-ink-3" />
      <span className="flex-1 truncate">{name}</span>
      {hint && <span className="engrave !text-[8px]">{hint}</span>}
    </button>
  );
}

/**
 * The roaming fly's on/off switch, drawn like the signs on insect-spray packs: a green "flies welcome" circle
 * when the fly is out on the screen, the red "no flies" prohibition sign when it's away (with a puff of mist).
 */
export function RoamSign({ className }: { className?: string }) {
  const roam = useFly((s) => s.gfx.roam);
  const setGfx = useFly((s) => s.setGfx);
  const [puff, setPuff] = useState(0);
  const toggle = () => {
    if (roam) setPuff((n) => n + 1);
    setGfx({ roam: !roam });
  };
  const label = roam ? "Flies allowed: the fly roams your screen. Click to spray it away" : "No flies: the fly is away. Click to let it back";
  return (
    <button className={clsx("roamsign", className)} data-on={roam} onClick={toggle} title={label} aria-label={label} aria-pressed={roam}>
      <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden>
        <circle cx="16" cy="16" r="13.2" className="roamsign-ring" />
        <g className="roamsign-fly">
          <ellipse cx="11.6" cy="12.6" rx="4.4" ry="2.2" transform="rotate(-30 11.6 12.6)" className="roamsign-wing" />
          <ellipse cx="20.4" cy="12.6" rx="4.4" ry="2.2" transform="rotate(30 20.4 12.6)" className="roamsign-wing" />
          <ellipse cx="16" cy="18.6" rx="2.6" ry="4.6" />
          <circle cx="16" cy="12.8" r="2.4" />
          <path d="M13.6 17 l-3.6 -1.6 M13.6 19.4 l-3.8 0.6 M14 21.6 l-3 2.4 M18.4 17 l3.6 -1.6 M18.4 19.4 l3.8 0.6 M18 21.6 l3 2.4" className="roamsign-legs" />
        </g>
        {roam ? (
          <path d="M22.2 23.2 l2.2 2.2 l4.2 -4.6" className="roamsign-check" />
        ) : (
          <line x1="6.8" y1="25.2" x2="25.2" y2="6.8" className="roamsign-slash" />
        )}
      </svg>
      {puff > 0 && <span key={puff} className="roamsign-mist" aria-hidden />}
    </button>
  );
}
