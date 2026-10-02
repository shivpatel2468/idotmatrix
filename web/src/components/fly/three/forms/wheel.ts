import * as THREE from "three";
import type { FlyKey, Shot } from "../../../../lib/fly";
import { type BrainData, type BrainForm, GI, GROUPS, KEY_GROUP, LINKS, LineSet, N, PointSet, neuronPoints, pick, pulseLines } from "../data";
import { type Host, Particles, approach, glowSprite } from "../host";

/** The radial wheel: every neuron group of the circuit around a ring (a chord diagram in 3D). Each sector is a
 *  band of neurons (per-cell groups scan the eye image along their arc), an activity band and a spectrum of bars;
 *  synapse chords arc between the groups, bowed out of the plane so the wheel has depth, and pulse with activity.
 *  A spike sends a burst out of its sector and a ripple across the wheel. */

const R = 3.6;
const GAP = 0.035;
/** Sector order and relative size: the pathway clockwise from the top, the rest of the central brain last. */
const ORDER: [string, number][] = [
  ["eye", 3], ["l1", 2], ["l2", 2], ["t4", 2.2], ["t5", 2.2], ["hsl", 1], ["hsr", 1], ["vsu", 1], ["vsd", 1], ["lplc2", 1.4],
  ["gf", 0.9], ["dnl", 1], ["dnu", 1], ["dnd", 1], ["dnr", 1], ["vnc", 1.2], ["cb", 2.5],
];
const KEY_LABEL: Record<string, string> = { dnl: "←", dnu: "↑", dnd: "↓", dnr: "→", gf: "A" };

type Sector = { g: number; a0: number; a1: number; mid: number };
type Bar = { g: number; a: number; cell: number; h: number; phase: number };

export class WheelForm implements BrainForm {
  bloomThreshold = 0.1;
  shots: Shot[] = ["front", "orbit", "close", "top"];
  private sectors: Sector[] = [];
  private bySector: Record<number, Sector> = {};
  private bars: Bar[] = [];
  private barMesh!: THREE.InstancedMesh;
  private hub!: THREE.Sprite;
  private lightDot!: THREE.Sprite;
  private sparks!: Particles;
  private ripples: { mesh: THREE.Mesh; life: number }[] = [];
  private rippleGeo: THREE.RingGeometry | null = null;
  private keyEls: Partial<Record<FlyKey, HTMLElement>> = {};
  private tmp = new THREE.Object3D();
  private c = new THREE.Color();
  private dnMid = 0;

  frame(mode: Shot) {
    const dn = new THREE.Vector3(Math.cos(this.dnMid) * R * 0.85, Math.sin(this.dnMid) * R * 0.85, 0);
    const p: Record<Shot, THREE.Vector3> = {
      front: new THREE.Vector3(0, 0, 17.5),
      orbit: new THREE.Vector3(7, 4.5, 15),
      top: new THREE.Vector3(0.01, 13.5, 9),
      close: dn.clone().add(new THREE.Vector3(2.5, 0.8, 6.5)),
    };
    return { target: mode === "close" ? dn : new THREE.Vector3(0, 0, 0), position: p[mode] };
  }

  build(host: Host, data: BrainData) {
    const lv = host.lv;
    const root = host.root;

    // ---- sectors, clockwise from the top
    const total = ORDER.reduce((n, [, w]) => n + w, 0);
    const span = Math.PI * 2 - GAP * ORDER.length;
    let a = Math.PI / 2;
    this.sectors = [];
    this.bySector = {};
    for (const [id, w] of ORDER) {
      const len = (w / total) * span;
      const s: Sector = { g: GI[id], a0: a - len, a1: a, mid: a - len / 2 };
      this.sectors.push(s);
      this.bySector[s.g] = s;
      a -= len + GAP;
    }
    this.dnMid = (this.bySector[GI.dnu].mid + this.bySector[GI.dnd].mid) / 2;

    // ---- neurons: a dense band along each sector's arc
    const pts = new PointSet();
    const count = Math.round(Math.min(2800, Math.max(400, 1700 * lv.particles)));
    const v = new THREE.Vector3();
    for (const s of this.sectors) {
      const w = ORDER.find(([id]) => GI[id] === s.g)![1];
      const n = Math.max(12, Math.round((w / total) * count));
      for (let i = 0; i < n; i++) {
        const u = Math.random();
        const ang = s.a1 - u * (s.a1 - s.a0);
        const lane = Math.floor(Math.random() * 4);
        const r = R - lane * 0.16 - Math.random() * 0.1;
        v.set(Math.cos(ang) * r, Math.sin(ang) * r, (Math.random() - 0.5) * 0.25);
        // per-cell groups scan the eye image along their arc
        pts.add(v, s.g, GROUPS[s.g].chan ? Math.min(N * N - 1, Math.floor(u * N * N)) : -1, s.g === GI.gf ? 0.9 : 0.42 + Math.random() * 0.2);
      }
    }
    const cloud = new THREE.Points(pts.geometry(), neuronPoints(data, lv.pixelRatio, 1));
    cloud.frustumCulled = false;
    root.add(cloud);

    // ---- the activity band: one geometry for every sector, lit per group by the shader
    const band: number[] = [], bandG: number[] = [], bandV: number[] = [];
    const idx: number[] = [];
    for (const s of this.sectors) {
      const steps = Math.max(4, Math.round(((s.a1 - s.a0) / (Math.PI * 2)) * 160));
      const base = band.length / 3;
      for (let i = 0; i <= steps; i++) {
        const ang = s.a1 - (i / steps) * (s.a1 - s.a0);
        for (const [r, vv] of [[R + 0.22, 0], [R + 0.4, 1]] as const) {
          band.push(Math.cos(ang) * r, Math.sin(ang) * r, 0);
          bandG.push(s.g);
          bandV.push(vv);
        }
        if (i < steps) {
          const k = base + i * 2;
          idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2);
        }
      }
    }
    const bg = new THREE.BufferGeometry();
    bg.setAttribute("position", new THREE.Float32BufferAttribute(band, 3));
    bg.setAttribute("aGroup", new THREE.Float32BufferAttribute(bandG, 1));
    bg.setAttribute("aV", new THREE.Float32BufferAttribute(bandV, 1));
    bg.setIndex(idx);
    root.add(new THREE.Mesh(bg, bandMaterial(data)));

