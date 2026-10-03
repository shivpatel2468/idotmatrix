import { useEffect, useState } from "react";
import { create } from "zustand";
import { api } from "../../lib/api";
import { appMeta, useStore } from "../../lib/store";

/**
 * Casino mode (docs/CASINO.md §6): when the app on the panel is a casino game the studio becomes the host's
 * table — drawers shut, a marquee lights around the panel, and two wings slide in (house + rules on the left,
 * players on the right). Everything is generic: it reads `/api/meta` (schema, category) and the table's public
 * status; the host's own seat is read with the host op `view` (POST /api/apps/{id}/actions/casino).
 */

// ------------------------------------------------------------------ types (the engine's casino status)
export type Proof = { nonce: number; hash: string; client_seed: string; server_seed: string | null };
export type HistoryEntry = {
  round: number; game: string; label?: string; tone?: string;
  outcome?: Record<string, unknown>; rules?: Record<string, unknown>; proof?: Proof;
};
export type PlayerRow = {
  seat: number | "host" | null; name: string; color: string; avatar: string; online: boolean;
  credits: number; staked: number; net: number; biggest: number;
  pid?: string; kicked?: boolean; // host view only
};
export type House = {
  base_credits: number; min_bet: number; max_bet: number; bet_seconds: number;
  result_seconds: number; turn_seconds: number; auto_next: boolean;
};
export type CasinoStatus = {
  casino?: boolean; view?: string; name?: string; game?: string;
  phase?: string; round?: number | null; hash?: string | null;
  ends_in?: number | null; reveal_in?: number | null; next_in?: number | null;
  rules?: Record<string, unknown>; totals?: Record<string, number>;
  bettors?: (number | string)[]; done?: (number | string)[];
  paused?: boolean; house?: House; players?: PlayerRow[]; history?: HistoryEntry[];
  edges?: Record<string, number>; rtp?: number; lobby?: boolean; max_players?: number;
  result?: { round: number; outcome: Record<string, unknown>; label?: string; tone?: string; winners?: { seat: number | string | null; name: string; net: number }[] };
  [k: string]: unknown;
};
export type Spot = { id: string; label: string; kind: string; pays: string; numbers: number[] };
export type Avatar = { name: string; px: string[] };
export type HostPrivate = {
  seated: boolean; credits?: number; escrow?: number; bets?: Record<string, number>; staked?: number;
  last_bets?: Record<string, number>; can_bet?: boolean; done?: boolean; ops?: string[];
  result?: { round: number; stake: number; payout: number; net: number; wins: string[] };
  notice?: { id: number; text: string; kind: string } | null;
  [k: string]: unknown;
};
export type Verify = {
  ok: boolean; hash_ok?: boolean; matches?: boolean; outcome?: unknown; error?: string | null; round?: number; proof?: Proof;
  local?: boolean | null; // the browser's own SHA-256(seed) == hash check (null: not available here)
};

type CasinoStore = {
  /** the freshest public status (host view poll or the state stream), and when it arrived */
  status: CasinoStatus | null;
  at: number;
  app: string | null;
  me: HostPrivate;
  players: PlayerRow[] | null; // host view: with pid + kicked
  spots: Spot[];
  spotsKey: string;
  avatars: Record<string, Avatar>;
  verify: Record<number, Verify | "busy">;
  dismissedFor: string | null; // "Leave casino" for this app (re-enter from the stage)
  entered: number; // performance.now() of the last entrance (replays the show)
  wingL: number;
  wingR: number;
  tab: "table" | "house" | "players"; // phones / tablets
  leftTab: "tables" | "house" | "rules" | "odds";
  rightTab: "seats" | "ranking" | "rounds" | "play";
  set: (p: Partial<CasinoStore>) => void;
};

