import * as THREE from "three";
import { type FlyKey, type Shot, useFly } from "../../../../lib/fly";
import { type BrainData, type BrainForm, DN_GROUP, G, GI, GROUPS, KEY_GROUP, N } from "../data";
import { type Host, Particles, col, glowSprite } from "../host";

/** Spike raster + scope: a curved wall of spikes scrolling right to left (time × neuron rows, grouped by circuit
 *  stage, with each group's activity as a faint heat underlay), and in front of it an oscilloscope of the
 *  membrane potentials of the four descending neurons and the giant fibre, with their spike threshold. The wall
 *  is one texture (a ring buffer: one column per tick, no copying), the scope one ribbon mesh. */

const TICK = 1 / 30; // s per column
const W = 11; // wall width
const H = 6.2; // wall height
const WALL_Y = 1.3;
const BEND = 9; // wall curvature radius
const SW = 9.6; // scope width
const LANE = 0.62;
const SCOPE_Y = -2.45; // top of the scope's first lane
const SCOPE_Z = 2.2;
const ROWS: [string, number][] = [
  ["eye", 12], ["l1", 8], ["l2", 8], ["t4", 8], ["t5", 8], ["hsl", 4], ["hsr", 4], ["vsu", 4], ["vsd", 4], ["lplc2", 6],
  ["gf", 3], ["dnl", 5], ["dnu", 5], ["dnd", 5], ["dnr", 5], ["vnc", 4], ["cb", 6],
];
const TRACES: [FlyKey, string][] = [["left", "DN ←"], ["up", "DN ↑"], ["down", "DN ↓"], ["right", "DN →"], ["a", "Giant fibre"]];

export class RasterForm implements BrainForm {
  bloomThreshold = 0.14;
  shots: Shot[] = ["front", "close", "orbit", "top"];
  private T = 256;
  private rows: { g: number; j: number; n: number }[] = [];
  private px = new Uint8Array(0);
  private tex: THREE.DataTexture | null = null;
  private wallMat!: THREE.ShaderMaterial;
  private col = 0;
  private ticks = 0;
  private acc = 0;
  private pending = new Uint8Array(G); // groups that spiked since the last tick
  private gColor: THREE.Color[] = [];
  // scope
  private P = 256;
  private hist: Float32Array[] = [];
  private kick = new Uint8Array(TRACES.length);
  private ribbon!: THREE.Mesh;
  private rPos = new Float32Array(0);
  private rCol = new Float32Array(0);
  private heads: THREE.Sprite[] = [];
  private threshLines!: THREE.LineSegments;
  private thr = 1;
  private sparks!: Particles;
  private v = new THREE.Vector3();

  frame(mode: Shot) {
    const p: Record<Shot, THREE.Vector3> = {
      front: new THREE.Vector3(0, -0.6, 19.5),
      orbit: new THREE.Vector3(8, 2.6, 17.5),
      top: new THREE.Vector3(0.01, 15, 10.5),
      close: new THREE.Vector3(3, -2.4, 8.2),
    };
    return { target: mode === "close" ? new THREE.Vector3(0, -3.7, SCOPE_Z) : new THREE.Vector3(0, -1.3, 0), position: p[mode] };
  }

