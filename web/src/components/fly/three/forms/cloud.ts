import * as THREE from "three";
import type { FlyKey, Shot } from "../../../../lib/fly";
import {
  type BrainData, type BrainForm, GI, GROUPS, KEY_GROUP, LINKS, LineSet, N, PointSet, hullMaterial, inEllipsoid, neuronPoints, pick, pulseLines,
} from "../data";
import { type Host, Particles, col, glowSprite } from "../host";

/** The connectome cloud: a brain-shaped cloud of thousands of neurons (two optic lobes and the central brain,
 *  like a FlyWire rendering), every cluster one stage of the circuit. The optic lobes are retinotopic — each eye
 *  sees half of the panel, and the lamina and medulla behind it light up in the same layout. Bundled synapse
 *  tracts link the clusters and carry pulses as activity flows eye → lamina → medulla → lobula plate →
 *  LPLC2 / giant fibre → descending neurons → neck. Neurons and synapses are each one draw call. */

const V = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z);
type Side = -1 | 1;

export class CloudForm implements BrainForm {
  bloomThreshold = 0.1;
  shots: Shot[] = ["orbit", "close", "front", "top"];
  private pts = new PointSet();
  private side: number[] = []; // -1 / +1 per point (x sign), for wiring within one optic lobe
  private centroid: THREE.Vector3[] = [];
  private hulls: THREE.ShaderMaterial[] = [];
  private sparks!: Particles;
  private lightDot!: THREE.Sprite;
  private keycaps: Partial<Record<FlyKey, HTMLElement>> = {};
  private cloud!: THREE.Points;

  frame(mode: Shot) {
    const t = V(0, -0.9, 0);
    const p: Record<Shot, THREE.Vector3> = {
      orbit: V(8.5, 5, 17.5),
      front: V(0, 0.2, 20),
      top: V(0.01, 19, 4),
      close: V(8.8, 2, 6.2),
    };
    return { target: mode === "close" ? V(4.4, 0.1, 0) : t, position: p[mode] };
  }

