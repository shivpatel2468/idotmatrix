/**
 * The roulette layout's drop targets (docs/CASINO.md "drop targets", docs/STUDIO_UI.md): a chip dropped or clicked on
 * the number grid lands on the nearest legal spot by geometry, like a real table — inside a number: straight; within
 * ~22 % of a cell of the line between two numbers: split; where four numbers meet: corner (`c:<a>`); on the grid's
 * outer edge: street (`st:<a>`), or six line (`sl:<a>`) where two streets meet; against the zero: the zero splits,
 * trios and first four / top line (spot ids from casino/games/roulette.py). Chips on lines sit on the line.
 *
 * Geometry is in "grid units": u = 0…12 across the 12 columns (u = 0 is the line against the zero), v = 0…3 down the
 * three rows (row 0 is the top row: 3, 6, … 36; row 2 the bottom: 1, 4, … 34).
 */
import clsx from "clsx";
import type { Pt } from "./chipfx";
import { stackShadow } from "./chipfx";
import { chipLabel } from "./chips";
import type { Spot, SpotBettor } from "./state";
import { fmt } from "./state";

export const GAP = 3; // px between cells (.cz-nums / .cz-zeros gap)
const T = 0.22; // how close to a line (in cells) counts as on it

const col = (n: number) => Math.floor((n - 1) / 3);
const row = (n: number) => 2 - ((n - 1) % 3);
const at = (c: number, r: number) => 3 * c + 3 - r;

export type Hit = { id: string; u: number; v: number; zero?: boolean };

/** The grid's rects, read once per gesture (no layout reads per pointer move). */
export type GridBox = { nums: DOMRect; zeros: DOMRect | null };

export function gridBox(nums: HTMLElement | null, zeros: HTMLElement | null): GridBox | null {
  if (!nums) return null;
  const r = nums.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  return { nums: r, zeros: zeros?.getBoundingClientRect() ?? null };
}

/** Grid units → client coords (u may be < 0 only for the zero column: see `zero`). */
export function toClient(b: GridBox, h: { u: number; v: number; zero?: boolean }): Pt {
  const { nums } = b;
  const py = (nums.height + GAP) / 3;
  const y = nums.top + h.v * py - GAP / 2;
  if (h.zero && b.zeros) return [b.zeros.left + b.zeros.width / 2, y];
  const px = (nums.width + GAP) / 12;
  return [nums.left + h.u * px - GAP / 2, y];
}

/** The spot a point (client coords) lands on, or null when it is off the number grid (the DOM decides there). */
export function rouletteHit(b: GridBox, x: number, y: number, has: (id: string) => boolean, us: boolean): Hit | null {
  const { nums, zeros } = b;
  const px = (nums.width + GAP) / 12, py = (nums.height + GAP) / 3;
  const fx = (x - nums.left + GAP / 2) / px, fy = (y - nums.top + GAP / 2) / py;
  if (fy < -T || fy > 3 + T || fx > 12 + T) return null;
  const pick = (id: string, u: number, v: number, zero = false, fallback?: Hit): Hit | null =>
    has(id) ? { id, u, v, zero } : fallback ?? null;
  const cy = Math.max(0, Math.min(2.999, fy));
  // ---- the zero column
  if (fx < -T) {
    if (!zeros || x < zeros.left - 6) return null;
    if (!us) return pick("n:0", -1, 1.5, true);
    if (Math.abs(fy - 1.5) < T) return pick("s:0-00", -1, 1.5, true, pick(fy < 1.5 ? "n:00" : "n:0", -1, fy < 1.5 ? 0.75 : 2.25, true) ?? undefined);
    return fy < 1.5 ? pick("n:00", -1, 0.75, true) : pick("n:0", -1, 2.25, true);
  }
  const c = Math.max(0, Math.min(11, Math.floor(fx)));
  const r = Math.max(0, Math.min(2, Math.floor(cy)));
  const straight: Hit = { id: `n:${at(c, r)}`, u: c + 0.5, v: r + 0.5 };
  const vx = Math.round(fx), hy = Math.round(fy);
  const nearV = Math.abs(fx - vx) < T && vx <= 11;
  const nearH = Math.abs(fy - hy) < T;
  const edge = hy === 0 || hy === 3;
  // ---- against the zero
  if (nearV && vx === 0) {
    if (nearH && edge) return pick(us ? "tl" : "ff", 0, hy, false, straight);
    if (nearH) {
      const id = hy === 1 ? (us ? "tr:00-2-3" : "tr:0-2-3") : "tr:0-1-2";
      return pick(id, 0, hy, false, straight);
    }
    if (us && Math.abs(fy - 1.5) < T) return pick("tr:0-00-2", 0, 1.5, false, straight);
    const n = at(0, r);
    const z = !us ? "0" : n === 3 ? "00" : n === 1 ? "0" : fy < 1.5 ? "00" : "0";
    return pick(`s:${z}-${n}`, 0, us && n === 2 ? (z === "00" ? 1.25 : 1.75) : r + 0.5, false, straight);
  }
  // ---- between two columns
  if (nearV && vx >= 1) {
    if (nearH && edge) return pick(`sl:${3 * (vx - 1) + 1}`, vx, hy, false, straight);
    if (nearH) return pick(`c:${3 * (vx - 1) + (3 - hy)}`, vx, hy, false, straight);
    const n = at(vx - 1, r);
    return pick(`s:${n}-${n + 3}`, vx, r + 0.5, false, straight);
  }
  // ---- between two rows, or on the outer edge
  if (nearH) {
    if (edge) return pick(`st:${3 * c + 1}`, c + 0.5, hy, false, straight);
    const a = 3 * c + 3 - hy;
    return pick(`s:${a}-${a + 1}`, c + 0.5, hy, false, straight);
  }
  return pick(straight.id, straight.u, straight.v, false);
}

