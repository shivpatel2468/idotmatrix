import * as THREE from "three";
import { type FlyGfx, type FlyKey, type FlySnap, onPress, useFly } from "../../../lib/fly";
import { type FlyScene, type Host, Particles, approach, col, glowSprite, neuronMaterial, pointsMaterial } from "./host";

/** The fly's visual circuit as a glowing tower, top to bottom: compound eye → lamina (ON/OFF) → medulla T4/T5
 *  motion detectors → lobula plate HS/VS → LPLC2 looming → giant fibre → descending neurons → the keys.
 *  Every layer is driven by the live brain (GET /api/fly); signal pulses travel the wiring in proportion to
 *  activity, and each spike flashes its neuron and sends a pulse down to its key. */

const N = 16;
const CELL = 0.3;
const DN_ORDER = ["left", "up", "down", "right"] as const;

type Curve = { pts: Float32Array; src: () => number; color: THREE.Color; rate: number };

class Signals {
  points: THREE.Points;
  private pos: Float32Array;
  private colr: Float32Array;
  private size: Float32Array;
  private curve: Int32Array;
  private t: Float32Array;
  private speed: Float32Array;
  private next = 0;

  constructor(public n: number, public curves: Curve[]) {
    this.pos = new Float32Array(n * 3);
    this.colr = new Float32Array(n * 3);
    this.size = new Float32Array(n);
    this.curve = new Int32Array(n).fill(-1);
    this.t = new Float32Array(n);
    this.speed = new Float32Array(n);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(this.pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(this.colr, 3));
    g.setAttribute("aSize", new THREE.BufferAttribute(this.size, 1));
    this.points = new THREE.Points(g, pointsMaterial(1));
    this.points.frustumCulled = false;
  }

  fire(ci: number, boost = 1) {
    if (!this.n) return;
    const i = this.next;
    this.next = (this.next + 1) % this.n;
    this.curve[i] = ci;
    this.t[i] = 0;
    this.speed[i] = (0.9 + Math.random() * 0.6) * boost;
    const c = this.curves[ci].color;
    this.colr.set([c.r, c.g, c.b], i * 3);
    this.size[i] = 1.1 + Math.random() * 0.8 + (boost > 1 ? 1.2 : 0);
  }

  update(dt: number, density: number) {
    // spawn: each wire fires pulses in proportion to the activity of the cells it leaves
    for (let ci = 0; ci < this.curves.length; ci++) {
      const c = this.curves[ci];
      const p = c.src() * c.rate * density * dt;
      if (Math.random() < p) this.fire(ci);
    }
    for (let i = 0; i < this.n; i++) {
      const ci = this.curve[i];
      if (ci < 0) continue;
      this.t[i] += dt * this.speed[i];
      if (this.t[i] >= 1) {
        this.curve[i] = -1;
        this.size[i] = 0;
        continue;
      }
      const pts = this.curves[ci].pts;
      const segs = pts.length / 3 - 1;
      const f = this.t[i] * segs;
      const k = Math.floor(f);
      const u = f - k;
      for (let a = 0; a < 3; a++) this.pos[i * 3 + a] = pts[k * 3 + a] * (1 - u) + pts[(k + 1) * 3 + a] * u;
    }
    const g = this.points.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.color.needsUpdate = true;
    (g.attributes.aSize as THREE.BufferAttribute).needsUpdate = true;
  }
}

function bezier(a: THREE.Vector3, b: THREE.Vector3, bend: number, segs: number): Float32Array {
  const mid = a.clone().lerp(b, 0.5);
  mid.x += (Math.random() - 0.5) * bend;
  mid.z += (Math.random() - 0.5) * bend;
  const c = new THREE.QuadraticBezierCurve3(a, mid, b);
  const out = new Float32Array((segs + 1) * 3);
  c.getPoints(segs).forEach((p, i) => out.set([p.x, p.y, p.z], i * 3));
  return out;
}

