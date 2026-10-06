/**
 * The chip ladder (docs/CASINO.md §5) — a copy of `src/deskdot/casino/chips.py` for engines that don't publish
 * `status.chips` yet. A table offers only the chips the house allows (min_bet ≤ value ≤ max_bet), at most 7 spanning
 * the range; a table minimum that is not on the ladder becomes the smallest chip, coloured like the next one up.
 */

export type RackChip = { v: number; label: string; color: string; edge: string };

/** value, label, chip colour, edge-stripe colour */
export const LADDER: readonly RackChip[] = [
  { v: 1, label: "1", color: "#f2efe8", edge: "#2b6cd6" },
  { v: 5, label: "5", color: "#d23a3a", edge: "#ffffff" },
  { v: 25, label: "25", color: "#2e9a55", edge: "#ffffff" },
  { v: 100, label: "100", color: "#1c1c22", edge: "#e8e8e8" },
  { v: 500, label: "500", color: "#7b3fc4", edge: "#ffffff" },
  { v: 1_000, label: "1K", color: "#f2c230", edge: "#5a3d00" },
  { v: 2_000, label: "2K", color: "#e85d9f", edge: "#ffffff" },
  { v: 5_000, label: "5K", color: "#c9772b", edge: "#ffffff" },
  { v: 10_000, label: "10K", color: "#2f6fd6", edge: "#ffffff" },
  { v: 25_000, label: "25K", color: "#18a39a", edge: "#ffffff" },
  { v: 50_000, label: "50K", color: "#9a2f4d", edge: "#ffd36b" },
  { v: 100_000, label: "100K", color: "#c9a227", edge: "#1c1c22" },
  { v: 250_000, label: "250K", color: "#5b2a86", edge: "#ffd36b" },
  { v: 500_000, label: "500K", color: "#0f3d2e", edge: "#ffd36b" },
  { v: 1_000_000, label: "1M", color: "#111111", edge: "#ffd36b" },
];
export const RACK_MAX = 7;
/** The "ALL in" key's colour (not a ladder chip). */
export const ALL_IN: RackChip = { v: 0, label: "ALL", color: "#ff3f78", edge: "#ffffff" };

/** A chip amount with K / M, never rounded up (mirror of chips.py `short`): 1000 → 1K, 2500 → 2.5K,
 *  1250 → 1.25K, 12345 → 12.3K, 1000000 → 1M, 750 → 750. */
export function chipLabel(v: number): string {
  const n = Math.round(Number(v) || 0);
  for (const [unit, suf] of [[1_000_000, "M"], [1_000, "K"]] as const) {
    if (n >= unit) {
      const d = n < 10 * unit ? 2 : n < 100 * unit ? 1 : 0;
      const q = Math.floor((n * 10 ** d) / unit);
      const s = d ? `${Math.floor(q / 10 ** d)}.${String(q % 10 ** d).padStart(d, "0")}`.replace(/0+$/, "").replace(/\.$/, "") : String(q);
      return s + suf;
    }
  }
  return String(n);
}

/** The chips a table offers, smallest first (mirror of chips.py `chip_rack`). */
export function chipRack(minBet: number | null | undefined, maxBet: number | null | undefined): RackChip[] {
  const lo = Math.max(1, Math.floor(Number(minBet)) || 1);
  const hi = Math.max(lo, Math.floor(Number(maxBet)) || lo);
  const allowed = LADDER.filter((c) => c.v >= lo && c.v <= hi).map((c) => ({ ...c }));
  if (!allowed.length || allowed[0].v !== lo) {
    const above = LADDER.find((c) => c.v > lo) ?? LADDER[LADDER.length - 1];
    allowed.unshift({ v: lo, label: chipLabel(lo), color: above.color, edge: above.edge });
  }
  const n = allowed.length;
  if (n <= RACK_MAX) return allowed;
  const picks = [...new Set(Array.from({ length: RACK_MAX }, (_, i) => Math.floor((2 * i * (n - 1) + RACK_MAX - 1) / (2 * (RACK_MAX - 1)))))].sort((a, b) => a - b);
  return picks.map((i) => allowed[i]);
}

/** The rack to show: the engine's `status.chips` when it sends one, else the same rack computed here. */
export function rackOf(chips: unknown, minBet?: number, maxBet?: number): RackChip[] {
  if (Array.isArray(chips) && chips.length) {
    const ok = chips.filter((c): c is RackChip => !!c && typeof c === "object" && typeof (c as RackChip).v === "number" && (c as RackChip).v > 0);
    if (ok.length) return ok.map((c) => ({ v: c.v, label: c.label || chipLabel(c.v), color: c.color || styleOf(c.v).color, edge: c.edge || styleOf(c.v).edge }));
  }
  return chipRack(minBet, maxBet);
}

/** The look of a chip worth `v`: the ladder chip itself, else the largest ladder chip under it (the smallest when below 1). */
export function styleOf(v: number | "all"): RackChip {
  if (v === "all") return ALL_IN;
  let best = LADDER[0];
  for (const c of LADDER) if (c.v <= v) best = c;
  return best;
}

/** A stack's amount as ladder chips, largest first (greedy); `max` caps the count. */
export function breakInto(amount: number, max = Infinity): RackChip[] {
  let left = Math.max(0, Math.round(Number(amount) || 0));
  const out: RackChip[] = [];
  for (let i = LADDER.length - 1; i >= 0 && out.length < max; i--) {
    const c = LADDER[i];
    while (left >= c.v && out.length < max) {
      out.push(c);
      left -= c.v;
    }
  }
  return out;
}

/** Light chips (the white 1, the yellow 1K, the gold 100K) get dark numerals. */
export function isLight(hex: string): boolean {
  const h = hex.replace("#", "");
  if (h.length !== 6) return false;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.55;
}
