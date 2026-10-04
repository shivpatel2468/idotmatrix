import clsx from "clsx";
import { Bot, Check, Copy, Play, Users, Wifi, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { copyText } from "../lib/compat";
import { qrEncode } from "../lib/qr";
import { EMPTY_LIST, toast, useStore } from "../lib/store";
import type { LobbyInfo, SeatStatus } from "../lib/types";

/**
 * Local-Wi-Fi multiplayer in Play mode: "vs AI" / "Play with friends", the lobby (join QR, URL, room code, seats
 * filling in), and the versus scoreboard. The engine owns the lobby (`/api/play/lobby`); phones join at /p/<code>.
 */
export const SEAT_COLORS: Record<number, string> = { 1: "#00c8ff", 2: "#ff3c5a", 3: "#50ff78", 4: "#ffc800" };

// ------------------------------------------------------------------ data
let lastJson = "";

/** Fetch the lobby into the store; only writes when something changed (no re-render per poll). */
export async function refreshLobby() {
  try {
    const r = await api.lobby();
    const json = JSON.stringify(r);
    if (json === lastJson) return r;
    lastJson = json;
    const prev = useStore.getState().mpGames;
    const games = Object.fromEntries(r.games.map((g) => [g.id, g.max_players]));
    useStore.setState({
      lobby: r.lobby,
      lanReady: r.lan_ready,
      mpGames: prev && JSON.stringify(prev) === JSON.stringify(games) ? prev : games,
    });
    return r;
  } catch {
    return null;
  }
}

/** Poll while Play mode is open: fast while a lobby waits for phones, slow otherwise. Seat joins also arrive
 * instantly through the engine state stream (`status.seats`), so the poll is only for names and the URL. */
export function useLobbyPoll() {
  const waiting = useStore((s) => !!s.lobby && !!s.state?.engine.current?.status?.lobby);
  useEffect(() => {
    refreshLobby();
    const iv = setInterval(refreshLobby, waiting ? 700 : 2500);
    return () => clearInterval(iv);
  }, [waiting]);
}

/** Open a lobby for `app` (default: the game showing if it's multiplayer, else the first multiplayer game). */
export async function openFriends(app?: string) {
  const s = useStore.getState();
  let games = s.mpGames;
  if (!games) games = (await refreshLobby()) ? useStore.getState().mpGames : null;
  const cur = s.state?.engine.current?.app;
  const id = app ?? (cur && games?.[cur] ? cur : Object.keys(games ?? {})[0]);
  if (!id) {
    toast("No game supports friends on Wi-Fi yet", "error");
    return;
  }
  useStore.setState({ playMode: true, palette: false, drawer: null, opening: { app: id, since: performance.now() } });
  try {
    const r = await api.openLobby(id);
    if (r.warning) toast(r.warning, "error");
  } finally {
    lastJson = "";
    refreshLobby();
  }
}

export async function closeFriends() {
  if (!useStore.getState().lobby) return;
  useStore.setState({ lobby: null });
  try {
    await api.closeLobby();
  } finally {
    lastJson = "";
    refreshLobby();
  }
}

/** Play-mode helper: friend game state for the game that's showing. */
export function useFriends(playing: string | null) {
  const lobby = useStore((s) => s.lobby);
  const maxPlayers = useStore((s) => (playing ? (s.mpGames?.[playing] ?? 1) : 1));
  const waiting = useStore((s) => !!s.state?.engine.current?.status?.lobby);
  const active = !!lobby && lobby.app === playing;
  return { lobby: active ? lobby : null, multiplayer: maxPlayers > 1, maxPlayers, waiting: active && waiting };
}

const seatsOf = (status: Record<string, unknown> | undefined) =>
  ((status?.seats as SeatStatus[] | undefined) ?? (EMPTY_LIST as unknown as SeatStatus[]));

// ------------------------------------------------------------------ pieces
export function ModeChoice({ playing, friends }: { playing: string; friends: boolean }) {
  const [busy, setBusy] = useState(false);
  const pick = async (f: boolean) => {
    if (f === friends || busy) return;
    setBusy(true);
    try {
      if (f) await openFriends(playing);
      else await closeFriends();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="seg !p-1" role="radiogroup" aria-label="Opponent">
      <button role="radio" aria-checked={!friends} data-active={!friends} disabled={busy} onMouseDown={(e) => e.preventDefault()}
        onClick={() => pick(false)} className="!h-9 flex items-center justify-center gap-1.5"><Bot size={13} /> vs AI</button>
      <button role="radio" aria-checked={friends} data-active={friends} disabled={busy} onMouseDown={(e) => e.preventDefault()}
        onClick={() => pick(true)} className="!h-9 flex items-center justify-center gap-1.5"><Users size={13} /> Play with friends</button>
    </div>
  );
}

/** The join QR code as crisp SVG modules (dark on white, 4-module quiet zone — what phone cameras expect). */
export function QrCode({ text, size = 208 }: { text: string; size?: number }) {
  const { d, n } = useMemo(() => {
    const m = qrEncode(text, "L");
    let path = "";
    m.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        if (!row[x]) continue;
        let w = 1;
        while (x + w < row.length && row[x + w]) w++;
        path += `M${x + 4} ${y + 4}h${w}v1h-${w}z`;
        x += w - 1;
      }
    });
    return { d: path, n: m.length + 8 };
  }, [text]);
  return (
    <svg viewBox={`0 0 ${n} ${n}`} width={size} height={size} shapeRendering="crispEdges" role="img" aria-label={`QR code for ${text}`}
      className="rounded-[10px] shadow-[0_0_0_1px_rgba(255,255,255,.08),0_18px_40px_-18px_rgba(0,0,0,.9)]">
      <rect width={n} height={n} fill="#fff" />
      <path d={d} fill="#000" />
    </svg>
  );
}

