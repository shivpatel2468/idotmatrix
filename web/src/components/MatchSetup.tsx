import clsx from "clsx";
import { Bot, Check, ChevronDown, ChevronLeft, ChevronRight, Gamepad2, Home, Keyboard, Play, RotateCcw, Smartphone, Trophy } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useControls } from "../lib/controls";
import { usePads } from "../lib/gamepads";
import { EMPTY_MAP, appMeta, useStore } from "../lib/store";
import type { GameFlow, GameMode, GameOutcome, JsonSchemaProp, RosterEntry } from "../lib/types";
import { sendInput } from "../lib/ws";
import { SEAT_COLORS } from "./Multiplayer";

/**
 * Play mode's game setup, mirroring the game's own flow on the panel (games_core.GameApp):
 *   MatchSetup  — mode / players / map / theme + Start (`start` action) + Menu on panel (`menu` action)
 *   SideSelect  — the FIFA-style side select while `status.flow === "teams"` (←/→ + A from every controller)
 *   Results     — `status.flow === "outro"`: the outcome, Rematch (key A) and Menu (key B)
 * Every option comes from /api/meta (the settings schema + `modes`); nothing is hard-coded per game.
 */
export const TEAM_COLORS = { 0: "#00c8ff", 1: "#ff3c5a" } as const;
const TEAM_NAMES = { 0: "Team A", 1: "Team B" } as const;

const FLOW_LABEL: Record<GameFlow, string> = {
  attract: "AI demo", home: "Menu on panel", teams: "Picking sides", intro: "Get ready", play: "Playing", outro: "Results",
};
const FLOW_LED: Record<GameFlow, "ok" | "warn" | "ember" | undefined> = {
  attract: undefined, home: "warn", teams: "warn", intro: "ember", play: "ok", outro: "ember",
};

const noFocus = (e: React.MouseEvent) => e.preventDefault(); // keep keyboard focus on Play mode

type Option = { id: string; label: string };
const optionsOf = (p: JsonSchemaProp | undefined): Option[] =>
  p?.enum?.map((id) => ({ id, label: p.enumLabels?.[id] ?? id })) ?? [];

/** What a game offers (modes with player ranges, maps, themes), read from /api/meta. */
export function useGameOptions(app: string | null) {
  useStore((s) => s.meta); // re-render when meta loads
  const m = appMeta(app);
  const props = m?.schema.properties ?? {};
  const playersMax = props.players?.maximum ?? Math.max(1, m?.max_players ?? 1);
  const modes: GameMode[] = m?.modes?.length
    ? m.modes
    : optionsOf(props.mode).map((o) => ({ id: o.id, name: o.label, min_players: 1, max_players: playersMax, teams: "ffa" as const }));
  return { modes, maps: optionsOf(props.map), themes: optionsOf(props.theme), playersMax };
}

export function useGameStatus() {
  const status = useStore((s) => s.state?.engine.current?.status);
  const flow = (typeof status?.flow === "string" ? status.flow : null) as GameFlow | null;
  const roster = (status?.roster as Record<string, RosterEntry> | undefined) ?? (EMPTY_MAP as unknown as Record<string, RosterEntry>);
  return {
    flow,
    mode: typeof status?.mode === "string" ? status.mode : null,
    map: typeof status?.map === "string" ? status.map : null,
    roster,
    outcome: (status?.outcome as GameOutcome | undefined) ?? null,
  };
}

export function FlowPill({ flow }: { flow: GameFlow | null }) {
  if (!flow) return null;
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-line-2 bg-chassis-0 px-2.5 py-1 font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-2"
      title="What the panel is showing now" aria-live="polite">
      <span className="led !h-[6px] !w-[6px]" data-on={FLOW_LED[flow]} /> {FLOW_LABEL[flow]}
    </span>
  );
}

// ------------------------------------------------------------------ controller chips
type Device = { kind: "keys" | "pad" | "touch" | "phone"; label: string };
/** How seat `n` is played from here: phone (lobby), gamepad, keyboard preset or on-screen controls. */
function useSeatDevice(n: number): Device | null {
  const cfg = useControls((s) => s.players[n - 1]);
  const assign = useControls((s) => s.pads);
  const pads = usePads((s) => s.pads);
  const phone = useStore((s) => s.lobby?.seats.find((x) => x.seat === n));
  if (phone) return { kind: "phone", label: phone.name || "Phone" };
  const pad = pads.find((p) => assign[p.key] === n);
  if (pad) return { kind: "pad", label: pad.brand === "generic" ? "Gamepad" : `${pad.brand === "playstation" ? "PS" : pad.brand[0].toUpperCase() + pad.brand.slice(1)} pad` };
  if (!cfg) return null;
  if (cfg.kb === "arrows") return { kind: "keys", label: "Arrows" };
  if (cfg.kb === "wasd") return { kind: "keys", label: "WASD" };
  if (cfg.kb === "ijkl") return { kind: "keys", label: "IJKL" };
  if (cfg.kb === "custom") return { kind: "keys", label: "Custom keys" };
  if (cfg.touch) return { kind: "touch", label: "On-screen" };
  return null;
}

