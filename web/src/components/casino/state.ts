import { type CSSProperties, useEffect, useState } from "react";
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
  /** who has chips on which spot, in table order (table.py spot_bets) — the same list every phone draws */
  spot_bets?: Record<string, SpotBettor[]>;
  /** the session's change counter: the newest status wins whichever feed delivers it */
  rev?: number;
  bettors?: (number | string)[]; done?: (number | string)[];
  paused?: boolean; house?: House; players?: PlayerRow[]; history?: HistoryEntry[];
  edges?: Record<string, number>; rtp?: number; lobby?: boolean; max_players?: number;
  table_theme?: TableTheme;
  result?: { round: number; outcome: Record<string, unknown>; label?: string; tone?: string; winners?: { seat: number | string | null; name: string; net: number }[] };
  [k: string]: unknown;
};
export type SpotBettor = { seat: number | "host"; name: string; color: string; amount: number };
/** Housie's own status block (`status.housie`, casino/games/housie.py). */
export type HousiePrize = {
  id: string; name: string; share: number; amount: number; state: "open" | "claimed" | "won"; call: number | null;
  winners: { seat: number | string | null; name: string; color: string; ticket: number }[];
};
export type HousieStatus = {
  price: number; max: number; pace: number; pot: number; rake: number; sold: number; called: number; calls: number[];
  call_in: number | null; first_in: number | null; finished: boolean; returned: number; prizes: HousiePrize[];
  buyers: { seat: number | string | null; name: string; color: string; n: number }[];
};
/** A table theme (apps/_casino.py TABLE_THEMES): CSS colours for the felt, the accent and the wings. */
export type TableTheme = { id: string; name: string; css: Record<string, string> };
/** Every table theme (mirror of apps/_casino.py TABLE_THEMES; tests/test_casino_themes.py checks they match), so the
 *  studio can show the swatches before the table has sent its own list. */