  build(host: Host, data: BrainData) {
    const th = host.theme;
    const lv = host.lv;
    const root = host.root;
    this.pts = new PointSet();
    this.side = [];
    const total = Math.round(Math.min(18000, Math.max(1500, 10000 * lv.particles)));
    const n = (share: number) => Math.max(8, Math.round(total * share));

    // ---- the optic lobes: retina, lamina, medulla (T4), lobula (T5), lobula plate (HS/VS), LPLC2
    for (const s of [-1, 1] as Side[]) {
      this.retina(s, GI.eye, n(0.08), V(s * 5.7, 0.15, 0.3), V(1.0, 1.9, 1.5), 0.1, 0.5);
      // lamina: half L1 (ON), half L2 (OFF), the same layout just behind the eye
      this.retina(s, GI.l1, n(0.035), V(s * 5.25, 0.15, 0.25), V(0.75, 1.65, 1.3), 0.14, 0.4);
      this.retina(s, GI.l2, n(0.035), V(s * 5.2, 0.15, 0.25), V(0.72, 1.6, 1.25), 0.14, 0.4);
      // medulla (T4) and lobula (T5): still retinotopic, smaller and further in
      this.retina(s, GI.t4, n(0.05), V(s * 4.55, 0.1, 0.15), V(0.55, 1.35, 1.1), 0.3, 0.36);
      this.retina(s, GI.t5, n(0.035), V(s * 3.95, 0.0, -0.15), V(0.4, 1.05, 0.85), 0.3, 0.36);
      // lobula plate: the four wide-field cells
      this.blob(s, GI.hsl, n(0.008), V(s * 3.35, 0.5, -0.45), V(0.24, 0.32, 0.3), 0.55);
      this.blob(s, GI.hsr, n(0.008), V(s * 3.35, 0.5, 0.1), V(0.24, 0.32, 0.3), 0.55);
      this.blob(s, GI.vsu, n(0.008), V(s * 3.35, -0.35, -0.45), V(0.24, 0.32, 0.3), 0.55);
      this.blob(s, GI.vsd, n(0.008), V(s * 3.35, -0.35, 0.1), V(0.24, 0.32, 0.3), 0.55);
      this.blob(s, GI.lplc2, n(0.02), V(s * 3.6, 0.8, 0.6), V(0.38, 0.42, 0.36), 0.45);
      // the giant fibre: a pair of huge neurons in the central brain
      this.blob(s, GI.gf, n(0.0025), V(s * 0.5, 0.35, -0.3), V(0.16, 0.16, 0.16), 1.4);
    }
    // ---- central brain: the bulk (mushroom bodies, central complex…), then the descending neurons and the neck
    const cb = n(0.3);
    for (let i = 0; i < cb; i++) this.add(inEllipsoid(V(0, 0.15, 0), V(2.55, 1.75, 1.45)), GI.cb, -1, 0.3 + Math.random() * 0.15);
    for (const s of [-1, 1] as Side[]) this.blob(s, GI.cb, n(0.03), V(s * 1.1, 0.95, -0.6), V(0.55, 0.42, 0.42), 0.32); // mushroom-body calyces
    for (let i = 0; i < n(0.03); i++) {
      // the central complex: a fan-shaped band across the midline
      const a = (Math.random() - 0.5) * 2.2;
      this.add(V(Math.sin(a) * 0.95, 0.35 + Math.cos(a) * 0.35 + (Math.random() - 0.5) * 0.12, 0.25 + (Math.random() - 0.5) * 0.25), GI.cb, -1, 0.34);
    }
    this.blob(-1, GI.dnl, n(0.012), V(-0.8, -0.95, 0.35), V(0.26, 0.24, 0.24), 0.75);
    this.blob(1, GI.dnr, n(0.012), V(0.8, -0.95, 0.35), V(0.26, 0.24, 0.24), 0.75);
    this.blob(-1, GI.dnu, n(0.012), V(-0.18, -0.6, 0.75), V(0.24, 0.22, 0.22), 0.75);
    this.blob(1, GI.dnd, n(0.012), V(0.18, -1.25, 0.6), V(0.24, 0.22, 0.22), 0.75);
    for (let i = 0; i < n(0.025); i++) {
      const u = Math.random();
      const r = 0.32 * (1 - u * 0.35) * Math.sqrt(Math.random());
      const a = Math.random() * Math.PI * 2;
      this.add(V(Math.cos(a) * r, -1.55 - u * 1.9, 0.15 + u * 0.15 + Math.sin(a) * r), GI.vnc, -1, 0.45);
    }

    // centroids, for labels, bursts and tract bundling
    this.centroid = GROUPS.map((_, g) => {
      const m = this.pts.members[g];
      const c = new THREE.Vector3();
      const tmp = new THREE.Vector3();
      for (const i of m) c.add(this.pts.at(i, tmp));
      return m.length ? c.divideScalar(m.length) : c;
    });

    this.cloud = new THREE.Points(this.pts.geometry(), neuronPoints(data, lv.pixelRatio, 1));
    this.cloud.frustumCulled = false;
    root.add(this.cloud);

    // ---- synapse tracts: per link and side, a bundle of curves through a shared waypoint
    const lines = new LineSet();
    const per = Math.round(Math.min(60, Math.max(5, 30 * lv.particles)));
    const segs = lv.segments >= 24 ? 12 : lv.segments >= 16 ? 9 : 6;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), ctrl = new THREE.Vector3(), way = new THREE.Vector3();
    LINKS.forEach((l, li) => {
      for (const s of [-1, 1] as Side[]) {
        const from = this.bySide(l.from, s);
        const to = this.bySide(l.to, s);
        if (!from.length || !to.length) continue;
        const ca = this.sideCentroid(l.from, s), cb2 = this.sideCentroid(l.to, s);
        const dist = ca.distanceTo(cb2);
        way.copy(ca).lerp(cb2, 0.5).add(V(0, dist * 0.18, -dist * 0.12));
        for (let k = 0; k < per; k++) {
          this.pts.at(pick(from), a);
          this.pts.at(pick(to), b);
          const spread = 0.12 + dist * 0.06;
          ctrl.copy(way).add(V((Math.random() - 0.5) * spread, (Math.random() - 0.5) * spread, (Math.random() - 0.5) * spread));
          lines.curve(a, ctrl, b, li, segs);
        }
      }
    });
    if (host.gfx.trails) {
      const wires = new THREE.LineSegments(lines.geometry(), pulseLines(data, 0.85, 1.1));
      wires.frustumCulled = false;
      root.add(wires);
    }

