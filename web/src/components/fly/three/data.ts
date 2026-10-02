import * as THREE from "three";
import type { FlyKey, FlySnap, Shot, Theme } from "../../../lib/fly";
import type { Host } from "./host";

/** The live brain, shared by every brain view form: GET /api/fly smoothed to the frame rate, split into the
 *  circuit's neuron groups (each with an activity 0..1 and a spike flash), the synapse links between them,
 *  and a 16×16 texture of the eye / lamina / motion maps so shaders can light thousands of neurons on the GPU. */

export const N = 16;

type Tone = keyof Omit<Theme, "name">;
export type Group = {
  id: string;
  label: string;
  short: string;
  color: Tone;
  /** 0 = one activity for the whole group; 1 eye, 2 ON, 3 OFF, 4 T4 (ON motion), 5 T5 (OFF motion): per-cell. */
  chan: number;
  /** Position along the pathway (eye 0 … neck 7); -1 = the rest of the central brain. */
  stage: number;
};

export const GROUPS: Group[] = [
  { id: "eye", label: "Photoreceptors", short: "Eye", color: "eye", chan: 1, stage: 0 },
  { id: "l1", label: "Lamina L1 · ON", short: "L1 ON", color: "on", chan: 2, stage: 1 },
  { id: "l2", label: "Lamina L2 · OFF", short: "L2 OFF", color: "off", chan: 3, stage: 1 },
  { id: "t4", label: "T4 · ON motion", short: "T4", color: "on", chan: 4, stage: 2 },
  { id: "t5", label: "T5 · OFF motion", short: "T5", color: "off", chan: 5, stage: 2 },
  { id: "hsl", label: "HS ←", short: "HS ←", color: "left", chan: 0, stage: 3 },
  { id: "hsr", label: "HS →", short: "HS →", color: "right", chan: 0, stage: 3 },
  { id: "vsu", label: "VS ↑", short: "VS ↑", color: "up", chan: 0, stage: 3 },
  { id: "vsd", label: "VS ↓", short: "VS ↓", color: "down", chan: 0, stage: 3 },
  { id: "lplc2", label: "LPLC2 · looming", short: "LPLC2", color: "loom", chan: 0, stage: 4 },
  { id: "gf", label: "Giant fibre", short: "GF", color: "gf", chan: 0, stage: 5 },
  { id: "dnl", label: "DN ←", short: "DN ←", color: "dn", chan: 0, stage: 6 },
  { id: "dnu", label: "DN ↑", short: "DN ↑", color: "dn", chan: 0, stage: 6 },
  { id: "dnd", label: "DN ↓", short: "DN ↓", color: "dn", chan: 0, stage: 6 },
  { id: "dnr", label: "DN →", short: "DN →", color: "dn", chan: 0, stage: 6 },
  { id: "vnc", label: "Neck → legs", short: "Neck", color: "dn", chan: 0, stage: 7 },
  { id: "cb", label: "Central brain", short: "CB", color: "wire", chan: 0, stage: -1 },
];
export const G = GROUPS.length;
export const GI = Object.fromEntries(GROUPS.map((g, i) => [g.id, i])) as Record<string, number>;
const DIRS = ["left", "right", "up", "down"] as const;
type Dir = (typeof DIRS)[number];
export const HS_GROUP: Record<Dir, number> = { left: GI.hsl, right: GI.hsr, up: GI.vsu, down: GI.vsd };
export const DN_GROUP: Record<Dir, number> = { left: GI.dnl, right: GI.dnr, up: GI.dnu, down: GI.dnd };
/** The group that fires when a key is pressed. */
export const KEY_GROUP: Record<FlyKey, number> = { ...DN_GROUP, a: GI.gf };

export type Link = { from: number; to: number; tone?: Tone };