export const TABLE_THEMES: TableTheme[] = [
  { id: "classic", name: "Classic green", css: {"felt": "#0d6b45", "felt2": "#0a5236", "felt3": "#063823", "accent": "#ffcc33", "accent_hi": "#ffe08a", "accent_lo": "#e2a400", "accent_deep": "#3a2c08", "accent_rgb": "255, 204, 51", "ink": "#1a1200", "wing": "#102a20", "wing2": "#0b1c16", "wing3": "#0a1512", "bg": "#060c0a", "surface": "#0f1a17", "surface2": "#172722", "surface3": "#1c352b", "surface4": "#2a4139", "felt_ink": "#e7f0ec", "accent_text": "#ffcc33"} },
  { id: "royal", name: "Royal blue", css: {"felt": "#1b4aa8", "felt2": "#123680", "felt3": "#0a1f4d", "accent": "#ffcc33", "accent_hi": "#ffe08a", "accent_lo": "#e2a400", "accent_deep": "#3a2c08", "accent_rgb": "255, 204, 51", "ink": "#1a1200", "wing": "#13214a", "wing2": "#0d1734", "wing3": "#0a1128", "bg": "#060916", "surface": "#0f162c", "surface2": "#19233e", "surface3": "#1f2c53", "surface4": "#2d395e", "felt_ink": "#e8edf6", "accent_text": "#ffcc33"} },
  { id: "crimson", name: "Crimson velvet", css: {"felt": "#8c1a2e", "felt2": "#691322", "felt3": "#3d0a14", "accent": "#e8b04a", "accent_hi": "#f6d38a", "accent_lo": "#c48a24", "accent_deep": "#3a2508", "accent_rgb": "232, 176, 74", "ink": "#1a1200", "wing": "#2c1016", "wing2": "#200b10", "wing3": "#170809", "bg": "#0d0405", "surface": "#1c0d0e", "surface2": "#2b171c", "surface3": "#371c22", "surface4": "#432a30", "felt_ink": "#f4e8ea", "accent_text": "#e8b04a"} },
  { id: "midnight", name: "Midnight neon", css: {"felt": "#3a1d72", "felt2": "#29145a", "felt3": "#140a33", "accent": "#c77dff", "accent_hi": "#e2bcff", "accent_lo": "#9a4ae0", "accent_deep": "#2a1145", "accent_rgb": "199, 125, 255", "ink": "#12001f", "wing": "#1a1230", "wing2": "#120c22", "wing3": "#0c0818", "bg": "#07040d", "surface": "#110d1d", "surface2": "#1e182d", "surface3": "#251e3a", "surface4": "#332c47", "felt_ink": "#ebe8f1", "accent_text": "#c77dff"} },
  { id: "strip", name: "Neon strip", css: {"felt": "#5a1260", "felt2": "#410c47", "felt3": "#22052a", "accent": "#ff3fb0", "accent_hi": "#ff9ad6", "accent_lo": "#d81f8a", "accent_deep": "#3d0a2a", "accent_rgb": "255, 63, 176", "ink": "#1f0013", "wing": "#22102e", "wing2": "#170b22", "wing3": "#100717", "bg": "#09040d", "surface": "#150c1c", "surface2": "#23172d", "surface3": "#2d1c38", "surface4": "#3a2a45", "felt_ink": "#eee7ef", "accent_text": "#ff5abb"} },
  { id: "emerald", name: "Emerald & champagne", css: {"felt": "#0b5a43", "felt2": "#084431", "felt3": "#03241a", "accent": "#f1dca0", "accent_hi": "#fbefcc", "accent_lo": "#cdb26a", "accent_deep": "#352c12", "accent_rgb": "241, 220, 160", "ink": "#1a1200", "wing": "#0d2a22", "wing2": "#091e18", "wing3": "#071612", "bg": "#040c0a", "surface": "#0c1b17", "surface2": "#152924", "surface3": "#19352d", "surface4": "#28413a", "felt_ink": "#e7eeec", "accent_text": "#f1dca0"} },
  { id: "burgundy", name: "Burgundy & ivory", css: {"felt": "#6b1f36", "felt2": "#521729", "felt3": "#2c0b16", "accent": "#f4ead2", "accent_hi": "#fffaf0", "accent_lo": "#d6c8a4", "accent_deep": "#3a3020", "accent_rgb": "244, 234, 210", "ink": "#1a1200", "wing": "#2a121a", "wing2": "#1e0d13", "wing3": "#16090e", "bg": "#0c0508", "surface": "#1b0e13", "surface2": "#29191f", "surface3": "#351e25", "surface4": "#412c33", "felt_ink": "#f0e9eb", "accent_text": "#f4ead2"} },
];
/** "How to play" + rulebook for one game (casino/rulebook.py); `**bold**` is the only markup. */
export type Guide = { id: string; title: string; tagline: string; how: string[]; rules: { h: string; items: string[] }[] };
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
  leftTab: "tables" | "house" | "rules" | "odds" | "guide";
  guide: Guide | null; // how to play + rulebook for this table (host view, with the spots)
  themes: TableTheme[]; // every table theme (host view, with the spots): the studio's swatches
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
  guide: null, themes: [], verify: {}, dismissedFor: null, entered: 0, ...loadWings(), tab: "table", leftTab: "tables", rightTab: "seats",
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
type ViewReply = { status: CasinoStatus; private: HostPrivate; players: PlayerRow[]; spots?: Spot[]; avatars?: Record<string, Avatar>; guide?: Guide | null; themes?: TableTheme[] };

/** A host op (start_round, lock, settings, credits, kick, pause, reset_session, verify) or a play op as the host. */
export async function casinoOp<T = Record<string, unknown>>(op: string, payload: Record<string, unknown> = {}, app?: string): Promise<T> {
  const id = app ?? useCasino.getState().app ?? useStore.getState().state?.engine.current?.app;
  if (!id) throw new Error("no casino table is showing");
  const r = (await api.action(id, "casino", { op, ...payload })) as { result: T };
  if (op !== "view") refreshView().catch(() => undefined);
  return r.result;
}

/**
 * The status arrives from two feeds (the engine's state stream and the host-view poll) that can overtake each other.
 * Keep the newer one: an older `rev` is dropped unless the current status is a few seconds old (an engine restart
 * starts the counter again) or belongs to another table.
 */