  build(host: Host, data: BrainData) {
    const lv = host.lv;
    const root = host.root;
    const th = host.theme;
    const k = Math.min(1.3, Math.max(0.55, lv.particles));
    this.T = lv.segments >= 24 ? 256 : lv.segments >= 16 ? 200 : 150;
    this.P = this.T;
    this.gColor = data.colors.map((c) => c.clone());

    // ---- rows, top (the eye) to bottom (the rest of the central brain)
    this.rows = [];
    for (const [id, n0] of ROWS) {
      const n = Math.max(2, Math.round(n0 * k));
      for (let j = 0; j < n; j++) this.rows.push({ g: GI[id], j, n });
    }
    const R = this.rows.length;
    this.px = new Uint8Array(this.T * R * 4);
    this.tex = new THREE.DataTexture(this.px, this.T, R, THREE.RGBAFormat);
    this.tex.magFilter = THREE.NearestFilter;
    this.tex.minFilter = THREE.LinearFilter;
    this.tex.wrapS = THREE.RepeatWrapping;
    this.tex.needsUpdate = true;
    this.col = 0;
    this.ticks = 0;

    // ---- the wall: a plane bent towards the viewer
    const wall = new THREE.PlaneGeometry(W, H, 48, 1);
    const wp = wall.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < wp.count; i++) {
      const a = wp.getX(i) / BEND;
      wp.setXYZ(i, Math.sin(a) * BEND, wp.getY(i) + WALL_Y, (1 - Math.cos(a)) * BEND);
    }
    this.wallMat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: {
        uTex: { value: this.tex }, uHead: { value: 0 }, uTicks: { value: 0 }, uT: { value: this.T }, uRows: { value: R },
        uGrid: { value: col(th.wire).lerp(col(th.accent), 0.3) },
      },
      vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader: /* glsl */ `
        uniform sampler2D uTex; uniform float uHead; uniform float uTicks; uniform float uT; uniform float uRows; uniform vec3 uGrid;
        varying vec2 vUv;
        void main() {
          float u = fract(vUv.x + uHead);
          vec4 s = texture2D(uTex, vec2(u, vUv.y));
          float colIdx = floor(vUv.x * uT);                      // 0 = oldest … uT-1 = newest
          float age = uT - 1.0 - colIdx;
          float when = uTicks - age;
          float sec = 1.0 - step(0.5, mod(when, 30.0));           // a tick line every second
          float rowF = fract(vUv.y * uRows);
          float gap = smoothstep(0.0, 0.12, rowF) * smoothstep(1.0, 0.88, rowF);
          vec3 c = s.rgb * (0.55 + 0.45 * gap) * (s.a > 0.5 ? 1.7 : 1.0);
          c += uGrid * sec * 0.10;
          c *= 0.35 + 0.65 * smoothstep(0.0, 0.35, vUv.x);       // the past fades out on the left
          float now = smoothstep(0.992, 1.0, vUv.x);
          c += uGrid * now * 1.5;
          gl_FragColor = vec4(c, 0.96);
        }`,
    });
    root.add(new THREE.Mesh(wall, this.wallMat));
    // a dark backing so the wall reads as a screen
    const back = new THREE.Mesh(wall.clone(), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.6, depthWrite: false }));
    back.position.z = -0.05;
    root.add(back);

    // group labels down the wall's left edge
    let r0 = 0;
    for (const [id] of ROWS) {
      const g = GI[id];
      const n = this.rows.filter((r) => r.g === g).length;
      const yc = WALL_Y + H / 2 - ((r0 + n / 2) / R) * H;
      r0 += n;
      const a = -W / 2 / BEND;
      const l = host.label(GROUPS[g].short, "fly-label-side fly-label-row");
      l.position.set(Math.sin(a) * BEND - 0.15, yc, (1 - Math.cos(a)) * BEND);
      root.add(l);
    }
    const title = host.label(`Spikes · ${Math.round(this.T * TICK)} s`, "fly-label-side");
    title.position.set(0, WALL_Y + H / 2 + 0.3, 0);
    root.add(title);

    // ---- the scope: graticule, threshold lines, glowing traces
    const scope = new THREE.Group();
    scope.position.set(0, 0, SCOPE_Z);
    scope.rotation.x = -0.18;
    root.add(scope);
    const glassH = LANE * TRACES.length + 0.6;
    const glass = new THREE.Mesh(new THREE.PlaneGeometry(SW + 0.6, glassH), new THREE.MeshBasicMaterial({ color: 0x02030a, transparent: true, opacity: 0.72, depthWrite: false }));
    glass.position.set(0, SCOPE_Y - glassH / 2 + 0.45, -0.02);
    scope.add(glass);
    const grid: number[] = [];
    for (let i = 0; i <= 8; i++) {
      const x = -SW / 2 + (i / 8) * SW;
      grid.push(x, SCOPE_Y + 0.42, 0, x, SCOPE_Y - LANE * TRACES.length + 0.32, 0);
    }
    TRACES.forEach((_, i) => {
      const y = this.base(i);
      grid.push(-SW / 2, y, 0, SW / 2, y, 0);
    });
    const gg = new THREE.BufferGeometry();
    gg.setAttribute("position", new THREE.Float32BufferAttribute(grid, 3));
    scope.add(new THREE.LineSegments(gg, new THREE.LineBasicMaterial({ color: col(th.wire).lerp(col(th.accent), 0.2), transparent: true, opacity: 0.35, depthWrite: false })));
    this.threshLines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: col(th.gf), transparent: true, opacity: 0.45, depthWrite: false }));
    this.thr = useFly.getState().brainCfg?.threshold ?? 1;
    this.writeThreshold();
    scope.add(this.threshLines);

    this.hist = TRACES.map(() => new Float32Array(this.P));
    this.kick.fill(0);
    const P = this.P;
    const nT = TRACES.length;
    this.rPos = new Float32Array(nT * P * 2 * 3);
    this.rCol = new Float32Array(nT * P * 2 * 3);
    const idx: number[] = [];
    for (let t = 0; t < nT; t++)
      for (let i = 0; i < P - 1; i++) {
        const a = (t * P + i) * 2;
        idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
      }
    const rg = new THREE.BufferGeometry();
    rg.setAttribute("position", new THREE.BufferAttribute(this.rPos, 3));
    rg.setAttribute("color", new THREE.BufferAttribute(this.rCol, 3));
    rg.setIndex(idx);
    this.ribbon = new THREE.Mesh(rg, new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    this.ribbon.frustumCulled = false;
    scope.add(this.ribbon);
    this.heads = TRACES.map(([key]) => {
      const s = glowSprite(data.colors[KEY_GROUP[key]], 0.45, 0.9);
      scope.add(s);
      return s;
    });
    TRACES.forEach(([, name], i) => {
      const l = host.label(name, "fly-label-row");
      l.position.set(-SW / 2 - 0.2, this.base(i) + LANE * 0.3, 0);
      scope.add(l);
    });
    const st = host.label("Membrane potential", "fly-label-side");
    st.position.set(0, SCOPE_Y + 0.62, 0);
    scope.add(st);
    this.writeRibbon();

    this.sparks = new Particles(Math.round(420 * lv.particles), 1);
    this.sparks.gravity = 0;
    this.sparks.drag = 1.6;
    root.add(this.sparks.points);
  }

  /** Baseline (resting potential) of scope lane i. */
  private base(i: number) {
    return SCOPE_Y - i * LANE - LANE * 0.62;
  }

  spike(k: FlyKey, host: Host, data: BrainData) {
    const g = KEY_GROUP[k];
    this.pending[g] = 1;
    if (k === "a") this.pending[GI.lplc2] = 1;
    else this.pending[DN_GROUP[k]] = 1;
    this.pending[GI.vnc] = 1;
    const ti = TRACES.findIndex(([key]) => key === k);
    if (ti >= 0) this.kick[ti] = 2;
    // sparks fly off the "now" edge of the wall at the group's rows
    const rs = this.rows.findIndex((r) => r.g === g);
    if (rs >= 0) {
      const R = this.rows.length;
      const n = this.rows[rs].n;
      const y = WALL_Y + H / 2 - ((rs + n / 2) / R) * H;
      const a = W / 2 / BEND;
      this.v.set(Math.sin(a) * BEND, y, (1 - Math.cos(a)) * BEND + 0.1);
      this.sparks.sphere(this.v, data.colors[g], Math.round(24 * host.lv.particles) + 5, 2.2, 0.8, 1.2);
    }
  }

  private tick(data: BrainData) {
    const T = this.T;
    const R = this.rows.length;
    this.col = (this.col + 1) % T;
    this.ticks++;
    const px = this.px;
    const flash = data.uFlash.value;
    for (let r = 0; r < R; r++) {
      const row = this.rows[r];
      const g = row.g;
      let act: number;
      if (GROUPS[g].chan) {
        // per-cell groups: each row reads its own band of the eye's rows
        const r0 = Math.floor((row.j / row.n) * N);
        const r1 = Math.max(r0 + 1, Math.floor(((row.j + 1) / row.n) * N));
        let s = 0;
        for (let y = r0; y < r1; y++) for (let x = 0; x < N; x += 2) s += data.cell(g, y * N + x);
        act = s / ((r1 - r0) * (N / 2));
      } else act = data.act[g];
      const forced = this.pending[g] && Math.random() < 0.85;
      const fire = forced || Math.random() < act * (GROUPS[g].chan ? 0.42 : 0.16) + 0.008;
      const c = this.gColor[g];
      const ti = ((R - 1 - r) * T + this.col) * 4; // texture row 0 is the bottom
      if (fire) {
        const b = 230 + Math.random() * 25;
        px[ti] = Math.min(255, c.r * b + 40);
        px[ti + 1] = Math.min(255, c.g * b + 40);
        px[ti + 2] = Math.min(255, c.b * b + 40);
        px[ti + 3] = 255;
      } else {
        const bg = (0.035 + (row.j % 2) * 0.012 + act * 0.15 + flash[g] * 0.1) * 255;
        px[ti] = c.r * bg;
        px[ti + 1] = c.g * bg;
        px[ti + 2] = c.b * bg;
        px[ti + 3] = 0;
      }
    }
    this.pending.fill(0);
    this.tex!.needsUpdate = true;

    // scope samples: the potential, a spike's overshoot, then the reset below rest
    TRACES.forEach(([key], i) => {
      const h = this.hist[i];
      h.copyWithin(0, 1);
      const v = key === "a" ? data.gf : data.dn[key];
      let s = v;
      if (this.kick[i] === 2) {
        s = 1.75;
        this.kick[i] = 1;
      } else if (this.kick[i] === 1) {
        s = -0.3;
        this.kick[i] = 0;
      }
      h[h.length - 1] = s;
    });
  }

  /** Rebuild the trace ribbons from the history (old samples dim, like phosphor). */
  private writeRibbon() {
    const P = this.P;
    const thr = Math.max(0.3, this.thr);
    const amp = LANE * 0.5;
    const w = 0.022;
    TRACES.forEach(([key], t) => {
      const h = this.hist[t];
      const base = this.base(t);
      const c = this.gColor[KEY_GROUP[key]];
      for (let i = 0; i < P; i++) {
        const x = -SW / 2 + (i / (P - 1)) * SW;
        const y = base + Math.max(-0.5, Math.min(2, h[i] / thr)) * amp;
        // normal from the neighbours, so steep spikes stay as thick as flat stretches
        const j0 = Math.max(0, i - 1), j1 = Math.min(P - 1, i + 1);
        const dx = ((j1 - j0) / (P - 1)) * SW;
        const dy = (Math.max(-0.5, Math.min(2, h[j1] / thr)) - Math.max(-0.5, Math.min(2, h[j0] / thr))) * amp;
        const len = Math.hypot(dx, dy) || 1;
        const nx = (-dy / len) * w, ny = (dx / len) * w;
        const o = ((t * P + i) * 2) * 3;
        this.rPos[o] = x + nx; this.rPos[o + 1] = y + ny; this.rPos[o + 2] = 0;
        this.rPos[o + 3] = x - nx; this.rPos[o + 4] = y - ny; this.rPos[o + 5] = 0;
        const k = 0.12 + 1.2 * (i / (P - 1)) ** 1.6;
        for (const q of [o, o + 3]) {
          this.rCol[q] = c.r * k;
          this.rCol[q + 1] = c.g * k;
          this.rCol[q + 2] = c.b * k;
        }
        if (i === P - 1) this.heads[t].position.set(x, y, 0.01);
      }
    });
    const g = this.ribbon.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.color.needsUpdate = true;
  }

  /** The dashed spike-threshold line in each lane (traces are drawn relative to the threshold, so it stays put). */
  private writeThreshold() {
    const amp = LANE * 0.5;
    const pts: number[] = [];
    TRACES.forEach((_, t) => {
      const y = this.base(t) + amp;
      for (let x = -SW / 2; x < SW / 2; x += 0.24) pts.push(x, y, 0.005, Math.min(SW / 2, x + 0.12), y, 0.005);
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    this.threshLines.geometry.dispose();
    this.threshLines.geometry = g;
  }

  update(dt: number, _t: number, _host: Host, data: BrainData) {
    this.thr = useFly.getState().brainCfg?.threshold ?? 1; // the brain's tuning (Brain tab) scales the traces
    this.acc += dt;
    let n = 0;
    while (this.acc >= TICK && n++ < 6) {
      this.acc -= TICK;
      this.tick(data);
    }
    if (this.acc > TICK) this.acc = 0; // fell far behind (tab was hidden): skip ahead
    if (n) {
      this.wallMat.uniforms.uHead.value = (this.col + 1) / this.T;
      this.wallMat.uniforms.uTicks.value = this.ticks;
      this.writeRibbon();
    }
    for (const s of this.heads) s.scale.setScalar(0.4 + Math.random() * 0.06);
    this.sparks.update(dt);
  }

  dispose() {
    this.tex?.dispose();
    this.tex = null;
  }
}
