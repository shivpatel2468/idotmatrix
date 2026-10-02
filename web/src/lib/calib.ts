/**
 * Panel colour calibration, mirrored from `src/deskdot/gfx/calib.py` so the studio preview can show exactly what
 * the panel is sent (and the wizard can sketch A/B candidates locally). Keep the maths in lock-step with Python:
 * `tests/test_calibration.py` pins golden LUT values (GOLDEN below) — change both together.
 * Rounding: Python rounds half-to-even, JS half-up, so a rare level can differ by 1. Invisible on the preview.
 */

export type Calib = {
  red: number;
  green: number;
  blue: number;
  gamma: number;
  gamma_red: number;
  gamma_green: number;
  gamma_blue: number;
  black_level: number;
  lift: number;
  saturation: number;
  contrast: number;
  temperature: number;
  level: number;
  dither: boolean;
  preset: string;
};

export const NEUTRAL_K = 6500;

export const IDENTITY: Calib = {
  red: 1, green: 1, blue: 1, gamma: 1, gamma_red: 1, gamma_green: 1, gamma_blue: 1,
  black_level: 0, lift: 0, saturation: 1, contrast: 1, temperature: NEUTRAL_K, level: 1, dither: false, preset: "",
};

/** Merge whatever the engine sent (older engines send fewer keys) over the identity. */
export function toCalib(raw: unknown): Calib {
  const out: Calib = { ...IDENTITY };
  if (raw && typeof raw === "object") {
    for (const k of Object.keys(IDENTITY) as (keyof Calib)[]) {
      const v = (raw as Record<string, unknown>)[k];
      if (v !== undefined && v !== null && typeof v === typeof IDENTITY[k]) (out as Record<string, unknown>)[k] = v;
    }
  }
  return out;
}

export function isIdentity(c: Calib): boolean {
  return (Object.keys(IDENTITY) as (keyof Calib)[]).every((k) => k === "preset" || c[k] === IDENTITY[k]);
}

/** The fields that change the picture (preset is just a tag). */
export function sameLook(a: Calib, b: Calib): boolean {
  return (Object.keys(IDENTITY) as (keyof Calib)[]).every((k) => k === "preset" || Math.abs(+a[k] - +b[k]) < 1e-6);
}

const r4 = (x: number) => Math.round(x * 1e4) / 1e4;

function blackbody(kelvin: number): [number, number, number] {
  const k = Math.max(1000, Math.min(40000, kelvin)) / 100;
  const r = k <= 66 ? 255 : 329.698727446 * (k - 60) ** -0.1332047592;
  const g = k <= 66 ? 99.4708025861 * Math.log(k) - 161.1195681661 : 288.1221695283 * (k - 60) ** -0.0755148492;
  const b = k >= 66 ? 255 : k <= 19 ? 0 : 138.5177312231 * Math.log(k - 10) - 305.0447927307;
  const c = (v: number) => Math.max(1, Math.min(255, v));
  return [c(r), c(g), c(b)];
}

/** RGB multipliers that move white from 6500 K to `kelvin` (max channel = 1: never brightens). */
export function kelvinGains(kelvin: number): [number, number, number] {
  if (Math.round(kelvin) === NEUTRAL_K) return [1, 1, 1];
  const a = blackbody(kelvin), b = blackbody(NEUTRAL_K);
  const rel = a.map((x, i) => x / b[i]);
  const top = Math.max(...rel);
  return [r4(rel[0] / top), r4(rel[1] / top), r4(rel[2] / top)];
}

/** Final per-channel gain: white balance × colour temperature × peak level. */
export function channelGains(c: Calib): [number, number, number] {
  const t = kelvinGains(c.temperature);
  return [c.red * t[0] * c.level, c.green * t[1] * c.level, c.blue * t[2] * c.level];
}

/** (3 × 256) drive levels before rounding: contrast S-curve, gamma, gain, lift, black cut. */
export function lutF(c: Calib): Float64Array[] {
  const gains = channelGains(c).map(r4);
  const gch = [r4(c.gamma_red), r4(c.gamma_green), r4(c.gamma_blue)];
  const gamma = r4(c.gamma), contrast = r4(c.contrast);
  const out = [new Float64Array(256), new Float64Array(256), new Float64Array(256)];
  for (let i = 0; i < 256; i++) {
    let x = i / 255;
    if (contrast !== 1) {
      const a = x ** contrast, b = (1 - x) ** contrast;
      x = a / (a + b);
    }
    for (let ch = 0; ch < 3; ch++) {
      let v = x ** (gamma * gch[ch]) * gains[ch] * 255;
      v = v > 0.5 ? c.lift + (v * (255 - c.lift)) / 255 : 0;
      if (i < c.black_level) v = 0;
      out[ch][i] = Math.max(0, Math.min(255, Math.fround(v)));
    }
  }
  return out;
}