    // ---- the FlyWire-style hull: translucent neuropil shells with a faint wireframe
    this.hulls = [];
    const hullCol = col(th.wire).lerp(col(th.accent), 0.25);
    const shell = (c: THREE.Vector3, r: THREE.Vector3, seed: number) => {
      const geo = new THREE.SphereGeometry(1, Math.max(24, lv.segments * 2), Math.max(16, lv.segments * 1.4));
      const p = geo.attributes.position as THREE.BufferAttribute;
      for (let i = 0; i < p.count; i++) {
        const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
        const bump = 1 + 0.045 * Math.sin(x * 5 + seed) * Math.sin(y * 4 - seed) + 0.03 * Math.sin(z * 7 + seed * 2);
        p.setXYZ(i, x * r.x * bump + c.x, y * r.y * bump + c.y, z * r.z * bump + c.z);
      }
      geo.computeVertexNormals();
      const mat = hullMaterial(hullCol, 0.9);
      this.hulls.push(mat);
      root.add(new THREE.Mesh(geo, mat));
      const wire = new THREE.SphereGeometry(1, 22, 14);
      const wp = wire.attributes.position as THREE.BufferAttribute;
      for (let i = 0; i < wp.count; i++) wp.setXYZ(i, wp.getX(i) * r.x * 1.01 + c.x, wp.getY(i) * r.y * 1.01 + c.y, wp.getZ(i) * r.z * 1.01 + c.z);
      root.add(new THREE.LineSegments(new THREE.WireframeGeometry(wire), new THREE.LineBasicMaterial({ color: hullCol, transparent: true, opacity: 0.07, blending: THREE.AdditiveBlending, depthWrite: false })));
      wire.dispose();
    };
    shell(V(0, 0.15, 0), V(2.75, 1.95, 1.6), 1);
    shell(V(-4.55, 0.1, 0.1), V(1.55, 2.05, 1.7), 2);
    shell(V(4.55, 0.1, 0.1), V(1.55, 2.05, 1.7), 3);

    // ---- light the fly is drawn to, sparks, labels
    this.lightDot = glowSprite(col(th.eye), 1.1, 0);
    root.add(this.lightDot);
    this.sparks = new Particles(Math.round(500 * lv.particles), 1);
    this.sparks.gravity = 0;
    this.sparks.drag = 2.4;
    root.add(this.sparks.points);

