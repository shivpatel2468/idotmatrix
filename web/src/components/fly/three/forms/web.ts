import * as THREE from "three";
import type { FlyKey, Shot } from "../../../../lib/fly";
import { type BrainData, type BrainForm, DN_GROUP, G, GI, GROUPS, KEY_GROUP, LINKS, N, PointSet, neuronPoints, pulseLines } from "../data";
import { type Host, Particles } from "../host";

/** The neural web: a living force-directed graph of a few hundred neurons. Nodes repel, synapses pull, and each
 *  stage of the circuit is drawn to its own layer, so the web settles into the pathway (eye on top, neck at the
 *  bottom) and keeps breathing: busy synapses pull tighter, a spike jolts its neurons. One draw call for the
 *  neurons, one for the synapses (positions stream every frame; pulses run in the shader). */

const SHARE: Record<string, number> = {
  eye: 0.13, l1: 0.065, l2: 0.065, t4: 0.085, t5: 0.085, hsl: 0.03, hsr: 0.03, vsu: 0.03, vsd: 0.03, lplc2: 0.06, gf: 0.012,
  dnl: 0.035, dnu: 0.035, dnd: 0.035, dnr: 0.035, vnc: 0.05, cb: 0.13,
};
const LAYER = (stage: number) => 4.4 - stage * 1.25;
const LABELS: [string[], string][] = [
  [["eye"], "Eye"], [["l1", "l2"], "Lamina"], [["t4", "t5"], "T4 / T5"], [["hsl", "hsr", "vsu", "vsd"], "HS / VS"],
  [["lplc2"], "LPLC2"], [["gf"], "Giant fibre"], [["dnl", "dnu", "dnd", "dnr"], "Descending neurons"], [["vnc"], "Neck"], [["cb"], "Central brain"],
];

export class WebForm implements BrainForm {
  bloomThreshold = 0.12;
  shots: Shot[] = ["orbit", "close", "front", "top"];
  private n = 0;
  private pos: Float32Array<ArrayBufferLike> = new Float32Array(0);
  private vel = new Float32Array(0);
  private layerY = new Float32Array(0);
  private edges = new Int32Array(0); // pairs
  private edgeLink = new Int32Array(0);
  private ePos = new Float32Array(0);
  private nodes!: THREE.Points;
  private lines: THREE.LineSegments | null = null;
  private alpha = 1;
  private members: number[][] = [];
  private labels: { obj: THREE.Object3D; groups: number[] }[] = [];
  private sparks!: Particles;
  private c = new THREE.Vector3();

  frame(mode: Shot) {
    const dn = this.centroid([DN_GROUP.left, DN_GROUP.right, DN_GROUP.up, DN_GROUP.down], new THREE.Vector3());
    if (!this.n) dn.set(0, LAYER(6), 0);
    const p: Record<Shot, THREE.Vector3> = {
      orbit: new THREE.Vector3(9, 4.5, 18.5),
      front: new THREE.Vector3(0, 0.3, 21),
      top: new THREE.Vector3(0.01, 17, 3.5),
      close: dn.clone().add(new THREE.Vector3(3, 1.6, 6.5)),
    };
    return { target: mode === "close" ? dn : new THREE.Vector3(0, -0.6, 0), position: p[mode] };
  }