/** The synapse pathways, in the circuit's order. Activity and flashes are per link (`BrainData.linkAct`). */
export const LINKS: Link[] = [];
const link = (from: string, to: string, tone?: Tone) => LINKS.push({ from: GI[from], to: GI[to], tone }) - 1;
const L = {
  eyeL1: link("eye", "l1"), eyeL2: link("eye", "l2"),
  l1t4: link("l1", "t4"), l2t5: link("l2", "t5"),
  t4hs: DIRS.map((d) => link("t4", ({ left: "hsl", right: "hsr", up: "vsu", down: "vsd" } as const)[d])),
  t5hs: DIRS.map((d) => link("t5", ({ left: "hsl", right: "hsr", up: "vsu", down: "vsd" } as const)[d])),
  t4lp: link("t4", "lplc2"), t5lp: link("t5", "lplc2"), lpgf: link("lplc2", "gf"),
  hsdn: DIRS.map((d) => link(({ left: "hsl", right: "hsr", up: "vsu", down: "vsd" } as const)[d], ({ left: "dnl", right: "dnr", up: "dnu", down: "dnd" } as const)[d])),
  // phototaxis: the eye's light drives the descending neurons directly
  eyedn: DIRS.map((d) => link("eye", ({ left: "dnl", right: "dnr", up: "dnu", down: "dnd" } as const)[d], "dn")),
  dnvnc: DIRS.map((d) => link(({ left: "dnl", right: "dnr", up: "dnu", down: "dnd" } as const)[d], "vnc")),
  gfvnc: link("gf", "vnc"),
  // the rest of the central brain chatters with the descending neurons (state, context)
  cbdn: DIRS.map((d) => link("cb", ({ left: "dnl", right: "dnr", up: "dnu", down: "dnd" } as const)[d])),
  eyecb: link("eye", "cb"),
};
export const NL = LINKS.length;

/** A form of the brain view: one way of drawing the same live circuit. */
export interface BrainForm {
  bloomThreshold?: number;
  shots?: Shot[];
  build(host: Host, data: BrainData): void;
  update(dt: number, t: number, host: Host, data: BrainData): void;
  frame(mode: Shot): { target: THREE.Vector3; position: THREE.Vector3 };
  /** A descending neuron (or the giant fibre, key A) fired. */
  spike?(k: FlyKey, host: Host, data: BrainData): void;
  /** Free what the host's tree walk can't see (textures, timers). */
  dispose?(): void;
}

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

export class BrainData {
  eye = new Float32Array(N * N);
  on = new Float32Array(N * N);
  off = new Float32Array(N * N);
  mh = new Float32Array(N * N);
  mv = new Float32Array(N * N);
  hs: Record<Dir, number> = { left: 0, right: 0, up: 0, down: 0 };
  dn: Record<Dir, number> = { left: 0, right: 0, up: 0, down: 0 };
  loom = 0;
  gf = 0;
  light: [number, number] = [0, 0];
  /** Mean activity of everything: drives ambient glow. */
  overall = 0;
  /** Shared uniforms (one object, every material): updating them here updates every shader. */
  uAct = { value: new Float32Array(G) };
  uFlash = { value: new Float32Array(G) };
  uColor = { value: new Float32Array(G * 3) };
  uChan = { value: new Float32Array(G) };
  uLinkAct = { value: new Float32Array(NL) };
  uLinkFlash = { value: new Float32Array(NL) };
  uLinkColor = { value: new Float32Array(NL * 3) };
  uTime = { value: 0 };
  map: THREE.DataTexture;
  uMap: { value: THREE.DataTexture };
  colors: THREE.Color[] = GROUPS.map(() => new THREE.Color());
  private px = new Uint8Array(N * N * 4);
  private peak = new Float32Array(G);
  private cellPeak = new Float32Array(3);
  private cellGain = [2.5, 2.5, 1.4];

  constructor() {
    this.map = new THREE.DataTexture(this.px, N, N, THREE.RGBAFormat);
    this.map.magFilter = THREE.LinearFilter;
    this.map.minFilter = THREE.LinearFilter;
    this.map.needsUpdate = true;
    this.uMap = { value: this.map };
    GROUPS.forEach((g, i) => (this.uChan.value[i] = g.chan));
  }

  get act() {
    return this.uAct.value;
  }

  setTheme(th: Theme) {
    const c = new THREE.Color();
    GROUPS.forEach((g, i) => {
      c.set(th[g.color]);
      if (g.id === "cb") c.lerp(new THREE.Color(th.accent), 0.45); // the theme's wire colour alone is too dark
      if (g.id === "t4" || g.id === "t5") c.lerp(new THREE.Color("#ffffff"), 0.18); // a touch apart from the lamina
      this.colors[i].copy(c);
      this.uColor.value.set([c.r, c.g, c.b], i * 3);
    });
    LINKS.forEach((l, i) => {
      c.copy(l.tone ? new THREE.Color(th[l.tone]) : this.colors[l.from]);
      this.uLinkColor.value.set([c.r, c.g, c.b], i * 3);
    });
  }