type Soma = { mesh: THREE.Mesh; mat: THREE.ShaderMaterial; halo: THREE.Sprite; flash: number; charge: number; color: THREE.Color };

export class BrainScene implements FlyScene {
  private eye!: THREE.InstancedMesh;
  private lam!: THREE.InstancedMesh;
  private med!: THREE.InstancedMesh;
  private lp: Record<"left" | "right" | "up" | "down", Soma> = {} as never;
  private lplc2: Soma[] = [];
  private gf!: Soma;
  private gfTube!: THREE.Mesh;
  private dn: Record<string, Soma> = {};
  private outLabels: Record<string, HTMLElement> = {};
  private rings: { mesh: THREE.Mesh; life: number }[] = [];
  private signals!: Signals;
  private sparks!: Particles;
  private dust!: THREE.Points;
  private lightDot!: THREE.Sprite;
  private y = { eye: 0, lam: 0, med: 0, lp: 0, lplc2: 0, gf: 0, dn: 0, out: 0 };
  private cur = { eye: new Float32Array(N * N), on: new Float32Array(N * N), off: new Float32Array(N * N), mh: new Float32Array(N * N), mv: new Float32Array(N * N) };
  private val = { hs: { left: 0, right: 0, up: 0, down: 0 }, loom: 0, gf: 0, dn: { left: 0, right: 0, up: 0, down: 0 } };
  private unsub: (() => void) | null = null;
  private host: Host | null = null;
  private tmp = new THREE.Object3D();
  private c = new THREE.Color();
  private spread = 1;

  frame(mode: FlyGfx["camera"]) {
    const s = this.spread;
    const t = new THREE.Vector3(0, 0.2 * s, 0);
    const p: Record<FlyGfx["camera"], THREE.Vector3> = {
      orbit: new THREE.Vector3(10, 8.5 * s, 18),
      front: new THREE.Vector3(0, 1.5 * s, 23),
      top: new THREE.Vector3(0.01, 22, 4),
      close: new THREE.Vector3(3.5, 7.5 * s, 7),
    };
    return { target: mode === "close" ? new THREE.Vector3(0, 4.2 * s, 0) : t, position: p[mode] };
  }