    // ---- spectrum bars outside the band (one instanced mesh)
    this.bars = [];
    for (const s of this.sectors) {
      const n = Math.max(3, Math.round(((s.a1 - s.a0) / (Math.PI * 2)) * 150 * Math.min(1.3, Math.max(0.5, lv.particles))));
      for (let i = 0; i < n; i++) {
        const u = (i + 0.5) / n;
        this.bars.push({ g: s.g, a: s.a1 - u * (s.a1 - s.a0), cell: Math.floor(u * N * N), h: 0, phase: Math.random() * 6.28 });
      }
    }
    this.barMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.055, 1, 0.055), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false }), this.bars.length);
    this.barMesh.frustumCulled = false;
    for (let i = 0; i < this.bars.length; i++) this.barMesh.setColorAt(i, this.c.set(0));
    root.add(this.barMesh);

    // ---- synapse chords: through the middle for far groups, along the rim for neighbours, bowed out of plane
    const lines = new LineSet();
    const per = Math.round(Math.min(44, Math.max(4, 22 * lv.particles)));
    const segs = lv.segments >= 24 ? 22 : lv.segments >= 16 ? 16 : 10;
    const pa = new THREE.Vector3(), pb = new THREE.Vector3(), ctrl = new THREE.Vector3();
    LINKS.forEach((l, li) => {
      const from = pts.members[l.from], to = pts.members[l.to];
      if (!from.length || !to.length) return;
      for (let k = 0; k < per; k++) {
        pts.at(pick(from), pa);
        pts.at(pick(to), pb);
        const ang = pa.angleTo(pb); // 0 … π
        ctrl.copy(pa).add(pb).multiplyScalar(0.5 * (0.1 + 0.75 * (1 - ang / Math.PI) ** 1.5));
        ctrl.z += (Math.random() - 0.5) * 3.2;
        lines.curve(pa, ctrl, pb, li, segs);
      }
    });
    if (host.gfx.trails) {
      const chords = new THREE.LineSegments(lines.geometry(), pulseLines(data, 0.8, 0.9));
      chords.frustumCulled = false;
      root.add(chords);
    }

    // ---- hub, light, sparks, ripples, labels
    this.hub = glowSprite(data.colors[GI.cb], 2.2, 0.3);
    root.add(this.hub);
    this.lightDot = glowSprite(data.colors[GI.eye], 0.9, 0);
    root.add(this.lightDot);
    this.sparks = new Particles(Math.round(500 * lv.particles), 1);
    this.sparks.gravity = 0;
    this.sparks.drag = 2;
    root.add(this.sparks.points);
    this.ripples = [];
    this.rippleGeo = new THREE.RingGeometry(0.96, 1, 96);

    this.keyEls = {};
    for (const s of this.sectors) {
      const lr = R + (s.g === GI.cb || s.g === GI.eye ? 2.0 : 1.85);
      const l = host.label(GROUPS[s.g].short, KEY_LABEL[GROUPS[s.g].id] ? "fly-keycap fly-keycap-sm" : "");
      l.position.set(Math.cos(s.mid) * lr, Math.sin(s.mid) * lr, 0);
      root.add(l);
      const key = (Object.entries(KEY_GROUP) as [FlyKey, number][]).find(([, g]) => g === s.g)?.[0];
      if (key) this.keyEls[key] = l.element.firstElementChild as HTMLElement;
    }
  }

  spike(k: FlyKey, host: Host, data: BrainData) {
    const g = KEY_GROUP[k];
    const s = this.bySector[g];
    if (!s || !this.rippleGeo) return;
    const at = new THREE.Vector3(Math.cos(s.mid) * R, Math.sin(s.mid) * R, 0);
    this.sparks.sphere(at, data.colors[g], Math.round(34 * host.lv.particles) + 6, 3, 0.9, 1.4);
    const ring = new THREE.Mesh(this.rippleGeo, new THREE.MeshBasicMaterial({ color: data.colors[g], transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    ring.scale.setScalar(0.3);
    host.root.add(ring);
    this.ripples.push({ mesh: ring, life: 1 });
    const el = this.keyEls[k];
    if (el) {
      el.classList.remove("hit");
      void el.offsetWidth;
      el.classList.add("hit");
    }
  }

  update(dt: number, t: number, host: Host, data: BrainData) {
    // bars: per-cell groups read their eye cell, the rest wobble around their group's activity
    const flash = data.uFlash.value;
    for (let i = 0; i < this.bars.length; i++) {
      const b = this.bars[i];
      const chan = GROUPS[b.g].chan;
      const target = chan ? data.cell(b.g, b.cell) : data.act[b.g] * (0.75 + 0.25 * Math.sin(t * 3.1 + b.phase)) + flash[b.g] * 0.6;
      b.h = approach(b.h, target, 10, dt);
      const h = 0.06 + b.h * 1.1;
      const r = R + 0.55 + h / 2;
      this.tmp.position.set(Math.cos(b.a) * r, Math.sin(b.a) * r, 0);
      this.tmp.rotation.set(0, 0, b.a - Math.PI / 2);
      this.tmp.scale.set(1, h, 1);
      this.tmp.updateMatrix();
      this.barMesh.setMatrixAt(i, this.tmp.matrix);
      const k = 0.25 + b.h * 1.1 + flash[b.g];
      const gc = data.colors[b.g];
      this.c.setRGB(gc.r * k, gc.g * k, gc.b * k);
      this.barMesh.setColorAt(i, this.c);
    }
    this.barMesh.instanceMatrix.needsUpdate = true;
    this.barMesh.instanceColor!.needsUpdate = true;

    const hm = this.hub.material as THREE.SpriteMaterial;
    hm.opacity = 0.15 + Math.min(0.6, data.overall * 1.8);
    this.hub.scale.setScalar(2 + data.overall * 2 + (host.reduced ? 0 : Math.sin(t * 2) * 0.1));
    const [lx, ly] = data.light;
    this.lightDot.position.set(lx * R * 0.75, -ly * R * 0.75, 0.4);
    const lm = this.lightDot.material as THREE.SpriteMaterial;
    lm.opacity = approach(lm.opacity, Math.hypot(lx, ly) > 0.02 ? 0.9 : 0, 5, dt);

    for (const r of this.ripples) {
      r.life -= dt * 1.3;
      r.mesh.scale.setScalar(0.3 + (1 - r.life) * (R + 0.6));
      (r.mesh.material as THREE.MeshBasicMaterial).opacity = Math.max(0, r.life) * 0.8;
      if (r.life <= 0) {
        host.root.remove(r.mesh);
        (r.mesh.material as THREE.Material).dispose();
      }
    }
    this.ripples = this.ripples.filter((r) => r.life > 0);
    this.sparks.update(dt);
  }

  dispose() {
    this.rippleGeo?.dispose();
    this.rippleGeo = null;
  }
}

/** The activity band: each sector's arc lit by its group's activity and flash, brighter on the outer edge. */
function bandMaterial(data: BrainData) {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    defines: { NG: GROUPS.length },
    uniforms: { uAct: data.uAct, uFlash: data.uFlash, uColor: data.uColor, uTime: data.uTime },
    vertexShader: /* glsl */ `
      attribute float aGroup; attribute float aV;
      uniform float uAct[NG]; uniform float uFlash[NG]; uniform vec3 uColor[NG];
      varying vec3 vCol; varying float vV; varying float vA;
      void main() {
        int g = int(aGroup + 0.5);
        vCol = uColor[g];
        vA = uAct[g] + uFlash[g] * 1.4;
        vV = aV;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      varying vec3 vCol; varying float vV; varying float vA;
      void main() {
        float edge = smoothstep(0.0, 0.25, vV) * smoothstep(1.0, 0.7, vV);
        gl_FragColor = vec4(vCol * (0.12 + vA * 0.9) * (0.4 + edge * 0.8), 1.0);
      }`,
  });
}