function SeatSlots({ lobby, status }: { lobby: LobbyInfo; status: Record<string, unknown> | undefined }) {
  const live = seatsOf(status);
  const slots = Array.from({ length: lobby.max_players }, (_, i) => i + 1);
  return (
    <div className="flex flex-col gap-1.5">
      {slots.map((n) => {
        const c = SEAT_COLORS[n];
        const joined = n === 1 || live.find((x) => x.seat === n)?.human || lobby.seats.some((x) => x.seat === n);
        const name = n === 1 ? "You · host" : (lobby.seats.find((x) => x.seat === n)?.name ?? `Player ${n}`);
        return (
          <div key={n} className={clsx("flex items-center gap-3 rounded-[10px] border px-3 py-2 transition", joined ? "bg-chassis-0" : "border-dashed")}
            style={{ borderColor: joined ? `${c}66` : "var(--color-line-2)", boxShadow: joined ? `0 0 18px -8px ${c}` : undefined }}>
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full font-mono text-[11px] font-[700] text-black"
              style={{ background: joined ? c : "transparent", border: joined ? "none" : `1.5px dashed ${c}88`, color: joined ? "#000" : c }}>{n}</span>
            <span className="min-w-0 flex-1 truncate text-[13px]" style={{ color: joined ? "var(--color-ink-1)" : "var(--color-ink-3)" }}>
              {joined ? name : "Waiting for a phone…"}
            </span>
            {joined ? <Check size={14} style={{ color: c }} /> : <span className="led !h-[6px] !w-[6px]" data-on="warn" />}
          </div>
        );
      })}
    </div>
  );
}