function loadWings(): { wingL: number; wingR: number } {
  try {
    const w = JSON.parse(localStorage.getItem("deskdot.casino.wings") ?? "{}");
    const ok = (v: unknown) => typeof v === "number" && v > 0.3 && v < 1.7;
    return { wingL: ok(w.l) ? w.l : 1, wingR: ok(w.r) ? w.r : 1 };
  } catch {
    return { wingL: 1, wingR: 1 };
  }
}

export const useCasino = create<CasinoStore>((set) => ({
  status: null, at: 0, app: null, me: { seated: false }, players: null, spots: [], spotsKey: "", avatars: {},
  verify: {}, dismissedFor: null, entered: 0, ...loadWings(), tab: "table", leftTab: "tables", rightTab: "seats",
  set: (p) => set(p),
}));

export function saveWings(l: number, r: number) {
  useCasino.setState({ wingL: l, wingR: r });
  try {
    localStorage.setItem("deskdot.casino.wings", JSON.stringify({ l, r }));
  } catch {
    /* private mode */
  }
}

// ------------------------------------------------------------------ mode
/** The casino app showing on the panel (category "casino"), or null. */
export function useCasinoApp(): string | null {
  return useStore((s) => {
    const id = s.state?.engine.current?.app;
    if (!id || !s.meta) return null;
    return s.meta.apps.find((a) => a.id === id)?.category === "casino" ? id : null;
  });
}

/** Is the studio in casino mode? (A casino game is showing and the host hasn't left the casino for it.) */
export function useCasinoView(): boolean {
  const app = useCasinoApp();
  const dismissed = useCasino((s) => s.dismissedFor);
  return !!app && dismissed !== app;
}

export function leaveCasino() {
  const app = useStore.getState().state?.engine.current?.app ?? null;
  useCasino.setState({ dismissedFor: app });
}

export function enterCasino() {
  useCasino.setState({ dismissedFor: null, entered: performance.now() });
}

export const casinoApps = () => (useStore.getState().meta?.apps ?? []).filter((a) => a.category === "casino");

// ------------------------------------------------------------------ ops
type ViewReply = { status: CasinoStatus; private: HostPrivate; players: PlayerRow[]; spots?: Spot[]; avatars?: Record<string, Avatar> };

/** A host op (start_round, lock, settings, credits, kick, pause, reset_session, verify) or a play op as the host. */
export async function casinoOp<T = Record<string, unknown>>(op: string, payload: Record<string, unknown> = {}, app?: string): Promise<T> {
  const id = app ?? useCasino.getState().app ?? useStore.getState().state?.engine.current?.app;
  if (!id) throw new Error("no casino table is showing");
  const r = (await api.action(id, "casino", { op, ...payload })) as { result: T };
  if (op !== "view") refreshView().catch(() => undefined);
  return r.result;
}

let inflight = false;
/** Read the table: fresh status, the host seat's own view, and (when the rules changed) the spots. */
export async function refreshView(): Promise<void> {
  const app = useStore.getState().state?.engine.current?.app;
  if (!app || inflight || appMeta(app)?.category !== "casino") return;
  inflight = true;
  try {
    const c = useCasino.getState();
    const rules = JSON.stringify(c.status?.rules ?? null);
    const key = `${app}|${rules}`;
    const want = c.spotsKey !== key || !c.spots.length;
    const r = (await fetch(`/api/apps/${app}/actions/casino`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ op: "view", spots: want }),
    }).then((x) => (x.ok ? x.json() : null))) as { result: ViewReply } | null;
    if (!r || useStore.getState().state?.engine.current?.app !== app) return;
    const v = r.result;
    const patch: Partial<CasinoStore> = { status: v.status, at: performance.now(), app, me: v.private, players: v.players ?? null };
    if (v.spots) {
      patch.spots = v.spots;
      patch.spotsKey = `${app}|${JSON.stringify(v.status?.rules ?? null)}`;
    }
    if (v.avatars) patch.avatars = v.avatars;
    useCasino.setState(patch);
  } finally {
    inflight = false;
  }
}

