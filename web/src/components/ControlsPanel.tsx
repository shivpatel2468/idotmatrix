import clsx from "clsx";
import { Gamepad2, Info, Keyboard, Smartphone, TriangleAlert, Users, Vibrate, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  type KbPreset, type PlayerCfg, type TouchStyle, GAME_KEYS, PRESETS, TOUCH_STYLES, bindingOf, coarsePointer, conflicts,
  keyLabel, maxPlayersOf, soloKeyboard, touchStyleFor, twoOnOneKeyboard, useControls,
} from "../lib/controls";
import { type GameKey, useInputFlash } from "../lib/gameInput";
import { GLYPHS, type PadInfo, onPadActivity, testRumble, usePads } from "../lib/gamepads";
import { EMPTY_LIST, appMeta, useStore } from "../lib/store";
import type { SeatStatus } from "../lib/types";
import { SEAT_COLORS } from "./Multiplayer";

/**
 * Play mode's Controls panel: per player (P1..P{max_players}) the keyboard preset or custom binding, the gamepad,
 * and on-screen touch controls; the connected gamepads with their player, dead zone and rumble; the on-screen
 * controller style for this game; conflicts; and what works where. Everything persists (lib/controls.ts).
 */
const KB_OPTIONS: { id: KbPreset; label: string }[] = [
  { id: "none", label: "No keyboard" },
  { id: "arrows", label: PRESETS.arrows.label },
  { id: "wasd", label: PRESETS.wasd.label },
  { id: "ijkl", label: PRESETS.ijkl.label },
  { id: "custom", label: "Custom…" },
];
const KEY_NAMES: Record<GameKey, string> = { up: "Up", down: "Down", left: "Left", right: "Right", a: "A", b: "B" };
const STYLE_NAMES: Record<TouchStyle, string> = { dpad: "D-pad", joystick: "Joystick", swipe: "Swipe", tap: "Tap zones" };

function Light({ on, color }: { on: boolean; color: string }) {
  return (
    <span className="h-2 w-2 shrink-0 rounded-full transition-[background,box-shadow] duration-100" title="Last input"
      style={{ background: on ? color : "var(--color-chassis-4)", boxShadow: on ? `0 0 10px ${color}, 0 0 0 2px rgba(0,0,0,.35)` : "0 0 0 2px rgba(0,0,0,.35)" }} />
  );
}

function usePadFlash(key: string) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = onPadActivity((k) => {
      if (k !== key) return;
      setOn(true);
      clearTimeout(t);
      t = setTimeout(() => setOn(false), 160);
    });
    return () => {
      off();
      clearTimeout(t);
    };
  }, [key]);
  return on;
}