  /** Follow the latest reading (smoothed, frame-rate independent) and derive group and link activity. */
  update(dt: number, t: number, snap: FlySnap) {
    this.uTime.value = t;
    const k = 1 - Math.exp(-12 * dt);
    const take = (dst: Float32Array, src: number[] | undefined, scale: number) => {
      if (!src) return;
      for (let i = 0; i < dst.length; i++) dst[i] += ((src[i] ?? 0) * scale - dst[i]) * k;
    };
    take(this.eye, snap.eye, 1 / 255);
    take(this.on, snap.on, 1 / 255);
    take(this.off, snap.off, 1 / 255);
    take(this.mh, snap.mh, 1 / 127);
    take(this.mv, snap.mv, 1 / 127);
    for (const d of DIRS) {
      this.hs[d] += ((snap.hs?.[d] ?? 0) - this.hs[d]) * k;
      this.dn[d] += ((snap.dn?.[d] ?? 0) - this.dn[d]) * k;
    }
    this.loom += ((snap.looming ?? 0) - this.loom) * k;
    this.gf += ((snap.gf ?? 0) - this.gf) * k;
    const [lx, ly] = snap.light ?? [0, 0];
    this.light[0] += (lx - this.light[0]) * k;
    this.light[1] += (ly - this.light[1]) * k;

    // per-cell maps → texture (r eye, g ON, b OFF, a motion) and their means. Like the groups, the per-cell
    // channels are scaled by their recent peak so faint contrast and slow motion still show.
    let se = 0, son = 0, soff = 0, s4 = 0, s5 = 0, mOn = 0, mOff = 0, mM = 0;
    for (let i = 0; i < N * N; i++) {
      const m = Math.hypot(this.mh[i], this.mv[i]);
      if (this.on[i] > mOn) mOn = this.on[i];
      if (this.off[i] > mOff) mOff = this.off[i];
      if (m > mM) mM = m;
    }
    const cd = Math.exp(-dt / 6);
    this.cellPeak[0] = Math.max(mOn, this.cellPeak[0] * cd, 0.08);
    this.cellPeak[1] = Math.max(mOff, this.cellPeak[1] * cd, 0.08);
    this.cellPeak[2] = Math.max(mM, this.cellPeak[2] * cd, 0.04);
    const [kOn, kOff, kM] = [1.6 / this.cellPeak[0], 1.6 / this.cellPeak[1], 1.4 / this.cellPeak[2]];
    this.cellGain = [kOn, kOff, kM];
    const px = this.px;
    for (let i = 0; i < N * N; i++) {
      const e = this.eye[i], a = this.on[i], b = this.off[i];
      const m = Math.min(1, Math.hypot(this.mh[i], this.mv[i]) * kM);
      se += e; son += a; soff += b;
      const share = a + b > 0.001 ? a / (a + b) : 0.5;
      s4 += m * share;
      s5 += m * (1 - share);
      px[i * 4] = clamp01(e) * 255;
      px[i * 4 + 1] = clamp01(a * kOn) * 255;
      px[i * 4 + 2] = clamp01(b * kOff) * 255;
      px[i * 4 + 3] = m * 255;
    }
    this.map.needsUpdate = true;
    const n = N * N;
    const act = this.uAct.value;
    // Automatic gain per group: the real brain's signals are sparse and small (a dark arena, brief motion), so each
    // group is scaled by its own recent peak (decaying over ~8 s, never below a floor). Quiet stays quiet; the
    // busiest moment of the last few seconds fills the scale.
    const decay = Math.exp(-dt / 8);
    const gain = (g: number, raw: number, floor: number) => {
      this.peak[g] = Math.max(raw, this.peak[g] * decay, floor);
      act[g] = clamp01(raw / this.peak[g]);
    };
    gain(GI.eye, se / n, 0.12);
    gain(GI.l1, son / n, 0.012);
    gain(GI.l2, soff / n, 0.012);
    gain(GI.t4, s4 / n, 0.02);
    gain(GI.t5, s5 / n, 0.02);
    for (const d of DIRS) {
      gain(HS_GROUP[d], this.hs[d], 0.008);
      act[DN_GROUP[d]] = clamp01(this.dn[d]); // a membrane potential: 1 = threshold already
    }
    gain(GI.lplc2, this.loom, 0.03);
    gain(GI.gf, this.gf, 0.08);
    const dnMax = Math.max(this.dn.left, this.dn.right, this.dn.up, this.dn.down);
    act[GI.vnc] = clamp01(dnMax * 0.8 + act[GI.gf] * 0.5);
    let sum = 0;
    for (let g = 0; g < G; g++) if (g !== GI.cb) sum += act[g];
    this.overall = sum / (G - 1);
    act[GI.cb] = clamp01(0.12 + this.overall * 1.2);

    const la = this.uLinkAct.value;
    la[L.eyeL1] = act[GI.l1];
    la[L.eyeL2] = act[GI.l2];
    la[L.l1t4] = act[GI.t4];
    la[L.l2t5] = act[GI.t5];
    DIRS.forEach((d, i) => {
      la[L.t4hs[i]] = act[HS_GROUP[d]] * 0.8 + act[GI.t4] * 0.2;
      la[L.t5hs[i]] = act[HS_GROUP[d]] * 0.8 + act[GI.t5] * 0.2;
      la[L.hsdn[i]] = clamp01(act[HS_GROUP[d]] * 0.8 + act[DN_GROUP[d]] * 0.5);
      const toward = d === "left" ? -this.light[0] : d === "right" ? this.light[0] : d === "up" ? -this.light[1] : this.light[1];
      la[L.eyedn[i]] = clamp01(Math.max(0, toward) * 1.4 + act[DN_GROUP[d]] * 0.3);
      la[L.dnvnc[i]] = act[DN_GROUP[d]];
      la[L.cbdn[i]] = 0.1 + act[GI.cb] * 0.25;
    });
    la[L.t4lp] = act[GI.lplc2];
    la[L.t5lp] = act[GI.lplc2];
    la[L.lpgf] = Math.max(act[GI.lplc2], act[GI.gf]);
    la[L.gfvnc] = act[GI.gf];
    la[L.eyecb] = act[GI.eye] * 0.5;

    // spike flashes fade
    const f = this.uFlash.value;
    const lf = this.uLinkFlash.value;
    const fade = dt * 2.4;
    for (let g = 0; g < G; g++) f[g] = Math.max(0, f[g] - fade);
    for (let l = 0; l < NL; l++) lf[l] = Math.max(0, lf[l] - fade);
  }