export function lut(c: Calib): Uint8Array[] {
  return lutF(c).map((t) => Uint8Array.from(t, (v) => Math.round(v)));
}

const BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]].map((r) => r.map((v) => (v + 0.5) / 16 - 0.5));

/** A reusable transform for a calibration: rgb (w×h×3, row-major) → calibrated copy. */
export function calibrator(c: Calib, width = 32): (rgb: Uint8Array, out?: Uint8Array) => Uint8Array {
  if (isIdentity(c)) return (rgb) => rgb;
  const tf = c.dither ? lutF(c) : null;
  const t8 = c.dither ? null : lut(c);
  const sat = c.saturation;
  return (rgb, out = new Uint8Array(rgb.length)) => {
    for (let p = 0; p < rgb.length; p += 3) {
      let r = rgb[p], g = rgb[p + 1], b = rgb[p + 2];
      if (sat !== 1) {
        const grey = (r + g + b) / 3;
        const s = (v: number) => Math.max(0, Math.min(255, Math.round(grey + (v - grey) * sat)));
        r = s(r); g = s(g); b = s(b);
      }
      if (t8) {
        out[p] = t8[0][r]; out[p + 1] = t8[1][g]; out[p + 2] = t8[2][b];
      } else {
        const px = (p / 3) | 0;
        const thr = BAYER4[Math.floor(px / width) % 4][(px % width) % 4];
        const d = (v: number) => (v > 0 ? Math.max(1, Math.min(255, Math.round(v + thr))) : 0);
        out[p] = d(tf![0][r]); out[p + 1] = d(tf![1][g]); out[p + 2] = d(tf![2][b]);
      }
    }
    return out;
  };
}

/** Golden values shared with tests/test_calibration.py. */
export const GOLDEN = {
  calib: { ...IDENTITY, gamma: 1.7, red: 0.95, blue: 0.9, lift: 3, black_level: 2, contrast: 1.15, temperature: 5000, gamma_blue: 1.1, level: 0.9 },
  idx: [0, 1, 2, 8, 32, 64, 128, 192, 255],
  lut: [[0, 0, 0, 0, 7, 20, 70, 145, 218], [0, 0, 0, 0, 7, 19, 66, 137, 207], [0, 0, 0, 0, 5, 13, 49, 109, 171]],
};

/** Dev self-check: `calibSelfTest()` in the console returns true when the port matches Python's golden LUT. */
export function calibSelfTest(): boolean {
  const t = lut(GOLDEN.calib);
  return GOLDEN.lut.every((row, ch) => row.every((v, i) => t[ch][GOLDEN.idx[i]] === v));
}

// ---------------------------------------------------------------------------------------------- field metadata
export type FieldKey = Exclude<keyof Calib, "dither" | "preset">;
export type FieldMeta = { key: FieldKey; label: string; min: number; max: number; step: number; unit?: string; hint: string };

