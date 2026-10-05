/**
 * Studio sound effects — every one synthesized live with the Web Audio API (oscillators, a shared noise buffer,
 * filters and envelopes). No audio files, nothing sampled or copied, no dependencies.
 *
 *   sfx("coin-insert")            play one effect (dropped while muted, while the tab is hidden, or before the
 *                                 first user gesture — the browser's autoplay rule)
 *   sfx("chip", { pan: -0.3 })    optional stereo pan −1…1 and volume 0…1 (× the master volume)
 *
 * Preferences (master volume, mute, per-category switches, "mute when the tab is hidden") persist per browser in
 * localStorage `deskdot.sound`; Settings → Display → Sound edits them (`getSound` / `setSound` / `onSound`).
 * Polyphony is capped (oldest voice fades out) and every effect has a minimum gap between repeats.
 * docs/STUDIO_UI.md "Sound" lists every effect and every trigger point.
 */
export type SfxName =
  // intro / outro (components/Boot.tsx, components/boot/*)
  | "boot-hum" | "door-open" | "door-close" | "logo-buzz"
  | "coin-insert" | "coin-drop" | "coin-roll" | "gate-unlock" | "gate-open" | "gate-close"
  // studio UI
  | "click" | "toggle" | "tab" | "sheet-open" | "sheet-close" | "toast" | "error" | "success" | "app-switch"
  | "playlist-next" | "playlist-prev"
  // casino (studio)
  | "chip" | "chips-stack" | "no-more-bets" | "wheel-spin" | "ball-drop" | "card-deal" | "card-flip"
  | "dice-roll" | "reel-spin" | "reel-stop" | "win" | "big-win" | "lose" | "bingo-call" | "bingo-win"
  | "round-open" | "tick"
  // games / fly
  | "fly-buzz" | "game-start" | "game-over" | "score";

export type SfxOptions = { pan?: number; volume?: number };

export type SoundCategory = "ui" | "casino" | "intro" | "games";
export type SoundPrefs = {
  on: boolean; // global switch (false = muted)
  volume: number; // master 0..1
  cats: Record<SoundCategory, boolean>;
  hiddenMute: boolean; // silent while the tab is in the background
};

export const SOUND_CATEGORIES: [SoundCategory, string, string][] = [
  ["ui", "Interface", "Soft ticks on keys, tabs and switches; sheets, toasts, app changes"],
  ["casino", "Casino", "Chips, no more bets, wheels, cards, dice, reels, wins"],
  ["intro", "Intro & outro", "The boot show: coins, gates, hums"],
  ["games", "Games & fly", "Game start / over, scoring, the fruit fly's buzz"],
];

const CAT: Record<SfxName, SoundCategory> = {
  "boot-hum": "intro", "door-open": "intro", "door-close": "intro", "logo-buzz": "intro", "coin-insert": "intro",
  "coin-drop": "intro", "coin-roll": "intro", "gate-unlock": "intro", "gate-open": "intro", "gate-close": "intro",
  click: "ui", toggle: "ui", tab: "ui", "sheet-open": "ui", "sheet-close": "ui", toast: "ui", error: "ui",
  success: "ui", "app-switch": "ui", "playlist-next": "ui", "playlist-prev": "ui",
  chip: "casino", "chips-stack": "casino", "no-more-bets": "casino", "wheel-spin": "casino", "ball-drop": "casino",
  "card-deal": "casino", "card-flip": "casino", "dice-roll": "casino", "reel-spin": "casino", "reel-stop": "casino",
  win: "casino", "big-win": "casino", lose: "casino", "bingo-call": "casino", "bingo-win": "casino",
  "round-open": "casino", tick: "casino",
  "fly-buzz": "games", "game-start": "games", "game-over": "games", score: "games",
};
/** Every effect name (for the Settings preview list). */
export const SFX_NAMES = Object.keys(CAT) as SfxName[];
export const sfxCategory = (n: SfxName) => CAT[n];