  build(host: Host) {
    this.host = host;
    const th = host.theme;
    const lv = host.lv;
    const root = host.root;
    const s = (this.spread = host.gfx.brainSpread);
    this.y = { eye: 6.6 * s, lam: 4.7 * s, med: 2.9 * s, lp: 1.1 * s, lplc2: -0.6 * s, gf: -1.9 * s, dn: -3.4 * s, out: -5.1 * s };
    const seg = lv.segments;

    // light: a cool key, a warm rim, and the scene's own glow does the rest
    root.add(new THREE.AmbientLight(0xffffff, 0.25));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(4, 10, 8);
    root.add(key);
    const rim = new THREE.PointLight(col(th.accent), 30, 30);
    rim.position.set(-5, 2, -5);
    root.add(rim);

    const gx = (c: number) => (c - (N - 1) / 2) * CELL;

    // ---- compound eye: 256 hexagonal ommatidia on a dome
    const hex = new THREE.CylinderGeometry(CELL * 0.56, CELL * 0.5, 0.12, 6);
    const eyeMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.25, metalness: 0.1, emissive: 0xffffff, emissiveIntensity: 0.0 });
    eyeMat.onBeforeCompile = (sh) => {
      // emissive follows the instance colour: the ommatidia glow with what they see
      sh.fragmentShader = sh.fragmentShader.replace("#include <emissivemap_fragment>", "#include <emissivemap_fragment>\n totalEmissiveRadiance = vColor * 1.6;");
    };
    this.eye = new THREE.InstancedMesh(hex, eyeMat, N * N);
    for (let r = 0; r < N; r++)
      for (let c = 0; c < N; c++) {
        const x = gx(c) + (r % 2 ? CELL * 0.5 : 0);
        const z = gx(r) * 0.88;
        const d = x * x + z * z;
        this.tmp.position.set(x, this.y.eye + 0.9 - d * 0.075, z);
        this.tmp.lookAt(x * 2.2, this.y.eye + 6, z * 2.2);
        this.tmp.rotateX(Math.PI / 2);
        this.tmp.updateMatrix();
        this.eye.setMatrixAt(r * N + c, this.tmp.matrix);
        this.eye.setColorAt(r * N + c, this.c.set(0x111122));
      }
    root.add(this.eye);
    this.lightDot = glowSprite(col(th.eye), 0.9, 0.0);
    root.add(this.lightDot);

    // ---- lamina: ON (L1) and OFF (L2) cells
    this.lam = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.075, seg > 16 ? 2 : 1), new THREE.MeshBasicMaterial({ color: 0xffffff }), N * N);
    // ---- medulla: T4/T5 motion detectors, each a cone pointing the way it sees motion
    this.med = new THREE.InstancedMesh(new THREE.ConeGeometry(0.06, 0.26, 6), new THREE.MeshBasicMaterial({ color: 0xffffff }), N * N);
    for (let i = 0; i < N * N; i++) {
      this.lam.setColorAt(i, this.c.set(0x000000));
      this.med.setColorAt(i, this.c.set(0x000000));
    }
    root.add(this.lam, this.med);

    // ---- lobula plate tangential cells
    const lpPos = { left: [-2.1, 0], right: [2.1, 0], up: [0, -1.7], down: [0, 1.7] } as const;
    const lpName = { left: "HS ←", right: "HS →", up: "VS ↑", down: "VS ↓" };
    for (const k of ["left", "right", "up", "down"] as const) {
      const soma = this.soma(root, col(th[k]), 0.52, seg, new THREE.Vector3(lpPos[k][0], this.y.lp, lpPos[k][1]));
      soma.mesh.scale.set(1.25, 0.55, 1.25);
      this.lp[k] = soma;
      this.addLabel(host, soma.mesh, lpName[k], "", 0.8);
    }
    // ---- LPLC2 ring and the giant fibre
    this.lplc2 = [];
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2;
      this.lplc2.push(this.soma(root, col(th.loom), 0.17, seg, new THREE.Vector3(Math.cos(a) * 1.15, this.y.lplc2, Math.sin(a) * 1.15)));
    }
    const ringLbl = new THREE.Object3D();
    ringLbl.position.set(1.9, this.y.lplc2, 0);
    root.add(ringLbl);
    this.addLabel(host, ringLbl, "LPLC2 · looming", "", 0);
    this.gf = this.soma(root, col(th.gf), 0.48, seg, new THREE.Vector3(0, this.y.gf, 0));
    this.addLabel(host, this.gf.mesh, "Giant fibre", "", 0.75);
    const gfPath = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, this.y.lplc2, 0), new THREE.Vector3(0, this.y.gf, 0), new THREE.Vector3(0, this.y.dn, 0), new THREE.Vector3(0, this.y.out - 0.9, 0),
    ]);
    this.gfTube = new THREE.Mesh(
      new THREE.TubeGeometry(gfPath, 48, 0.07, Math.max(6, seg / 2), false),
      new THREE.MeshBasicMaterial({ color: col(th.gf), transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    root.add(this.gfTube);

    // ---- descending neurons and the keys they press
    this.dn = {};
    this.outLabels = {};
    // the descending neurons sit in a ring (each one reads from every camera angle), their keys below them
    const ring = (i: number, r: number) => {
      const a = ({ left: Math.PI, up: -Math.PI / 2, down: Math.PI / 2, right: 0 } as Record<string, number>)[DN_ORDER[i]];
      return [Math.cos(a) * r, Math.sin(a) * r] as const;
    };
    DN_ORDER.forEach((k, i) => {
      const [x, z] = ring(i, 1.9);
      const soma = this.soma(root, col(th.dn), 0.4, seg, new THREE.Vector3(x, this.y.dn, z));
      this.dn[k] = soma;
      this.addLabel(host, soma.mesh, `DN ${({ left: "←", up: "↑", down: "↓", right: "→" } as Record<string, string>)[k]}`, "", 0.62);
      const out = new THREE.Object3D();
      const [ox, oz] = ring(i, 2.3);
      out.position.set(ox, this.y.out, oz);
      root.add(out);
      this.outLabels[k] = this.addLabel(host, out, ({ left: "←", up: "↑", down: "↓", right: "→" } as Record<string, string>)[k], "fly-keycap", 0);
    });
    const outA = new THREE.Object3D();
    outA.position.set(0, this.y.out - 0.9, 0);
    root.add(outA);
    this.outLabels.a = this.addLabel(host, outA, "A", "fly-keycap fly-keycap-a", 0);

    for (const [y, text] of [[this.y.eye + 0.6, "Eye · 256 ommatidia"], [this.y.lam, "Lamina L1 ON / L2 OFF"], [this.y.med, "Medulla T4 / T5 motion"]] as const) {
      const o = new THREE.Object3D();
      o.position.set(0, y + 0.55, -gx(N - 1) - 0.3);
      root.add(o);
      this.addLabel(host, o, text, "fly-label-side", 0);
    }

    // ---- wiring: thin glowing lines, and the pulses that travel them
    const curves: Curve[] = [];
    const segs = 14;
    const pick = (n: number) => Array.from({ length: n }, () => Math.floor(Math.random() * N * N));
    const at = (i: number, y: number) => new THREE.Vector3(gx(i % N), y, gx(Math.floor(i / N)) * 0.88);
    const nWires = Math.round(40 * Math.min(1.5, Math.max(0.4, lv.particles)));
    for (const i of pick(nWires)) curves.push({ pts: bezier(at(i, this.y.eye + 0.8), at(i, this.y.lam), 0.3, segs), src: () => this.cur.eye[i] * 0.7 + 0.08, color: col(th.eye), rate: 1.3 });
    for (const i of pick(nWires)) curves.push({ pts: bezier(at(i, this.y.lam), at(i, this.y.med), 0.3, segs), src: () => Math.min(1, this.cur.on[i] + this.cur.off[i]) + 0.04, color: this.cur.on[i] >= this.cur.off[i] ? col(th.on) : col(th.off), rate: 3 });
    for (const i of pick(nWires)) {
      const k = (["left", "right", "up", "down"] as const)[Math.floor(Math.random() * 4)];
      const p = this.lp[k].mesh.position;
      curves.push({ pts: bezier(at(i, this.y.med), p, 1.4, segs), src: () => Math.min(1, this.val.hs[k] * 2) + 0.03, color: col(th[k]), rate: 2.4 });
    }
    for (const k of ["left", "right", "up", "down"] as const) {
      const from = this.lp[k].mesh.position;
      for (const d of DN_ORDER) {
        const to = this.dn[d].mesh.position;
        curves.push({ pts: bezier(from, to, 1.0, segs), src: () => (d === k ? 0.9 : 0.12) * Math.min(1, this.val.hs[k] * 2 + this.val.dn[d] * 0.5), color: col(th[k]), rate: 2.6 });
      }
    }
    for (const n of this.lplc2) curves.push({ pts: bezier(n.mesh.position, this.gf.mesh.position, 0.5, segs), src: () => Math.min(1, this.val.loom * 1.2), color: col(th.loom), rate: 6 });
    this.dnCurve = {};
    for (const k of DN_ORDER) {
      // the eye's light (phototaxis) feeds the descending neurons directly
      curves.push({ pts: bezier(new THREE.Vector3(0, this.y.eye, 0), this.dn[k].mesh.position, 3.5, segs * 2), src: () => this.val.dn[k] * 0.6, color: col(th.dn), rate: 1.4 });
      // and each one's axon runs down to its key (pulses only when it spikes)
      const p = this.dn[k].mesh.position;
      this.dnCurve[k] = curves.length;
      curves.push({ pts: bezier(p, new THREE.Vector3(p.x * 1.21, this.y.out, p.z * 1.21), 0.2, segs), src: () => 0, color: col(th.dn), rate: 0 });
    }
    const gfOut = gfPath.getPoints(segs * 2);
    const gfPts = new Float32Array(gfOut.length * 3);
    gfOut.forEach((q, i) => gfPts.set([q.x, q.y, q.z], i * 3));
    this.gfCurve = curves.length;
    curves.push({ pts: gfPts, src: () => 0, color: col(th.gf), rate: 0 });

    if (host.gfx.trails) {
      const pos: number[] = [];
      for (const c of curves) {
        for (let i = 0; i + 3 < c.pts.length; i += 3) pos.push(c.pts[i], c.pts[i + 1], c.pts[i + 2], c.pts[i + 3], c.pts[i + 4], c.pts[i + 5]);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      root.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: col(th.wire), transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false })));
    }
    this.signals = new Signals(Math.round(900 * lv.particles), curves);
    root.add(this.signals.points);
    this.sparks = new Particles(Math.round(500 * lv.particles), 1);
    root.add(this.sparks.points);

    // ---- atmosphere: floating dust and a floor that fades into the fog
    const nd = Math.round(260 * lv.particles);
    const dp = new Float32Array(nd * 3);
    const dc = new Float32Array(nd * 3);
    const ds = new Float32Array(nd);
    const ac = col(th.accent);
    for (let i = 0; i < nd; i++) {
      dp.set([(Math.random() - 0.5) * 16, (Math.random() - 0.5) * 16 * s, (Math.random() - 0.5) * 12], i * 3);
      dc.set([ac.r * 0.35, ac.g * 0.35, ac.b * 0.35], i * 3);
      ds[i] = 0.4 + Math.random() * 0.7;
    }
    const dg = new THREE.BufferGeometry();
    dg.setAttribute("position", new THREE.BufferAttribute(dp, 3));
    dg.setAttribute("color", new THREE.BufferAttribute(dc, 3));
    dg.setAttribute("aSize", new THREE.BufferAttribute(ds, 1));
    this.dust = new THREE.Points(dg, pointsMaterial(1));
    root.add(this.dust);
    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(9, 64),
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        uniforms: { uColor: { value: col(th.accent) }, uTime: { value: 0 } },
        vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
        fragmentShader: /* glsl */ `
          uniform vec3 uColor; uniform float uTime; varying vec2 vUv;
          void main(){
            vec2 p = (vUv - 0.5) * 18.0;
            float r = length(p);
            vec2 g = abs(fract(p) - 0.5);
            float line = smoothstep(0.47, 0.5, max(g.x, g.y));
            float ring = smoothstep(0.08, 0.0, abs(fract(r * 0.5 - uTime * 0.25) - 0.5) - 0.42);
            float fade = smoothstep(9.0, 1.0, r);
            gl_FragColor = vec4(uColor, (line * 0.16 + ring * 0.12) * fade);
          }`,
      }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = this.y.out - 1.6;
    this.floor = floor;
    root.add(floor);

    this.rings = [];
    this.unsub?.();
    this.unsub = onPress((p) => this.spike(p.key));
  }

  private gfCurve = 0;
  private dnCurve: Record<string, number> = {};
  private floor: THREE.Mesh | null = null;

  private soma(root: THREE.Object3D, color: THREE.Color, r: number, seg: number, at: THREE.Vector3): Soma {
    const mat = neuronMaterial(color);
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(r, seg, Math.max(8, seg * 0.75)), mat);
    mesh.position.copy(at);
    const halo = glowSprite(color, r * 5, 0.25);
    halo.position.copy(at);
    root.add(mesh, halo);
    return { mesh, mat, halo, flash: 0, charge: 0, color };
  }

  private addLabel(host: Host, parent: THREE.Object3D, text: string, cls: string, dy: number): HTMLElement {
    const l = host.label(text, cls);
    l.position.set(0, dy, 0);
    parent.add(l);
    return l.element.firstElementChild as HTMLElement;
  }

  /** A descending neuron (or the giant fibre) fired: flash, shockwave, sparks, and a pulse down to its key. */
  private spike(k: FlyKey) {
    const host = this.host;
    if (!host) return;
    const soma = k === "a" ? this.gf : this.dn[k];
    if (!soma) return;
    soma.flash = 1;
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.5, 0.025, 6, 48),
      new THREE.MeshBasicMaterial({ color: soma.color, transparent: true, opacity: 1, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    ring.position.copy(soma.mesh.position);
    ring.rotation.x = Math.PI / 2;
    host.root.add(ring);
    this.rings.push({ mesh: ring, life: 1 });
    this.sparks.burst(soma.mesh.position, soma.color, Math.round(26 * host.lv.particles) + 4, 3.2);
    const ci = k === "a" ? this.gfCurve : this.dnCurve[k];
    for (let i = 0; i < 4; i++) setTimeout(() => this.signals.fire(ci, 1.6), i * 45);
    if (k === "a") for (const n of this.lplc2) n.flash = 1;
    const el = this.outLabels[k];
    if (el) {
      el.classList.remove("hit");
      void el.offsetWidth;
      el.classList.add("hit");
    }
  }

  update(dt: number, t: number, host: Host) {
    const snap: FlySnap = useFly.getState().snap;
    const th = host.theme;
    const cur = this.cur;
    const rate = 12;
    const k = 1 - Math.exp(-rate * dt);
    const take = (dst: Float32Array, src: number[] | undefined, scale: number) => {
      if (!src) return;
      for (let i = 0; i < dst.length; i++) dst[i] += ((src[i] ?? 0) * scale - dst[i]) * k;
    };
    take(cur.eye, snap.eye, 1 / 255);
    take(cur.on, snap.on, 1 / 255);
    take(cur.off, snap.off, 1 / 255);
    take(cur.mh, snap.mh, 1 / 127);
    take(cur.mv, snap.mv, 1 / 127);
    const v = this.val;
    for (const d of ["left", "right", "up", "down"] as const) {
      v.hs[d] = approach(v.hs[d], snap.hs?.[d] ?? 0, rate, dt);
      v.dn[d] = approach(v.dn[d], snap.dn?.[d] ?? 0, rate, dt);
    }
    v.loom = approach(v.loom, snap.looming ?? 0, rate, dt);
    v.gf = approach(v.gf, snap.gf ?? 0, rate, dt);

    // eye: ommatidia glow with what they see
    const eyeC = col(th.eye);
    for (let i = 0; i < N * N; i++) {
      const e = cur.eye[i];
      this.c.setRGB(0.03 + eyeC.r * e * 1.2, 0.03 + eyeC.g * e * 1.2, 0.05 + eyeC.b * e * 1.2);
      this.eye.setColorAt(i, this.c);
    }
    this.eye.instanceColor!.needsUpdate = true;
    const [lx, ly] = snap.light ?? [0, 0];
    const lit = Math.hypot(lx, ly) > 0.01;
    this.lightDot.position.set(lx * 8 * CELL, this.y.eye + 1.1, ly * 8 * CELL * 0.88);
    (this.lightDot.material as THREE.SpriteMaterial).opacity = approach((this.lightDot.material as THREE.SpriteMaterial).opacity, lit ? 0.9 : 0, 6, dt);
    this.lightDot.scale.setScalar(0.8 + Math.sin(t * 6) * 0.12);

    // lamina and medulla
    const on = col(th.on);
    const off = col(th.off);
    const gx = (c: number) => (c - (N - 1) / 2) * CELL;
    for (let r = 0; r < N; r++)
      for (let c = 0; c < N; c++) {
        const i = r * N + c;
        const a = Math.min(1, cur.on[i]);
        const b = Math.min(1, cur.off[i]);
        const act = Math.max(a, b);
        this.tmp.position.set(gx(c), this.y.lam + act * 0.25, gx(r) * 0.88);
        this.tmp.rotation.set(0, 0, 0);
        this.tmp.scale.setScalar(0.45 + act * 1.6);
        this.tmp.updateMatrix();
        this.lam.setMatrixAt(i, this.tmp.matrix);
        this.c.setRGB(0.04 + on.r * a + off.r * b, 0.04 + on.g * a + off.g * b, 0.06 + on.b * a + off.b * b);
        this.lam.setColorAt(i, this.c);

        const mx = cur.mh[i];
        const mz = cur.mv[i];
        const m = Math.min(1, Math.hypot(mx, mz) * 1.4);
        this.tmp.position.set(gx(c), this.y.med, gx(r) * 0.88);
        this.tmp.rotation.set(0, 0, 0);
        if (m > 0.02) {
          // the cone points along the motion it detects (+x right, +z down the panel)
          this.tmp.lookAt(gx(c) + mx, this.y.med, gx(r) * 0.88 + mz);
          this.tmp.rotateX(Math.PI / 2);
        }
        this.tmp.scale.set(0.6 + m, 0.35 + m * 1.6, 0.6 + m);
        this.tmp.updateMatrix();
        this.med.setMatrixAt(i, this.tmp.matrix);
        const dirCol = Math.abs(mx) > Math.abs(mz) ? (mx > 0 ? th.right : th.left) : mz > 0 ? th.down : th.up;
        const dc = col(dirCol);
        this.c.setRGB(0.05 + dc.r * m, 0.05 + dc.g * m, 0.07 + dc.b * m);
        this.med.setColorAt(i, this.c);
      }
    this.lam.instanceMatrix.needsUpdate = true;
    this.lam.instanceColor!.needsUpdate = true;
    this.med.instanceMatrix.needsUpdate = true;
    this.med.instanceColor!.needsUpdate = true;

    const drive = (s: Soma, charge: number) => {
      s.charge = approach(s.charge, Math.min(1, charge), 10, dt);
      s.flash = Math.max(0, s.flash - dt * 2.6);
      s.mat.uniforms.uCharge.value = s.charge;
      s.mat.uniforms.uFlash.value = s.flash;
      s.mat.uniforms.uTime.value = t;
      const pulse = 1 + s.flash * 0.35 + Math.sin(t * 3 + s.mesh.position.x) * 0.015;
      s.halo.material.opacity = 0.1 + s.charge * 0.28 + s.flash * 0.8;
      s.halo.scale.setScalar((s.mesh.geometry as THREE.SphereGeometry).parameters.radius * 5 * pulse);
    };
    for (const d of ["left", "right", "up", "down"] as const) drive(this.lp[d], v.hs[d] * 2.2);
    for (const n of this.lplc2) drive(n, v.loom * 1.2);
    drive(this.gf, v.gf);
    for (const d of DN_ORDER) drive(this.dn[d], v.dn[d]);
    (this.gfTube.material as THREE.MeshBasicMaterial).opacity = 0.18 + v.gf * 0.5 + this.gf.flash * 0.8;

    for (const r of this.rings) {
      r.life -= dt * 1.6;
      r.mesh.scale.setScalar(1 + (1 - r.life) * 4);
      (r.mesh.material as THREE.MeshBasicMaterial).opacity = Math.max(0, r.life);
      if (r.life <= 0) {
        host.root.remove(r.mesh);
        r.mesh.geometry.dispose();
        (r.mesh.material as THREE.Material).dispose();
      }
    }
    this.rings = this.rings.filter((r) => r.life > 0);
    this.signals.update(dt, host.lv.particles);
    this.sparks.update(dt);
    this.dust.rotation.y = t * 0.02;
    this.dust.position.y = Math.sin(t * 0.3) * 0.2;
    if (this.floor) (this.floor.material as THREE.ShaderMaterial).uniforms.uTime.value = t;
    // a slow breath of the whole tower
    host.root.position.y = Math.sin(t * 0.6) * 0.06;
  }

  dispose() {
    this.unsub?.();
  }
}