function BindingGrid({ player, cfg, bad }: { player: number; cfg: PlayerCfg; bad: Map<string, string> }) {
  const capture = useControls((s) => s.capture);
  const b = bindingOf(cfg);
  return (
    <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
      {GAME_KEYS.map((k) => {
        const codes = b[k];
        const listening = capture?.player === player && capture.key === k;
        const clash = codes.find((c) => bad.has(c));
        return (
          <button key={k} onMouseDown={(e) => e.preventDefault()}
            onClick={() => useControls.setState({ capture: listening ? null : { player, key: k } })}
            title={clash ? bad.get(clash) : listening ? "Press a key (Esc cancels, Backspace clears)" : `${codes.map(keyLabel).join(" or ") || "Unbound"} — click, then press a key to remap`}
            className={clsx("flex min-w-0 flex-col items-center gap-0.5 overflow-hidden rounded-[9px] border px-1.5 py-1.5 transition",
              listening ? "border-ember bg-ember-deep" : clash ? "border-bad/70 bg-bad/10" : "border-line bg-chassis-0 hover:border-line-2")}>
            <span className="font-mono text-[8.5px] uppercase tracking-[0.14em] text-ink-3">{KEY_NAMES[k]}</span>
            <span className={clsx("max-w-full truncate font-mono text-[11px]", listening ? "animate-pulse text-ember" : codes.length ? "text-ink-1" : "text-ink-4")}>
              {listening ? "press…" : codes.length ? keyLabel(codes[0]) + (codes.length > 1 ? " +" : "") : "—"}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function PlayerCard({ n, cfg, pads, bad, seat, coarse }: {
  n: number; cfg: PlayerCfg; pads: readonly PadInfo[]; bad: Map<string, string>; seat: SeatStatus | undefined; coarse: boolean;
}) {
  const color = SEAT_COLORS[n];
  const flash = useInputFlash(n);
  const assign = useControls((s) => s.pads);
  const setPlayer = useControls((s) => s.setPlayer);
  const mine = pads.filter((p) => assign[p.key] === n);
  const touchOn = cfg.touch === true || (cfg.touch === null && n === 1 && coarse);
  const pickPad = (key: string) => {
    const next = { ...assign };
    for (const p of pads) if (next[p.key] === n) next[p.key] = 0;
    if (key) next[key] = n;
    useControls.getState().set({ pads: next });
  };
  const devices = [
    cfg.kb !== "none" && (cfg.kb === "custom" ? "Custom keys" : PRESETS[cfg.kb].label.split(" +")[0]),
    ...mine.map((p) => p.name),
    touchOn && "On-screen",
  ].filter(Boolean) as string[];
  return (
    <div className="rounded-[12px] border bg-chassis-0 p-3.5" style={{ borderColor: `${color}55`, boxShadow: `0 0 22px -14px ${color}` }}>
      <div className="flex items-center gap-2.5">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full font-mono text-[11px] font-[700] text-black" style={{ background: color }}>{n}</span>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-[620]">Player {n}{n === 1 && <span className="ml-1.5 font-normal text-ink-3">· host</span>}</div>
          <div className="truncate text-[11.5px] text-ink-3">{devices.length ? devices.join(" · ") : "No device — the AI plays this seat"}</div>
        </div>
        {seat && n > 1 && (
          <span className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-3">{seat.human ? "playing" : "AI"}</span>
        )}
        <Light on={flash} color={color} />
      </div>
      <div className="mt-3 flex flex-col gap-2.5">
        <label className="flex items-center gap-2.5">
          <Keyboard size={14} className="shrink-0 text-ink-3" />
          <select className="field !h-8 !text-[12.5px]" value={cfg.kb} aria-label={`Player ${n} keyboard`}
            onChange={(e) => {
              const kb = e.target.value as KbPreset;
              setPlayer(n, kb === "custom" ? { kb, custom: cfg.kb === "none" || cfg.kb === "custom" ? cfg.custom : { ...bindingOf(cfg) } } : { kb });
            }}>
            {KB_OPTIONS.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
        {cfg.kb !== "none" && <BindingGrid player={n} cfg={cfg} bad={bad} />}
        <label className="flex items-center gap-2.5">
          <Gamepad2 size={14} className="shrink-0 text-ink-3" />
          <select className="field !h-8 !text-[12.5px]" value={mine[0]?.key ?? ""} aria-label={`Player ${n} gamepad`}
            onChange={(e) => pickPad(e.target.value)} disabled={!pads.length}>
            <option value="">{pads.length ? "No gamepad" : "No gamepad connected"}</option>
            {pads.map((p) => (
              <option key={p.key} value={p.key}>{p.name}{assign[p.key] && assign[p.key] !== n ? ` (now P${assign[p.key]})` : ""}</option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-2.5">
          <Smartphone size={14} className="shrink-0 text-ink-3" />
          <span className="flex-1 text-[12.5px] text-ink-2">On-screen touch controls{cfg.touch === null && n === 1 ? <span className="text-ink-4"> · auto</span> : null}</span>
          <button role="switch" aria-checked={touchOn} aria-label={`Player ${n} on-screen controls`} className="toggle"
            onMouseDown={(e) => e.preventDefault()} onClick={() => setPlayer(n, { touch: !touchOn })} />
        </div>
      </div>
    </div>
  );
}

function PadRow({ pad, player, max }: { pad: PadInfo; player: number | undefined; max: number }) {
  const flash = usePadFlash(pad.key);
  const g = GLYPHS[pad.brand];
  const color = player ? SEAT_COLORS[player] : "var(--color-ink-3)";
  return (
    <div className="flex flex-col gap-2 rounded-[12px] border border-line bg-chassis-0 p-3">
      <div className="flex items-center gap-2.5">
        <Gamepad2 size={16} style={{ color }} className="shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-[600]" title={pad.id}>{pad.name}</div>
          <div className="font-mono text-[9.5px] uppercase tracking-[0.12em] text-ink-3">
            {pad.brand === "generic" ? "generic" : pad.brand} · {pad.standard ? "standard mapping" : "non-standard mapping"}{pad.rumble ? " · rumble" : ""}
          </div>
        </div>
        <Light on={flash} color={player ? SEAT_COLORS[player] : "#efece4"} />
        <select className="field !h-8 !w-[108px] !text-[12px]" aria-label={`${pad.name} player`}
          value={player === undefined ? "" : String(player)}
          onChange={(e) => useControls.getState().set({ pads: { ...useControls.getState().pads, [pad.key]: Number(e.target.value || 0) } })}>
          {player === undefined && <option value="">Press a button…</option>}
          <option value="0">Off</option>
          {Array.from({ length: 4 }, (_, i) => i + 1).map((p) => (
            <option key={p} value={p}>Player {p}{p > max ? " (not in this game)" : ""}</option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-3">
        <span><Glyph t={g.a} /> A</span>
        <span><Glyph t={g.b} /> B</span>
        <span><Glyph t={g.x} /> <Glyph t={g.y} /> shoulders · alternates</span>
        <span><Glyph t={g.start} /> restart</span>
        <span><Glyph t={g.select} /> let AI play</span>
        {pad.rumble && (
          <button className="ml-auto flex items-center gap-1 text-ink-2 hover:text-ink-1" onMouseDown={(e) => e.preventDefault()} onClick={() => testRumble(pad.key)}>
            <Vibrate size={12} /> test
          </button>
        )}
      </div>
      {g.note && <div className="text-[11px] leading-snug text-ink-3">{g.note}</div>}
    </div>
  );
}
const Glyph = ({ t }: { t: string }) => <kbd className="kbd !mx-0">{t}</kbd>;

export function ControlsPanel({ app, onClose }: { app: string | null; onClose: () => void }) {
  const players = useControls((s) => s.players);
  const assign = useControls((s) => s.pads);
  const deadzone = useControls((s) => s.deadzone);
  const rumble = useControls((s) => s.rumble);
  const ways = useControls((s) => s.ways);
  const picked = useControls((s) => s.touchStyle);
  const pads = usePads((s) => s.pads);
  const status = useStore((s) => s.state?.engine.current?.status);
  useStore((s) => s.meta); // re-render when meta loads
  useStore((s) => s.mpGames);
  const coarse = coarsePointer();
  const max = Math.max(1, maxPlayersOf(app));
  const bad = useMemo(() => conflicts(players.slice(0, Math.max(max, 1))), [players, max]);
  const seats = (status?.seats as SeatStatus[] | undefined) ?? (EMPTY_LIST as unknown as SeatStatus[]);
  const style = touchStyleFor(app, picked);
  const recommended: readonly string[] = (app && appMeta(app)?.controls) || EMPTY_LIST;
  const recTouch = recommended.find((c) => (TOUCH_STYLES as readonly string[]).includes(c)) ?? "dpad";
  const twoKb = players[0].kb === "wasd" && players[1].kb === "arrows";
  const unassigned = pads.filter((p) => assign[p.key] === undefined).length;

  // close on Esc is handled by Play mode; stop an unfinished remap when the panel closes
  useEffect(() => () => useControls.setState({ capture: null }), []);

  return (
    <>
      <div className="fixed inset-0 z-[70] bg-black/50 backdrop-blur-[2px]" onClick={onClose} />
      <aside role="dialog" aria-label="Controls" className="surface fixed inset-y-3 right-3 z-[71] flex w-[min(560px,calc(100vw-24px))] flex-col overflow-hidden animate-rise max-md:inset-x-3 max-md:w-auto">
        <header className="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <Gamepad2 size={16} className="text-ember" />
          <div className="min-w-0 flex-1">
            <div className="font-display text-[17px] font-[640] leading-tight">Controls</div>
            <div className="truncate text-[11.5px] text-ink-3">
              {appMeta(app)?.name ?? "No game"} · {max === 1 ? "1 player — every player's controls drive it" : `${max} players`}
            </div>
          </div>
          <button className="key key-icon" onMouseDown={(e) => e.preventDefault()} onClick={onClose} aria-label="Close controls" title="Close (Esc)"><X size={15} /></button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-5">
          {/* quick setups */}
          <section className="flex flex-col gap-2">
            <div className="engrave">Keyboard setup</div>
            <div className="seg !p-1">
              <button data-active={!twoKb} className="!h-9 flex items-center justify-center gap-1.5" onMouseDown={(e) => e.preventDefault()} onClick={soloKeyboard}>
                <Keyboard size={13} /> One player
              </button>
              <button data-active={twoKb} className="!h-9 flex items-center justify-center gap-1.5" onMouseDown={(e) => e.preventDefault()} onClick={twoOnOneKeyboard}>
                <Users size={13} /> Two on one keyboard
              </button>
            </div>
            <p className="text-[11.5px] leading-snug text-ink-3">
              {twoKb ? "P1 uses W A S D + F / G, P2 uses the arrows + Space / Shift. P2 takes their seat on the first press; after 10 s idle the AI takes it back."
                : "P1 on the arrows + Space / Shift (W A S D also steer while nobody else is on the keyboard)."}
            </p>
          </section>

          {/* players */}
          <section className="flex flex-col gap-2.5">
            <div className="engrave">Players</div>
            {players.slice(0, max).map((cfg, i) => (
              <PlayerCard key={i} n={i + 1} cfg={cfg} pads={pads} bad={bad} seat={seats.find((s) => s.seat === i + 1)} coarse={coarse} />
            ))}
            {bad.size > 0 && (
              <div className="flex flex-col gap-1 rounded-[10px] border border-bad/40 bg-bad/10 p-3 text-[12px] leading-snug text-ink-1" role="alert">
                {[...bad.values()].map((m) => (
                  <div key={m} className="flex gap-2"><TriangleAlert size={13} className="mt-px shrink-0 text-bad" /> {m}</div>
                ))}
              </div>
            )}
          </section>

          {/* gamepads */}
          <section className="flex flex-col gap-2.5">
            <div className="flex items-center gap-2">
              <span className="engrave flex-1">Gamepads</span>
              <span className="font-mono text-[10px] text-ink-3">{pads.length} connected</span>
            </div>
            {pads.length ? pads.map((p) => <PadRow key={p.key} pad={p} player={assign[p.key]} max={max} />) : (
              <div className="rounded-[12px] border border-dashed border-line-2 p-4 text-center text-[12.5px] leading-snug text-ink-2">
                No controller detected. Connect one to this computer by USB or Bluetooth, then <b className="font-[620] text-ink-1">press any button</b>.
              </div>
            )}
            {(unassigned > 0 || !pads.length) && (
              <div className="flex items-center gap-2 rounded-[10px] border border-line bg-chassis-0 px-3 py-2 text-[12px] text-ink-2">
                <span className="led" data-on="warn" /> Press any button on a new controller to join as the next free player.
              </div>
            )}
            <div className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-2.5 pt-1">
              <span className="text-[12.5px] text-ink-2">Stick dead zone</span>
              <input type="range" min={0.05} max={0.6} step={0.01} value={deadzone} className="fader" aria-label="Stick dead zone"
                style={{ ["--fill" as string]: `${((deadzone - 0.05) / 0.55) * 100}%` }}
                onChange={(e) => useControls.getState().set({ deadzone: +e.target.value })} />
              <span className="w-10 text-right font-mono text-[11.5px] tabular-nums text-ink-1">{Math.round(deadzone * 100)}%</span>
              <span className="text-[12.5px] text-ink-2">Rumble on a hit</span>
              <span className="text-[11px] text-ink-4">life lost, game over, round won — where the pad supports it</span>
              <button role="switch" aria-checked={rumble} aria-label="Rumble" className="toggle justify-self-end"
                onMouseDown={(e) => e.preventDefault()} onClick={() => useControls.getState().set({ rumble: !rumble })} />
            </div>
            <p className="text-[11px] leading-snug text-ink-4">
              D-pad or left stick move (held = repeat; deeper stick = faster in racers and paddle games) · A / ✕ is A ·
              B / ○ is B · X, Y, shoulders and triggers are alternates · Start restarts · Select lets the AI play.
            </p>
          </section>

          {/* on-screen */}
          <section className="flex flex-col gap-2">
            <div className="engrave">On-screen controls{app ? ` · ${appMeta(app)?.name ?? app}` : ""}</div>
            <div className="seg !p-1" role="radiogroup" aria-label="On-screen controller">
              {TOUCH_STYLES.map((t) => (
                <button key={t} role="radio" aria-checked={style === t} data-active={style === t} className="!h-9"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => app && useControls.getState().set({ touchStyle: { ...picked, [app]: t } })}>
                  {STYLE_NAMES[t]}{recTouch === t ? " ★" : ""}
                </button>
              ))}
            </div>
            {style === "joystick" && (
              <div className="seg !p-1 !w-fit">
                {([4, 8] as const).map((w) => (
                  <button key={w} data-active={ways === w} className="!px-4" onMouseDown={(e) => e.preventDefault()}
                    onClick={() => useControls.getState().set({ ways: w })}>{w}-way</button>
                ))}
              </div>
            )}
            <p className="text-[11.5px] leading-snug text-ink-3">
              ★ recommended for this game. Shown for players with on-screen controls turned on (player 1 automatically on
              touch screens). Remembered per game.
            </p>
          </section>

          {/* what works */}
          <section className="flex gap-2.5 rounded-[12px] border border-line bg-chassis-0 p-3.5 text-[12px] leading-snug text-ink-2">
            <Info size={14} className="mt-px shrink-0 text-info" />
            <div className="flex flex-col gap-1.5">
              <b className="font-[620] text-ink-1">What works</b>
              <span>Keyboards and gamepads connect to <b className="font-[600] text-ink-1">this laptop</b> — Bluetooth or USB.</span>
              <span>Friends’ phones join with the QR code: <b className="font-[600] text-ink-1">Play with friends</b> opens the lobby.</span>
              <span>A physical controller paired to a friend’s phone is limited by the phone’s browser on plain http — they should use the on-screen controls, or plug the controller into this laptop instead.</span>
            </div>
          </section>
        </div>
      </aside>
    </>
  );
}
