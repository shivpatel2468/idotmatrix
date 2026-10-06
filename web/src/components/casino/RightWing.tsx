import clsx from "clsx";
import { Ban, Check, ChevronDown, CircleCheck, CircleX, Crown, Hand, Medal, RotateCcw, ShieldCheck, Undo2, UserCheck, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { sfx } from "../../lib/sound";
import { toast } from "../../lib/store";
import { casinoAlert } from "./alert";
import { AvatarPix, Chip, Credits, NumberInput, Section, Tabs } from "./bits";
import { type Pt, bump, centerOf, chipEl, drop, fly, perFrame, placeGhost, primary, stackShadow } from "./chipfx";
import { chipLabel, rackOf } from "./chips";
import { type GridBox, type Hit, LineChips, gridBox, rouletteHit, toClient, anchorOf } from "./roulette";
import {
  type HistoryEntry, type PlayerRow, type Spot, type SpotBettor, TONE, casinoOp, fmt, seatLabel, short, useCasino, verifyRound,
} from "./state";

const BET_OPS = new Set(["bet", "unbet", "clear", "rebet", "done"]);

const seatOrder = (p: PlayerRow) => (p.seat === "host" ? 0 : typeof p.seat === "number" && p.seat > 0 ? p.seat : 99);
const target = (p: PlayerRow): Record<string, unknown> | null =>
  p.pid ? { pid: p.pid } : p.seat === "host" || (typeof p.seat === "number" && p.seat > 0) ? { seat: p.seat } : null;

function usePlayers(): PlayerRow[] {
  const host = useCasino((s) => s.players);
  const pub = useCasino((s) => s.status?.players);
  return host ?? pub ?? [];
}

// ------------------------------------------------------------------ seats
function SeatCard({ p, betting, done }: { p: PlayerRow; betting: boolean; done: boolean }) {
  const [open, setOpen] = useState(false);
  const t = target(p);
  const credit = (body: Record<string, unknown>) => t && casinoOp("credits", { ...t, ...body }).catch(() => undefined);
  return (
    <div className={clsx("cz-seat", !p.online && "cz-seat-away", p.kicked && "cz-seat-kicked")} style={{ ["--c" as string]: p.color }}>
      <button className="cz-seat-main" onClick={() => setOpen((o) => !o)} aria-expanded={open} title="Credits, top-up and kick">
        <AvatarPix id={p.avatar} color={p.color} name={p.name} size={34} />
        <span className="min-w-0 flex-1 text-left">
          <span className="flex items-center gap-1.5">
            <b className="truncate">{p.name || "Player"}</b>
            {p.seat === "host" && <Crown size={11} className="shrink-0 text-[var(--gold)]" />}
          </span>
          <span className="cz-seat-sub">
            <span className="led !h-[6px] !w-[6px]" data-on={p.kicked ? "bad" : p.online ? "ok" : undefined} />
            {p.kicked ? "Off the table" : seatLabel(p.seat)}
            {betting && <span className="cz-tag !ml-0">{done ? "done" : "betting"}</span>}
          </span>
        </span>
        <span className="text-right">
          <Credits value={p.credits} className="cz-seat-credits" />
          <span className="cz-seat-sub justify-end">
            {p.staked > 0 && <span title="On the table (escrow)">⛁ {short(p.staked)}</span>}
            <span className={p.net > 0 ? "text-[#3ddc97]" : p.net < 0 ? "text-[#ff6b8a]" : ""} title="Net this session">{p.net > 0 ? "+" : ""}{short(p.net)}</span>
          </span>
        </span>
        <ChevronDown size={14} className={clsx("shrink-0 text-ink-4 transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="cz-seat-tools">
          <div className="flex flex-wrap items-center gap-1">
            {[100, 500, 1000].map((v) => (
              <button key={v} className="cz-pill" onClick={() => credit({ add: v })} disabled={!t}>+{fmt(v)}</button>
            ))}
            <button className="cz-pill" onClick={() => credit({ add: -100 })} disabled={!t || p.credits <= 0}>−100</button>
            <span className="ml-auto flex items-center gap-1">
              <span className="text-[10.5px] text-ink-3">Set</span>
              <NumberInput value={p.credits} min={0} max={1_000_000_000} width={84} label={`Set ${p.name}'s credits`}
                onCommit={(v) => credit({ set: v })} />
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-ink-3">
            <span>Biggest win <b className="text-ink-1">{fmt(p.biggest)}</b></span>
            <span>On the table <b className="text-ink-1">{fmt(p.staked)}</b></span>
            {p.seat !== "host" && t && (
              <button className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-[#ff8aa8] hover:bg-[#ff3f78]/10"
                onClick={() => casinoOp("kick", { ...t, on: !p.kicked }).catch(() => undefined)}>
                {p.kicked ? <><UserCheck size={12} /> Let back in</> : <><Ban size={12} /> Kick</>}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Everyone({ base }: { base: number }) {
  const [amt, setAmt] = useState(500);
  return (
    <div className="cz-everyone">
      <Users size={13} className="shrink-0 text-[var(--gold)]" />
      <span className="text-[11.5px] text-ink-2">Everyone</span>
      <NumberInput value={amt} min={0} max={1_000_000} width={74} onCommit={setAmt} label="Amount for everyone" />
      <button className="cz-pill" onClick={() => casinoOp("credits", { all: true, add: amt }).then(() => toast(`+${fmt(amt)} for everyone`, "ok")).catch(() => undefined)}>Add</button>
      <button className="cz-pill" onClick={() => casinoOp("credits", { all: true, set: amt }).then(() => toast(`Everyone set to ${fmt(amt)}`, "ok")).catch(() => undefined)}>Set</button>
      <button className="cz-pill" title="Everyone back to the starting credits" onClick={() => casinoOp("credits", { all: true, set: base }).catch(() => undefined)}>
        <RotateCcw size={11} /> {short(base)}
      </button>
    </div>
  );
}

function Seats() {
  const players = usePlayers();
  const bettors = useCasino((s) => s.status?.bettors);
  const done = useCasino((s) => s.status?.done);
  const phase = useCasino((s) => s.status?.phase);
  const base = useCasino((s) => s.status?.house?.base_credits ?? 1000);
  const rows = useMemo(() => [...players].sort((a, b) => seatOrder(a) - seatOrder(b) || b.credits - a.credits), [players]);
  const here = rows.filter((p) => p.online).length;
  return (
    <Section title="Players" hint={`${here} at the table${rows.length > here ? ` · ${rows.length - here} away` : ""}`}>
      {rows.length ? (
        <>
          <Everyone base={base} />
          <div className="flex flex-col gap-1.5">
            {rows.map((p, i) => (
              <SeatCard key={p.pid ?? `${p.seat}-${i}`} p={p} betting={phase === "betting" && !!bettors?.includes(p.seat as number)} done={!!done?.includes(p.seat as number)} />
            ))}
          </div>
        </>
      ) : (
        <p className="cz-empty">Nobody has sat down yet. Open the room under the panel — friends scan the QR code with their phones and get the starting credits.</p>
      )}
    </Section>
  );
}

function Ranking() {
  const players = usePlayers();
  const rows = useMemo(() => [...players].sort((a, b) => b.credits + b.staked - (a.credits + a.staked)), [players]);
  const medal = ["#ffcc33", "#d6dbe4", "#e08a4a"];
  return (
    <Section title="Leaderboard" hint="Credits plus chips on the table, across every casino game.">
      {rows.length ? (
        <ol className="flex flex-col gap-1">
          {rows.map((p, i) => (
            <li key={p.pid ?? `${p.seat}-${i}`} className="cz-rank" data-top={i < 3 || undefined} style={{ ["--c" as string]: p.color, ["--m" as string]: medal[i] ?? "transparent" }}>
              <span className="cz-rank-n">{i < 3 ? <Medal size={14} style={{ color: medal[i] }} /> : i + 1}</span>
              <AvatarPix id={p.avatar} color={p.color} name={p.name} size={26} />
              <span className="min-w-0 flex-1 truncate text-[12.5px]">{p.name}{!p.online && <span className="text-ink-4"> · away</span>}</span>
              <span className={clsx("w-14 text-right font-mono text-[10.5px]", p.net > 0 ? "text-[#3ddc97]" : p.net < 0 ? "text-[#ff6b8a]" : "text-ink-3")}>{p.net > 0 ? "+" : ""}{short(p.net)}</span>
              <Credits value={p.credits + p.staked} className="w-20 text-right font-display text-[15px] font-[650]" />
            </li>
          ))}
        </ol>
      ) : (
        <p className="cz-empty">The leaderboard fills in as players join.</p>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------ rounds + verify
function describe(o: unknown): string {
  if (!o || typeof o !== "object") return String(o ?? "—");
  return Object.entries(o as Record<string, unknown>)
    .filter(([, v]) => v == null || typeof v !== "object" || Array.isArray(v))
    .map(([k, v]) => `${k} ${Array.isArray(v) ? v.join("·") : String(v)}`)
    .join(" · ")
    .slice(0, 120);
}

function Round({ h }: { h: HistoryEntry }) {
  const [open, setOpen] = useState(false);
  const v = useCasino((s) => s.verify[h.round]);
  const pr = h.proof;
  return (
    <li className="cz-round">
      <button className="flex w-full items-center gap-2.5 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="cz-round-n">#{h.round}</span>
        <span className="cz-round-tile" style={{ background: TONE[h.tone ?? ""] ?? "#3a3a46" }}>{h.label ?? "?"}</span>
        <span className="min-w-0 flex-1 truncate text-[11px] text-ink-3">{describe(h.outcome)}</span>
        {v && v !== "busy" && (v.ok ? <CircleCheck size={14} className="text-[#3ddc97]" /> : <CircleX size={14} className="text-[#ff3f78]" />)}
        <ChevronDown size={13} className={clsx("text-ink-4 transition", open && "rotate-180")} />
      </button>
      {open && pr && (
        <div className="cz-proof">
          <dl>
            <dt>Hash (shown before bets)</dt><dd>{pr.hash}</dd>
            <dt>Server seed (revealed)</dt><dd>{pr.server_seed ?? "—"}</dd>
            <dt>Client seed</dt><dd>{pr.client_seed || "deskdot"}</dd>
            <dt>Nonce</dt><dd>{pr.nonce}</dd>
          </dl>
          <div className="flex items-center gap-2">
            <button className="cz-gold !h-8" disabled={v === "busy" || !pr.server_seed} onClick={() => verifyRound(h.round, pr)}>
              <ShieldCheck size={13} /> {v === "busy" ? "Checking…" : "Verify"}
            </button>
            {v && v !== "busy" && (
              <span className={clsx("text-[11.5px] font-[600]", v.ok ? "text-[#3ddc97]" : "text-[#ff6b8a]")}>{v.ok ? "Fair — it all checks out" : v.error ?? "Mismatch"}</span>
            )}
          </div>
          {v && v !== "busy" && (
            <ul className="cz-checks">
              <li data-ok={v.hash_ok}>SHA-256(server seed) matches the hash committed before betting {v.hash_ok ? "✓" : "✗"}</li>
              {v.local != null && <li data-ok={v.local}>Re-hashed in this browser too {v.local ? "✓" : "✗"}</li>}
              <li data-ok={v.matches}>Recomputed outcome: <b>{describe(v.outcome)}</b> {v.matches ? "= what was paid ✓" : "≠ recorded ✗"}</li>
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

function Rounds() {
  const hist = useCasino((s) => s.status?.history);
  const rows = useMemo(() => [...(hist ?? [])].reverse(), [hist]);
  return (
    <Section title="Round history" hint="Every round is provably fair: the seed's hash is shown before any bet.">
      {rows.length ? <ul className="flex flex-col gap-1">{rows.map((h) => <Round key={h.round} h={h} />)}</ul>
        : <p className="cz-empty">Finished rounds appear here with their fairness proof.</p>}
    </Section>
  );
}

// ------------------------------------------------------------------ the host's own seat
function isRoulette(spots: Spot[]) {
  return spots.filter((s) => s.kind === "straight" && /^\d+$/.test(s.label)).length >= 36;
}

function SpotButton({ s, mine, total, who, onBet, onUnbet, onPress, disabled, className, style, num }: {
  s: Spot; mine: number; total: number; who?: SpotBettor[]; onBet: (e: React.MouseEvent) => void; onUnbet?: () => void;
  onPress?: (e: React.PointerEvent) => void; disabled: boolean; className?: string; style?: React.CSSProperties; num?: number;
}) {
  // who is on this spot (status.spot_bets): the same dots, in the same order, as every phone shows
  const list = who ?? [];
  const names = list.map((w) => `${w.name} ${fmt(w.amount)}`).join(" · ");
  return (
    <button className={clsx("cz-spot", className)} disabled={disabled} style={style} data-spot={s.id} data-num={num}
      title={`${s.label} · pays ${s.pays}${total ? ` · table ${fmt(total)}` : ""}${names ? `\n${names}` : ""}\nClick: add a chip · drag a chip here from the rack · right-click or drag your stack off: take it back`}
      onClick={onBet} onPointerDown={onPress} onContextMenu={onUnbet ? (e) => { e.preventDefault(); onUnbet(); } : undefined}>
      <span className="cz-spot-l">{s.label}</span>
      <span className="cz-spot-p">{s.pays}</span>
      {mine > 0 && <span className="cz-spot-mine" style={{ boxShadow: stackShadow(mine) }}>{chipLabel(mine)}</span>}
      {list.length > 0 ? (
        <span className="cz-spot-who" aria-label={names}>
          {list.slice(0, 4).map((w) => <i key={String(w.seat)} style={{ background: w.color }} data-host={w.seat === "host" || undefined} />)}
          {list.length > 4 && <b>+{list.length - 4}</b>}
          {total > mine && <b>{chipLabel(total)}</b>}
        </span>
      ) : !mine && total > 0 && <span className="cz-spot-total" />}
    </button>
  );
}

/** Card games: the host seat's own cards, whatever shape the game sends (strings like "AS", {rank, suit}, hands). */
const SUIT: Record<string, string> = { S: "♠", H: "♥", D: "♦", C: "♣", s: "♠", h: "♥", d: "♦", c: "♣" };
function cardText(c: unknown): string {
  if (typeof c === "string") return c.length <= 3 && SUIT[c.slice(-1)] ? c.slice(0, -1).replace("T", "10") + SUIT[c.slice(-1)] : c;
  if (c && typeof c === "object") {
    const o = c as Record<string, unknown>;
    if (o.rank != null) return `${String(o.rank).replace("T", "10")}${SUIT[String(o.suit ?? "")] ?? String(o.suit ?? "")}`;
    if (Array.isArray(o.cards)) return o.cards.map(cardText).join(" ");
  }
  return String(c ?? "");
}
function MyCards({ me }: { me: Record<string, unknown> }) {
  const hands: [string, unknown[]][] = [];
  for (const k of ["hole", "cards", "hand"]) if (Array.isArray(me[k]) && (me[k] as unknown[]).length) hands.push([k, me[k] as unknown[]]);
  if (Array.isArray(me.hands)) (me.hands as unknown[]).forEach((h, i) => {
    const cards = Array.isArray(h) ? h : (h as Record<string, unknown>)?.cards;
    if (Array.isArray(cards)) hands.push([`hand ${i + 1}`, cards]);
  });
  if (!hands.length) return null;
  return (
    <div className="cz-mycards">
      {hands.map(([k, cards]) => (
        <div key={k} className="flex items-center gap-1.5">
          <span className="engrave w-12 !text-[8px]">{k}</span>
          {cards.map((c, i) => {
            const t = cardText(c);
            return <span key={i} className="cz-card" data-red={/[♥♦]/.test(t) || undefined}>{t}</span>;
          })}
        </div>
      ))}
    </div>
  );
}

const RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);

function Play() {
  const me = useCasino((s) => s.me);
  const spots = useCasino((s) => s.spots);
  const st = useCasino((s) => s.status);
  const [chip, setChip] = useState<number | "all">(25);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const undo = useRef<[string, number][]>([]);
  const house = st?.house;
  // the rack: only the chips this table allows (status.chips from the engine, else the same ladder rack computed here)
  const rack = useMemo(() => rackOf(st?.chips, house?.min_bet, house?.max_bet), [st?.chips, house?.min_bet, house?.max_bet]);
  useEffect(() => {
    if (chip !== "all" && rack.length && !rack.some((c) => c.v === chip)) setChip(rack[0].v);
  }, [rack, chip]);
  const credits = me.seated ? (me.credits ?? 0) : (house?.base_credits ?? 0);
  const betting = st?.phase === "betting";
  const amount = chip === "all" ? credits : chip;
  const bets = me.bets ?? {};
  const totals = st?.totals ?? {};
  const who = st?.spot_bets ?? {};
  const gameOps = (me.ops ?? []).filter((o) => !BET_OPS.has(o));
  const roulette = isRoulette(spots);
  const us = roulette && spots.some((s) => s.id === "n:00");
  const byId = useMemo(() => Object.fromEntries(spots.map((s) => [s.id, s])), [spots]);

  // ---- chip flights (chipfx.ts): the same feel as the phones
  const rackRef = useRef<HTMLDivElement>(null);
  const boardRef = useRef<HTMLDivElement>(null);
  const wheelRef = useRef<HTMLDivElement>(null);
  const numsRef = useRef<HTMLDivElement>(null);
  const zerosRef = useRef<HTMLDivElement>(null);
  const spotEl = (id: string) => boardRef.current?.querySelector<HTMLElement>(`[data-spot="${CSS.escape(id)}"]`) ?? null;
  const box = (): GridBox | null => (roulette ? gridBox(numsRef.current, zerosRef.current) : null);
  const spotPoint = (id: string): Pt | null => {
    const el = spotEl(id);
    const badge = el?.querySelector(".cz-spot-mine");
    if (badge) return centerOf(badge);
    const a = roulette ? anchorOf(id, us) : null;
    const b = a && box();
    return a && b ? toClient(b, a) : centerOf(el);
  };
  const rackPoint = (): Pt | null => centerOf(rackRef.current?.querySelector("[data-active]") ?? rackRef.current);
  const bumpWant = useRef<Record<string, number>>({});
  const land = (id: string) => {
    sfx("chip", { pan: 0.2 });
    const b = spotEl(id)?.querySelector(".cz-spot-mine");
    if (b) bump(b);
    else bumpWant.current[id] = performance.now(); // the new stack is still on its way from the engine
  };
  useEffect(() => {
    for (const [id, t] of Object.entries(bumpWant.current)) {
      const b = spotEl(id)?.querySelector(".cz-spot-mine");
      if (b && performance.now() - t < 900) bump(b);
      if (b || performance.now() - t >= 900) delete bumpWant.current[id];
    }
  }, [bets]); // eslint-disable-line react-hooks/exhaustive-deps

  const bet = (id: string, from?: Pt) => {
    if (!betting) return casinoAlert(st?.phase === "idle" ? "The table is closed — press Start round" : "Bets are closed");
    if (amount <= 0) return casinoAlert("Not enough credits");
    const amt = amount;
    undo.current.push([id, amt]);
    const to = spotPoint(id);
    fly(amt, from ?? rackPoint(), to, { s0: from ? 1.3 : 1.2, s1: 0.8, done: () => land(id) });
    casinoOp("bet", { spot: id, amount: amt }).catch(() => {
      // rejected (the centred alert says why): drop it from the undo list and send the chip home
      for (let i = undo.current.length - 1; i >= 0; i--) if (undo.current[i][0] === id && undo.current[i][1] === amt) { undo.current.splice(i, 1); break; }
      window.setTimeout(() => fly(amt, to, live.current.rackPoint(), { s0: 0.8, s1: 1.1, fade: true, ms: 320 }), 140);
    });
  };
  const unbet = (id: string, amt?: number, from?: Pt) => {
    const m = amt ?? bets[id] ?? 0;
    casinoOp("unbet", amt ? { spot: id, amount: amt } : { spot: id }).catch(() => undefined);
    sfx("chips-stack", { volume: 0.55 });
    if (m) fly(m, from ?? spotPoint(id), rackPoint(), { s0: from ? 1.3 : 0.85, s1: 1.1, fade: true });
  };
  const op = (o: string, extra: Record<string, unknown> = {}) => casinoOp(o, extra).catch(() => undefined);
  const clearAll = () => {
    undo.current = [];
    Object.entries(bets).forEach(([id, m], i) => window.setTimeout(() => fly(m, spotPoint(id), rackPoint(), { s0: 0.85, s1: 1.1, fade: true }), i * 45));
    sfx("chips-stack", { volume: 0.6 });
    op("clear");
  };
  const rebet = () => {
    const last = Object.entries(me.last_bets ?? {});
    undo.current = last.map(([id, m]): [string, number] => [id, m]);
    last.forEach(([id, m], i) => window.setTimeout(() => fly(m, rackPoint(), spotPoint(id), { s0: 1.2, s1: 0.8, done: () => land(id) }), i * 70));
    op("rebet");
  };

  // ---- where a point lands: on the roulette grid by geometry (roulette.tsx: straight / split / corner / street /
  // six line …), elsewhere the spot under it. `cover` = what lights up: every number the bet covers.
  type Target = { id: string; at: Pt | null; cover: Element[] };
  const coverOf = (id: string, self?: Element | null): Element[] => {
    const sp = byId[id];
    const w = wheelRef.current;
    const out: Element[] = self ? [self] : [];
    if (!sp || !w || !roulette) return out;
    for (const n of sp.numbers) {
      const c = w.querySelector(`[data-num="${n}"]`);
      if (c && c !== self) out.push(c);
    }
    const line = w.querySelector(`.cz-linechip[data-spot="${CSS.escape(id)}"]`);
    if (line) out.push(line);
    return out;
  };
  const resolve = (x: number, y: number, b: GridBox | null): Target | null => {
    if (roulette && b) {
      const h: Hit | null = rouletteHit(b, x, y, (id) => id in byId, us);
      if (h) return { id: h.id, at: toClient(b, h), cover: coverOf(h.id) };
    }
    const z = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-spot]");
    if (!z || !boardRef.current?.contains(z) || z.classList.contains("cz-linechip")) return null;
    return { id: z.dataset.spot!, at: null, cover: coverOf(z.dataset.spot!, z) };
  };

  // ---- drag a chip from the rack onto the table, or a stack off its spot (pointer events: mouse, pen, touch).
  // Moves are rAF-throttled and only move the ghost (a transform); the grid's rects are read once per gesture; the
  // pointer is captured by the pressed element once the drag really starts (a plain click stays a click).
  type Drag = {
    kind: "rack" | "stack"; pid: number; x0: number; y0: number; v: number | "all"; spot?: string; el: Element;
    dy: number; ghost?: HTMLDivElement; box?: GridBox | null;
  };
  const drag = useRef<Drag | null>(null);
  const lit = useRef<Element[]>([]);
  const noClickUntil = useRef(0); // the click that ends a drag must not bet again
  const amountOf = (v: number | "all") => (v === "all" ? credits : Math.min(v, credits));
  const live = useRef({ bet, unbet, spotPoint, rackPoint, amountOf, betting, resolve, box });
  live.current = { bet, unbet, spotPoint, rackPoint, amountOf, betting, resolve, box };
  const light = (els: Element[]) => {
    const prev = lit.current;
    if (prev.length === els.length && prev.every((e, i) => e === els[i])) return;
    for (const e of prev) if (!els.includes(e)) e.classList.remove("cz-dd-on");
    for (const e of els) e.classList.add("cz-dd-on");
    lit.current = els;
  };
  const startDrag = (d: Drag) => {
    drag.current = d;
    const move = perFrame((e: PointerEvent) => {
      const g = drag.current;
      if (!g || e.pointerId !== g.pid) return;
      const L = live.current;
      if (!g.ghost) {
        if (Math.hypot(e.clientX - g.x0, e.clientY - g.y0) < (g.kind === "rack" ? 5 : 7) || !L.betting) return;
        if (g.kind === "rack") setChip(g.v);
        g.ghost = chipEl(g.kind === "rack" ? L.amountOf(g.v) : g.v, { ghost: true });
        g.box = L.box();
        try {
          (g.el as HTMLElement).setPointerCapture(g.pid);
        } catch {
          /* the element went away: the document listeners still follow the pointer */
        }
        sfx("click", { volume: 0.5 });
      }
      const p: Pt = [e.clientX, e.clientY - g.dy];
      const t = L.resolve(p[0], p[1], g.box ?? null);
      const gp = t?.at ?? p; // the ghost snaps to the line / intersection it will land on
      placeGhost(g.ghost, gp[0], gp[1]);
      if (g.kind === "stack") {
        const home = t?.id === g.spot;
        g.ghost.classList.toggle("rm", !home);
        light(home && t ? t.cover : []);
      } else light(t?.cover ?? []);
    });
    const end = (e: PointerEvent) => {
      const g = drag.current;
      if (!g || e.pointerId !== g.pid) return;
      drag.current = null;
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", end);
      light([]);
      try {
        (g.el as HTMLElement).releasePointerCapture(g.pid);
      } catch {
        /* not captured */
      }
      if (!g.ghost) return; // a plain click: the click handlers take it
      noClickUntil.current = performance.now() + 400;
      g.ghost.remove();
      const L = live.current;
      const p: Pt = [e.clientX, e.clientY - g.dy];
      const t = e.type === "pointerup" ? L.resolve(p[0], p[1], g.box ?? null) : null;
      const from = t?.at ?? p;
      if (g.kind === "rack") {
        if (t) L.bet(t.id, from);
        else fly(L.amountOf(g.v), p, L.rackPoint(), { s0: 1.3, s1: 1.2, fade: true, ms: 260 });
      } else if (e.type === "pointerup" && t?.id !== g.spot) L.unbet(g.spot!, undefined, p);
      else fly(g.v, from, L.spotPoint(g.spot!), { s0: 1.3, s1: 0.8, ms: 220 });
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", end);
    document.addEventListener("pointercancel", end);
  };
  // a finger hides what's under it: on touch the chip lands a little above the fingertip; a mouse lands at the tip
  const lift = (e: React.PointerEvent) => (e.pointerType === "touch" ? 34 : 0);
  const onRackDown = (e: React.PointerEvent) => {
    const b = (e.target as HTMLElement).closest<HTMLElement>(".cz-chip[data-v]");
    if (!b || !primary(e) || drag.current) return;
    if (e.pointerType === "mouse") e.preventDefault(); // no text selection while dragging
    const v = b.dataset.v === "all" ? "all" : Number(b.dataset.v);
    startDrag({ kind: "rack", pid: e.pointerId, x0: e.clientX, y0: e.clientY, v, el: b, dy: lift(e) });
  };
  const onSpotDown = (id: string) => (e: React.PointerEvent) => {
    const m = bets[id] ?? 0;
    if (!m || !betting || !primary(e) || drag.current) return;
    if (e.pointerType === "mouse") e.preventDefault();
    startDrag({ kind: "stack", pid: e.pointerId, x0: e.clientX, y0: e.clientY, v: m, spot: id, el: e.currentTarget, dy: lift(e) });
  };
  // the roulette grid handles its own pointer: a click / right-click / press anywhere on it — a number, a line, an
  // intersection, the outer edge — resolves by geometry
  const gridDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!primary(e)) return;
    if (e.pointerType === "mouse") e.preventDefault();
    if (drag.current || !betting) return;
    const t = resolve(e.clientX, e.clientY, box());
    const m = t ? (bets[t.id] ?? 0) : 0;
    if (t && m > 0) startDrag({ kind: "stack", pid: e.pointerId, x0: e.clientX, y0: e.clientY, v: m, spot: t.id, el: e.currentTarget, dy: lift(e) });
  };
  const gridClick = (e: React.MouseEvent) => {
    if (e.detail === 0) return; // the keyboard: the focused number's own button bets
    if (performance.now() < noClickUntil.current) return;
    const t = resolve(e.clientX, e.clientY, box());
    if (t) bet(t.id);
  };
  const gridMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const t = resolve(e.clientX, e.clientY, box());
    if (t && bets[t.id]) unbet(t.id, typeof chip === "number" ? chip : undefined);
  };

  // ---- other players' chips drop onto their spot in their colour (status.spot_bets going up)
  const seen = useRef<{ round: unknown; amt: Record<string, number> } | null>(null);
  useEffect(() => {
    const key = (id: string, seat: unknown) => `${id}|${String(seat)}`;
    const amt: Record<string, number> = {};
    for (const [id, list] of Object.entries(who)) for (const w of list ?? []) if (w.seat !== "host") amt[key(id, w.seat)] = w.amount;
    const prev = seen.current;
    seen.current = { round: st?.round, amt };
    if (!prev || prev.round !== st?.round || !betting) return;
    let n = 0;
    for (const [id, list] of Object.entries(who)) {
      for (const w of list ?? []) {
        if (w.seat === "host" || n >= 12) continue;
        const d = w.amount - (prev.amt[key(id, w.seat)] ?? 0);
        if (d <= 0) continue;
        n++;
        window.setTimeout(() => drop(w.color, d, spotPoint(id), () => bump(spotEl(id))), n * 40);
      }
    }
  }, [who]); // eslint-disable-line react-hooks/exhaustive-deps

  const btn = (s: Spot, cls?: string, style?: React.CSSProperties) => (
    <SpotButton key={s.id} s={s} mine={bets[s.id] ?? 0} total={totals[s.id] ?? 0} who={who[s.id]} disabled={!betting}
      onBet={() => { if (performance.now() >= noClickUntil.current) bet(s.id); }}
      onUnbet={() => unbet(s.id, typeof chip === "number" ? chip : undefined)} onPress={onSpotDown(s.id)} className={cls} style={style} />
  );
  /** A number on the roulette grid: the grid takes pointer clicks (geometry); the button keeps the keyboard. */
  const cell = (s: Spot, cls: string) => (
    <SpotButton key={s.id} s={s} mine={bets[s.id] ?? 0} total={totals[s.id] ?? 0} who={who[s.id]} disabled={!betting}
      onBet={(e) => { if (e.detail === 0) bet(s.id); }} className={cls} num={s.numbers[0]} />
  );

  const groups = useMemo(() => {
    const g: [string, Spot[]][] = [];
    for (const s of spots) {
      const e = g.find(([k]) => k === s.kind);
      if (e) e[1].push(s);
      else g.push([s.kind, [s]]);
    }
    return g;
  }, [spots]);
  const lineSpots = useMemo(() => (roulette ? spots.filter((s) => s.kind !== "straight" && anchorOf(s.id, us)) : []), [spots, roulette, us]);

  let board: React.ReactNode;
  if (!spots.length && !gameOps.length) board = <p className="cz-empty">This table has no bets to place right now.</p>;
  else if (roulette) {
    // American: 00 sits beside 3 (top), 0 beside 1 (bottom) — the engine's 0/1, 0/2, 00/2, 00/3 splits
    const zeros = spots.filter((s) => s.kind === "straight" && (s.label === "0" || s.label === "00")).sort((a, b) => b.label.length - a.label.length);
    const num = (n: number) => byId[`n:${n}`];
    const outside = groups.filter(([k]) => ["dozen", "column", "red", "black", "odd", "even", "low", "high"].includes(k)).flatMap(([, v]) => v);
    const inside = groups.filter(([k]) => !["straight", "dozen", "column", "red", "black", "odd", "even", "low", "high"].includes(k));
    board = (
      <>
        <div ref={wheelRef} className="cz-wheelgrid" onPointerDown={gridDown} onClick={gridClick} onContextMenu={gridMenu}
          title="Click or drop a chip on a number, a line (split), a crossing (corner) or the outer edge (street / six line) · right-click or drag your stack off: take it back">
          <div ref={zerosRef} className="cz-zeros">{zeros.map((s) => cell(s, "cz-n cz-n-g"))}</div>
          <div ref={numsRef} className="cz-nums">
            {[3, 2, 1].map((r) => Array.from({ length: 12 }, (_, c) => num(c * 3 + r)).filter(Boolean).map((s) => cell(s!, clsx("cz-n", RED.has(+s!.label) ? "cz-n-r" : "cz-n-b"))))}
            <LineChips spots={lineSpots} bets={bets} totals={totals} who={who} us={us} />
          </div>
        </div>
        <div className="cz-outside">{outside.map((s) => btn(s, "cz-out"))}</div>
        {inside.map(([k, list]) => (
          <details key={k} className="cz-group" open={!!open[k]} onToggle={(e) => setOpen((o) => ({ ...o, [k]: (e.target as HTMLDetailsElement).open }))}>
            <summary>{k.replace(/_/g, " ")} <span>{list.length} bets · {list[0].pays}</span></summary>
            <div className="cz-spots">{list.map((s) => btn(s))}</div>
          </details>
        ))}
      </>
    );
  } else {
    board = groups.length <= 1 || spots.length <= 8 ? (
      <div className="cz-spots cz-spots-big">{spots.map((s) => btn(s))}</div>
    ) : (
      groups.map(([k, list]) => (
        <div key={k} className="mb-2">
          <div className="engrave mb-1 !text-[8.5px]">{k.replace(/_/g, " ")}</div>
          <div className="cz-spots">{list.map((s) => btn(s))}</div>
        </div>
      ))
    );
  }

  return (
    <Section title="Play from this laptop" hint="You sit in the host seat with your own wallet — the same bets the phones place."
      right={<span className="text-right"><span className="engrave block !text-[8px]">Your credits</span><Credits value={credits} className="font-display text-[18px] font-[700] text-[var(--gold)]" /></span>}>
      {me.result && st?.phase === "result" && (
        <div className={clsx("cz-myresult", me.result.net > 0 ? "cz-win" : me.result.net < 0 && "cz-lose")}>
          {me.result.net > 0 ? `You won ${fmt(me.result.net)}` : me.result.net < 0 ? `You lost ${fmt(-me.result.net)}` : "Push — stake returned"}
        </div>
      )}
      <MyCards me={me} />
      <div ref={rackRef} className="cz-rack" role="radiogroup" aria-label="Chip" onPointerDown={onRackDown}>
        {rack.map((c) => <Chip key={c.v} value={c.v} chip={c} active={chip === c.v} onClick={() => setChip(c.v)} title={`${fmt(c.v)} credits`} />)}
        <Chip value="all" active={chip === "all"} onClick={() => setChip("all")} title="All in" />
        <span className="ml-auto text-right text-[10.5px] text-ink-3">
          {house && <span className="block" title="Table limits per bet">{chipLabel(house.min_bet)} – {chipLabel(house.max_bet)}</span>}
          On the table<br /><b className="font-mono text-[12px] text-ink-1">{fmt(me.staked ?? 0)}</b>
        </span>
      </div>
      <div ref={boardRef} className={clsx("cz-board", !betting && "cz-board-closed")}>{board}</div>
      {!betting && spots.length > 0 && <p className="cz-foot !mt-1">{st?.phase === "idle" ? "The table is closed — press Start round." : "Bets are locked until the next round."}</p>}
      <div className="cz-actions">
        <button className="key !h-8" disabled={!betting || !undo.current.length} onClick={() => { const u = undo.current.pop(); if (u) unbet(u[0], u[1]); }}><Undo2 size={13} /> Undo</button>
        <button className="key !h-8" disabled={!betting || !(me.staked ?? 0)} onClick={clearAll}>Clear</button>
        <button className="key !h-8" disabled={!betting || !Object.keys(me.last_bets ?? {}).length} onClick={rebet}><RotateCcw size={12} /> Rebet</button>
        <button className="cz-gold !h-8 ml-auto" disabled={!betting || !(me.staked ?? 0) || me.done} onClick={() => op("done")} title="When everyone with chips is done, the round locks">
          <Check size={13} /> {me.done ? "Done" : "Done betting"}
        </button>
      </div>
      {gameOps.length > 0 && (
        <div className="cz-actions">
          <Hand size={14} className="text-[var(--gold)]" />
          {gameOps.map((o) => (
            <button key={o} className="cz-gold !h-8" onClick={() => op(o, o === "raise" || o === "bet_more" ? { amount } : {})}>{o.replace(/_/g, " ")}{o === "raise" ? ` ${short(amount)}` : ""}</button>
          ))}
        </div>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------ the wing
export function RightWing() {
  const tab = useCasino((s) => s.rightTab);
  const set = useCasino((s) => s.set);
  const n = useCasino((s) => (s.players ?? s.status?.players ?? []).filter((p) => p.online).length);
  const rounds = useCasino((s) => s.status?.history?.length ?? 0);
  return (
    <div className="cz-wing-body">
      <Tabs label="Players" value={tab} onChange={(t) => set({ rightTab: t })}
        options={[["seats", "Players", n], ["ranking", "Ranking"], ["rounds", "Rounds", rounds], ["play", "Play"]]} />
      <div className="cz-scroll">
        {tab === "seats" && <Seats />}
        {tab === "ranking" && <Ranking />}
        {tab === "rounds" && <Rounds />}
        {tab === "play" && <Play />}
      </div>
    </div>
  );
}