/** Minimum gap between two plays of the same effect, ms (default 25). */
const GAP: Partial<Record<SfxName, number>> = {
  chip: 40, click: 35, tab: 35, toggle: 35, score: 70, tick: 180, "reel-stop": 60, "card-deal": 60,
  "fly-buzz": 6000, "app-switch": 400, toast: 150, error: 300, success: 300, "sheet-open": 120, "sheet-close": 120,
  "wheel-spin": 1500, "reel-spin": 800, "dice-roll": 500, win: 600, "big-win": 1500, lose: 600, "no-more-bets": 800,
  "round-open": 800, "game-start": 600, "game-over": 1000, "boot-hum": 1000, "gate-open": 800, "gate-close": 800,
};
const MAX_VOICES = 12;

// ------------------------------------------------------------------ preferences
const KEY = "deskdot.sound";
const DEFAULTS: SoundPrefs = { on: true, volume: 0.6, cats: { ui: true, casino: true, intro: true, games: true }, hiddenMute: true };
function load(): SoundPrefs {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<SoundPrefs>;
    const vol = typeof raw.volume === "number" && raw.volume >= 0 && raw.volume <= 1 ? raw.volume : DEFAULTS.volume;
    return {
      on: typeof raw.on === "boolean" ? raw.on : DEFAULTS.on,
      volume: vol,
      cats: { ...DEFAULTS.cats, ...(raw.cats && typeof raw.cats === "object" ? raw.cats : {}) },
      hiddenMute: typeof raw.hiddenMute === "boolean" ? raw.hiddenMute : DEFAULTS.hiddenMute,
    };
  } catch {
    return { ...DEFAULTS, cats: { ...DEFAULTS.cats } };
  }
}
let prefs: SoundPrefs = typeof window === "undefined" ? DEFAULTS : load();
const listeners = new Set<() => void>();