const DEVICE_ICON = { keys: Keyboard, pad: Gamepad2, touch: Smartphone, phone: Smartphone } as const;

/** Side-select tile: stacked so it fits a third of the card (seat, who, controller, ready). */
function SeatTile({ n, entry }: { n: number; entry: RosterEntry }) {
  const dev = useSeatDevice(n);
  const c = SEAT_COLORS[n] ?? "#efece4";
  const Ico = dev ? DEVICE_ICON[dev.kind] : Keyboard;
  return (
    <div className="flex min-w-0 flex-col items-center gap-1 rounded-[10px] border bg-chassis-0 px-1 py-2 text-center transition animate-rise"
      style={{ borderColor: entry.ready ? c : `${c}66`, boxShadow: entry.ready ? `0 0 18px -6px ${c}` : undefined }}>
      <span className="grid h-7 w-7 place-items-center rounded-full font-mono text-[11px] font-[700] text-black" style={{ background: c, boxShadow: `0 0 12px -2px ${c}` }}>{n}</span>
      <span className="max-w-full truncate text-[11.5px] font-[600] text-ink-1">{n === 1 ? "You" : `Player ${n}`}</span>
      <span className="flex max-w-full items-center gap-1 truncate font-mono text-[8.5px] uppercase tracking-[0.08em] text-ink-3" title={dev?.label ?? "No controller"}>
        <Ico size={10} className="shrink-0" /> <span className="truncate">{dev?.label ?? "None"}</span>
      </span>
      {entry.ready
        ? <span className="flex items-center gap-0.5 font-mono text-[9px] font-[700] uppercase" style={{ color: c }}><Check size={11} /> Ready</span>
        : <span className="font-mono text-[9px] uppercase text-ink-4 animate-pulse">picking…</span>}
    </div>
  );
}

function SeatChip({ n, entry, compact }: { n: number; entry: RosterEntry | undefined; compact?: boolean }) {
  const dev = useSeatDevice(n);
  const c = SEAT_COLORS[n] ?? "#efece4";
  const human = entry?.human ?? n === 1;
  const ready = !!entry?.ready;
  const Ico = dev ? DEVICE_ICON[dev.kind] : Bot;
  return (
    <div className={clsx("flex items-center gap-2 rounded-[10px] border bg-chassis-0 transition", compact ? "px-2 py-1.5" : "px-2.5 py-2", !human && "border-dashed opacity-70")}
      style={{ borderColor: ready ? c : human ? `${c}66` : "var(--color-line-2)", boxShadow: ready ? `0 0 18px -6px ${c}` : undefined }}>
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full font-mono text-[10.5px] font-[700]"
        style={human ? { background: c, color: "#000" } : { border: `1.5px dashed ${c}88`, color: c }}>{n}</span>
      <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-[12px] font-[600] text-ink-1">{human ? (n === 1 ? "You" : `Player ${n}`) : "AI"}</div>
        <div className="flex items-center gap-1 truncate font-mono text-[9px] uppercase tracking-[0.1em] text-ink-3">
          <Ico size={10} className="shrink-0" /> {human ? (dev?.label ?? "No controller") : "computer"}
        </div>
      </div>
      {human && ready && <span className="flex items-center gap-0.5 font-mono text-[9px] font-[700] uppercase" style={{ color: c }}><Check size={12} /> Ready</span>}
    </div>
  );
}

// ------------------------------------------------------------------ match setup
type Pick = { mode: string; players: number; map: string; theme: string };

