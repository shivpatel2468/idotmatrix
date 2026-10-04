import clsx from "clsx";
import { Bot, ChevronDown, ChevronLeft, ChevronRight, Gamepad2, LogOut, Monitor, RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import {
  type Binding, bindingOf, captureKey, keyLabel, maxPlayersOf, touchPlayers, touchStyleFor, useControls,
} from "../lib/controls";
import { type GameKey, gameKeyDown, isPlayable, openPlay, playableGames, releaseAll, usePressedKeys } from "../lib/gameInput";
import { startGamepads, usePads } from "../lib/gamepads";
import { LOOK_HINT, LOOK_LABEL, LOOKS, useLook } from "../lib/look";
import { appMeta, onFrame, useStore } from "../lib/store";
import { Icon } from "./Icon";
import { ControlsPanel } from "./ControlsPanel";
import { FriendsPill, LobbyPanel, ModeChoice, SEAT_COLORS, VersusBoard, closeFriends, useFriends, useLobbyPoll } from "./Multiplayer";
import { TouchControl } from "./TouchControls";
import { FlyToggle } from "./FlyToggle";
import { Sheet } from "./Sheet";
import { LedPanel } from "./LedPanel";
import { MatchSetup, Results, SideSelect, useGameStatus } from "./MatchSetup";

/** What each key does, per game (from each game's `key()` in Python). Unknown games get the generic legend. */
const HINTS: Record<string, Partial<Record<GameKey | "move", string>>> = {
  arcade: { move: "Steer" },
  maze: { move: "Steer" },
  g2048: { move: "Slide the tiles" },
  tetris: { left: "Move", right: "Move", up: "Rotate", down: "Soft drop", a: "Hard drop", b: "Rotate back" },
  invaders: { left: "Move", right: "Move", a: "Fire" },
  starship: { left: "Move", right: "Move", a: "Bomb" },
  asteroids: { left: "Turn", right: "Turn", up: "Thrust", down: "Brake", a: "Fire", b: "Hyperspace" },
  infinity: { up: "Climb", down: "Dive", a: "Climb", b: "Dive" },
  tictactoe: { move: "Pick a square", a: "Place" },
  mines: { move: "Move", a: "Reveal", b: "Flag" },
  pong: { up: "Paddle up", down: "Paddle down" },
  breakout: { left: "Paddle", right: "Paddle" },
  flappy: { up: "Flap", a: "Flap" },
  dino: { up: "Jump", a: "Jump", down: "Duck" },
  racer: { left: "Lane left", right: "Lane right" },
};

function useMedia(q: string) {
  const [m, setM] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [q]);
  return m;
}

/** Does this window have keyboard focus? (Keys go nowhere while another window or devtools has it.) */
function useWindowFocus() {
  const [f, setF] = useState(() => document.hasFocus());
  useEffect(() => {
    const on = () => setF(true);
    const off = () => setF(false);
    window.addEventListener("focus", on);
    window.addEventListener("blur", off);
    return () => {
      window.removeEventListener("focus", on);
      window.removeEventListener("blur", off);
    };
  }, []);
  return f;
}

/** Frames per second arriving over the WebSocket (what this view shows). */
function useViewFps() {
  const [fps, setFps] = useState(0);
  useEffect(() => {
    let n = -1; // onFrame replays the last frame at once
    let t0 = performance.now();
    const off = onFrame(() => void n++);
    const iv = setInterval(() => {
      const t = performance.now();
      setFps(Math.max(0, n) / ((t - t0) / 1000));
      n = 0;
      t0 = t;
    }, 1000);
    return () => {
      off();
      clearInterval(iv);
    };
  }, []);
  return fps;
}

function current() {
  const s = useStore.getState();
  const app = s.state?.engine.current?.app;
  return app && isPlayable(appMeta(app)) ? app : null;
}

function switchGame(step: number) {
  const s = useStore.getState();
  const games = playableGames(s.meta);
  if (!games.length) return;
  const i = games.findIndex((g) => g.id === s.state?.engine.current?.app);
  const next = games[(Math.max(0, i) + step + games.length) % games.length];
  goTo(next.id);
}