  /** A key was pressed: its neuron (and the path that drove it) flashes. */
  spike(k: FlyKey) {
    const f = this.uFlash.value;
    const lf = this.uLinkFlash.value;
    f[KEY_GROUP[k]] = 1;
    f[GI.vnc] = Math.max(f[GI.vnc], 0.7);
    if (k === "a") {
      f[GI.lplc2] = 1;
      lf[L.lpgf] = lf[L.gfvnc] = lf[L.t4lp] = lf[L.t5lp] = 1;
    } else {
      const i = DIRS.indexOf(k);
      f[HS_GROUP[k]] = Math.max(f[HS_GROUP[k]], 0.5);
      lf[L.dnvnc[i]] = lf[L.hsdn[i]] = 1;
      lf[L.eyedn[i]] = 0.6;
    }
  }

  /** Activity of one neuron of a group: per-cell groups read their map, the rest share one value. */
  cell(g: number, i: number): number {
    const c = GROUPS[g].chan;
    const j = ((i % (N * N)) + N * N) % (N * N);
    if (c === 1) return clamp01(this.eye[j]);
    if (c === 2) return clamp01(this.on[j] * this.cellGain[0]);
    if (c === 3) return clamp01(this.off[j] * this.cellGain[1]);
    if (c >= 4) {
      const m = Math.min(1, Math.hypot(this.mh[j], this.mv[j]) * this.cellGain[2]);
      const a = this.on[j], b = this.off[j];
      const share = a + b > 0.001 ? a / (a + b) : 0.5;
      return clamp01(m * (c === 4 ? share : 1 - share) * 2);
    }
    return this.uAct.value[g];
  }

  dispose() {
    this.map.dispose();
  }
}

// ------------------------------------------------------------------ GPU materials driven by BrainData

const HASH = /* glsl */ `float hash(float n) { return fract(sin(n) * 43758.5453123); }`;

/** Thousands of neurons on one draw call. Each point carries its group (`aGroup`), its eye cell (`aCell`, or -1)
 *  and a seed; the shader reads the group's activity (or its cell from the map), and fires random spikes at a
 *  rate that rises with activity, plus the group's flash when its key is pressed. */