  build(host: Host, data: BrainData) {
    const lv = host.lv;
    const root = host.root;
    const total = Math.round(Math.min(520, Math.max(100, 420 * lv.particles)));

    // ---- nodes, seeded on their layer
    const pts = new PointSet();
    const v = new THREE.Vector3();
    GROUPS.forEach((g, gi) => {
      const n = Math.max(gi === GI.gf ? 2 : 4, Math.round(total * SHARE[g.id]));
      for (let i = 0; i < n; i++) {
        const a = Math.random() * Math.PI * 2;
        const r = Math.sqrt(Math.random()) * 2.4;
        if (g.stage < 0) v.set((Math.random() < 0.5 ? -1 : 1) * (3.2 + Math.random()), (Math.random() - 0.5) * 6, (Math.random() - 0.5) * 2);
        else v.set(Math.cos(a) * r, LAYER(g.stage) + (Math.random() - 0.5) * 0.4, Math.sin(a) * r);
        const big = gi === GI.gf ? 2.6 : g.stage === 6 ? 1.9 : g.stage === 3 ? 1.6 : 1.15;
        pts.add(v, gi, g.chan ? Math.floor(Math.random() * N * N) : -1, big * (0.85 + Math.random() * 0.3));
      }
    });
    this.n = pts.group.length;
    const geo = pts.geometry();
    this.pos = (geo.attributes.position as THREE.BufferAttribute).array as Float32Array;
    (geo.attributes.position as THREE.BufferAttribute).setUsage(THREE.DynamicDrawUsage);
    this.vel = new Float32Array(this.n * 3);
    this.layerY = Float32Array.from(pts.group, (g) => (GROUPS[g].stage < 0 ? NaN : LAYER(GROUPS[g].stage)));
    this.members = pts.members;
    this.nodes = new THREE.Points(geo, neuronPoints(data, lv.pixelRatio, 1.6));
    this.nodes.frustumCulled = false;
    root.add(this.nodes);

    // ---- synapses: every neuron of a target group takes inputs from a few of its source group, plus some
    // lateral wiring inside the per-cell layers
    const e: number[] = [], el: number[] = [];
    LINKS.forEach((l, li) => {
      const from = this.members[l.from], to = this.members[l.to];
      if (!from.length || !to.length) return;
      const fan = from.length < 4 ? from.length : l.from === GI.cb || l.to === GI.cb ? 1 : 2;
      const keep = l.tone || l.from === GI.cb ? 0.4 : 1; // long-range modulation: sparser, so the pathway reads
      for (const b of to) for (let k = 0; k < fan; k++) {
        if (Math.random() > keep) continue;
        e.push(from[Math.floor(Math.random() * from.length)], b);
        el.push(li);
      }
    });
    for (let g = 0; g < G; g++) {
      if (!GROUPS[g].chan) continue;
      const li = LINKS.findIndex((l) => l.from === g);
      const m = this.members[g];
      if (li < 0) continue;
      for (let k = 0; k < m.length * 0.5; k++) {
        e.push(m[Math.floor(Math.random() * m.length)], m[Math.floor(Math.random() * m.length)]);
        el.push(li);
      }
    }
    this.edges = Int32Array.from(e);
    this.edgeLink = Int32Array.from(el);
    const ne = el.length;
    this.ePos = new Float32Array(ne * 6);
    const lg = new THREE.BufferGeometry();
    const pa = new THREE.BufferAttribute(this.ePos, 3);
    pa.setUsage(THREE.DynamicDrawUsage);
    lg.setAttribute("position", pa);
    lg.setAttribute("aLink", new THREE.Float32BufferAttribute(Array.from(el, (x) => [x, x]).flat(), 1));
    lg.setAttribute("aT", new THREE.Float32BufferAttribute(Array.from({ length: ne }, () => [0, 1]).flat(), 1));
    lg.setAttribute("aSeed", new THREE.Float32BufferAttribute(Array.from({ length: ne }, () => { const s = Math.random(); return [s, s]; }).flat(), 1));
    this.lines = null;
    if (host.gfx.trails) {
      this.lines = new THREE.LineSegments(lg, pulseLines(data, 1, 1.3));
      this.lines.frustumCulled = false;
      root.add(this.lines);
    } else lg.dispose();

    // the layout settles over the first seconds (and keeps breathing after)
    this.alpha = 1;
    for (let i = 0; i < 40; i++) this.step(data, 1);
    this.writeEdges();

    this.labels = LABELS.map(([ids, text]) => {
      const l = host.label(text, ids[0] === "cb" || ids[0] === "vnc" ? "fly-label-side" : "");
      root.add(l);
      return { obj: l, groups: ids.map((id) => GI[id]) };
    });
    this.sparks = new Particles(Math.round(420 * lv.particles), 1);
    this.sparks.gravity = 0;
    this.sparks.drag = 2.2;
    root.add(this.sparks.points);
  }

  private centroid(groups: number[], out: THREE.Vector3) {
    out.set(0, 0, 0);
    let n = 0;
    for (const g of groups)
      for (const i of this.members[g] ?? []) {
        out.x += this.pos[i * 3];
        out.y += this.pos[i * 3 + 1];
        out.z += this.pos[i * 3 + 2];
        n++;
      }
    return n ? out.divideScalar(n) : out;
  }

  /** The right-hand half of a group that hangs on both sides (the rest of the central brain). */
  private sideCentroid(g: number, out: THREE.Vector3) {
    out.set(0, 0, 0);
    let n = 0;
    for (const i of this.members[g]) {
      if (this.pos[i * 3] <= 0) continue;
      out.x += this.pos[i * 3];
      out.y += this.pos[i * 3 + 1];
      out.z += this.pos[i * 3 + 2];
      n++;
    }
    return n ? out.divideScalar(n) : out;
  }