export function isFresher(next: CasinoStatus | null | undefined): boolean {
  const c = useCasino.getState();
  const cur = c.status;
  if (!next || !cur || typeof next.rev !== "number" || typeof cur.rev !== "number") return true;
  if (next.game !== cur.game) return true;
  return next.rev >= cur.rev || performance.now() - c.at > 3000;
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
    const patch: Partial<CasinoStore> = { app, me: v.private, players: v.players ?? null };
    if (isFresher(v.status)) Object.assign(patch, { status: v.status, at: performance.now() });
    if (v.spots) {
      patch.spots = v.spots;
      patch.spotsKey = `${app}|${JSON.stringify(v.status?.rules ?? null)}`;
    }
    if (v.avatars) patch.avatars = v.avatars;
    if (v.guide !== undefined) patch.guide = v.guide;
    if (v.themes) patch.themes = v.themes;
    useCasino.setState(patch);
  } finally {
    inflight = false;
  }
}

/** Keep the casino store fresh while casino mode is open: the state stream + a light host-view poll. */
export function useCasinoFeed(app: string | null) {
  useEffect(() => {
    if (!app) return;
    useCasino.setState({ app, spots: [], spotsKey: "", me: { seated: false }, players: null, status: null, guide: null });
    const off = useStore.subscribe((s, prev) => {
      if (s.state === prev.state) return;
      const cur = s.state?.engine.current;
      if (cur?.app !== app) return;
      const st = cur.status as CasinoStatus;
      if (st && st.casino && isFresher(st)) useCasino.setState({ status: st, at: s.stateAt });
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

// ------------------------------------------------------------------ table theme
/** CSS variables for `.cz` from the status's table theme (nothing for classic: the stylesheet is the classic look). */
export function themeVars(t: TableTheme | null | undefined): CSSProperties | undefined {
  if (!t || t.id === "classic" || !t.css) return undefined;
  const c = t.css;
  const v: Record<string, string | undefined> = {
    "--felt": c.felt, "--felt-2": c.felt2, "--felt-deep": c.felt3, "--felt-hi": c.felt,
    "--gold": c.accent, "--gold-2": c.accent_hi, "--gold-lo": c.accent_lo, "--gold-deep": c.accent_deep,
    "--gold-rgb": c.accent_rgb, "--gold-ink": c.ink, "--gold-text": c.accent_text, "--felt-ink": c.felt_ink,
    "--cz-wing": c.wing, "--cz-wing-2": c.wing2, "--cz-wing-3": c.wing3,
    "--cz-bg": c.bg, "--cz-s1": c.surface, "--cz-s2": c.surface2, "--cz-s3": c.surface3, "--cz-s4": c.surface4,
  };
  return Object.fromEntries(Object.entries(v).filter(([, x]) => !!x)) as CSSProperties;
}

/** `html[data-cz]` variables (casino.css): the page around the casino view — body, top bar keys, toasts — follows the
 *  theme while the casino view is on screen. Classic sets nothing (the stylesheet's defaults are classic). */
export function pageVars(t: TableTheme | null | undefined): Record<string, string> {
  if (!t || t.id === "classic" || !t.css) return {};
  const c = t.css;
  const v: Record<string, string | undefined> = {
    "--cz-page-bg": c.bg, "--cz-page-s1": c.surface, "--cz-page-s2": c.surface2, "--cz-page-s3": c.surface3,
    "--cz-page-s4": c.surface4, "--cz-page-felt": c.felt, "--cz-page-accent": c.accent, "--cz-page-accent-2": c.accent_hi,
    "--cz-page-deep": c.accent_deep, "--cz-page-ink": c.ink, "--cz-page-text": c.felt_ink,
  };
  return Object.fromEntries(Object.entries(v).filter(([, x]) => !!x)) as Record<string, string>;
}

/** Stamp the theme on <html> while the casino view is mounted (and take it off again when it closes). */
export const PAGE_VAR_NAMES = ["--cz-page-bg", "--cz-page-s1", "--cz-page-s2", "--cz-page-s3", "--cz-page-s4", "--cz-page-felt",
  "--cz-page-accent", "--cz-page-accent-2", "--cz-page-deep", "--cz-page-ink", "--cz-page-text"];
export function stampPage(t: TableTheme | null | undefined): () => void {
  const root = document.documentElement;
  root.dataset.cz = t?.id ?? "classic";
  const v = pageVars(t);
  for (const k of PAGE_VAR_NAMES) {
    if (v[k]) root.style.setProperty(k, v[k]);
    else root.style.removeProperty(k);
  }
  return () => {
    delete root.dataset.cz;
    for (const k of PAGE_VAR_NAMES) root.style.removeProperty(k);
  };
}