/** Where a spot's chips sit on the grid (grid units), or null for spots off the grid / the straight-up numbers. */
export function anchorOf(id: string, us: boolean): { u: number; v: number; zero?: boolean } | null {
  if (id === "s:0-00") return { u: -1, v: 1.5, zero: true };
  if (id === "ff" || id === "tl") return { u: 0, v: 3 };
  if (id === "tr:0-1-2") return { u: 0, v: 2 };
  if (id === "tr:0-2-3" || id === "tr:00-2-3") return { u: 0, v: 1 };
  if (id === "tr:0-00-2") return { u: 0, v: 1.5 };
  let m = /^s:(0|00)-(\d+)$/.exec(id);
  if (m) {
    const n = +m[2];
    return { u: 0, v: us && n === 2 ? (m[1] === "00" ? 1.25 : 1.75) : row(n) + 0.5 };
  }
  m = /^s:(\d+)-(\d+)$/.exec(id);
  if (m) {
    const a = +m[1], b = +m[2];
    return b === a + 1 ? { u: col(a) + 0.5, v: row(a) } : { u: col(a) + 1, v: row(a) + 0.5 };
  }
  m = /^(st|c|sl):(\d+)$/.exec(id);
  if (m) {
    const a = +m[2];
    if (m[1] === "st") return { u: col(a) + 0.5, v: 3 };
    if (m[1] === "sl") return { u: col(a) + 1, v: 3 };
    return { u: col(a) + 1, v: row(a) };
  }
  return null;
}

/** CSS position of a grid point inside `.cz-nums` (percent of the grid plus the gap correction). */
function posOf(a: { u: number; v: number; zero?: boolean }): React.CSSProperties {
  const top = `calc(${(a.v / 3) * 100}% + ${(a.v - 1.5).toFixed(2)}px)`;
  if (a.zero) return { left: -(GAP + 17), top };
  return { left: `calc(${(a.u / 12) * 100}% + ${(a.u * 0.25 - 1.5).toFixed(2)}px)`, top };
}

/** The chips on a line / an intersection: the host's stack (gold badge, ladder edges) and everyone's colour dots. */
export function LineChips({ spots, bets, totals, who, us }: {
  spots: Spot[]; bets: Record<string, number>; totals: Record<string, number>; who: Record<string, SpotBettor[]>; us: boolean;
}) {
  return (
    <>
      {spots.map((s) => {
        const mine = bets[s.id] ?? 0, total = totals[s.id] ?? 0;
        if (!mine && !total) return null;
        const a = anchorOf(s.id, us);
        if (!a) return null;
        const list = who[s.id] ?? [];
        const names = list.map((w) => `${w.name} ${fmt(w.amount)}`).join(" · ");
        return (
          <span key={s.id} className={clsx("cz-linechip", !mine && "cz-linechip-others")} data-spot={s.id} style={posOf(a)}
            title={`${s.label} · pays ${s.pays} · table ${fmt(total)}${names ? `\n${names}` : ""}${mine ? "\nRight-click or drag your stack off: take it back" : ""}`}>
            {mine > 0 ? <span className="cz-spot-mine" style={{ boxShadow: stackShadow(mine) }}>{chipLabel(mine)}</span> : (
              <span className="cz-linechip-dots">
                {list.slice(0, 3).map((w) => <i key={String(w.seat)} style={{ background: w.color }} />)}
              </span>
            )}
          </span>
        );
      })}
    </>
  );
}
