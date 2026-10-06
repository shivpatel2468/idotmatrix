import { casinoAlert } from "./alert";
import type { RackChip } from "./chips";
import { untilAnchor } from "./sync";
import { type CSSProperties, useEffect, useState } from "react";
import { playCoinDrop } from "../CoinDrop";
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
  /** the round's timers as engine wall-clock anchors (shared clock: ./sync.ts) */
  clock?: { phase_at?: number; lock_at?: number | null; ends_at?: number | null; reveal_at?: number | null;
    next_at?: number | null; turn_at?: number; stage_at?: number; call_at?: number };
  rules?: Record<string, unknown>; totals?: Record<string, number>;
  /** who has chips on which spot, in table order (table.py spot_bets) — the same list every phone draws */
  spot_bets?: Record<string, SpotBettor[]>;
  /** the session's change counter: the newest status wins whichever feed delivers it */
  rev?: number;
  bettors?: (number | string)[]; done?: (number | string)[];
  paused?: boolean; house?: House; players?: PlayerRow[]; history?: HistoryEntry[];
  edges?: Record<string, number>; rtp?: number; lobby?: boolean; max_players?: number;
  table_theme?: TableTheme;
  /** the table's chip rack (casino/chips.py chip_rack): only the chips the house allows; older engines: absent */
  chips?: RackChip[];
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
/** A table theme (apps/_casino.py TABLE_THEMES): CSS colours for the felt, the accent and the wings, plus the felt's
 *  motif (`pattern` / `pattern_size`: pure CSS gradients) and a one-line `description`. */
export type TableTheme = { id: string; name: string; description?: string; css: Record<string, string> };
/** Every table theme (mirror of apps/_casino.py TABLE_THEMES; tests/test_casino_themes.py checks they match), so the
 *  studio can show the swatches before the table has sent its own list. */