    const label = (text: string, at: THREE.Vector3, cls = "") => {
      const l = host.label(text, cls);
      l.position.copy(at);
      root.add(l);
      return l.element.firstElementChild as HTMLElement;
    };
    label("Retina", this.sideCentroid(GI.eye, 1).clone().add(V(0.6, 2.0, 0)), "fly-label-side");
    label("Lamina", this.sideCentroid(GI.l1, 1).clone().add(V(0, -1.95, 0.4)), "fly-label-side");
    label("Medulla · T4", this.sideCentroid(GI.t4, 1).clone().add(V(0, 1.6, 0)), "fly-label-side");
    label("Lobula · T5", this.sideCentroid(GI.t5, 1).clone().add(V(-0.2, -1.4, 0)), "fly-label-side");
    label("HS / VS", this.sideCentroid(GI.hsl, 1).clone().add(V(-0.2, -1.3, -0.4)));
    label("LPLC2", this.sideCentroid(GI.lplc2, 1).clone().add(V(0.3, 0.75, 0.5)));
    label("Giant fibre", this.sideCentroid(GI.gf, 1).clone().add(V(0.5, 0.35, 0)));
    label("Descending neurons", V(0, -0.2, 1.3));
    label("Central brain", V(0, 2.2, 0), "fly-label-side");
    label("Neck", V(0.75, -2.6, 0.3), "fly-label-side");
    this.keycaps = {};
    const keys: [FlyKey, string, number][] = [["left", "←", -1.3], ["up", "↑", -0.45], ["down", "↓", 0.45], ["right", "→", 1.3]];
    for (const [k, g, x] of keys) this.keycaps[k] = label(g, V(x, -4.0, 0.4), "fly-keycap");
    this.keycaps.a = label("A", V(0, -4.75, 0.4), "fly-keycap fly-keycap-a");
  }

  private add(p: THREE.Vector3, g: number, cell: number, size: number) {
    this.pts.add(p, g, cell, size);
    this.side.push(p.x < 0 ? -1 : 1);
  }

  /** Retinotopic layer: each point belongs to one eye cell. The left eye sees the left half of the panel,
   *  the right eye the right half, laid out so the image reads left → right from the front. */
  private retina(s: Side, g: number, count: number, c: THREE.Vector3, r: THREE.Vector3, depth: number, size: number) {
    const d = new THREE.Vector3();
    for (let i = 0; i < count; i++) {
      const row = Math.floor(Math.random() * N);
      const half = Math.floor(Math.random() * (N / 2));
      const colIdx = s < 0 ? half : N / 2 + half;
      // 0 = lateral edge … 1 = facing front
      const lateral = s < 0 ? half / (N / 2 - 1) : (N - 1 - colIdx) / (N / 2 - 1);
      const phi = (lateral + (Math.random() - 0.5) / (N / 2)) * 1.25;
      const el = (0.5 - (row + Math.random() - 0.5) / (N - 1)) * 2.1;
      d.set(s * Math.cos(phi) * Math.cos(el), Math.sin(el), Math.sin(phi) * Math.cos(el));
      const k = 1 - Math.random() * depth;
      this.add(V(c.x + d.x * r.x * k, c.y + d.y * r.y * k, c.z + d.z * r.z * k), g, row * N + colIdx, size * (0.8 + Math.random() * 0.4));
    }
  }

  private blob(_s: Side, g: number, count: number, c: THREE.Vector3, r: THREE.Vector3, size: number) {
    for (let i = 0; i < count; i++) this.add(inEllipsoid(c, r, undefined, 0.6), g, -1, size * (0.75 + Math.random() * 0.5));
  }

  /** Points of a group on one side (central groups that sit on one side only count for both). */
  private bySide(g: number, s: Side): number[] {
    const m = this.pts.members[g];
    const own = m.filter((i) => this.side[i] === s);
    return own.length ? own : m;
  }

  private sideCentroid(g: number, s: Side) {
    const m = this.bySide(g, s);
    const c = new THREE.Vector3();
    const tmp = new THREE.Vector3();
    for (const i of m) c.add(this.pts.at(i, tmp));
    return m.length ? c.divideScalar(m.length) : c;
  }

  spike(k: FlyKey, host: Host, data: BrainData) {
    const g = KEY_GROUP[k];
    const at = this.centroid[g];
    if (at) this.sparks.sphere(at, data.colors[g], Math.round(30 * host.lv.particles) + 6, 2.6, 0.8, 1.3);
    const el = this.keycaps[k];
    if (el) {
      el.classList.remove("hit");
      void el.offsetWidth;
      el.classList.add("hit");
    }
  }

  update(dt: number, t: number, host: Host, data: BrainData) {
    const glow = Math.min(1, data.overall * 2.5);
    for (const h of this.hulls) h.uniforms.uGlow.value = glow;
    const [lx, ly] = data.light;
    const lit = Math.hypot(lx, ly) > 0.02;
    this.lightDot.position.set(lx * 6, 0.2 - ly * 2.5, 3.4);
    const m = this.lightDot.material as THREE.SpriteMaterial;
    m.opacity += ((lit ? 0.85 : 0) - m.opacity) * Math.min(1, dt * 5);
    this.lightDot.scale.setScalar(1 + Math.sin(t * 5) * 0.12);
    this.sparks.update(dt);
    if (!host.reduced) this.cloud.scale.setScalar(1 + Math.sin(t * 0.7) * 0.006); // a faint breath
  }
}