export const getSound = (): SoundPrefs => prefs;
export function setSound(p: Partial<SoundPrefs>) {
  prefs = { ...prefs, ...p, cats: { ...prefs.cats, ...(p.cats ?? {}) } };
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    /* private mode: just won't persist */
  }
  applyMaster();
  listeners.forEach((l) => l());
}
/** Subscribe to preference changes (for useSyncExternalStore). */
export function onSound(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

// ------------------------------------------------------------------ the audio graph
let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let noiseBuf: AudioBuffer | null = null;
let unlocked = false;
let pending: { name: SfxName; opts?: SfxOptions; at: number } | null = null;
const lastAt = new Map<SfxName, number>();
type Voice = { name: SfxName; bus: GainNode; end: number; nodes: AudioScheduledSourceNode[] };
let voices: Voice[] = [];

const hidden = () => typeof document !== "undefined" && document.visibilityState === "hidden";
const masterLevel = () => (prefs.on && !(prefs.hiddenMute && hidden()) ? prefs.volume * prefs.volume * 0.9 : 0); // perceptual curve
function applyMaster() {
  if (!ctx || !master) return;
  master.gain.setTargetAtTime(masterLevel(), ctx.currentTime, 0.03);
}

function ensureCtx(): AudioContext | null {
  if (ctx) return ctx;
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return null;
    ctx = new AC({ latencyHint: "interactive" });
    const comp = ctx.createDynamicsCompressor(); // a safety limiter: stacked effects never clip
    comp.threshold.value = -10;
    comp.knee.value = 8;
    comp.ratio.value = 6;
    comp.attack.value = 0.003;
    comp.release.value = 0.15;
    master = ctx.createGain();
    master.gain.value = masterLevel();
    master.connect(comp).connect(ctx.destination);
    const n = Math.floor(ctx.sampleRate * 1.5);
    noiseBuf = ctx.createBuffer(1, n, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
  } catch {
    ctx = null;
  }
  return ctx;
}

/** Every gesture (re)starts the context: the first one creates it, later ones revive a suspended one. */
function unlock() {
  if (unlocked && ctx?.state === "running") return;
  const c = ensureCtx();
  if (!c) return;
  const go = () => {
    if (c.state !== "running") return;
    unlocked = true;
    applyMaster();
    // a call made just before the gesture (e.g. the intro starting) still plays — only the latest, only if fresh
    const p = pending;
    pending = null;
    if (p && performance.now() - p.at < 300) sfx(p.name, p.opts);
  };
  if (c.state === "running") go();
  else c.resume().then(go).catch(() => undefined);
}
const GESTURES = ["pointerdown", "keydown", "touchstart"] as const;
if (typeof window !== "undefined") {
  for (const e of GESTURES) window.addEventListener(e, unlock, { capture: true, passive: true });
  document.addEventListener("visibilitychange", applyMaster);
}

/** Was `name` played in the last `ms`? (Lets watchers avoid doubling a sound a key already made.) */
export function recentlyPlayed(name: SfxName, ms: number): boolean {
  return performance.now() - (lastAt.get(name) ?? -1e9) < ms;
}

/** Stop a long effect (a wheel spin when the result arrives early, a shutter…), or everything. */
export function stopSfx(name?: SfxName) {
  if (!ctx) return;
  const now = ctx.currentTime;
  voices = voices.filter((v) => {
    if (name && v.name !== name) return true;
    v.bus.gain.setTargetAtTime(0, now, 0.03);
    v.nodes.forEach((s) => { try { s.stop(now + 0.2); } catch { /* already stopped */ } });
    return false;
  });
}

// ------------------------------------------------------------------ the public call
/** Play "sheet-open" / "sheet-close" when `open` flips (Sheet, Modal). */
export function sheetSound(open: boolean, was: { current: boolean }) {
  if (open === was.current) return;
  was.current = open;
  sfx(open ? "sheet-open" : "sheet-close");
}

export function sfx(name: SfxName, opts?: SfxOptions): void {
  if (typeof window === "undefined" || !prefs.on || !prefs.cats[CAT[name]] || !(name in FX)) return;
  if (prefs.hiddenMute && hidden()) return;
  const now = performance.now();
  if (!unlocked || !ctx || ctx.state !== "running") {
    pending = { name, opts, at: now }; // only the latest is kept; the next gesture plays it if still fresh
    if (unlocked && ctx?.state === "suspended") ctx.resume().then(unlock).catch(() => undefined);
    return;
  }
  if (now - (lastAt.get(name) ?? -1e9) < (GAP[name] ?? 25)) return;
  lastAt.set(name, now);
  try {
    play(name, opts ?? {});
  } catch {
    /* a broken effect must never break the studio */
  }
}

function play(name: SfxName, o: SfxOptions) {
  const c = ctx!;
  const t0 = c.currentTime + 0.005;
  voices = voices.filter((v) => v.end > t0);
  while (voices.length >= MAX_VOICES) {
    const old = voices.shift()!;
    old.bus.gain.setTargetAtTime(0, t0, 0.02);
    old.nodes.forEach((s) => { try { s.stop(t0 + 0.12); } catch { /* fine */ } });
  }
  const bus = c.createGain();
  bus.gain.value = Math.max(0, Math.min(1, o.volume ?? 1));
  let out: AudioNode = bus;
  if (o.pan && c.createStereoPanner) {
    const p = c.createStereoPanner();
    p.pan.value = Math.max(-1, Math.min(1, o.pan));
    bus.connect(p);
    out = p;
  }
  out.connect(master!);
  const v: Voice = { name, bus, end: t0, nodes: [] };
  const dur = FX[name](new Synth(c, bus, t0, v));
  v.end = t0 + dur + 0.1;
  voices.push(v);
  setTimeout(() => {
    try { out.disconnect(); bus.disconnect(); } catch { /* fine */ }
  }, (dur + 0.4) * 1000);
}

// ------------------------------------------------------------------ synthesis kit
const rnd = (a: number, b: number) => a + Math.random() * (b - a);
const NOTE = (n: number) => 440 * 2 ** ((n - 69) / 12); // MIDI note → Hz

class Synth {
  constructor(readonly c: AudioContext, readonly out: AudioNode, readonly t: number, readonly v: Voice) {}

  /** A gain node with an attack / exponential-decay envelope, starting at `at` (s after the effect start). */
  env(at: number, peak: number, attack: number, decay: number, dest: AudioNode = this.out): GainNode {
    const g = this.c.createGain();
    const s = this.t + at;
    g.gain.setValueAtTime(0.0001, s);
    g.gain.linearRampToValueAtTime(Math.max(0.0002, peak), s + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, s + attack + decay);
    g.connect(dest);
    return g;
  }

  /** One oscillator note; `to` glides the pitch exponentially over the note. */
  tone(at: number, type: OscillatorType, f: number, peak: number, attack: number, decay: number, to?: number, dest?: AudioNode) {
    const o = this.c.createOscillator();
    o.type = type;
    const s = this.t + at;
    o.frequency.setValueAtTime(f, s);
    if (to) o.frequency.exponentialRampToValueAtTime(to, s + attack + decay);
    o.connect(this.env(at, peak, attack, decay, dest));
    o.start(s);
    o.stop(s + attack + decay + 0.05);
    this.v.nodes.push(o);
    return o;
  }

  /** Filtered noise; `to` sweeps the filter frequency. */
  noise(at: number, peak: number, attack: number, decay: number, type: BiquadFilterType, f: number, q = 1, to?: number, dest?: AudioNode) {
    const src = this.c.createBufferSource();
    src.buffer = noiseBuf;
    src.loop = true;
    const fl = this.c.createBiquadFilter();
    fl.type = type;
    fl.Q.value = q;
    const s = this.t + at;
    fl.frequency.setValueAtTime(f, s);
    if (to) fl.frequency.exponentialRampToValueAtTime(to, s + attack + decay);
    src.connect(fl).connect(this.env(at, peak, attack, decay, dest));
    src.start(s, rnd(0, 1));
    src.stop(s + attack + decay + 0.05);
    this.v.nodes.push(src);
    return fl;
  }

  /** A struck metal body: inharmonic partials, the high ones dying first (coins, bells, latches). */
  metal(at: number, f: number, peak: number, decay: number, ratios = [1, 2.76, 5.4, 8.93]) {
    ratios.forEach((r, i) => this.tone(at, "sine", f * r, peak / (1 + i * 0.9), 0.001, decay / (1 + i * 0.8)));
  }

  /** A tiny hard click (plastic, wood, a ratchet tooth). */
  click(at: number, f: number, peak: number, len = 0.012) {
    this.noise(at, peak, 0.0008, len, "bandpass", f, 2.5);
    this.tone(at, "triangle", f * 0.5, peak * 0.35, 0.0005, len * 0.8);
  }

  /** A low body thump (a weight landing, a bolt). */
  thump(at: number, f: number, peak: number, decay = 0.18) {
    this.tone(at, "sine", f, peak, 0.002, decay, f * 0.5);
    this.noise(at, peak * 0.5, 0.001, decay * 0.4, "lowpass", f * 6, 0.7);
  }

  /** A sequence of notes (MIDI numbers), `step` apart. */
  arp(at: number, notes: number[], step: number, type: OscillatorType, peak: number, decay: number, last = decay) {
    notes.forEach((n, i) => {
      const d = i === notes.length - 1 ? last : decay;
      this.tone(at + i * step, type, NOTE(n), peak, 0.004, d);
      this.tone(at + i * step, "sine", NOTE(n) * 2, peak * 0.18, 0.002, d * 0.5); // a little sparkle on top
    });
  }
}

// ------------------------------------------------------------------ the effects (each returns its duration, s)
type Fx = (s: Synth) => number;

/** A shutter of `n` slats rattling past at `rate` slats/s (a rolling gate), with a motor under it. */
function shutter(s: Synth, dur: number, rateFrom: number, rateTo: number, up: boolean): number {
  let t = 0.02;
  let i = 0;
  while (t < dur) {
    const k = t / dur;
    const rate = rateFrom + (rateTo - rateFrom) * k;
    const swell = Math.sin(Math.PI * Math.min(1, k * 1.15)) * 0.8 + 0.2;
    s.click(t, rnd(700, 1300), 0.09 * swell, 0.02);
    if (i % 3 === 0) s.tone(t, "triangle", rnd(160, 220), 0.03 * swell, 0.001, 0.03);
    t += 1 / rate * rnd(0.85, 1.15);
    i++;
  }
  // the roll itself: rumbling low noise + a motor whine gliding with the speed
  s.noise(0, 0.12, dur * 0.25, dur * 0.85, "lowpass", 380, 0.8, up ? 520 : 260);
  const hum = s.c.createBiquadFilter();
  hum.type = "lowpass";
  hum.frequency.value = 260;
  hum.connect(s.out);
  s.tone(0, "sawtooth", up ? 52 : 66, 0.05, dur * 0.2, dur * 0.85, up ? 66 : 48, hum);
  return dur + 0.1;
}

function clunk(s: Synth, at: number, big = 1) {
  s.thump(at, 70, 0.55 * big, 0.28);
  s.noise(at, 0.22 * big, 0.001, 0.09, "lowpass", 700, 0.8);
  s.metal(at + 0.004, 1450, 0.06 * big, 0.12, [1, 2.4, 4.1]);
}

const FX: Record<SfxName, Fx> = {
  // ---------------------------------------------------------- intro / outro
  "boot-hum": (s) => {
    const lp = s.c.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = 420;
    lp.connect(s.out);
    s.tone(0, "sawtooth", 50, 0.12, 0.5, 1.1, 50, lp);
    s.tone(0, "sawtooth", 100.4, 0.06, 0.6, 1.0, 100, lp);
    s.noise(0, 0.03, 0.4, 1.0, "bandpass", 2400, 1.5);
    return 1.6;
  },
  "door-open": (s) => {
    clunk(s, 0, 0.6);
    s.noise(0.06, 0.16, 0.05, 0.55, "highpass", 3800, 0.7, 900); // pneumatic hiss falling
    return 0.7;
  },
  "door-close": (s) => {
    s.noise(0, 0.12, 0.03, 0.3, "highpass", 1200, 0.7, 4000);
    clunk(s, 0.3, 0.8);
    return 0.65;
  },
  "logo-buzz": (s) => {
    // neon tube striking: a 120 Hz buzz gated by flicker
    const bp = s.c.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = 1800;
    bp.Q.value = 0.8;
    bp.connect(s.out);
    let t = 0;
    for (const len of [0.04, 0.03, 0.08, 0.05, 0.42]) {
      s.tone(t, "sawtooth", 120, 0.09, 0.004, len, 120, bp);
      s.click(t, 4200, 0.05, 0.008);
      t += len + rnd(0.03, 0.08);
    }
    return t + 0.1;
  },
  "coin-insert": (s) => {
    // a silver coin: bright clink on the slot lip, a short ring, a slide down the chute, a soft landing
    const f = rnd(2700, 3000);
    s.metal(0, f, 0.22, 0.32);
    s.click(0, 6500, 0.12, 0.006);
    s.metal(0.055, f * 1.04, 0.09, 0.16); // a tiny bounce
    s.noise(0.09, 0.05, 0.02, 0.26, "bandpass", 3600, 3, 1600); // the slide
    s.tone(0.09, "sine", f * 0.5, 0.012, 0.03, 0.24, f * 0.42);
    s.metal(0.36, 1900, 0.06, 0.12);
    s.thump(0.37, 180, 0.12, 0.08);
    return 0.55;
  },
  "coin-drop": (s) => {
    const f = rnd(2300, 2600);
    let t = 0;
    let g = 0.2;
    for (const gap of [0.13, 0.095, 0.072, 0.056, 0.045, 0.036]) {
      s.metal(t, f * rnd(0.98, 1.03), g, 0.18);
      t += gap;
      g *= 0.68;
    }
    s.thump(t, 220, 0.05, 0.06);
    return t + 0.25;
  },
  "coin-roll": (s) => {
    // rolling on its edge, then the wobble speeding up as it settles (the Euler's-disk whirr)
    let t = 0;
    let gap = 0.065;
    s.noise(0, 0.05, 0.05, 0.9, "bandpass", 1800, 1.2);
    while (t < 1.25) {
      s.metal(t, rnd(2500, 2900), 0.05 * (1 - t / 1.6), 0.05, [1, 2.76]);
      t += gap * rnd(0.85, 1.15);
      if (t > 0.75) gap = Math.max(0.014, gap * 0.86);
    }
    s.metal(t, 2600, 0.08, 0.2);
    return t + 0.25;
  },
  "gate-unlock": (s) => {
    // a heavy bolt: latch click, the bolt sliding, the deep clunk
    s.metal(0, 1650, 0.08, 0.08, [1, 2.2, 3.9]);
    s.click(0, 3000, 0.12, 0.01);
    s.noise(0.04, 0.06, 0.02, 0.08, "bandpass", 900, 2, 500);
    clunk(s, 0.12, 1.1);
    s.click(0.31, 2200, 0.06, 0.015);
    return 0.6;
  },
  "gate-open": (s) => {
    const d = shutter(s, 1.5, 34, 20, true);
    clunk(s, 1.5, 0.7); // the shutter hits its top stop
    return d + 0.3;
  },
  "gate-close": (s) => {
    const d = shutter(s, 1.3, 22, 36, false);
    clunk(s, 1.3, 1.2);
    return d + 0.35;
  },

  // ---------------------------------------------------------- studio UI (quiet on purpose)
  click: (s) => {
    s.noise(0, 0.06, 0.0006, 0.007, "bandpass", rnd(3200, 3800), 1.4);
    s.tone(0, "sine", 1900, 0.018, 0.0008, 0.012);
    return 0.03;
  },
  tab: (s) => {
    s.tone(0, "sine", 1250, 0.035, 0.002, 0.03, 950);
    s.noise(0, 0.035, 0.0006, 0.006, "highpass", 4200, 0.7);
    return 0.05;
  },
  toggle: (s) => {
    s.tone(0, "triangle", 900, 0.035, 0.001, 0.018);
    s.tone(0.032, "triangle", 1350, 0.03, 0.001, 0.02);
    s.noise(0.032, 0.025, 0.0006, 0.006, "bandpass", 4000, 1.5);
    return 0.07;
  },
  "sheet-open": (s) => {
    s.noise(0, 0.05, 0.05, 0.14, "bandpass", 450, 1.4, 2600);
    s.tone(0, "sine", 260, 0.025, 0.03, 0.12, 390);
    return 0.2;
  },
  "sheet-close": (s) => {
    s.noise(0, 0.045, 0.03, 0.13, "bandpass", 2400, 1.4, 420);
    s.tone(0, "sine", 380, 0.022, 0.02, 0.11, 250);
    return 0.18;
  },
  toast: (s) => {
    s.tone(0, "triangle", NOTE(81), 0.05, 0.003, 0.22);
    s.tone(0.07, "triangle", NOTE(88), 0.04, 0.003, 0.3);
    return 0.4;
  },
  success: (s) => {
    s.arp(0, [76, 80, 83], 0.06, "triangle", 0.05, 0.14, 0.32);
    return 0.5;
  },
  error: (s) => {
    const lp = s.c.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = 1100;
    lp.connect(s.out);
    s.tone(0, "square", 233, 0.05, 0.005, 0.12, 233, lp);
    s.tone(0.13, "square", 185, 0.055, 0.005, 0.22, 180, lp);
    return 0.4;
  },
  "app-switch": (s) => {
    s.noise(0, 0.04, 0.02, 0.09, "highpass", 1500, 0.8, 5200);
    s.tone(0.02, "sine", 520, 0.04, 0.004, 0.07, 790);
    s.tone(0.07, "sine", 1040, 0.02, 0.002, 0.06);
    return 0.18;
  },
  "playlist-next": (s) => {
    s.noise(0, 0.045, 0.03, 0.08, "bandpass", 900, 1.6, 3600);
    s.click(0.1, 3000, 0.05, 0.01);
    return 0.16;
  },
  "playlist-prev": (s) => {
    s.noise(0, 0.045, 0.03, 0.08, "bandpass", 3600, 1.6, 900);
    s.click(0.1, 2200, 0.05, 0.01);
    return 0.16;
  },

  // ---------------------------------------------------------- casino
  chip: (s) => {
    // clay chips knocking: two tight clacks
    const f = rnd(3800, 5200);
    s.noise(0, 0.14, 0.0005, 0.016, "bandpass", f, 3.5);
    s.tone(0, "triangle", f * 0.46, 0.04, 0.0005, 0.012);
    s.noise(rnd(0.012, 0.022), 0.08, 0.0005, 0.014, "bandpass", f * 1.12, 3.5);
    return 0.06;
  },
  "chips-stack": (s) => {
    let t = 0;
    const n = 4 + Math.floor(Math.random() * 3);
    for (let i = 0; i < n; i++) {
      const f = rnd(3600, 5400);
      s.noise(t, 0.12 * (1 - i / (n + 2)), 0.0005, 0.016, "bandpass", f, 3.5);
      s.tone(t, "triangle", f * 0.45, 0.03, 0.0005, 0.012);
      t += rnd(0.035, 0.06);
    }
    return t + 0.05;
  },
  "no-more-bets": (s) => {
    // a two-tone desk bell, high then low
    s.metal(0, NOTE(79), 0.14, 0.7, [1, 2.0, 3.01, 4.2]);
    s.metal(0.24, NOTE(74), 0.14, 0.9, [1, 2.0, 3.01, 4.2]);
    return 1.1;
  },
  "wheel-spin": (s) => {
    // a whoosh that fades as the wheel slows, and the ratchet ticks spreading out
    const dur = 4.2;
    s.noise(0, 0.08, 0.2, dur, "bandpass", 700, 0.9, 260);
    let t = 0.05;
    let gap = 0.045;
    while (t < dur) {
      s.click(t, rnd(2300, 2800), 0.08, 0.008);
      t += gap;
      gap *= 1.045;
    }
    return dur + 0.1;
  },
  "ball-drop": (s) => {
    // the ball skittering over the frets into a pocket
    let t = 0;
    let g = 0.13;
    for (const gap of [0.15, 0.11, 0.085, 0.07, 0.055, 0.045, 0.04]) {
      s.click(t, rnd(3000, 4300), g, 0.014);
      s.tone(t, "sine", rnd(1300, 1700), g * 0.25, 0.001, 0.03);
      t += gap;
      g *= 0.82;
    }
    s.thump(t, 300, 0.05, 0.05);
    return t + 0.15;
  },
  "card-deal": (s) => {
    s.noise(0, 0.09, 0.012, 0.06, "bandpass", 1800, 1.1, 5200); // the swish across the felt
    s.noise(0.075, 0.08, 0.0006, 0.01, "highpass", 2600, 0.7); // the snap as it lands
    s.thump(0.075, 160, 0.03, 0.04);
    return 0.13;
  },
  "card-flip": (s) => {
    s.noise(0, 0.05, 0.004, 0.035, "bandpass", 3000, 1.2, 5500);
    s.noise(0.04, 0.09, 0.0006, 0.012, "highpass", 3200, 0.7);
    s.thump(0.04, 200, 0.025, 0.04);
    return 0.1;
  },
  "dice-roll": (s) => {
    s.noise(0, 0.05, 0.03, 0.55, "lowpass", 600, 0.7); // the rumble across the felt
    let t = 0;
    let g = 0.16;
    for (let i = 0; i < 8; i++) {
      s.click(t, rnd(1500, 3200), g, 0.02);
      s.tone(t, "triangle", rnd(500, 800), g * 0.25, 0.001, 0.025);
      t += rnd(0.045, 0.11) * (1 + i * 0.12);
      g *= 0.8;
    }
    return t + 0.15;
  },
  "reel-spin": (s) => {
    // three reels whirring: a ratchet train over a soft motor tone
    const dur = 1.3;
    let t = 0;
    while (t < dur) {
      s.click(t, rnd(1500, 1900), 0.035, 0.008);
      t += 1 / 26;
    }
    s.noise(0, 0.035, 0.08, dur, "bandpass", 850, 1.5);
    return dur;
  },
  "reel-stop": (s) => {
    s.thump(0, 150, 0.12, 0.09);
    s.click(0, 2600, 0.08, 0.012);
    return 0.14;
  },
  win: (s) => {
    s.arp(0, [72, 76, 79, 84], 0.075, "triangle", 0.07, 0.16, 0.5);
    return 0.85;
  },
  "big-win": (s) => {
    s.arp(0, [72, 76, 79, 84], 0.07, "triangle", 0.07, 0.14);
    s.arp(0.32, [76, 79, 84, 88], 0.07, "triangle", 0.075, 0.14, 0.7);
    for (let i = 0; i < 10; i++) s.metal(0.4 + i * rnd(0.05, 0.09), rnd(2600, 3400), 0.035, 0.15, [1, 2.76]); // coins
    return 1.4;
  },
  lose: (s) => {
    const lp = s.c.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = 1400;
    lp.connect(s.out);
    s.tone(0, "triangle", NOTE(67), 0.06, 0.01, 0.2, NOTE(66), lp);
    s.tone(0.2, "triangle", NOTE(63), 0.06, 0.01, 0.42, NOTE(62), lp);
    return 0.7;
  },
  "bingo-call": (s) => {
    s.metal(0, NOTE(84), 0.12, 1.1, [1, 2.0, 3.01, 4.2]);
    return 1.2;
  },
  "bingo-win": (s) => {
    s.metal(0, NOTE(84), 0.1, 0.9, [1, 2.0, 3.01]);
    s.metal(0.12, NOTE(88), 0.1, 0.9, [1, 2.0, 3.01]);
    s.arp(0.25, [79, 84, 88, 91], 0.07, "triangle", 0.06, 0.14, 0.6);
    return 1.2;
  },
  "round-open": (s) => {
    s.metal(0, NOTE(86), 0.09, 0.6, [1, 2.0, 3.01, 4.2]);
    return 0.7;
  },
  tick: (s) => {
    s.tone(0, "sine", 1800, 0.05, 0.001, 0.04);
    s.click(0, 4000, 0.04, 0.006);
    return 0.06;
  },

  // ---------------------------------------------------------- games / fly
  "fly-buzz": (s) => {
    // a fly passing: ~200 Hz wingbeat buzz with a wobbling pitch, in and out
    const dur = rnd(0.9, 1.4);
    const bp = s.c.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = 650;
    bp.Q.value = 0.9;
    const g = s.c.createGain();
    const st = s.t;
    g.gain.setValueAtTime(0.0001, st);
    g.gain.linearRampToValueAtTime(0.06, st + dur * 0.35);
    g.gain.linearRampToValueAtTime(0.0001, st + dur);
    bp.connect(g).connect(s.out);
    const o = s.c.createOscillator();
    o.type = "sawtooth";
    o.frequency.value = rnd(185, 215);
    const lfo = s.c.createOscillator();
    lfo.frequency.value = rnd(5, 9);
    const depth = s.c.createGain();
    depth.gain.value = 14;
    lfo.connect(depth).connect(o.frequency);
    o.connect(bp);
    o.start(st);
    lfo.start(st);
    o.stop(st + dur + 0.05);
    lfo.stop(st + dur + 0.05);
    s.v.nodes.push(o, lfo);
    return dur;
  },
  "game-start": (s) => {
    const lp = s.c.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = 2400;
    lp.connect(s.out);
    [60, 64, 67, 72].forEach((n, i) => s.tone(i * 0.08, "square", NOTE(n), 0.04, 0.003, i === 3 ? 0.35 : 0.09, undefined, lp));
    return 0.7;
  },
  "game-over": (s) => {
    const lp = s.c.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = 1800;
    lp.connect(s.out);
    [67, 63, 60].forEach((n, i) => s.tone(i * 0.16, "square", NOTE(n), 0.04, 0.004, 0.16, undefined, lp));
    const o = s.tone(0.5, "square", NOTE(55), 0.045, 0.004, 0.6, NOTE(53), lp);
    const vib = s.c.createOscillator();
    vib.frequency.value = 6;
    const d = s.c.createGain();
    d.gain.value = 5;
    vib.connect(d).connect(o.frequency);
    vib.start(s.t + 0.5);
    vib.stop(s.t + 1.2);
    s.v.nodes.push(vib);
    return 1.2;
  },
  score: (s) => {
    s.tone(0, "sine", 1320, 0.04, 0.002, 0.045);
    s.tone(0.035, "sine", 1760, 0.035, 0.002, 0.06);
    return 0.11;
  },
};