export const TABLE_THEMES: TableTheme[] = [
  { id: "classic", name: "Classic green", description: "The original: green baize with a fine twill and gold trim.", css: {"felt": "#0d6b45", "felt2": "#0a5236", "felt3": "#063823", "accent": "#ffcc33", "accent_hi": "#ffe08a", "accent_lo": "#e2a400", "accent_deep": "#3a2c08", "accent_rgb": "255, 204, 51", "ink": "#1a1200", "wing": "#102a20", "wing2": "#0b1c16", "wing3": "#0a1512", "bg": "#060c0a", "surface": "#0f1a17", "surface2": "#172722", "surface3": "#1c352b", "surface4": "#2a4139", "felt_ink": "#e7f0ec", "accent_text": "#ffcc33", "pattern": "repeating-linear-gradient(45deg, rgba(255, 255, 255, 0.035) 0 1px, transparent 1px 5px)", "pattern_size": "auto"} },
  { id: "royal", name: "Royal blue", description: "Deep blue baize under a gold diamond lattice, like a palace card room.", css: {"felt": "#1b4aa8", "felt2": "#123680", "felt3": "#0a1f4d", "accent": "#ffcc33", "accent_hi": "#ffe08a", "accent_lo": "#e2a400", "accent_deep": "#3a2c08", "accent_rgb": "255, 204, 51", "ink": "#1a1200", "wing": "#13214a", "wing2": "#0d1734", "wing3": "#0a1128", "bg": "#060916", "surface": "#0f162c", "surface2": "#19233e", "surface3": "#1f2c53", "surface4": "#2d395e", "felt_ink": "#e8edf6", "accent_text": "#ffcc33", "pattern": "repeating-linear-gradient(45deg, rgba(255, 204, 51, 0.06) 0 1px, transparent 1px 22px), repeating-linear-gradient(-45deg, rgba(255, 204, 51, 0.06) 0 1px, transparent 1px 22px)", "pattern_size": "auto, auto"} },
  { id: "crimson", name: "Crimson velvet", description: "Red velvet with brass medallions: an old-world salon.", css: {"felt": "#8c1a2e", "felt2": "#691322", "felt3": "#3d0a14", "accent": "#e8b04a", "accent_hi": "#f6d38a", "accent_lo": "#c48a24", "accent_deep": "#3a2508", "accent_rgb": "232, 176, 74", "ink": "#1a1200", "wing": "#2c1016", "wing2": "#200b10", "wing3": "#170809", "bg": "#0d0405", "surface": "#1c0d0e", "surface2": "#2b171c", "surface3": "#371c22", "surface4": "#432a30", "felt_ink": "#f4e8ea", "accent_text": "#e8b04a", "pattern": "radial-gradient(circle, rgba(232, 176, 74, 0.1) 0 2px, transparent 2.5px), repeating-radial-gradient(circle, transparent 0 8px, rgba(232, 176, 74, 0.05) 8px 9px, transparent 9px 16px)", "pattern_size": "36px 36px, 36px 36px"} },
  { id: "midnight", name: "Midnight neon", description: "Violet after-hours felt with faint neon scan lines.", css: {"felt": "#3a1d72", "felt2": "#29145a", "felt3": "#140a33", "accent": "#c77dff", "accent_hi": "#e2bcff", "accent_lo": "#9a4ae0", "accent_deep": "#2a1145", "accent_rgb": "199, 125, 255", "ink": "#12001f", "wing": "#1a1230", "wing2": "#120c22", "wing3": "#0c0818", "bg": "#07040d", "surface": "#110d1d", "surface2": "#1e182d", "surface3": "#251e3a", "surface4": "#332c47", "felt_ink": "#ebe8f1", "accent_text": "#c77dff", "pattern": "repeating-linear-gradient(135deg, rgba(199, 125, 255, 0.07) 0 1px, transparent 1px 12px)", "pattern_size": "auto"} },
  { id: "strip", name: "Neon strip", description: "Hot-pink boulevard felt with a neon chevron and cyan sparks.", css: {"felt": "#5a1260", "felt2": "#410c47", "felt3": "#22052a", "accent": "#ff3fb0", "accent_hi": "#ff9ad6", "accent_lo": "#d81f8a", "accent_deep": "#3d0a2a", "accent_rgb": "255, 63, 176", "ink": "#1f0013", "wing": "#22102e", "wing2": "#170b22", "wing3": "#100717", "bg": "#09040d", "surface": "#150c1c", "surface2": "#23172d", "surface3": "#2d1c38", "surface4": "#3a2a45", "felt_ink": "#eee7ef", "accent_text": "#ff5abb", "pattern": "linear-gradient(135deg, rgba(255, 63, 176, 0.08) 25%, transparent 25%), linear-gradient(225deg, rgba(255, 63, 176, 0.08) 25%, transparent 25%)", "pattern_size": "24px 24px, 24px 24px"} },
  { id: "emerald", name: "Emerald & champagne", description: "Dark emerald with a champagne harlequin check: the high-limit room.", css: {"felt": "#0b5a43", "felt2": "#084431", "felt3": "#03241a", "accent": "#f1dca0", "accent_hi": "#fbefcc", "accent_lo": "#cdb26a", "accent_deep": "#352c12", "accent_rgb": "241, 220, 160", "ink": "#1a1200", "wing": "#0d2a22", "wing2": "#091e18", "wing3": "#071612", "bg": "#040c0a", "surface": "#0c1b17", "surface2": "#152924", "surface3": "#19352d", "surface4": "#28413a", "felt_ink": "#e7eeec", "accent_text": "#f1dca0", "pattern": "repeating-conic-gradient(from 45deg, rgba(241, 220, 160, 0.05) 0 25%, transparent 0 50%)", "pattern_size": "22px 22px"} },
  { id: "burgundy", name: "Burgundy & ivory", description: "Burgundy felt quilted in ivory thread, like a members' club.", css: {"felt": "#6b1f36", "felt2": "#521729", "felt3": "#2c0b16", "accent": "#f4ead2", "accent_hi": "#fffaf0", "accent_lo": "#d6c8a4", "accent_deep": "#3a3020", "accent_rgb": "244, 234, 210", "ink": "#1a1200", "wing": "#2a121a", "wing2": "#1e0d13", "wing3": "#16090e", "bg": "#0c0508", "surface": "#1b0e13", "surface2": "#29191f", "surface3": "#351e25", "surface4": "#412c33", "felt_ink": "#f0e9eb", "accent_text": "#f4ead2", "pattern": "repeating-linear-gradient(60deg, rgba(244, 234, 210, 0.05) 0 1px, transparent 1px 18px), repeating-linear-gradient(-60deg, rgba(244, 234, 210, 0.05) 0 1px, transparent 1px 18px)", "pattern_size": "auto, auto"} },
  { id: "noir", name: "Riviera noir", description: "Black baize, silver rails and champagne pinstripes: a seaside salon after midnight.", css: {"felt": "#26282e", "felt2": "#1c1d22", "felt3": "#0f1013", "accent": "#e8d7a8", "accent_hi": "#f7eed6", "accent_lo": "#b9a97e", "accent_deep": "#2e2a1e", "accent_rgb": "232, 215, 168", "ink": "#1a1200", "wing": "#18191d", "wing2": "#111215", "wing3": "#0c0c0e", "bg": "#070708", "surface": "#111113", "surface2": "#1d1e21", "surface3": "#242428", "surface4": "#313236", "felt_ink": "#e9eaea", "accent_text": "#e8d7a8", "pattern": "repeating-linear-gradient(90deg, rgba(232, 215, 168, 0.07) 0 1px, transparent 1px 14px), repeating-linear-gradient(90deg, rgba(200, 204, 216, 0.04) 0 1px, transparent 1px 7px)", "pattern_size": "auto, auto"} },
  { id: "jade", name: "Imperial jade", description: "Deep jade felt, red-gold trim and rolling auspicious clouds.", css: {"felt": "#0c6655", "felt2": "#084e41", "felt3": "#032a23", "accent": "#f2c14e", "accent_hi": "#fbe3a0", "accent_lo": "#d39a22", "accent_deep": "#3d2a08", "accent_rgb": "242, 193, 78", "ink": "#1a1200", "wing": "#0e2a26", "wing2": "#0a1f1c", "wing3": "#071614", "bg": "#040c0b", "surface": "#0c1b19", "surface2": "#162a27", "surface3": "#1a3531", "surface4": "#29413e", "felt_ink": "#e7f0ee", "accent_text": "#f2c14e", "pattern": "radial-gradient(circle at 50% 100%, transparent 0 7px, rgba(242, 193, 78, 0.09) 7px 8px, transparent 8.5px 11px, rgba(242, 193, 78, 0.06) 11px 12px, transparent 12.5px), radial-gradient(circle at 0 50%, transparent 0 7px, rgba(242, 193, 78, 0.09) 7px 8px, transparent 8.5px 11px, rgba(242, 193, 78, 0.06) 11px 12px, transparent 12.5px), radial-gradient(circle at 100% 50%, transparent 0 7px, rgba(242, 193, 78, 0.09) 7px 8px, transparent 8.5px 11px, rgba(242, 193, 78, 0.06) 11px 12px, transparent 12.5px)", "pattern_size": "28px 28px, 28px 28px, 28px 28px"} },
  { id: "deco", name: "Gilded deco", description: "Jazz-age black lacquer with gold sunburst fans.", css: {"felt": "#24211b", "felt2": "#1a1814", "felt3": "#0e0d0b", "accent": "#e9c46a", "accent_hi": "#f6e2a8", "accent_lo": "#c49a3c", "accent_deep": "#33270c", "accent_rgb": "233, 196, 106", "ink": "#1a1200", "wing": "#1b1914", "wing2": "#13110e", "wing3": "#0d0c0a", "bg": "#070706", "surface": "#12110f", "surface2": "#1f1d1a", "surface3": "#262420", "surface4": "#34322e", "felt_ink": "#e9e9e8", "accent_text": "#e9c46a", "pattern": "repeating-conic-gradient(from -90deg at 50% 100%, rgba(233, 196, 106, 0.1) 0 3deg, transparent 3deg 15deg), radial-gradient(circle at 50% 100%, transparent 0 19px, rgba(233, 196, 106, 0.1) 19px 20px, transparent 20.5px)", "pattern_size": "48px 24px, 48px 24px"} },
  { id: "marigold", name: "Marigold masala", description: "Magenta silk felt, saffron gold and a scatter of paisley buds — the big-screen wedding table.", css: {"felt": "#7c1452", "felt2": "#5e0f3e", "felt3": "#320822", "accent": "#ffa21f", "accent_hi": "#ffd08a", "accent_lo": "#e07b00", "accent_deep": "#3d2306", "accent_rgb": "255, 162, 31", "ink": "#1f0f00", "wing": "#2b0c1f", "wing2": "#1f0816", "wing3": "#160610", "bg": "#0c0309", "surface": "#1b0b15", "surface2": "#2a1422", "surface3": "#36182a", "surface4": "#422738", "felt_ink": "#f2e8ee", "accent_text": "#ffa21f", "pattern": "radial-gradient(5px 8px at 30% 38%, rgba(255, 162, 31, 0.12) 98%, transparent 100%), radial-gradient(circle at 36% 22%, rgba(255, 162, 31, 0.1) 0 2px, transparent 2.5px), radial-gradient(4px 6px at 78% 80%, rgba(255, 208, 138, 0.09) 98%, transparent 100%), radial-gradient(circle at 74% 66%, rgba(255, 208, 138, 0.08) 0 1.5px, transparent 2px)", "pattern_size": "40px 40px, 40px 40px, 40px 40px, 40px 40px"} },
  { id: "diwali", name: "Festival of lights", description: "Deep maroon felt, diya-gold flames and a rangoli of dots.", css: {"felt": "#6a1424", "felt2": "#510f1b", "felt3": "#2b070e", "accent": "#ffbf3c", "accent_hi": "#ffe39a", "accent_lo": "#e09612", "accent_deep": "#3d2808", "accent_rgb": "255, 191, 60", "ink": "#1a1200", "wing": "#260b10", "wing2": "#1b080c", "wing3": "#130508", "bg": "#0a0304", "surface": "#180a0d", "surface2": "#261418", "surface3": "#31171c", "surface4": "#3e262a", "felt_ink": "#f0e8e9", "accent_text": "#ffbf3c", "pattern": "radial-gradient(circle at 25% 25%, rgba(255, 191, 60, 0.16) 0 1.5px, transparent 2px), radial-gradient(circle at 75% 75%, rgba(255, 191, 60, 0.16) 0 1.5px, transparent 2px), radial-gradient(circle at 75% 25%, rgba(255, 120, 160, 0.1) 0 1px, transparent 1.5px), radial-gradient(circle at 25% 75%, rgba(255, 120, 160, 0.1) 0 1px, transparent 1.5px), repeating-linear-gradient(45deg, rgba(255, 191, 60, 0.04) 0 1px, transparent 1px 13px)", "pattern_size": "18px 18px, 18px 18px, 18px 18px, 18px 18px, auto"} },
  { id: "cyber", name: "Cyber grid", description: "Graphite felt traced with a teal circuit grid and magenta nodes.", css: {"felt": "#1f2a33", "felt2": "#172029", "felt3": "#0c1116", "accent": "#2ff3e0", "accent_hi": "#a6fff6", "accent_lo": "#12bfae", "accent_deep": "#0a3330", "accent_rgb": "47, 243, 224", "ink": "#00201d", "wing": "#141b22", "wing2": "#0f141a", "wing3": "#0a0e12", "bg": "#06080a", "surface": "#0f1317", "surface2": "#1b2025", "surface3": "#20262d", "surface4": "#2e343a", "felt_ink": "#e9eaeb", "accent_text": "#2ff3e0", "pattern": "linear-gradient(rgba(47, 243, 224, 0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(47, 243, 224, 0.07) 1px, transparent 1px), radial-gradient(circle at 1px 1px, rgba(255, 60, 200, 0.28) 0 1.5px, transparent 2px)", "pattern_size": "22px 22px, 22px 22px, 44px 44px"} },
  { id: "arcade", name: "Pixel arcade", description: "Cabinet-black felt on a neon-green pixel grid, coin-yellow chips.", css: {"felt": "#14201a", "felt2": "#0f1813", "felt3": "#070b09", "accent": "#39ff6a", "accent_hi": "#b3ffc6", "accent_lo": "#12d14a", "accent_deep": "#0b3315", "accent_rgb": "57, 255, 106", "ink": "#002a0c", "wing": "#111a15", "wing2": "#0c130f", "wing3": "#080d0a", "bg": "#040706", "surface": "#0d120f", "surface2": "#181f1b", "surface3": "#1d2521", "surface4": "#2b332f", "felt_ink": "#e8e9e8", "accent_text": "#39ff6a", "pattern": "linear-gradient(rgba(57, 255, 106, 0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(57, 255, 106, 0.07) 1px, transparent 1px), repeating-conic-gradient(rgba(57, 255, 106, 0.05) 0 25%, transparent 0 50%)", "pattern_size": "8px 8px, 8px 8px, 32px 32px"} },
  { id: "sakura", name: "Sakura night", description: "Indigo felt under drifting blossom-pink petals.", css: {"felt": "#26306e", "felt2": "#1c2455", "felt3": "#0f1433", "accent": "#ffa3c7", "accent_hi": "#ffd6e6", "accent_lo": "#e8749f", "accent_deep": "#3d1828", "accent_rgb": "255, 163, 199", "ink": "#2a0614", "wing": "#161a38", "wing2": "#10132a", "wing3": "#0b0d1e", "bg": "#060710", "surface": "#101222", "surface2": "#1c1f35", "surface3": "#222542", "surface4": "#30334e", "felt_ink": "#e9eaf0", "accent_text": "#ffa3c7", "pattern": "radial-gradient(4px 7px at 22% 30%, rgba(255, 163, 199, 0.16) 98%, transparent 100%), radial-gradient(7px 4px at 68% 72%, rgba(255, 214, 230, 0.12) 98%, transparent 100%), radial-gradient(circle at 86% 18%, rgba(255, 163, 199, 0.12) 0 1.5px, transparent 2px), radial-gradient(circle at 40% 88%, rgba(255, 163, 199, 0.09) 0 1px, transparent 1.5px)", "pattern_size": "52px 52px, 52px 52px, 52px 52px, 52px 52px"} },
  { id: "arctic", name: "Glacier", description: "Glacier-blue felt with silver frost crystals, like a table carved in ice.", css: {"felt": "#164e6c", "felt2": "#103c54", "felt3": "#082233", "accent": "#d8ecf6", "accent_hi": "#f4fbff", "accent_lo": "#a9c6d6", "accent_deep": "#1d2c35", "accent_rgb": "216, 236, 246", "ink": "#0a1a24", "wing": "#0f2433", "wing2": "#0b1a25", "wing3": "#08131b", "bg": "#040a0f", "surface": "#0d1820", "surface2": "#172530", "surface3": "#1b2f3d", "surface4": "#293c49", "felt_ink": "#e8edf0", "accent_text": "#d8ecf6", "pattern": "repeating-linear-gradient(60deg, rgba(216, 236, 246, 0.06) 0 1px, transparent 1px 16px), repeating-linear-gradient(-60deg, rgba(216, 236, 246, 0.06) 0 1px, transparent 1px 16px), repeating-linear-gradient(0deg, rgba(216, 236, 246, 0.04) 0 1px, transparent 1px 14px)", "pattern_size": "auto, auto, auto"} },
  { id: "oasis", name: "Desert oasis", description: "Turquoise pool felt framed in sand gold, laid with star-and-diamond tiles.", css: {"felt": "#0d5c63", "felt2": "#09464c", "felt3": "#04262a", "accent": "#f0cf8e", "accent_hi": "#faeacb", "accent_lo": "#cfa75a", "accent_deep": "#3a2b10", "accent_rgb": "240, 207, 142", "ink": "#1a1200", "wing": "#2a2117", "wing2": "#1f1811", "wing3": "#16110c", "bg": "#0c0907", "surface": "#1b1611", "surface2": "#2a241d", "surface3": "#352c23", "surface4": "#413931", "felt_ink": "#e7efef", "accent_text": "#f0cf8e", "pattern": "repeating-conic-gradient(from 45deg, rgba(240, 207, 142, 0.07) 0 25%, transparent 0 50%), radial-gradient(circle, transparent 0 5px, rgba(240, 207, 142, 0.1) 5px 6px, transparent 6.5px)", "pattern_size": "24px 24px, 24px 24px"} },
  { id: "abyss", name: "Ocean abyss", description: "Deep-sea teal with bioluminescent aqua sparks and rising bubbles.", css: {"felt": "#08424f", "felt2": "#063440", "felt3": "#021c24", "accent": "#5cf2ff", "accent_hi": "#b9faff", "accent_lo": "#22c3d6", "accent_deep": "#08323a", "accent_rgb": "92, 242, 255", "ink": "#00222a", "wing": "#0a2128", "wing2": "#07181d", "wing3": "#051115", "bg": "#03090c", "surface": "#0a161a", "surface2": "#132428", "surface3": "#162c33", "surface4": "#253940", "felt_ink": "#e6eced", "accent_text": "#5cf2ff", "pattern": "radial-gradient(circle at 30% 30%, rgba(92, 242, 255, 0.16) 0 1.5px, transparent 2px), radial-gradient(circle at 75% 62%, rgba(92, 242, 255, 0.1) 0 1px, transparent 1.5px), radial-gradient(circle at 55% 88%, transparent 0 4px, rgba(92, 242, 255, 0.08) 4px 5px, transparent 5.5px)", "pattern_size": "40px 40px, 40px 40px, 40px 40px"} },
  { id: "volcano", name: "Volcano", description: "Charcoal basalt felt split by glowing lava seams.", css: {"felt": "#2e2420", "felt2": "#221b18", "felt3": "#120e0c", "accent": "#ff6a1f", "accent_hi": "#ffb07a", "accent_lo": "#e04a00", "accent_deep": "#3d1806", "accent_rgb": "255, 106, 31", "ink": "#1f0800", "wing": "#211b18", "wing2": "#181311", "wing3": "#110d0c", "bg": "#090707", "surface": "#161211", "surface2": "#241f1d", "surface3": "#2c2624", "surface4": "#393431", "felt_ink": "#eae9e9", "accent_text": "#ff7831", "pattern": "repeating-linear-gradient(115deg, transparent 0 18px, rgba(255, 106, 31, 0.1) 18px 19px, transparent 19px 31px), repeating-linear-gradient(35deg, transparent 0 23px, rgba(255, 106, 31, 0.07) 23px 24px, transparent 24px 41px)", "pattern_size": "auto, auto"} },
  { id: "galaxy", name: "Galaxy", description: "Deep-space purple felt scattered with a cyan starfield.", css: {"felt": "#2a1a55", "felt2": "#1e1240", "felt3": "#0d0823", "accent": "#59e3ff", "accent_hi": "#b5f3ff", "accent_lo": "#1fb5db", "accent_deep": "#0d3340", "accent_rgb": "89, 227, 255", "ink": "#001d26", "wing": "#171230", "wing2": "#100c22", "wing3": "#0b0818", "bg": "#06040d", "surface": "#100d1d", "surface2": "#1c182d", "surface3": "#231e3a", "surface4": "#312c47", "felt_ink": "#eae8ee", "accent_text": "#59e3ff", "pattern": "radial-gradient(circle at 12% 18%, rgba(255, 255, 255, 0.34) 0 1px, transparent 1.5px), radial-gradient(circle at 68% 42%, rgba(89, 227, 255, 0.3) 0 1px, transparent 1.5px), radial-gradient(circle at 38% 78%, rgba(255, 255, 255, 0.2) 0 0.8px, transparent 1.3px), radial-gradient(circle at 88% 86%, rgba(200, 160, 255, 0.24) 0 1.2px, transparent 1.8px)", "pattern_size": "64px 64px, 64px 64px, 64px 64px, 64px 64px"} },
  { id: "riverboat", name: "Riverboat mahogany", description: "Paddle-steamer mahogany grain with polished brass and ivory chips.", css: {"felt": "#5a2e1c", "felt2": "#45230f", "felt3": "#26130a", "accent": "#d9a648", "accent_hi": "#f0d08c", "accent_lo": "#b0802a", "accent_deep": "#33230a", "accent_rgb": "217, 166, 72", "ink": "#1a1200", "wing": "#24150e", "wing2": "#1a0f0a", "wing3": "#120a07", "bg": "#0a0604", "surface": "#170f0c", "surface2": "#251b16", "surface3": "#2f211a", "surface4": "#3c2f29", "felt_ink": "#eeeae8", "accent_text": "#d9a648", "pattern": "repeating-linear-gradient(92deg, rgba(0, 0, 0, 0.12) 0 2px, transparent 2px 9px, rgba(217, 166, 72, 0.06) 9px 10px, transparent 10px 17px)", "pattern_size": "auto"} },
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

/** The casino table the host played last: the top bar's Casino key and the library's Casino chip reopen it. */
const LAST_CASINO = "deskdot.casino.last";
export function rememberCasino(id: string) {
  try {
    localStorage.setItem(LAST_CASINO, id);
  } catch {
    /* private mode */
  }
}

/**
 * Enter casino mode from anywhere, with the coin drop: back into the table that's on the panel, or put the last
 * casino table (Roulette the first time) on the panel first.
 */
export async function openCasino() {
  playCoinDrop();
  const s = useStore.getState();
  const apps = s.meta?.apps ?? [];
  const cur = s.state?.engine.current?.app;
  if (cur && apps.find((a) => a.id === cur)?.category === "casino") return enterCasino();
  let last = "casino_roulette";
  try {
    last = localStorage.getItem(LAST_CASINO) || last;
  } catch {
    /* private mode */
  }
  const id = apps.some((a) => a.id === last) ? last : apps.find((a) => a.category === "casino")?.id;
  if (!id) return;
  try {
    await api.activate(id);
    enterCasino();
  } catch {
    /* the api layer shows the error */
  }
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
  if (!id) {
    casinoAlert("No casino table is showing");
    throw new Error("no casino table is showing");
  }
  // Not api.action: its errors go to the corner toast, which the host doesn't see over the table. Host ops answer
  // HTTP 400 on bad input; play ops (bet, unbet, …, the host's own seat) answer 200 with {ok: false, error} — the
  // engine's note for the host pid. Both become the centred casino alert (alert.tsx), and the promise rejects.
  let r: Response;
  try {
    r = await fetch(`/api/apps/${id}/actions/casino`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ op, ...payload }),
    });
  } catch (e) {
    casinoAlert("Can't reach DeskDot — is it still running?");
    throw e;
  }
  if (!r.ok) {
    let detail = r.statusText || `Request failed (${r.status})`;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : (j.detail?.[0]?.msg ?? detail);
    } catch {
      /* not json */
    }
    casinoAlert(detail);
    throw new Error(detail);
  }
  const res = ((await r.json()) as { result: T }).result;
  if (op !== "view") refreshView().catch(() => undefined);
  const rr = res as unknown as { ok?: unknown; error?: unknown } | null;
  if (op !== "view" && op !== "verify" && rr && rr.ok === false) {
    const msg = typeof rr.error === "string" && rr.error ? rr.error : "That didn't work";
    casinoAlert(msg);
    throw new Error(msg);
  }
  return res;
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

/** Seconds left on a status countdown: to its `status.clock` anchor on the shared clock when there is one (every
 * device flips at the same moment), else counted down locally since the status arrived. */
export function secondsLeft(v: number | null | undefined, at: number, anchor?: number | null): number | null {
  if (v == null) return null;
  if (anchor != null) return untilAnchor(anchor);
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
/** CSS variables for `.cz` from the status's table theme (classic: only the felt pattern — the stylesheet is the classic look). */
export function themeVars(t: TableTheme | null | undefined): CSSProperties | undefined {
  if (!t || !t.css) return undefined;
  const c = t.css;
  // the felt's motif (pure CSS gradients, one background-size entry per layer): every theme, classic included
  const pat: Record<string, string | undefined> = { "--cz-pat": c.pattern, "--cz-pat-size": c.pattern_size };
  if (t.id === "classic") return Object.fromEntries(Object.entries(pat).filter(([, x]) => !!x)) as CSSProperties;
  const v: Record<string, string | undefined> = {
    ...pat,
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