/** Switch game; a friend room belongs to one game, so leaving it closes the room (and frees the phones). */
async function goTo(id: string) {
  if (useStore.getState().lobby) await closeFriends().catch(() => {});
  api.activate(id);
}

// ------------------------------------------------------------------ pieces
function Keycap({ label, down, wide, title }: { label: React.ReactNode; down?: boolean; wide?: boolean; title?: string }) {
  return (
    <kbd className={clsx("keycap", wide && "keycap-wide")} data-down={down || undefined} title={title}>{label}</kbd>
  );
}

const cap = (b: Binding, k: GameKey, fallback: string) => (b[k][0] ? keyLabel(b[k][0]) : fallback);

/** Keyboard legend: player 1's keys (whatever preset or remap), plus a line for each extra keyboard player. */
function Legend({ app }: { app: string | null }) {
  const down = usePressedKeys(1);
  const players = useControls((s) => s.players);
  const max = maxPlayersOf(app);
  const b = bindingOf(players[0]);
  const h = (app && HINTS[app]) || {};
  const arrowHint = h.move ?? ([h.up, h.down, h.left, h.right].filter(Boolean).length ? null : "Move");
  const solo = players[0].kb === "arrows" && players.slice(1).every((p) => p.kb === "none");
  const glyph: Record<string, string> = { up: cap(b, "up", "↑"), down: cap(b, "down", "↓"), left: cap(b, "left", "←"), right: cap(b, "right", "→") };
  const rows: [React.ReactNode, string][] = [];
  if (!arrowHint) {
    const seen = new Map<string, GameKey[]>();
    (["up", "down", "left", "right"] as const).forEach((k) => h[k] && seen.set(h[k]!, [...(seen.get(h[k]!) ?? []), k]));
    seen.forEach((keys, what) => rows.push([
      <span className="flex gap-1">{keys.map((k) => <Keycap key={k} label={glyph[k]} down={down.has(k)} />)}</span>, what,
    ]));
  }
  const wide = (k: GameKey) => cap(b, k, "").length > 2;
  rows.push([<span className="flex gap-1"><Keycap label={cap(b, "a", "—")} wide={wide("a")} down={down.has("a")} /></span>, h.a ?? "Action (A)"]);
  rows.push([<span className="flex gap-1"><Keycap label={cap(b, "b", "—")} wide={wide("b")} down={down.has("b")} /></span>, h.b ?? "Second action (B)"]);
  const extra = players.map((p, i) => ({ p, n: i + 1 })).filter(({ p, n }) => n > 1 && n <= Math.max(2, max) && p.kb !== "none");
  return (
    <div className="surface flex flex-col gap-4 p-5" aria-label="Controls">
      <div className="engrave flex items-center gap-2">
        {extra.length > 0 && <span className="h-2 w-2 rounded-full" style={{ background: SEAT_COLORS[1] }} />}
        {extra.length ? "Player 1 · keys" : "Controls"}
      </div>
      {players[0].kb === "none" ? (
        <p className="text-[12px] text-ink-3">Player 1 has no keyboard keys — open <b className="font-[600] text-ink-2">Controls</b> to pick some.</p>
      ) : (
        <div className="flex flex-col items-center gap-1.5 py-1">
          <Keycap label={glyph.up} down={down.has("up")} title="Up" />
          <div className="flex gap-1.5">
            <Keycap label={glyph.left} down={down.has("left")} title="Left" />
            <Keycap label={glyph.down} down={down.has("down")} title="Down" />
            <Keycap label={glyph.right} down={down.has("right")} title="Right" />
          </div>
          <div className="mt-1 text-[11.5px] text-ink-2">{arrowHint ?? (players[0].kb === "arrows" ? "Arrows" : "Move")}{solo && <><span className="text-ink-4"> · or</span> W A S D</>}</div>
        </div>
      )}
      <div className="flex flex-col gap-2.5 border-t border-line pt-4">
        {rows.map(([keys, what], i) => (
          <div key={i} className="flex items-center justify-between gap-3">
            {keys}
            <span className="text-right text-[12px] text-ink-2">{what}</span>
          </div>
        ))}
      </div>
      {extra.map(({ p, n }) => <ExtraKeys key={n} n={n} b={bindingOf(p)} />)}
      <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 border-t border-line pt-4 text-[11.5px] text-ink-3">
        <Keycap label="R" /> <span>Restart</span>
        <span className="flex gap-1"><Keycap label="[" /><Keycap label="]" /></span> <span>Previous / next game</span>
        <Keycap label="Esc" wide /> <span>Leave Play mode</span>
      </div>
    </div>
  );
}