export function MatchSetup({ app, onControls, collapsible = false }: { app: string; onControls: () => void; collapsible?: boolean }) {
  const { modes, maps, themes, playersMax } = useGameOptions(app);
  const { flow, mode: liveMode, map: liveMap } = useGameStatus();
  const settings = useStore((s) => s.state?.apps?.[app]);
  const humans = useStore((s) => ((s.state?.engine.current?.status?.seats as { seat: number; human: boolean }[] | undefined) ?? []).filter((x) => x.human).length);
  const [open, setOpen] = useState(!collapsible);
  const initial = (): Pick => ({
    mode: liveMode ?? String(settings?.mode ?? modes[0]?.id ?? ""),
    players: Number(settings?.players ?? 1),
    map: liveMap ?? String(settings?.map ?? maps[0]?.id ?? ""),
    theme: String(settings?.theme ?? themes[0]?.id ?? ""),
  });
  const [pick, setPick] = useState<Pick>(initial);
  // the panel's own menu changed mode / map: follow it (the panel and this card are the same menu)
  useEffect(() => {
    if (liveMode) setPick((p) => (p.mode === liveMode ? p : { ...p, mode: liveMode }));
  }, [liveMode]);
  useEffect(() => {
    if (liveMap) setPick((p) => (p.map === liveMap ? p : { ...p, map: liveMap }));
  }, [liveMap]);

  const mode = modes.find((m) => m.id === pick.mode) ?? modes[0];
  const lo = mode ? mode.min_players : 1;
  const hi = mode ? Math.min(mode.max_players, playersMax) : playersMax;
  const players = Math.max(lo, Math.min(hi, pick.players));
  const set = (p: Partial<Pick>) => setPick((x) => ({ ...x, ...p }));
  const versus = mode?.teams === "versus" && players > 1;

  const start = async () => {
    const body: Record<string, unknown> = { players };
    if (modes.length > 1 && mode) body.mode = mode.id;
    if (maps.length) body.map = pick.map;
    if (themes.length) body.theme = pick.theme;
    // remember the choice as this game's defaults (settings patches don't restart a game), then start
    api.patchSettings(app, Object.fromEntries(Object.entries(body).filter(([k]) => k !== "players" || playersMax > 1))).catch(() => {});
    await api.action(app, "start", body);
  };

  const summary = [mode && modes.length > 1 ? mode.name : null, playersMax > 1 ? `${players}P` : null, maps.find((m) => m.id === pick.map)?.label]
    .filter(Boolean).join(" · ");

  return (
    <section className="surface flex flex-col gap-3.5 p-4" aria-label="Match setup">
      <div className="flex items-center gap-2">
        {collapsible ? (
          <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onMouseDown={noFocus} onClick={() => setOpen(!open)} aria-expanded={open}>
            <span className="engrave !text-ink-2">Match setup</span>
            {!open && <span className="truncate text-[11.5px] text-ink-3">{summary}</span>}
            <ChevronDown size={13} className={clsx("ml-auto shrink-0 text-ink-3 transition", open && "rotate-180")} />
          </button>
        ) : <span className="engrave flex-1 !text-ink-2">Match setup</span>}
        <FlowPill flow={flow} />
      </div>
      {open && (
        <>
          {modes.length > 1 && (
            <Row label="Mode">
              <div className="seg !p-1" role="radiogroup" aria-label="Mode">
                {modes.map((m) => (
                  <button key={m.id} role="radio" aria-checked={m.id === mode?.id} data-active={m.id === mode?.id} onMouseDown={noFocus}
                    title={`${m.name} · ${m.min_players === m.max_players ? m.min_players : `${m.min_players}–${m.max_players}`} player${m.max_players > 1 ? "s" : ""}`}
                    onClick={() => set({ mode: m.id, players: Math.max(m.min_players, Math.min(m.max_players, pick.players)) })}
                    className="!h-8 min-w-0 truncate">{m.name}</button>
                ))}
              </div>
            </Row>
          )}
          {playersMax > 1 && (
            <Row label="Players" hint={hi > 1 ? `${lo === hi ? lo : `${lo}–${hi}`} in ${mode?.name ?? "this mode"} · AI fills empty seats` : "Single player"}>
              <div className="seg !p-1" role="radiogroup" aria-label="Players">
                {Array.from({ length: Math.max(1, hi) }, (_, i) => i + 1).map((n) => (
                  <button key={n} role="radio" aria-checked={n === players} data-active={n === players} disabled={n < lo} onMouseDown={noFocus}
                    onClick={() => set({ players: n })} className={clsx("!h-8", n < lo && "opacity-30")}>
                    <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full" style={{ background: SEAT_COLORS[n] }} />{n}</span>
                  </button>
                ))}
              </div>
            </Row>
          )}
          {maps.length > 0 && (
            <Row label="Map">
              {maps.length <= 3 ? (
                <div className="seg !p-1" role="radiogroup" aria-label="Map">
                  {maps.map((m) => (
                    <button key={m.id} role="radio" aria-checked={m.id === pick.map} data-active={m.id === pick.map} onMouseDown={noFocus}
                      onClick={() => set({ map: m.id })} className="!h-8 min-w-0 truncate">{m.label}</button>
                  ))}
                </div>
              ) : (
                <Select value={pick.map} options={maps} onChange={(map) => set({ map })} label="Map" />
              )}
            </Row>
          )}
          {themes.length > 0 && (
            <Row label="Theme">
              <Select value={pick.theme} options={themes} onChange={(theme) => set({ theme })} label="Theme" />
            </Row>
          )}
          <button className="key key-ember !h-12 w-full !text-[12px]" onMouseDown={noFocus} onClick={start}
            title={versus ? "Start — then everyone picks a side on the panel (←/→, A = ready)" : "Start the match"}>
            <Play size={15} fill="currentColor" /> Start{mode && modes.length > 1 ? ` ${mode.name}` : ""}
          </button>
          {versus && <p className="-mt-1.5 text-center text-[11px] text-ink-3">Next: pick sides — <b className="font-[600] text-ink-2">← / →</b> then <b className="font-[600] text-ink-2">A</b></p>}
          <div className="grid grid-cols-2 gap-2">
            <button className="key !h-9" onMouseDown={noFocus} onClick={() => api.action(app, "menu")} title="Open the game's own menu on the panel (same as B)">
              <Home size={13} /> Menu on panel
            </button>
            <button className="key !h-9" onMouseDown={noFocus} onClick={onControls} title="Keyboards, gamepads and on-screen controls per player">
              <Gamepad2 size={13} /> Controllers
            </button>
          </div>
          {players > 1 && (
            <div className="flex flex-col gap-1.5 border-t border-line pt-3">
              <div className="flex items-center justify-between">
                <span className="engrave">Seats</span>
                <span className="font-mono text-[9.5px] text-ink-4">{Math.max(1, humans)} ready to play</span>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {Array.from({ length: players }, (_, i) => i + 1).map((n) => <SetupSeat key={n} n={n} />)}
              </div>
              <p className="text-[10.5px] leading-snug text-ink-4">Extra players: press any key on your controller before Start to take a seat.</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function SetupSeat({ n }: { n: number }) {
  const human = useStore((s) => n === 1 || !!(s.state?.engine.current?.status?.seats as { seat: number; human: boolean }[] | undefined)?.find((x) => x.seat === n)?.human);
  return <SeatChip n={n} entry={{ team: null, human, ready: false }} compact />;
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[12px] font-[540] text-ink-1">{label}</span>
        {hint && <span className="truncate text-[10.5px] text-ink-4">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function Select({ value, options, onChange, label }: { value: string; options: Option[]; onChange: (v: string) => void; label: string }) {
  return (
    <select className="field !h-9 !text-[12.5px]" value={value} aria-label={label}
      onChange={(e) => {
        onChange(e.target.value);
        e.currentTarget.blur(); // hand the arrow keys back to the game
      }}>
      {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
  );
}

// ------------------------------------------------------------------ side select (flow "teams")
export function SideSelect({ app }: { app: string }) {
  const { roster } = useGameStatus();
  const seats = Object.keys(roster).map(Number).sort((a, b) => a - b);
  const people = seats.filter((s) => roster[s].human);
  const ai = seats.length - people.length;
  const col = (team: 0 | 1 | null) => people.filter((s) => roster[s].team === team);
  const key = (k: string) => sendInput(app, k, 1);
  const me = roster[1];
  const waiting = people.filter((s) => !roster[s].ready).length;
  return (
    <section className="surface flex flex-col gap-3 p-4 animate-rise" aria-label="Pick sides">
      <div className="flex items-center gap-2">
        <span className="engrave flex-1 !text-ink-2">Pick sides</span>
        <FlowPill flow="teams" />
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        {([0, null, 1] as const).map((t) => (
          <div key={String(t)} className={clsx("flex min-h-[120px] min-w-0 flex-col gap-1.5 rounded-[11px] border p-1.5", t === null ? "border-dashed border-line-2" : "")}
            style={t === null ? undefined : { borderColor: `${TEAM_COLORS[t]}55`, background: `${TEAM_COLORS[t]}0d`, boxShadow: `inset 0 0 26px -16px ${TEAM_COLORS[t]}` }}>
            <div className="truncate pb-0.5 text-center font-mono text-[9.5px] font-[700] uppercase tracking-[0.14em]"
              style={{ color: t === null ? "var(--color-ink-4)" : TEAM_COLORS[t] }}>{t === null ? "Middle" : TEAM_NAMES[t]}</div>
            {col(t).map((s) => <SeatTile key={s} n={s} entry={roster[s]} />)}
          </div>
        ))}
      </div>
      {ai > 0 && (
        <div className="flex items-center gap-2 rounded-[10px] border border-dashed border-line-2 px-3 py-2 text-[11.5px] text-ink-3">
          <Bot size={13} className="shrink-0" />
          <span className="flex-1">AI fills {ai} seat{ai > 1 ? "s" : ""} on the smaller side</span>
          <span className="flex -space-x-1">{seats.filter((s) => !roster[s].human).map((s) => (
            <span key={s} className="h-2.5 w-2.5 rounded-full ring-2 ring-chassis-1" style={{ background: `${SEAT_COLORS[s]}88` }} />
          ))}</span>
        </div>
      )}
      <div className="flex items-center gap-1.5">
        <button className="key key-icon !h-10 !w-10" onMouseDown={noFocus} onClick={() => key("left")} disabled={!!me?.ready} aria-label="Move left" title="Move left (←)"><ChevronLeft size={16} /></button>
        <button className={clsx("key !h-10 flex-1", me?.team != null && !me.ready && "key-ember")} onMouseDown={noFocus} onClick={() => key("a")}
          disabled={me?.team == null} title="Ready (A) — press again to change your mind">
          <Check size={14} /> {me?.ready ? "Not ready" : "Ready"}
        </button>
        <button className="key key-icon !h-10 !w-10" onMouseDown={noFocus} onClick={() => key("right")} disabled={!!me?.ready} aria-label="Move right" title="Move right (→)"><ChevronRight size={16} /></button>
      </div>
      <p className="text-[11px] leading-snug text-ink-3">
        Every controller: <b className="font-[600] text-ink-2">← / →</b> picks a side, <b className="font-[600] text-ink-2">A</b> = ready, <b className="font-[600] text-ink-2">B</b> = back.
        {waiting > 0 ? ` Waiting for ${waiting} player${waiting > 1 ? "s" : ""}.` : ""}
      </p>
    </section>
  );
}

// ------------------------------------------------------------------ results (flow "outro")
export function Results({ app }: { app: string }) {
  const { outcome, roster } = useGameStatus();
  const score = useStore((s) => Number(s.state?.engine.current?.status?.score ?? 0));
  const people = Object.values(roster).filter((r) => r.human).length;
  let title = "Game over";
  let color: string = "var(--color-ember)";
  if (outcome?.team === 0 || outcome?.team === 1) {
    title = `${TEAM_NAMES[outcome.team]} wins`;
    color = TEAM_COLORS[outcome.team];
    if (roster["1"]?.team === outcome.team) title += " — that's you!";
  } else if (typeof outcome?.seat === "number") {
    const s = outcome.seat;
    const team = roster[String(s)]?.team;
    const versus = new Set(Object.values(roster).map((r) => r.team)).size > 1; // two sides: the panel uses team colours
    color = versus && (team === 0 || team === 1) ? TEAM_COLORS[team] : (SEAT_COLORS[s] ?? color);
    title = s === 1 ? (people <= 1 ? "You win!" : "Player 1 wins") : roster[String(s)]?.human ? `Player ${s} wins` : "The AI wins";
  }
  return (
    <section className="surface flex flex-col gap-3.5 p-4 animate-rise" aria-label="Results">
      <div className="flex items-center gap-2">
        <span className="engrave flex-1 !text-ink-2">Results</span>
        <FlowPill flow="outro" />
      </div>
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full" style={{ background: `${color}22`, color, boxShadow: `0 0 26px -8px ${color}` }}>
          <Trophy size={20} />
        </span>
        <div className="min-w-0">
          <div className="font-display text-[21px] font-[680] leading-tight" style={{ color }}>{title}</div>
          {outcome?.text ? <div className="text-[12px] text-ink-2">{outcome.text}</div> : <div className="font-mono text-[11px] text-ink-3">score {score}</div>}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button className="key key-ember !h-11" onMouseDown={noFocus} onClick={() => sendInput(app, "a", 1)} title="Play again with the same sides (A)">
          <RotateCcw size={14} /> Rematch
        </button>
        <button className="key !h-11" onMouseDown={noFocus} onClick={() => sendInput(app, "b", 1)} title="Back to the game's menu (B)">
          <Home size={14} /> Menu
        </button>
      </div>
      <p className="text-center text-[10.5px] text-ink-4">A = rematch · B = menu</p>
    </section>
  );
}