/** Keep the casino store fresh while casino mode is open: the state stream + a light host-view poll. */
export function useCasinoFeed(app: string | null) {
  useEffect(() => {
    if (!app) return;
    useCasino.setState({ app, spots: [], spotsKey: "", me: { seated: false }, players: null, status: null });
    const off = useStore.subscribe((s, prev) => {
      if (s.state === prev.state) return;
      const cur = s.state?.engine.current;
      if (cur?.app !== app) return;
      const st = cur.status as CasinoStatus;
      if (st && st.casino) useCasino.setState({ status: st, at: s.stateAt });
    });
    refreshView();
    const iv = setInterval(() => document.visibilityState === "visible" && refreshView(), 900);
    return () => {
      off();
      clearInterval(iv);
    };
  }, [app]);
}

/** Re-render every `ms` (local countdowns between status updates). */
export function useTick(ms = 200) {
  const [, set] = useState(0);
  useEffect(() => {
    const t = setInterval(() => set((n) => n + 1), ms);
    return () => clearInterval(t);
  }, [ms]);
}

/** Seconds left on a status countdown, counted down locally since the status arrived. */
export function secondsLeft(v: number | null | undefined, at: number): number | null {
  if (v == null) return null;
  return Math.max(0, v - (performance.now() - at) / 1000);
}

// ------------------------------------------------------------------ verify
async function sha256hex(hex: string): Promise<string | null> {
  try {
    if (!globalThis.crypto?.subtle) return null; // only in a secure context (localhost / https)
    const bytes = new Uint8Array((hex.match(/../g) ?? []).map((h) => parseInt(h, 16)));
    const d = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;
  }
}

export async function verifyRound(round: number, proof?: Proof) {
  useCasino.setState((s) => ({ verify: { ...s.verify, [round]: "busy" } }));
  try {
    const r = await casinoOp<Verify>("verify", { round });
    let local: boolean | null = null;
    if (proof?.server_seed) {
      const h = await sha256hex(proof.server_seed);
      local = h == null ? null : h === proof.hash.toLowerCase();
    }
    useCasino.setState((s) => ({ verify: { ...s.verify, [round]: { ...r, local } } }));
  } catch (e) {
    useCasino.setState((s) => ({ verify: { ...s.verify, [round]: { ok: false, error: e instanceof Error ? e.message : String(e) } } }));
  }
}

// ------------------------------------------------------------------ helpers
export const fmt = (n: number | null | undefined) => (n == null ? "—" : Math.round(n).toLocaleString("en-US"));
export const short = (n: number) =>
  n >= 1_000_000 ? `${+(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M` : n >= 10_000 ? `${+(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k` : fmt(n);

export const TONE: Record<string, string> = {
  red: "#e3263f", black: "#2b2b35", green: "#13a65a", white: "#5a5a68", down: "#2f6bff", seven: "#e0a400", up: "#e3263f",
  gold: "#d4a017", player: "#2f6bff", banker: "#e3263f", tie: "#13a65a", andar: "#2f6bff", bahar: "#e3263f",
};

export const PHASE: Record<string, { label: string; hint: string; tone: "gold" | "red" | "green" | "dim" }> = {
  idle: { label: "Table closed", hint: "Open a round when everyone's ready", tone: "dim" },
  betting: { label: "Place your bets", hint: "The countdown starts with the first chip", tone: "green" },
  locked: { label: "No more bets", hint: "Bets are frozen", tone: "red" },
  spinning: { label: "Spinning", hint: "The outcome was fixed at the lock", tone: "gold" },
  dealing: { label: "Dealing", hint: "Cards from the round's shuffled shoe", tone: "gold" },
  action: { label: "Players' turn", hint: "Each seat acts before its turn timer runs out", tone: "gold" },
  result: { label: "Result", hint: "Paid out — the seed is revealed", tone: "gold" },
};

export const seatLabel = (s: PlayerRow["seat"]) => (s === "host" ? "Host" : s ? `Seat ${s}` : "Away");
