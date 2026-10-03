import clsx from "clsx";
import { Check, Copy, DoorOpen, Lock, Pause, Play, QrCode as QrIcon, ShieldCheck, Smartphone, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/api";
import { copyText } from "../../lib/compat";
import { appMeta, useStore } from "../../lib/store";
import { LedPanel } from "../LedPanel";
import { QrCode, useLobbyPoll } from "../Multiplayer";
import { CountdownRing, Credits, Tabs } from "./bits";
import { LeftWing } from "./LeftWing";
import { RightWing } from "./RightWing";
import { closeCasinoLobby, hideCasinoQr, lobbyFor, openCasinoLobby } from "./lobby";
import { PHASE, TONE, casinoOp, fmt, leaveCasino, saveWings, secondsLeft, useCasino, useCasinoApp, useCasinoFeed, useTick } from "./state";
import "./casino.css";

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// ------------------------------------------------------------------ the show: bulbs + chips
/** Chasing bulbs around the panel. They light up one after another on entry, then chase (faster on a win). */
function Marquee({ w, h, hot }: { w: number; h: number; hot: boolean }) {
  const bulbs = useMemo(() => {
    const gap = 21;
    const inset = 8;
    const W = w - inset * 2, H = h - inset * 2;
    const per = 2 * (W + H);
    const n = Math.max(16, Math.round(per / gap / 3) * 3);
    return Array.from({ length: n }, (_, i) => {
      let d = (i / n) * per;
      let x: number, y: number;
      if (d < W) [x, y] = [d, 0];
      else if ((d -= W) < H) [x, y] = [W, d];
      else if ((d -= H) < W) [x, y] = [W - d, H];
      else [x, y] = [0, H - (d - W)];
      return { x: x + inset, y: y + inset, i };
    });
  }, [w, h]);
  return (
    <div className="cz-marquee" data-hot={hot || undefined} aria-hidden>
      {bulbs.map((b) => (
        <span key={b.i} className="cz-bulb" style={{ left: b.x, top: b.y, ["--i" as string]: b.i, ["--k" as string]: b.i % 3 }} />
      ))}
    </div>
  );
}

/** Gold chips raining once over the stage when the casino opens. */
let lastSeen = -1e9; // when the casino stage was last on screen (a re-layout remounts it: no second show)
function ChipCascade({ run }: { run: number }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const fresh = performance.now() - lastSeen > 1500 || (run > 0 && performance.now() - run < 1500);
    lastSeen = performance.now();
    const keep = setInterval(() => (lastSeen = performance.now()), 500);
    if (!fresh || reducedMotion()) return () => clearInterval(keep);
    setOn(true);
    const t = setTimeout(() => setOn(false), 3200);
    return () => {
      clearTimeout(t);
      clearInterval(keep);
    };
  }, [run]);
  const chips = useMemo(() => Array.from({ length: 30 }, (_, i) => {
    const r = (k: number) => {
      const x = Math.sin((i + 1) * 12.9898 * k + run * 0.001) * 43758.5453;
      return x - Math.floor(x);
    };
    const col = ["#ffcc33", "#ffcc33", "#ff3f78", "#ff7419", "#13a65a", "#f3efe2"][Math.floor(r(1) * 6)];
    return { left: `${4 + r(2) * 92}%`, delay: `${r(3) * 0.9}s`, dur: `${1.5 + r(4) * 0.9}s`, size: 16 + r(5) * 16, spin: `${(r(6) - 0.5) * 900}deg`, col };
  }), [run]);
  if (!on) return null;
  return (
    <div className="cz-cascade" aria-hidden>
      {chips.map((c, i) => (
        <span key={i} className="cz-fall" style={{ left: c.left, width: c.size, height: c.size, animationDelay: c.delay, animationDuration: c.dur, ["--spin" as string]: c.spin, ["--chip" as string]: c.col }} />
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ host bar
function HostBar() {
  useTick(250);
  const st = useCasino((s) => s.status);
  const at = useCasino((s) => s.at);
  const phase = st?.phase ?? "idle";
  const ph = PHASE[phase] ?? { label: phase, hint: "", tone: "dim" as const };
  const paused = !!st?.paused;
  const ends = secondsLeft(st?.ends_in, at);
  const next = secondsLeft(st?.next_in, at);
  const span = st?.house?.bet_seconds ?? 20;
  const canStart = phase === "idle" || phase === "result";
  const anyBets = Object.keys(st?.totals ?? {}).length > 0;
  return (
    <div className="cz-hostbar">
      {phase === "result" && st?.result ? <ResultBanner /> : <div className="cz-phase" data-tone={paused ? "dim" : ph.tone}>
        {phase === "betting" ? <CountdownRing left={ends} span={span} size={42} /> : <span className="cz-phase-dot" />}
        <span className="min-w-0">
          <b>{paused ? "Paused" : ph.label}</b>
          <span>
            {paused ? "Timers are frozen" : phase === "betting" && ends == null ? "Waiting for the first chip" : phase === "result" && next != null && st?.house?.auto_next ? `Next round in ${Math.ceil(next)}s` : ph.hint}
          </span>
        </span>
      </div>}
      <div className="cz-hostkeys">
        <button className="cz-gold" disabled={!canStart || paused} onClick={() => casinoOp("start_round").catch(() => undefined)} title="Open betting for a new round" aria-label={phase === "result" ? "Next round" : "Start round"}>
          <Play size={13} /> <span className="cz-lbl">{phase === "result" ? "Next round" : "Start round"}</span>
        </button>
        <button className="key !h-9" disabled={phase !== "betting" || !anyBets || paused} onClick={() => casinoOp("lock").catch(() => undefined)} title="No more bets: close betting now and spin" aria-label="Lock now">
          <Lock size={13} /> <span className="cz-lbl">Lock now</span>
        </button>
        <button className="key !h-9" data-on={paused || undefined} onClick={() => casinoOp("pause").catch(() => undefined)} title={paused ? "Resume the timers" : "Freeze every timer"} aria-label={paused ? "Resume" : "Pause"}>
          {paused ? <Play size={13} /> : <Pause size={13} />} <span className="cz-lbl">{paused ? "Resume" : "Pause"}</span>
        </button>
      </div>
    </div>
  );
}

/** Round number and its fairness commitment (the seed's SHA-256, published before any bet). */
function RoundInfo() {
  const st = useCasino((s) => s.status);
  const [copied, setCopied] = useState(false);
  const hash = st?.hash ?? "";
  const copy = async () => {
    if (hash && (await copyText(hash))) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    }
  };
  return (
    <div className="cz-roundinfo">
        <span className="engrave !text-[8px]">Round</span>
        <b>{st?.round != null ? `#${st.round}` : "—"}</b>
        {hash && (
          <button onClick={copy} title={`Commitment: SHA-256 of this round's secret seed, published before any bet.\n${hash}\nClick to copy`}>
            <ShieldCheck size={11} /> <span className="cz-lbl">{hash.slice(0, 10)}…</span>{copied ? <Check size={11} /> : <Copy size={10} />}
          </button>
        )}
    </div>
  );
}

/** The result, big, while the table shows it. */
function ResultBanner() {
  const r = useCasino((s) => (s.status?.phase === "result" ? s.status.result : undefined));
  const next = secondsLeft(useCasino((s) => s.status?.next_in), useCasino((s) => s.at));
  if (!r) return null;
  const winners = r.winners ?? [];
  return (
    <div className="cz-result" key={r.round}>
      <span className="cz-result-tile" style={{ background: TONE[r.tone ?? ""] ?? "#3a3a46" }}>{r.label ?? "?"}</span>
      <span className="min-w-0 flex-1">
        <b>{winners.length ? (winners.length === 1 ? `${winners[0].name} wins` : `${winners.length} winners`) : "House wins"}</b>
        <span className="truncate">{winners.length ? winners.slice(0, 4).map((w) => `${w.name} +${fmt(w.net)}`).join(" · ") : "No winning bets this round"}{next != null ? ` · next in ${Math.ceil(next)}s` : ""}</span>
      </span>
    </div>
  );
}

// ------------------------------------------------------------------ lobby strip
function LobbyStrip({ app }: { app: string }) {
  useLobbyPoll();
  const lobby = lobbyFor(useStore((s) => s.lobby), app);
  const waiting = useCasino((s) => !!s.status?.lobby);
  const phones = useCasino((s) => (s.players ?? s.status?.players ?? []).filter((p) => p.online && typeof p.seat === "number").length);
  const [big, setBig] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const run = async (f: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await f();
    } catch {
      /* toasted */
    } finally {
      setBusy(false);
    }
  };
  if (!lobby)
    return (
      <div className="cz-lobby">
        <Smartphone size={16} className="shrink-0 text-[#ffcc33]" />
        <span className="min-w-0 flex-1 text-[12px] leading-snug text-ink-2">Friends join from their phones — up to 8 seats.</span>
        <button className="cz-gold" disabled={busy} onClick={() => run(() => openCasinoLobby(app))}><QrIcon size={14} /> Open the room</button>
      </div>
    );
  const copy = async () => {
    if (lobby.url && (await copyText(lobby.url))) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    }
  };
  return (
    <div className="cz-lobby">
      {lobby.url && (
        <button className="cz-qr" onClick={() => setBig(true)} title="Show the QR code bigger">
          <QrCode text={lobby.url} size={58} />
        </button>
      )}
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className="engrave !text-[8px]">Room</span>
          <b className="font-mono text-[18px] tracking-[0.24em] text-[#ffcc33]">{lobby.code}</b>
          <span className="text-[11px] text-ink-3">{phones}/{lobby.max_players - 1} phones</span>
        </span>
        <button className="block max-w-full truncate font-mono text-[10.5px] text-ink-3 hover:text-ink-1" onClick={copy} title="Copy the join address">
          {lobby.url?.replace(/^https?:\/\//, "")} {copied ? "✓" : ""}
        </button>
        {!lobby.lan_ready && <span className="block text-[10.5px] text-[#ff6b8a]">Phones can't reach this computer: set host = "0.0.0.0" in deskdot.toml.</span>}
      </span>
      {waiting && <button className="key !h-8" disabled={busy} onClick={() => run(hideCasinoQr)} title="Hide the QR on the panel and show the table (phones can still join with the code)">Hide QR</button>}
      <button className="key key-icon !h-8 !w-8" disabled={busy} onClick={() => run(closeCasinoLobby)} title="Close the room and disconnect the phones (wallets are kept)"><X size={14} /></button>
      {big && lobby.url && (
        <div className="cz-qrbig" role="dialog" aria-label="Join QR code" onClick={() => setBig(false)} onKeyDown={(e) => e.key === "Escape" && setBig(false)}>
          <div onClick={(e) => e.stopPropagation()}>
            <QrCode text={lobby.url} size={280} />
            <b className="font-mono text-[30px] tracking-[0.3em] text-[#ffcc33]">{lobby.code}</b>
            <span className="text-[12px] text-ink-2">Scan with a phone camera, or open {lobby.url.replace(/^https?:\/\//, "")}</span>
            <button className="key" autoFocus onClick={() => setBig(false)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ wing resize
function WingSplit({ side }: { side: "left" | "right" }) {
  const [drag, setDrag] = useState(false);
  const start = useRef<{ x: number; mine: number; total: number } | null>(null);
  const measure = (el: HTMLElement) => {
    const row = el.parentElement;
    const l = row?.querySelector<HTMLElement>(":scope > .cz-wing-l");
    const r = row?.querySelector<HTMLElement>(":scope > .cz-wing-r");
    if (!l || !r) return null;
    const wl = l.getBoundingClientRect().width, wr = r.getBoundingClientRect().width;
    return { mine: side === "left" ? wl : wr, total: wl + wr };
  };
  const apply = (mine: number, total: number) => {
    const min = Math.min(270, total * 0.3);
    const m = Math.max(min, Math.min(total - min, mine));
    const a = (m / total) * 2, b = 2 - a;
    if (side === "left") saveWings(a, b);
    else saveWings(b, a);
  };
  return (
    <div className="cz-split" data-drag={drag || undefined} role="separator" aria-orientation="vertical" tabIndex={0}
      aria-label={side === "left" ? "Casino settings width" : "Players width"} title="Drag to resize · double-click to even out"
      onDoubleClick={() => saveWings(1, 1)}
      onKeyDown={(e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const m = measure(e.currentTarget);
        if (!m) return;
        const dx = (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 80 : 24);
        apply(m.mine + (side === "left" ? dx : -dx), m.total);
      }}
      onPointerDown={(e) => {
        const m = measure(e.currentTarget);
        if (!m) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        start.current = { x: e.clientX, ...m };
        setDrag(true);
      }}
      onPointerMove={(e) => {
        const s = start.current;
        if (s) apply(s.mine + (side === "left" ? e.clientX - s.x : s.x - e.clientX), s.total);
      }}
      onPointerUp={() => { start.current = null; setDrag(false); }}
      onPointerCancel={() => { start.current = null; setDrag(false); }}>
      <span />
    </div>
  );
}

// ------------------------------------------------------------------ the panel, framed
function Table({ side, hot }: { side: number; hot: boolean }) {
  const power = useStore((s) => s.state?.settings.power ?? true);
  const pad = Math.round(Math.max(18, side * 0.05));
  return (
    <div className="cz-table" style={{ width: side + pad * 2, height: side + pad * 2, padding: pad }}>
      <Marquee w={side + pad * 2} h={side + pad * 2} hot={hot} />
      <div className="bezel cz-bezel" style={{ width: side, height: side }}>
        <div className={clsx("relative h-full w-full transition-opacity duration-500", !power && "opacity-15")}>
          <LedPanel />
        </div>
      </div>
    </div>
  );
}

function PreviewNotice({ app }: { app: string }) {
  const view = useCasino((s) => s.status?.view);
  if (!view || view === "live") return null;
  return (
    <div className="cz-notice">
      The panel shows a preview (<b>{view}</b>), not the live table.
      <button className="cz-gold !h-7" onClick={() => api.patchSettings(app, { view: "live" }).catch(() => undefined)}>Play live</button>
    </div>
  );
}

/** Casino mode: replaces the stage while a casino game is on the panel (docs/CASINO.md §6, docs/STUDIO_UI.md). */
export function CasinoStage() {
  const app = useCasinoApp();
  useCasinoFeed(app);
  const entered = useCasino((s) => s.entered);
  const wl = useCasino((s) => s.wingL);
  const wr = useCasino((s) => s.wingR);
  const tab = useCasino((s) => s.tab);
  const setC = useCasino((s) => s.set);
  const hot = useCasino((s) => s.status?.phase === "result" && !!s.status.result?.winners?.length);
  const me = useCasino((s) => s.me);
  const root = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState(() => ({ w: window.innerWidth - 24, h: window.innerHeight - 220 }));
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setBox({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  if (!app) return null;
  const wide = box.w >= 980;
  const name = appMeta(app)?.name ?? app;
  // the panel: as big as the height allows, but the wings keep at least ~30 % each
  const side = wide
    ? Math.floor(Math.max(220, Math.min(box.h - 262, box.w * 0.34, 760)))
    : Math.floor(Math.max(200, Math.min(box.w - 56, 380, box.h > 0 ? box.h * 0.5 : 380)));
  const centre = (
    <div className="cz-centre" style={wide ? { width: Math.max(side + Math.round(Math.max(18, side * 0.05)) * 2 + 8, 430) } : undefined}>
      <div className="cz-title">
        <span className="cz-title-name">{name}</span>
        <RoundInfo />
        {me.seated && <span className="cz-title-me">You <Credits value={me.credits ?? 0} /></span>}
        <button className="cz-leave" onClick={leaveCasino} title="Back to the normal studio (the table keeps running)" aria-label="Leave casino"><DoorOpen size={13} /> <span className="cz-lbl">Leave casino</span></button>
      </div>
      <HostBar />
      <PreviewNotice app={app} />
      <div className="relative grid place-items-center">
        <Table side={side} hot={hot} />
      </div>
      <LobbyStrip app={app} />
    </div>
  );
  return (
    <div ref={root} className="cz" data-wide={wide || undefined}>
      <ChipCascade run={entered} />
      {wide ? (
        <div className="cz-row3">
          <aside className="cz-wing cz-wing-l" style={{ flex: `${wl} 1 0%` }} aria-label="Casino settings"><LeftWing /></aside>
          <WingSplit side="left" />
          {centre}
          <WingSplit side="right" />
          <aside className="cz-wing cz-wing-r" style={{ flex: `${wr} 1 0%` }} aria-label="Players"><RightWing /></aside>
        </div>
      ) : (
        <div className="cz-stack">
          {centre}
          <Tabs label="Casino" value={tab === "house" ? "house" : "players"} onChange={(t) => setC({ tab: t })}
            options={[["players", "Players"], ["house", "House & rules"]]} />
          <div className="cz-wing cz-wing-tab">{tab === "house" ? <LeftWing /> : <RightWing />}</div>
        </div>
      )}
    </div>
  );
}
