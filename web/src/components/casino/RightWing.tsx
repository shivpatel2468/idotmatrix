import clsx from "clsx";
import { Ban, Check, ChevronDown, CircleCheck, CircleX, Crown, Hand, Medal, RotateCcw, ShieldCheck, Undo2, UserCheck, Users } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "../../lib/store";
import { AvatarPix, Chip, Credits, NumberInput, Section, Tabs } from "./bits";
import {
  type HistoryEntry, type PlayerRow, type Spot, TONE, casinoOp, fmt, seatLabel, short, useCasino, verifyRound,
} from "./state";

const BET_OPS = new Set(["bet", "unbet", "clear", "rebet", "done"]);
const CHIPS = [1, 5, 25, 100, 500] as const;

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

function SpotButton({ s, mine, total, onBet, onUnbet, disabled, className, style }: {
  s: Spot; mine: number; total: number; onBet: () => void; onUnbet: () => void; disabled: boolean; className?: string; style?: React.CSSProperties;
}) {
  return (
    <button className={clsx("cz-spot", className)} disabled={disabled} style={style}
      title={`${s.label} · pays ${s.pays}${total ? ` · table ${fmt(total)}` : ""}\nClick: add a chip · right-click: take one back`}
      onClick={onBet} onContextMenu={(e) => { e.preventDefault(); onUnbet(); }}>
      <span className="cz-spot-l">{s.label}</span>
      <span className="cz-spot-p">{s.pays}</span>
      {mine > 0 && <span className="cz-spot-mine">{short(mine)}</span>}
      {!mine && total > 0 && <span className="cz-spot-total" />}
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
  const credits = me.seated ? (me.credits ?? 0) : (house?.base_credits ?? 0);
  const betting = st?.phase === "betting";
  const amount = chip === "all" ? credits : chip;
  const bets = me.bets ?? {};
  const totals = st?.totals ?? {};
  const gameOps = (me.ops ?? []).filter((o) => !BET_OPS.has(o));

  const bet = (id: string) => {
    if (!betting) return toast("Bets are closed — wait for the next round", "error");
    if (amount <= 0) return toast("No credits left", "error");
    undo.current.push([id, amount]);
    casinoOp("bet", { spot: id, amount }).catch(() => undefined);
  };
  const unbet = (id: string, amt?: number) => casinoOp("unbet", amt ? { spot: id, amount: amt } : { spot: id }).catch(() => undefined);
  const op = (o: string, extra: Record<string, unknown> = {}) => casinoOp(o, extra).catch(() => undefined);
  const btn = (s: Spot, cls?: string, style?: React.CSSProperties) => (
    <SpotButton key={s.id} s={s} mine={bets[s.id] ?? 0} total={totals[s.id] ?? 0} disabled={!betting}
      onBet={() => bet(s.id)} onUnbet={() => unbet(s.id, typeof chip === "number" ? chip : undefined)} className={cls} style={style} />
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
  const roulette = isRoulette(spots);
  const byId = useMemo(() => Object.fromEntries(spots.map((s) => [s.id, s])), [spots]);

  let board: React.ReactNode;
  if (!spots.length && !gameOps.length) board = <p className="cz-empty">This table has no bets to place right now.</p>;
  else if (roulette) {
    const zeros = spots.filter((s) => s.kind === "straight" && (s.label === "0" || s.label === "00"));
    const num = (n: number) => byId[`n:${n}`];
    const outside = groups.filter(([k]) => ["dozen", "column", "red", "black", "odd", "even", "low", "high"].includes(k)).flatMap(([, v]) => v);
    const inside = groups.filter(([k]) => !["straight", "dozen", "column", "red", "black", "odd", "even", "low", "high"].includes(k));
    board = (
      <>
        <div className="cz-wheelgrid">
          <div className="cz-zeros">{zeros.map((s) => btn(s, "cz-n cz-n-g"))}</div>
          <div className="cz-nums">
            {[3, 2, 1].map((row) => Array.from({ length: 12 }, (_, c) => num(c * 3 + row)).filter(Boolean).map((s) => btn(s!, clsx("cz-n", RED.has(+s!.label) ? "cz-n-r" : "cz-n-b"))))}
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
      <div className="cz-rack" role="radiogroup" aria-label="Chip">
        {CHIPS.map((v) => <Chip key={v} value={v} active={chip === v} onClick={() => setChip(v)} title={`${v} credits`} />)}
        <Chip value="all" active={chip === "all"} onClick={() => setChip("all")} title="All in" />
        <span className="ml-auto text-right text-[10.5px] text-ink-3">
          On the table<br /><b className="font-mono text-[12px] text-ink-1">{fmt(me.staked ?? 0)}</b>
        </span>
      </div>
      <div className={clsx("cz-board", !betting && "cz-board-closed")}>{board}</div>
      {!betting && spots.length > 0 && <p className="cz-foot !mt-1">{st?.phase === "idle" ? "The table is closed — press Start round." : "Bets are locked until the next round."}</p>}
      <div className="cz-actions">
        <button className="key !h-8" disabled={!betting || !undo.current.length} onClick={() => { const u = undo.current.pop(); if (u) unbet(u[0], u[1]); }}><Undo2 size={13} /> Undo</button>
        <button className="key !h-8" disabled={!betting || !(me.staked ?? 0)} onClick={() => { undo.current = []; op("clear"); }}>Clear</button>
        <button className="key !h-8" disabled={!betting || !Object.keys(me.last_bets ?? {}).length} onClick={() => op("rebet")}><RotateCcw size={12} /> Rebet</button>
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