export function neuronPoints(data: BrainData, pixelRatio: number, size = 1): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    defines: { NG: G },
    uniforms: {
      uAct: data.uAct, uFlash: data.uFlash, uColor: data.uColor, uChan: data.uChan, uMap: data.uMap, uTime: data.uTime,
      uSize: { value: size }, uScale: { value: pixelRatio },
    },
    vertexShader: /* glsl */ `
      attribute float aGroup; attribute float aCell; attribute float aSeed; attribute float aSize;
      uniform float uAct[NG]; uniform float uFlash[NG]; uniform vec3 uColor[NG]; uniform float uChan[NG];
      uniform sampler2D uMap; uniform float uTime; uniform float uSize; uniform float uScale;
      varying vec3 vColor; varying float vHot;
      ${HASH}
      void main() {
        int g = int(aGroup + 0.5);
        float act = uAct[g];
        float ch = uChan[g];
        if (ch > 0.5 && aCell >= 0.0) {
          vec2 uv = vec2(mod(aCell, 16.0) + 0.5, floor(aCell / 16.0) + 0.5) / 16.0;
          vec4 m = texture2D(uMap, uv);
          float share = m.g / max(0.004, m.g + m.b);
          float s = ch < 1.5 ? m.r : ch < 2.5 ? m.g : ch < 3.5 ? m.b : ch < 4.5 ? m.a * share * 2.0 : m.a * (1.0 - share) * 2.0;
          act = clamp(s, 0.0, 1.0) * 0.85 + act * 0.15;
        }
        float rate = 2.5 + aSeed * 8.0;
        float c = uTime * rate + aSeed * 37.0;
        float fire = step(1.0 - act * 0.7 - 0.012, hash(floor(c) * 1.31 + aSeed * 113.0));
        float pulse = fire * pow(1.0 - fract(c), 3.0);
        float fl = uFlash[g] * (0.6 + 0.4 * hash(aSeed * 7.0));
        float b = 0.09 + act * 0.55 + pulse * 1.25 + fl * 1.3;
        vHot = pulse + fl;
        vColor = uColor[g] * b + vec3(0.22) * (pulse * 0.6 + fl * 0.8);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = aSize * uSize * uScale * (0.7 + act * 0.45 + pulse * 0.7 + fl * 0.9) * (120.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      varying vec3 vColor; varying float vHot;
      void main() {
        vec2 d = gl_PointCoord - 0.5;
        float r = length(d);
        float a = smoothstep(0.5, 0.0, r);
        a *= a;
        if (a < 0.02) discard;
        float core = smoothstep(0.18, 0.0, r) * min(1.0, vHot);
        gl_FragColor = vec4(vColor * (0.55 + a * 1.3) + vec3(core * 0.6), a);
      }`,
  });
}

/** Synapse lines on one draw call. Each vertex carries its link (`aLink`), how far along the line it is (`aT`,
 *  0 at the source) and a seed; pulses travel source → target on a link as often as the link is active, and the
 *  whole link lights up on a spike. */
export function pulseLines(data: BrainData, base = 1, speed = 1): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    defines: { NL },
    uniforms: {
      uAct: data.uLinkAct, uFlash: data.uLinkFlash, uColor: data.uLinkColor, uTime: data.uTime,
      uBase: { value: base }, uSpeed: { value: speed },
    },
    vertexShader: /* glsl */ `
      attribute float aLink; attribute float aT; attribute float aSeed;
      uniform float uAct[NL]; uniform float uFlash[NL]; uniform vec3 uColor[NL];
      varying float vT; varying float vSeed; varying vec3 vCol; varying float vAct; varying float vFl;
      void main() {
        int l = int(aLink + 0.5);
        vCol = uColor[l]; vAct = uAct[l]; vFl = uFlash[l]; vT = aT; vSeed = aSeed;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform float uTime; uniform float uBase; uniform float uSpeed;
      varying float vT; varying float vSeed; varying vec3 vCol; varying float vAct; varying float vFl;
      ${HASH}
      void main() {
        float c = uTime * uSpeed * (0.45 + vSeed * 0.6) + vSeed * 9.0;
        float s = fract(c) * 1.3 - 0.15;
        float fire = step(1.0 - vAct * 0.85 - 0.02, hash(floor(c) * 1.7 + vSeed * 91.0));
        float d = vT - s;
        float head = exp(-d * d * 700.0);
        float tail = d < 0.0 ? exp(d * 9.0) * 0.45 : 0.0;
        float fl = vFl * (0.5 + 0.5 * exp(-pow(vT - (1.0 - vFl), 2.0) * 40.0)); // a spike runs down the line
        float glow = uBase * (0.1 + vAct * 0.32) + fire * (head * 1.5 + tail) + fl * 1.1;
        gl_FragColor = vec4(vCol * glow, 1.0);
      }`,
  });
}