  /** One iteration of the layout: repulsion (all pairs), springs on synapses (shorter when busy), each stage
   *  drawn to its layer, a gentle pull to the middle. */
  private step(data: BrainData, alpha: number) {
    const n = this.n, p = this.pos, v = this.vel;
    for (let i = 0; i < n; i++) {
      const ix = i * 3;
      for (let j = i + 1; j < n; j++) {
        const jx = j * 3;
        const dx = p[ix] - p[jx], dy = p[ix + 1] - p[jx + 1], dz = p[ix + 2] - p[jx + 2];
        const d2 = dx * dx + dy * dy + dz * dz + 0.02;
        if (d2 > 9) continue; // far apart: no push
        const f = 0.03 / d2;
        v[ix] += dx * f; v[ix + 1] += dy * f; v[ix + 2] += dz * f;
        v[jx] -= dx * f; v[jx + 1] -= dy * f; v[jx + 2] -= dz * f;
      }
    }
    const la = data.uLinkAct.value;
    const e = this.edges;
    for (let k = 0; k < e.length; k += 2) {
      const a = e[k] * 3, b = e[k + 1] * 3;
      const dx = p[b] - p[a], dy = p[b + 1] - p[a + 1], dz = p[b + 2] - p[a + 2];
      const len = Math.sqrt(dx * dx + dy * dy + dz * dz) + 1e-4;
      const li = this.edgeLink[k / 2];
      const rest = 1.1 * (1 - 0.3 * (li >= 0 ? la[li] : 0));
      const f = ((len - rest) / len) * 0.006;
      // springs mostly pull sideways, so the layers stay flat and the pathway reads top to bottom
      v[a] += dx * f; v[a + 1] += dy * f * 0.15; v[a + 2] += dz * f;
      v[b] -= dx * f; v[b + 1] -= dy * f * 0.15; v[b + 2] -= dz * f;
    }
    for (let i = 0; i < n; i++) {
      const ix = i * 3;
      const ly = this.layerY[i];
      if (!Number.isNaN(ly)) v[ix + 1] += (ly - p[ix + 1]) * 0.06;
      else v[ix] += (Math.sign(p[ix] || 1) * 4.2 - p[ix]) * 0.03; // the rest of the brain hangs at the sides
      v[ix] -= p[ix] * 0.0015;
      v[ix + 2] -= p[ix + 2] * 0.004;
      v[ix] *= 0.82; v[ix + 1] *= 0.82; v[ix + 2] *= 0.82;
      p[ix] += v[ix] * alpha; p[ix + 1] += v[ix + 1] * alpha; p[ix + 2] += v[ix + 2] * alpha;
    }
  }

  private writeEdges() {
    const e = this.edges, p = this.pos, out = this.ePos;
    for (let k = 0; k < e.length; k += 2) {
      const a = e[k] * 3, b = e[k + 1] * 3, o = k * 3;
      out[o] = p[a]; out[o + 1] = p[a + 1]; out[o + 2] = p[a + 2];
      out[o + 3] = p[b]; out[o + 4] = p[b + 1]; out[o + 5] = p[b + 2];
    }
    if (this.lines) this.lines.geometry.attributes.position.needsUpdate = true;
  }

  spike(k: FlyKey, host: Host, data: BrainData) {
    const g = KEY_GROUP[k];
    this.sparks.sphere(this.centroid([g], this.c), data.colors[g], Math.round(28 * host.lv.particles) + 5, 2.4, 0.8, 1.3);
    if (host.reduced) return;
    for (const i of this.members[g]) for (let a = 0; a < 3; a++) this.vel[i * 3 + a] += (Math.random() - 0.5) * 0.25; // a jolt
  }

  update(dt: number, _t: number, host: Host, data: BrainData) {
    this.alpha = Math.max(host.reduced ? 0 : 0.35, this.alpha - dt * 0.18);
    if (this.alpha > 0) {
      this.step(data, this.alpha);
      this.nodes.geometry.attributes.position.needsUpdate = true;
      this.writeEdges();
    }
    for (const l of this.labels) {
      if (l.groups[0] === GI.cb) this.sideCentroid(GI.cb, this.c);
      else this.centroid(l.groups, this.c);
      l.obj.position.set(this.c.x + 0.2, this.c.y + 0.55, this.c.z);
    }
    this.sparks.update(dt);
  }
}