/** Lobby: QR + URL + room code + seats + Start now / Cancel. */
export function LobbyPanel({ lobby, compact = false }: { lobby: LobbyInfo; compact?: boolean }) {
  const status = useStore((s) => s.state?.engine.current?.status);
  const lanReady = useStore((s) => s.lanReady) && lobby.lan_ready;
  const web = useStore((s) => s.meta?.platform === "web"); // the web app: phones join over the internet (WebRTC)
  const [copied, setCopied] = useState(false);
  const live = seatsOf(status);
  const joined = Array.from({ length: lobby.max_players - 1 }, (_, i) => i + 2)
    .filter((n) => live.find((x) => x.seat === n)?.human || lobby.seats.some((x) => x.seat === n)).length;
  const empty = lobby.max_players - 1 - joined;
  const copy = async () => {
    if (!lobby.url) return;
    if (await copyText(lobby.url)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } else {
      toast("Couldn't copy — select the address instead", "error");
    }
  };
  return (
    <div className="surface flex flex-col gap-4 p-5 animate-rise" aria-label="Friends lobby">
      <div className="flex items-center gap-2">
        <span className="led" data-on="ember" />
        <span className="engrave !text-ink-2">Waiting for friends</span>
        <span className="ml-auto font-mono text-[10px] text-ink-3">{joined}/{lobby.max_players - 1} joined</span>
      </div>
      {!lanReady && (
        <div className="rounded-[10px] border border-bad/40 bg-bad/10 p-3 text-[12px] leading-snug text-ink-1">
          <b className="font-[620] text-bad">Phones can't reach this computer.</b> DeskDot only listens to this computer.
          Set <code className="text-ink-1">host = "0.0.0.0"</code> in <code>deskdot.toml</code> (the default in new installs) and restart DeskDot.
        </div>
      )}
      <div className={clsx("flex gap-4", compact ? "flex-row items-center" : "flex-col items-center")}>
        {lobby.url && <QrCode text={lobby.url} size={compact ? 150 : 208} />}
        <div className={clsx("flex min-w-0 flex-col gap-2", compact ? "flex-1" : "w-full items-center text-center")}>
          <div className="text-[12.5px] text-ink-2">Scan with a phone camera — or type:</div>
          <button onMouseDown={(e) => e.preventDefault()} onClick={copy} title="Copy the address"
            className="flex max-w-full items-center gap-2 rounded-[8px] border border-line bg-chassis-0 px-2.5 py-1.5 font-mono text-[11.5px] text-ink-1 hover:border-line-2">
            <span className="truncate select-all">{lobby.url?.replace(/^https?:\/\//, "")}</span>
            {copied ? <Check size={12} className="shrink-0 text-ok" /> : <Copy size={12} className="shrink-0 text-ink-3" />}
          </button>
          <div className="flex items-baseline gap-2">
            <span className="engrave">Room</span>
            <span className="font-mono text-[24px] font-[700] tracking-[0.28em] text-ember">{lobby.code}</span>
          </div>
        </div>
      </div>
      <SeatSlots lobby={lobby} status={status} />
      <div className="flex flex-wrap gap-2">
        <button className="key key-ember !h-10 flex-1" onMouseDown={(e) => e.preventDefault()} onClick={() => api.startLobby().then(() => refreshLobby())}
          title={empty > 0 ? "Start with whoever joined; the AI plays the empty seats (or press Space)" : "Start (Space)"}>
          <Play size={13} /> Start now{empty > 0 && joined === 0 ? " vs AI" : ""}
        </button>
        <button className="key !h-10" onMouseDown={(e) => e.preventDefault()} onClick={() => closeFriends()} title="Close the room and disconnect the phones">
          <X size={13} /> Cancel
        </button>
      </div>
      <p className="flex gap-2 text-[11px] leading-snug text-ink-3">
        <Wifi size={13} className="mt-px shrink-0" />
        {web ? (
          <span>Friends can join from anywhere — their phone links straight to this tab, so keep it open (a direct link: very strict networks may block it).</span>
        ) : (
          <span>Friends must be on the same Wi-Fi. The first time, Windows may ask to allow DeskDot on the network — choose <b className="font-[600] text-ink-2">Allow</b> (private networks).</span>
        )}
      </p>
    </div>
  );
}

/** Friend game scoreboard: X vs O wins for tic-tac-toe, seats + score otherwise, and whose turn it is. */
export function VersusBoard({ maxPlayers, horizontal }: { maxPlayers: number; horizontal?: boolean }) {
  const status = useStore((s) => s.state?.engine.current?.status);
  const seats = seatsOf(status);
  const wins = status?.wins as { x: number; o: number; draws: number } | undefined;
  const turn = typeof status?.turn === "number" && !status?.lobby ? (status.turn as number) : null; // no turns while the lobby waits
  const seat = (n: number) => seats.find((x) => x.seat === n);
  const label = (n: number) => (n === 1 ? "You" : seat(n)?.human ? (seat(n)?.name ?? `P${n}`) : "AI");
  const turnText = turn == null ? null : turn === 1 ? "Your turn" : seat(turn)?.human ? "Their turn" : "AI's turn";
  const turnColor = turn ? SEAT_COLORS[turn] : undefined;
  const turnPill = turnText && (
    <div className="flex items-center gap-2 rounded-full border px-3 py-1.5 text-[13px] font-[620] transition"
      style={{ borderColor: `${turnColor}88`, color: turnColor, boxShadow: `0 0 22px -8px ${turnColor}`, background: `${turnColor}14` }}
      aria-live="polite">
      <span className="h-2 w-2 rounded-full" style={{ background: turnColor, boxShadow: `0 0 10px ${turnColor}` }} />
      {turnText}
    </div>
  );

  if (wins) {
    const side = (n: 1 | 2, mark: string, v: number) => (
      <div className={clsx("flex min-w-0 flex-1 flex-col", n === 2 && "items-end text-right")}>
        <div className="flex items-center gap-1.5 font-mono text-[11px] font-[700]" style={{ color: SEAT_COLORS[n] }}>
          {n === 1 && <span>{mark}</span>}<span className="truncate text-ink-2">{label(n)}</span>{n === 2 && <span>{mark}</span>}
        </div>
        <div key={v} className={clsx("score-bump font-display font-[700] leading-none tabular-nums", horizontal ? "text-[34px]" : "text-[64px]")}
          style={{ color: SEAT_COLORS[n], textShadow: `0 0 24px ${SEAT_COLORS[n]}55`, transformOrigin: n === 2 ? "right center" : undefined }}>{v}</div>
      </div>
    );
    return (
      <div className={clsx("surface flex flex-col", horizontal ? "gap-2 px-4 py-2.5" : "gap-4 p-5")}>
        {!horizontal && <div className="engrave">Wins</div>}
        <div className="flex items-end gap-3">
          {side(1, "X", wins.x)}
          <span className="pb-2 font-mono text-[11px] text-ink-4">vs</span>
          {side(2, "O", wins.o)}
        </div>
        <div className={clsx("flex items-center gap-3", horizontal ? "justify-between" : "flex-col items-start border-t border-line pt-4")}>
          <span className="font-mono text-[11px] text-ink-3">draws {wins.draws}</span>
          {turnPill}
        </div>
      </div>
    );
  }
  // generic 2–4 player game
  return (
    <div className="surface flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="engrave">Players</span>
        <span className="font-mono text-[12px] tabular-nums text-ink-1">score {String(status?.score ?? 0)}</span>
      </div>
      {Array.from({ length: maxPlayers }, (_, i) => i + 1).map((n) => (
        <div key={n} className="flex items-center gap-2.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: SEAT_COLORS[n], boxShadow: `0 0 10px ${SEAT_COLORS[n]}` }} />
          <span className="flex-1 text-[13px]">{label(n)}</span>
          <span className="font-mono text-[10px] uppercase text-ink-3">{n === 1 || seat(n)?.human ? "human" : "AI"}</span>
        </div>
      ))}
      {turnPill}
    </div>
  );
}

/** Header pill: who's connected, in seat colours. */
export function FriendsPill({ maxPlayers }: { maxPlayers: number }) {
  const status = useStore((s) => s.state?.engine.current?.status);
  const seats = seatsOf(status);
  const humans = seats.filter((x) => x.seat > 1 && x.human).length;
  return (
    <span className="flex items-center gap-2 rounded-full border border-line-2 bg-chassis-1 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-2"
      title={seats.map((x) => `${x.seat}: ${x.seat === 1 ? "you" : x.human ? x.name : "AI"}`).join(" · ")}>
      <span className="flex -space-x-1">
        {Array.from({ length: maxPlayers }, (_, i) => i + 1).map((n) => {
          const on = n === 1 || seats.find((x) => x.seat === n)?.human;
          return <span key={n} className="h-2.5 w-2.5 rounded-full ring-2 ring-chassis-1" style={{ background: on ? SEAT_COLORS[n] : "var(--color-chassis-4)" }} />;
        })}
      </span>
      {humans ? `${humans} friend${humans > 1 ? "s" : ""} connected` : "No friends connected"}
    </span>
  );
}