/** A translucent hull: bright at the rim (like FlyWire's neuropil meshes), nearly clear face-on. */
export function hullMaterial(color: THREE.Color, strength = 1): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    uniforms: { uColor: { value: color.clone() }, uStrength: { value: strength }, uGlow: { value: 0 } },
    vertexShader: /* glsl */ `
      varying vec3 vN; varying vec3 vV;
      void main() {
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vN = normalize(normalMatrix * normal);
        vV = normalize(-(viewMatrix * wp).xyz);
        gl_Position = projectionMatrix * viewMatrix * wp;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor; uniform float uStrength; uniform float uGlow;
      varying vec3 vN; varying vec3 vV;
      void main() {
        float fr = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 3.0);
        gl_FragColor = vec4(uColor * (fr * 0.55 + 0.015 + uGlow * 0.06) * uStrength, 1.0);
      }`,
  });
}

// ------------------------------------------------------------------ geometry builders

/** Accumulates neuron points: position, group, eye cell, seed and size. */
export class PointSet {
  pos: number[] = [];
  group: number[] = [];
  cell: number[] = [];
  seed: number[] = [];
  size: number[] = [];
  /** Indices of each group's points (for wiring and centroids). */
  members: number[][] = GROUPS.map(() => []);

  add(p: THREE.Vector3, g: number, cell: number, size: number) {
    this.members[g].push(this.group.length);
    this.pos.push(p.x, p.y, p.z);
    this.group.push(g);
    this.cell.push(cell);
    this.seed.push(Math.random());
    this.size.push(size);
  }

  at(i: number, out = new THREE.Vector3()) {
    return out.set(this.pos[i * 3], this.pos[i * 3 + 1], this.pos[i * 3 + 2]);
  }

  geometry(): THREE.BufferGeometry {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute("aGroup", new THREE.Float32BufferAttribute(this.group, 1));
    g.setAttribute("aCell", new THREE.Float32BufferAttribute(this.cell, 1));
    g.setAttribute("aSeed", new THREE.Float32BufferAttribute(this.seed, 1));
    g.setAttribute("aSize", new THREE.Float32BufferAttribute(this.size, 1));
    return g;
  }
}

/** Accumulates synapse curves as line segments carrying their link, position along the line and a seed. */
export class LineSet {
  pos: number[] = [];
  link: number[] = [];
  t: number[] = [];
  seed: number[] = [];

  /** A quadratic curve a → (control) → b in `segs` pieces. */
  curve(a: THREE.Vector3, ctrl: THREE.Vector3, b: THREE.Vector3, l: number, segs: number) {
    const s = Math.random();
    let px = a.x, py = a.y, pz = a.z;
    for (let i = 1; i <= segs; i++) {
      const u = i / segs, w = 1 - u;
      const x = w * w * a.x + 2 * w * u * ctrl.x + u * u * b.x;
      const y = w * w * a.y + 2 * w * u * ctrl.y + u * u * b.y;
      const z = w * w * a.z + 2 * w * u * ctrl.z + u * u * b.z;
      this.pos.push(px, py, pz, x, y, z);
      this.t.push((i - 1) / segs, u);
      this.link.push(l, l);
      this.seed.push(s, s);
      px = x; py = y; pz = z;
    }
  }

  get count() {
    return this.link.length;
  }

  geometry(): THREE.BufferGeometry {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute("aLink", new THREE.Float32BufferAttribute(this.link, 1));
    g.setAttribute("aT", new THREE.Float32BufferAttribute(this.t, 1));
    g.setAttribute("aSeed", new THREE.Float32BufferAttribute(this.seed, 1));
    return g;
  }
}

/** A random point inside an ellipsoid (denser towards the middle when `core` > 0). */
export function inEllipsoid(c: THREE.Vector3, r: THREE.Vector3, out = new THREE.Vector3(), core = 0) {
  out.randomDirection().multiplyScalar(Math.cbrt(Math.random()) ** (1 + core));
  return out.multiply(r).add(c);
}

export const pick = <T,>(a: T[]) => a[Math.floor(Math.random() * a.length)];