export const FIELDS: FieldMeta[] = [
  { key: "gamma", label: "Gamma", min: 0.5, max: 2.5, step: 0.05, hint: "Mid-tone brightness. Higher = darker mid-greys; LEDs usually want 1.4–1.9." },
  { key: "black_level", label: "Black cutoff", min: 0, max: 40, step: 1, hint: "Input levels below this switch the LED fully off — hides a faint glow in blacks." },
  { key: "lift", label: "Shadow lift", min: 0, max: 40, step: 1, hint: "Raises the dimmest visible level so dark details don't vanish." },
  { key: "contrast", label: "Contrast", min: 0.6, max: 1.6, step: 0.01, hint: "An S-curve around mid-grey. Black and white never move." },
  { key: "saturation", label: "Saturation", min: 0, max: 2, step: 0.05, hint: "Colour intensity. Too high and neighbouring colours bleed together." },
  { key: "temperature", label: "Colour temperature", min: 3000, max: 9500, step: 100, unit: " K", hint: "6500 K = neutral. Lower is warmer (amber), higher is cooler (blue)." },
  { key: "level", label: "Peak level", min: 0.5, max: 1, step: 0.01, hint: "Caps the brightest drive level: less glare without touching the panel brightness." },
  { key: "red", label: "Red gain", min: 0.3, max: 1.2, step: 0.01, hint: "White balance: how hard the red LEDs are driven." },
  { key: "green", label: "Green gain", min: 0.3, max: 1.2, step: 0.01, hint: "White balance: green. Lower it if whites look minty." },
  { key: "blue", label: "Blue gain", min: 0.3, max: 1.2, step: 0.01, hint: "White balance: blue. Most LED panels run blue-hot, so this is often below 1." },
  { key: "gamma_red", label: "Red gamma", min: 0.7, max: 1.4, step: 0.01, hint: "Per-channel gamma multiplier: fixes a tint that only shows in dark greys." },
  { key: "gamma_green", label: "Green gamma", min: 0.7, max: 1.4, step: 0.01, hint: "Per-channel gamma multiplier for green." },
  { key: "gamma_blue", label: "Blue gamma", min: 0.7, max: 1.4, step: 0.01, hint: "Per-channel gamma multiplier for blue (dark greys look blue? raise it a little)." },
];

// ---------------------------------------------------------------------------------------------- API types
export type CalibPreset = {
  id: string;
  name: string;
  group: "claude" | "inspired" | "standard";
  blurb: string;
  values: Partial<Calib>;
  swatches: string[];
};
export type PresetListing = { presets: CalibPreset[]; groups: Record<string, string>; disclaimer: string; current: string };
export type VideoInfo = { id: string; name: string; hint: string };
export type CalTest = {
  video: string;
  a: Calib;
  b?: Calib | null;
  layout?: "ab" | "wipe";
  split?: number;
  labels?: [string, string] | null;
  seconds?: number;
};
export type MotionCfg = { fps: number; speed: number; soft: boolean; smoothing: number; transition: "cut" | "push" | "fade" | "wipe" };
export type MotionPreset = { id: string; name: string; blurb: string; max_fps: number; packet_gap_ms: number; transition: MotionCfg["transition"]; smoothing: number };
export type MotionInfo = {
  presets: MotionPreset[];
  limits: {
    stream_fps_max: number; stream_fps_min: number; clip_fps_max: number; gif_budget_kb: number; frames_in_flight: number;
    packet_gap_min_ms: number; packet_gap_verified_ms: number; one_packet_bytes: number; measured_ui_fps: number;
    measured_photo_fps: number; device: string;
  };
  current: { max_fps: number; packet_gap_ms: number; smoothing: number; transition: MotionCfg["transition"]; preset: string | null };
  tests: VideoInfo[];
};
export type MotionTest = { test: string; a: MotionCfg; b?: MotionCfg | null; layout?: "stack" | "alternate"; mode?: "stream" | "clip"; seconds?: number };
export type Autotune = MotionPreset & { measured_fps: number; frame_bytes: number };

export const DEFAULT_MOTION: MotionCfg = { fps: 8, speed: 8, soft: false, smoothing: 0, transition: "cut" };

// ---------------------------------------------------------------------------------------------- A/B search
/**
 * A converging A/B search (like an eye test): show c−d and c+d; the pick moves c halfway towards it and halves d.
 * "Same" stops early — both are equally close, so the centre is the answer.
 */
export type Search = { c: number; d: number; round: number; rounds: number; min: number; max: number; int?: boolean; done?: boolean };

export function startSearch(min: number, max: number, rounds: number, int = false, centre?: number): Search {
  const c = centre ?? (min + max) / 2;
  return { c, d: (max - min) / 4, round: 0, rounds, min, max, int };
}

const clampTo = (s: Search, v: number) => {
  const x = Math.max(s.min, Math.min(s.max, v));
  return s.int ? Math.round(x) : Math.round(x * 1000) / 1000;
};

export function candidates(s: Search): [number, number] {
  return [clampTo(s, s.c - s.d), clampTo(s, s.c + s.d)];
}

export function choose(s: Search, pick: "a" | "b" | "same"): Search {
  if (pick === "same") return { ...s, c: clampTo(s, s.c), done: true };
  const [a, b] = candidates(s);
  const c = pick === "a" ? a : b; // the answer lies in the half around the pick
  const round = s.round + 1;
  return { ...s, c: clampTo(s, c), d: s.d / 2, round, done: round >= s.rounds };
}

export const result = (s: Search) => clampTo(s, s.c);
