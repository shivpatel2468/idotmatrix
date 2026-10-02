import clsx from "clsx";
import { useStore } from "../lib/store";
import { flyGames, letFlyPlay, takeBackFromFly, useCurrentIsFlyGame, useFlyPicker, useFlyPlaying } from "../lib/flyControl";
import { Icon } from "./Icon";

/**
 * "Let the fly play" / "Fly playing · Take back": one toggle used in the top bar, Play mode and a game's status bar.
 * When the panel isn't showing a game, it opens a small list of games to start with the fly (`picker`).
 */
export function FlyToggle({ compact = false, picker = false, className }: {
  compact?: boolean; // icon (+ short label) only — phones and tight bars
  picker?: boolean; // this instance owns the game list pop-over (only the top bar's does)
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
  return (
    <div className={clsx("relative", className)}>
      <button
        className={clsx("key", playing ? "key-ember" : "key-ghost", compact && "key-icon !w-auto !px-2.5")}
        aria-pressed={playing}
        aria-haspopup={!playing && !isGame ? "menu" : undefined}
        aria-expanded={picker && !playing && !isGame ? open : undefined}
        title={title}
        aria-label={label}
        onMouseDown={(e) => e.preventDefault()} // keep Play mode's keyboard focus
        onClick={() => (playing ? takeBackFromFly() : isGame ? letFlyPlay() : setOpen(!open))}
      >
        <Icon name="bug" size={14} className={playing ? "animate-pulse" : undefined} />
        {playing && <span className="led !h-[6px] !w-[6px]" data-on="ember" />}
        {!compact && <span className="normal-case tracking-normal">{label}</span>}
        {compact && playing && <span className="normal-case tracking-normal">Take back</span>}
      </button>
      {picker && open && !playing && <FlyGamePicker onClose={() => setOpen(false)} />}
    </div>
  );
}

function FlyGamePicker({ onClose }: { onClose: () => void }) {
  const meta = useStore((s) => s.meta);
  const lastGame = useStore((s) => s.lastGame);
  const games = flyGames(meta);
  const last = games.find((g) => g.id === lastGame);
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div role="menu" aria-label="Games the fly can play"
        className="surface absolute right-0 top-11 z-50 flex max-h-[min(420px,70vh)] w-[min(280px,86vw)] flex-col overflow-hidden animate-rise"
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