function ExtraKeys({ n, b }: { n: number; b: Binding }) {
  const down = usePressedKeys(n);
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-4">
      <div className="engrave flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: SEAT_COLORS[n] }} /> Player {n} · keys</div>
      <div className="flex flex-wrap gap-1">
        {(["up", "down", "left", "right", "a", "b"] as const).map((k) => (
          <Keycap key={k} label={cap(b, k, "—")} down={down.has(k)} wide={cap(b, k, "").length > 2} title={k} />
        ))}
      </div>
    </div>
  );
}

/** Touch: the on-screen controller (style per game) for each player that has one. */
function TouchArea({ app, compact, who }: { app: string | null; compact?: boolean; who: number[] }) {
  const picked = useControls((s) => s.touchStyle);
  const style = touchStyleFor(app, picked);
  return (
    <div className="flex flex-col gap-4">
      {who.map((n) => <TouchControl key={n} style={style} player={n} compact={compact} label={who.length > 1 || n > 1} />)}
    </div>
  );
}

function Scoreboard({ horizontal }: { horizontal?: boolean }) {
  const status = useStore((s) => s.state?.engine.current?.status);
  const score = Number(status?.score ?? 0);
  const best = Number(status?.best ?? 0);
  const you = status?.player === "you";
  const player = (
    <div className={clsx("flex items-center gap-2.5", horizontal ? "" : "mt-1")}>
      <span className="led" data-on={you ? "ok" : "ember"} />
      <div>
        <div className="font-display text-[17px] font-[640] leading-tight">{you ? "You" : status?.player === "fly" ? "Fruit fly" : "AI"}</div>
        {!horizontal && <div className="text-[11px] leading-snug text-ink-3">{you ? "It's your game — the AI takes over after 10 s idle" : "Press any game key to take over"}</div>}
      </div>
    </div>
  );
  if (horizontal)
    return (
      <div className="surface flex items-center gap-4 px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="engrave !text-[8px]">Score</div>
          <div key={score} className="score-bump font-display text-[34px] font-[700] leading-none tabular-nums">{score}</div>
        </div>
        <div>
          <div className="engrave !text-[8px]">Best</div>
          <div className="font-mono text-[15px] tabular-nums text-ink-2">{best}</div>
        </div>
        <div className="border-l border-line pl-4">{player}</div>
      </div>
    );
  return (
    <div className="surface flex flex-col gap-5 p-5">
      <div>
        <div className="engrave">Score</div>
        <div key={score} className="score-bump font-display text-[76px] font-[700] leading-[0.95] tracking-[-0.03em] tabular-nums">{score}</div>
      </div>
      <div className="border-t border-line pt-4">
        <div className="engrave">Best</div>
        <div className="font-display text-[32px] font-[640] leading-none tabular-nums text-ink-2">
          {best}{score > 0 && score >= best && <span className="engrave ml-2 !text-ember">new!</span>}
        </div>
      </div>
      <div className="border-t border-line pt-4">
        <div className="engrave mb-1">Playing</div>
        {player}
      </div>
    </div>
  );
}

function GameMenu({ open, setOpen, cur }: { open: boolean; setOpen: (o: boolean) => void; cur: string | null }) {
  const meta = useStore((s) => s.meta);
  const games = playableGames(meta);
  const name = appMeta(cur)?.name ?? "Pick a game";
  return (
    <div className="relative flex min-w-0 items-center gap-1">
      <button className="key key-icon max-sm:hidden" title="Previous game ([)" aria-label="Previous game" onMouseDown={(e) => e.preventDefault()} onClick={() => switchGame(-1)}><ChevronLeft size={16} /></button>
      <button className="key min-w-0 !px-3" aria-haspopup="menu" aria-expanded={open} onMouseDown={(e) => e.preventDefault()} onClick={() => setOpen(!open)} title="All games">
        <Icon name={appMeta(cur)?.icon ?? "gamepad-2"} size={15} className="text-ember" />
        <span className="truncate font-display text-[15px] font-[640] normal-case tracking-[-0.01em]">{name}</span>
        <ChevronDown size={13} className={clsx("transition", open && "rotate-180")} />
      </button>
      <button className="key key-icon max-sm:hidden" title="Next game (])" aria-label="Next game" onMouseDown={(e) => e.preventDefault()} onClick={() => switchGame(1)}><ChevronRight size={16} /></button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div role="menu" className="surface absolute left-0 top-full z-20 mt-2 grid w-[min(460px,calc(100vw-24px))] grid-cols-2 gap-1 p-1.5 animate-rise sm:grid-cols-3">
            {games.map((g) => (
              <button key={g.id} role="menuitem" onMouseDown={(e) => e.preventDefault()}
                onClick={() => { setOpen(false); if (g.id !== cur) goTo(g.id); }}
                className={clsx("flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-[13px] hover:bg-chassis-3",
                  g.id === cur ? "bg-ember-deep text-ember" : "text-ink-1")}>
                <Icon name={g.icon} size={15} className={g.id === cur ? "text-ember" : "text-ink-3"} />
                <span className="truncate">{g.name}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Per-browser display options for the preview: look (Glow / Pixel / LED) and, for Glow, the bloom amount. */
function DisplayMenu({ open, setOpen }: { open: boolean; setOpen: (o: boolean) => void }) {
  const look = useLook((s) => s.look);
  const setLook = useLook((s) => s.setLook);
  const bloom = useLook((s) => s.bloom);
  const setBloom = useLook((s) => s.setBloom);
  const pct = Math.round(bloom * 100);
  return (
    <div className="relative">
      <button className="key" onMouseDown={(e) => e.preventDefault()} onClick={() => setOpen(!open)} aria-haspopup="dialog" aria-expanded={open}
        title="How the preview is drawn on this screen">
        <Monitor size={14} /> <span className="hidden sm:inline">{LOOK_LABEL[look]}</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div role="dialog" aria-label="Display" className="surface absolute right-0 top-full z-20 mt-2 flex w-[min(300px,calc(100vw-24px))] flex-col gap-3.5 p-4 animate-rise">
            <div className="flex items-baseline justify-between">
              <span className="engrave !text-ink-2">Display</span>
              <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-4">this browser only</span>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-[12px] font-[540] text-ink-1">Look</span>
              <div className="seg !p-1" role="radiogroup" aria-label="Preview look">
                {LOOKS.map((l) => (
                  <button key={l} role="radio" aria-checked={look === l} data-active={look === l} className="!h-8" title={LOOK_HINT[l]}
                    onMouseDown={(e) => e.preventDefault()} onClick={() => setLook(l)}>{LOOK_LABEL[l]}</button>
                ))}
              </div>
              <p className="text-[11px] leading-snug text-ink-3">{LOOK_HINT[look]}.</p>
            </div>
            <div className={clsx("flex flex-col gap-1.5", look !== "glow" && "opacity-45")}>
              <div className="flex items-baseline justify-between">
                <span className="text-[12px] font-[540] text-ink-1">Sharpness</span>
                <span className="font-mono text-[11px] tabular-nums text-ink-2">{pct === 0 ? "Crisp" : `${pct}% glow`}</span>
              </div>
              <input type="range" min={0} max={1} step={0.05} value={bloom} className="fader" aria-label="Glow amount (0 = crisp)"
                disabled={look !== "glow"} style={{ ["--fill" as string]: `${pct}%` }}
                onChange={(e) => setBloom(+e.target.value)} onMouseUp={(e) => e.currentTarget.blur()} onTouchEnd={(e) => e.currentTarget.blur()} />
              <div className="flex justify-between font-mono text-[9px] uppercase tracking-[0.12em] text-ink-4"><span>Crisp</span><span>Soft glow</span></div>
              {look !== "glow" && <p className="text-[11px] text-ink-3">Sharpness applies to the Glow look.</p>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** Largest square that fits `box`, snapped so each LED is a whole number of device pixels. */
function useLedSide(pad: number) {
  const box = useRef<HTMLDivElement>(null);
  const [inner, setInner] = useState(0);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const dpr = Math.min(3, window.devicePixelRatio || 1);
      const avail = Math.min(e.contentRect.width, e.contentRect.height) - pad * 2;
      setInner(Math.max(128, (Math.floor((avail * dpr) / 32) * 32) / dpr));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [pad]);
  return { box, inner };
}

// ------------------------------------------------------------------ the view
export function PlayMode() {
  const open = useStore((s) => s.playMode);
  if (!open) return null;
  return <PlayView />;
}

function PlayView() {
  const set = useStore((s) => s.set);
  const cur = useStore((s) => s.state?.engine.current?.app ?? null);
  const power = useStore((s) => s.state?.settings.power ?? true);
  const linkFps = useStore((s) => s.state?.device.link_fps ?? 0);
  const deviceKind = useStore((s) => s.state?.device.kind);
  const opening = useStore((s) => s.opening);
  useStore((s) => s.meta); // re-render when meta loads
  const playing = cur && isPlayable(appMeta(cur)) ? cur : null;
  useLobbyPoll();
  const fr = useFriends(playing);
  const phone = useMedia("(max-width: 767.98px)");
  const touch = useMedia("(pointer: coarse)");
  const focused = useWindowFocus();
  const fps = useViewFps();
  const [menu, setMenu] = useState(false);
  const [controls, setControls] = useState(false);
  const [setup, setSetup] = useState(false); // phones: match setup, mode and actions live in a bottom sheet
  const [display, setDisplay] = useState(false);
  const { flow } = useGameStatus();
  const flowCard = playing && flow === "teams" ? <SideSelect app={playing} />
    : playing && flow === "outro" ? <Results app={playing} />
      : null;
  const players = useControls((s) => s.players);
  const padCount = usePads((s) => s.pads.length);
  const touchWho = touchPlayers(players, touch, maxPlayersOf(playing));
  const root = useRef<HTMLDivElement>(null);
  const pad = phone ? 10 : 22;
  const { box, inner } = useLedSide(pad);
  const exit = () => {
    releaseAll();
    set({ playMode: false });
  };

  // remember the game for next time
  useEffect(() => {
    if (playing && useStore.getState().lastGame !== playing) useStore.getState().prefs({ lastGame: playing });
  }, [playing]);

  // keyboard: game keys + R / [ / ] / Esc. Capture phase, so nothing underneath sees these keys.
  const menuRef = useRef(menu);
  menuRef.current = menu;
  const controlsRef = useRef(controls);
  controlsRef.current = controls;
  const displayRef = useRef(display);
  displayRef.current = display;
  useEffect(() => startGamepads(), []); // pads poll only while Play mode is open (and a pad is connected)
  useEffect(() => {
    root.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (captureKey(e)) return; // Controls panel: "press a key" to remap
      if (e.ctrlKey || e.metaKey || e.altKey) return; // Ctrl+R, Alt+Tab… stay the browser's
      if ((e.target as HTMLElement)?.closest("input, textarea, select, [contenteditable]")) return;
      e.stopPropagation();
      if (e.key === "Escape") {
        e.preventDefault();
        if (menuRef.current) setMenu(false);
        else if (displayRef.current) setDisplay(false);
        else if (controlsRef.current) setControls(false);
        else exit();
        return;
      }
      const app = current();
      if (app && gameKeyDown(e, app)) return;
      const k = e.key.toLowerCase();
      if (e.repeat) return;
      if (k === "r" && app) api.action(app, "restart");
      else if (k === "[") switchGame(-1);
      else if (k === "]") switchGame(1);
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      releaseAll();
    };
  }, []);

  const actions = (
    <>
      <button className="key" disabled={!playing} onMouseDown={(e) => e.preventDefault()} onClick={() => playing && api.action(playing, "restart")} title="Restart (R)">
        <RotateCcw size={13} /> Restart
      </button>
      {fr.lobby ? (
        <button className="key" onMouseDown={(e) => e.preventDefault()} onClick={() => closeFriends()} title="Close the room and disconnect the phones">
          <LogOut size={13} /> End friend game
        </button>
      ) : (
        <button className="key" disabled={!playing} onMouseDown={(e) => e.preventDefault()} onClick={() => playing && api.action(playing, "demo")} title="Hand the game to the AI">
          <Bot size={14} /> Let AI play
        </button>
      )}
      <FlyToggle className="col-span-2 [&>.flybtn]:w-full [&>.flybtn]:justify-center [&>.flybtn]:max-md:!h-11" />
    </>
  );

  const note = (
    <p className="text-center text-[11px] leading-snug text-ink-4">
      The panel shows ~6–9 fps over Bluetooth; this view is smoother.
      <span className="ml-2 font-mono text-[10px] text-ink-3">
        view {fps ? fps.toFixed(0) : "…"} fps{deviceKind !== "sim" ? ` · panel ${linkFps.toFixed(1)} fps` : ""}
      </span>
    </p>
  );

  const panel = (
    <div ref={box} className="relative grid min-h-0 w-full flex-1 place-items-center">
      {inner > 0 && (
        <div className="bezel bezel-play animate-rise" style={{ ["--bz" as string]: `${pad}px`, width: inner + pad * 2, height: inner + pad * 2 }}>
          {!phone && <><span className="screw left-[7px] top-[7px]" /><span className="screw right-[7px] top-[7px]" />
            <span className="screw bottom-[7px] left-[7px]" /><span className="screw bottom-[7px] right-[7px]" /></>}
          <div className={clsx("relative transition-opacity duration-500", !power && "opacity-15")} style={{ width: inner, height: inner }}>
            <LedPanel size={inner} crisp />
            {!playing && (
              <div className="absolute inset-0 grid place-items-center bg-black/60 p-6 text-center backdrop-blur-[2px]">
                <div>
                  <div className="font-display text-[20px] font-[640]">{opening ? `Opening ${appMeta(opening.app)?.name ?? opening.app}…` : "No game is showing"}</div>
                  {!opening && <p className="mt-1 text-[12.5px] text-ink-2">Pick one from the game menu above.</p>}
                </div>
              </div>
            )}
            {playing && !focused && !touch && (
              <button className="absolute inset-0 grid place-items-center bg-black/55 backdrop-blur-[1.5px]" onClick={() => root.current?.focus()}>
                <span className="surface flex items-center gap-2 px-4 py-2.5 text-[13px]"><span className="led" data-on="warn" /> Click to play — keys are paused</span>
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div ref={root} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Play mode"
      className="playmode fixed inset-0 z-[65] flex flex-col outline-none"
      onMouseDown={() => root.current?.focus({ preventScroll: true })}>
      {controls && <ControlsPanel app={playing} onClose={() => setControls(false)} />}
      <header className="flex shrink-0 items-center gap-2 px-3 pb-2 pt-[max(10px,env(safe-area-inset-top))] md:gap-3 md:px-6 md:pt-4">
        <span className="engrave hidden items-center gap-2 !text-ember lg:flex"><span className="led" data-on="ember" /> Play mode</span>
        <GameMenu open={menu} setOpen={setMenu} cur={playing} />
        <span className="flex-1" />
        {!phone && !touch && (
          <span className={clsx("hidden items-center gap-2 rounded-full border px-3 py-1 font-mono text-[10px] uppercase tracking-[0.14em] lg:flex",
            focused ? "border-[#1f5c43] text-ok" : "border-line text-warn")}>
            <span className="led" data-on={focused ? "ok" : "warn"} /> {focused ? "Keyboard ready" : "Keys paused"}
          </span>
        )}
        {fr.lobby && !fr.waiting && <span className="hidden sm:flex"><FriendsPill maxPlayers={fr.maxPlayers} /></span>}
        <DisplayMenu open={display} setOpen={setDisplay} />
        <button className="key" onMouseDown={(e) => e.preventDefault()} onClick={() => setControls(true)}
          title="Keyboards, gamepads and on-screen controls for each player" aria-haspopup="dialog" aria-expanded={controls}>
          <Gamepad2 size={14} /> <span className="hidden sm:inline">Controls</span>
          {padCount > 0 && <span className="rounded-full bg-chassis-0 px-1.5 font-mono text-[9px] text-ok" title={`${padCount} gamepad(s) connected`}>{padCount}</span>}
        </button>
        {!phone && actions}
        {phone && (
          <button className="key key-icon" onMouseDown={(e) => e.preventDefault()} onClick={() => setSetup(true)} aria-haspopup="dialog" aria-label="Match: mode, setup, restart, fruit fly" title="Match">
            <SlidersHorizontal size={15} />
          </button>
        )}
        <button className="key key-icon" onMouseDown={(e) => e.preventDefault()} onClick={exit} title="Leave Play mode (Esc)" aria-label="Leave Play mode"><X size={16} /></button>
      </header>

      {phone ? (
        // a handheld console: score strip, the panel as big as fits, the pad in the thumb zone — one screen, no scroll
        // (unless a match card — sides, results, the lobby — needs the room); everything else is one tap away in the sheet
        <div className={clsx("flex min-h-0 flex-1 flex-col gap-2.5 px-3 pb-[max(10px,env(safe-area-inset-bottom))]", (flowCard || fr.waiting) && "overflow-y-auto")}>
          {flowCard}
          {fr.multiplayer ? <VersusBoard maxPlayers={fr.maxPlayers} horizontal /> : <Scoreboard horizontal />}
          {fr.waiting || flowCard ? <div className="aspect-square w-full shrink-0">{panel}</div>
            : <div className="flex min-h-[46vw] flex-1 flex-col">{panel}</div>}
          {fr.waiting && fr.lobby ? <LobbyPanel lobby={fr.lobby} compact /> : <div className="shrink-0"><TouchArea app={playing} who={touchWho.length ? touchWho : [1]} /></div>}
          <Sheet open={setup} onClose={() => setSetup(false)} title={`${appMeta(playing)?.name ?? "Game"} · match`}>
            <div className="flex flex-col gap-3">
              {fr.multiplayer && playing && <ModeChoice playing={playing} friends={!!fr.lobby} />}
              {!flowCard && playing && !fr.waiting && <MatchSetup key={playing} app={playing} onControls={() => { setSetup(false); setControls(true); }} />}
              <div className="grid grid-cols-2 gap-2 [&>.key]:!h-11">{actions}</div>
              {note}
            </div>
          </Sheet>
        </div>
      ) : (
        <>
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(240px,320px)_minmax(0,1fr)_minmax(230px,300px)] items-center gap-6 px-6">
            <div className="flex max-h-full min-h-0 flex-col gap-3 overflow-y-auto py-2">
              {fr.multiplayer && playing && <ModeChoice playing={playing} friends={!!fr.lobby} />}
              {flowCard ?? (playing && !fr.waiting && <MatchSetup key={playing} app={playing} onControls={() => setControls(true)} />)}
              {fr.multiplayer ? <VersusBoard maxPlayers={fr.maxPlayers} /> : <Scoreboard />}
            </div>
            <div className="flex h-full min-h-0 flex-col py-2">{panel}</div>
            <div className="max-h-full min-h-0 overflow-y-auto py-2">
              {fr.waiting && fr.lobby ? <LobbyPanel lobby={fr.lobby} />
                : touchWho.length ? (
                  <div className="flex flex-col gap-3">
                    <div className="surface p-4"><TouchArea app={playing} who={touchWho} compact /></div>
                    {!touch && <Legend app={playing} />}
                  </div>
                ) : <Legend app={playing} />}
            </div>
          </div>
          <div className="shrink-0 px-6 pb-4 pt-2">{note}</div>
        </>
      )}
    </div>
  );
}

/** The one entry point for buttons/palette: re-exported so callers don't need lib/gameInput. */
export { openPlay };
