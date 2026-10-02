import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { type CameraMode, type FlyGfx, type Level, type Quality, type Shot, THEMES, type Theme, level } from "../../../lib/fly";

/** What a scene implements; the host owns the renderer, the loop and the quality. */
export interface FlyScene {
  /** Which setting holds this scene's camera. */
  camKey: "camBrain" | "camKeys";
  /** Settings (beyond theme and quality) whose change needs a rebuild; anything else applies live. */
  deps: (keyof FlyGfx)[];
  /** Build (or rebuild, when the theme or quality changes) everything inside `root`. */
  build(host: Host): void;
  update(dt: number, t: number, host: Host): void;
  /** Where the camera looks and how far it sits, per camera angle. */
  frame(mode: Shot): { target: THREE.Vector3; position: THREE.Vector3 };
  /** The angles the cinematic camera cuts between (default: all four). */
  shots?: Shot[];
  /** Settings that change the scene's shape: the camera re-frames when they change. */
  reframeOn?: (keyof FlyGfx)[];
  /** Bloom threshold (0..1): lit scenes need a higher one than glowing ones. */
  bloomThreshold?: number;
  dispose?(): void;
}

const ORDER: Exclude<Quality, "auto">[] = ["low", "balanced", "high", "ultra"];
const COMMON: (keyof FlyGfx)[] = ["theme", "quality", "bloom", "particles", "shadows"];
const Y = new THREE.Vector3(0, 1, 0);

type CamAnim = { from: THREE.Vector3; to: THREE.Vector3; tFrom: THREE.Vector3; tTo: THREE.Vector3; p: number; rate: number };

/** A WebGL view with bloom, labels, orbit controls, an fps cap, adaptive quality, a cinematic camera, and
 *  pause-when-hidden. One per visible canvas: dispose() gives the GL context back. */
export class Host {
  renderer: THREE.WebGLRenderer;
  labels: CSS2DRenderer;
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 200);
  controls: OrbitControls;
  root = new THREE.Group();
  composer: EffectComposer | null = null;
  bloom: UnrealBloomPass | null = null;
  gfx: FlyGfx;
  theme: Theme;
  lv: Level;
  /** The quality actually in use (Auto steps it up or down from measured frame times). */
  tier: Exclude<Quality, "auto">;
  fps = 0;
  /** prefers-reduced-motion: no auto-rotate, no cinematic cuts; scenes calm their own idle motion. */
  reduced = false;
  onFps?: (fps: number, tier: string) => void;

  private raf = 0;
  private last = 0;
  private acc = 0;
  private frames = 0;
  private slow = 0;
  private fast = 0;
  private clock = 0;
  private visible = true;
  private ro: ResizeObserver;
  private io: IntersectionObserver;
  private mq: MediaQueryList;
  private touched = false; // the person has moved the camera: stop re-framing on resize
  private camAnim: CamAnim | null = null;
  private cine = { next: 0, i: -1, shot: "orbit" as Shot };

  constructor(private el: HTMLElement, private view: FlyScene, gfx: FlyGfx) {
    this.gfx = gfx;
    this.theme = THEMES[gfx.theme];
    this.tier = gfx.quality === "auto" ? (navigator.hardwareConcurrency >= 8 ? "high" : "balanced") : gfx.quality;
    this.lv = level(this.tier, gfx);
    this.mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    this.reduced = this.mq.matches;
    this.mq.addEventListener("change", this.onMotionPref);
    this.renderer = this.makeRenderer();
    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "fly-labels";
    el.appendChild(this.labels.domElement);
    this.scene.add(this.root);
    this.controls = new OrbitControls(this.camera, this.labels.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.enablePan = false;
    this.controls.minDistance = 3;
    this.controls.maxDistance = 40;
    this.controls.addEventListener("start", () => {
      this.touched = true;
      this.camAnim = null;
      this.cine.next = this.clock + 12; // the cinematic camera waits while the person looks around
    });
    this.rebuild();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(el);
    this.io = new IntersectionObserver(([e]) => (this.visible = e.isIntersecting));
    this.io.observe(el);
    this.resize();
    this.last = performance.now();
    this.raf = requestAnimationFrame(this.loop);
  }

  /** The camera setting for this scene. */
  get mode(): CameraMode {
    return this.gfx[this.view.camKey];
  }

  /** The fixed angle the camera rests at: the cinematic camera's current shot, or the chosen angle. */
  private get rest(): Shot {
    const m = this.mode;
    return m === "cinematic" ? (this.reduced ? "orbit" : this.cine.shot) : m;
  }

  private onMotionPref = () => {
    this.reduced = this.mq.matches;
    this.syncControls();
  };

  private makeRenderer() {
    const r = new THREE.WebGLRenderer({ antialias: this.lv.aa, powerPreference: "high-performance", alpha: false });
    r.setPixelRatio(this.lv.pixelRatio);
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 1.05;
    r.shadowMap.enabled = this.lv.shadows;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.domElement.className = "fly-canvas";
    this.el.prepend(r.domElement);
    return r;
  }

  /** Settings changed. Only what needs it is rebuilt (theme, quality, the scene's own `deps`); camera, glow
   *  strength, rotation, labels and layout apply live, so dragging a wing's width never rebuilds a scene. */
  apply(gfx: FlyGfx, force = false) {
    const prev = this.gfx;
    this.gfx = gfx;
    this.theme = THEMES[gfx.theme];
    if (gfx.quality !== "auto") this.tier = gfx.quality;
    const lv = level(this.tier, gfx);
    const was = this.lv;
    const lvChanged = (Object.keys(lv) as (keyof Level)[]).some((k) => lv[k] !== was[k]);
    const need = force || lvChanged || [...COMMON, ...this.view.deps].some((k) => prev[k] !== gfx[k]);
    if (need) {
      this.lv = lv;
      if (lv.aa !== was.aa) {
        // antialiasing is fixed at context creation
        this.disposeRenderer();
        this.renderer = this.makeRenderer();
      }
      this.renderer.setPixelRatio(this.lv.pixelRatio);
      this.renderer.shadowMap.enabled = this.lv.shadows;
      this.rebuild();
      this.resize();
      if (this.view.reframeOn?.some((k) => prev[k] !== gfx[k])) this.flyTo(this.rest);
    }
    if (this.bloom) this.bloom.strength = gfx.bloomStrength;
    if (prev[this.view.camKey] !== gfx[this.view.camKey]) this.setMode();
    this.syncControls();
  }

  /** The camera setting changed: glide to the new angle (or start the cinematic camera). */
  private setMode() {
    if (this.mode === "cinematic") {
      this.cine.next = this.clock; // first cut now
      this.cine.i = -1;
      if (this.reduced) this.flyTo("orbit");
    } else this.flyTo(this.mode);
  }

  private syncControls() {
    const m = this.mode;
    this.controls.autoRotate = !this.reduced && ((this.gfx.autoRotate && m === "orbit") || m === "cinematic");
    this.controls.autoRotateSpeed = m === "cinematic" ? 0.35 : this.gfx.rotateSpeed * 1.2;
    this.labels.domElement.dataset.hide = String(!this.gfx.labels);
  }

  /** The scene's camera for an angle, pulled back so it fits a narrow (tall) view. */
  private fit(mode: Shot) {
    const f = this.view.frame(mode);
    const k = Math.max(1, 1.05 / Math.max(0.3, this.camera.aspect));
    f.position.sub(f.target).multiplyScalar(k).add(f.target);
    return f;
  }

  flyTo(mode: Shot, rate = 1.4) {
    this.touched = false;
    const f = this.fit(mode);
    this.camAnim = { from: this.camera.position.clone(), to: f.position, tFrom: this.controls.target.clone(), tTo: f.target, p: 0, rate };
  }

  /** Cinematic: the next shot, seen from a slightly different side and distance; a slow dolly most of the
   *  time, a hard cut now and then. */
  private cut() {
    const list = this.view.shots ?? ["orbit", "close", "front", "top"];
    this.cine.i = (this.cine.i + 1) % list.length;
    this.cine.shot = list[this.cine.i];
    const f = this.fit(this.cine.shot);
    const off = f.position.clone().sub(f.target).applyAxisAngle(Y, (Math.random() - 0.5) * 1.3).multiplyScalar(0.82 + Math.random() * 0.3);
    f.position.copy(f.target).add(off);
    this.touched = false;
    if (Math.random() < 0.3 && this.cine.i > 0) {
      this.camAnim = null;
      this.camera.position.copy(f.position);
      this.controls.target.copy(f.target);
    } else {
      this.camAnim = { from: this.camera.position.clone(), to: f.position, tFrom: this.controls.target.clone(), tTo: f.target, p: 0, rate: 0.42 };
    }
    this.cine.next = this.clock + 6.5 + Math.random() * 3.5;
  }

  private rebuild() {
    this.disposeTree(this.root);
    // CSS labels live in the DOM: take every one out (nested ones never see a "removed" event)
    this.root.traverse((o) => {
      if (o instanceof CSS2DObject) o.element.remove();
    });
    for (const c of [...this.root.children]) this.root.remove(c);
    const th = this.theme;
    this.scene.background = new THREE.Color(th.bg);
    this.scene.fog = new THREE.FogExp2(new THREE.Color(th.fog), 0.035);
    this.view.build(this);
    this.composer?.dispose();
    this.composer = null;
    this.bloom = null;
    if (this.lv.bloom) {
      const size = this.renderer.getSize(new THREE.Vector2());
      this.composer = new EffectComposer(this.renderer);
      this.composer.addPass(new RenderPass(this.scene, this.camera));
      // half-resolution bloom: most of the look for a fraction of the cost
      this.bloom = new UnrealBloomPass(new THREE.Vector2(size.x / 2, size.y / 2), this.gfx.bloomStrength, 0.5, this.view.bloomThreshold ?? 0.2);
      this.composer.addPass(this.bloom);
      this.composer.addPass(new OutputPass());
    }
    this.syncControls();
  }

  /** A DOM label pinned to a 3D point. The renderer positions the outer element with a transform, so styling
   *  and animation go on the inner one (`.firstElementChild`). */
  label(text: string, cls = ""): CSS2DObject {
    const outer = document.createElement("div");
    const d = document.createElement("div");
    d.className = `fly-label ${cls}`;
    d.textContent = text;
    outer.appendChild(d);
    return new CSS2DObject(outer);
  }

  private resize() {
    const w = Math.max(1, this.el.clientWidth);
    const h = Math.max(1, this.el.clientHeight);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = `${w}px`;
    this.renderer.domElement.style.height = `${h}px`;
    this.labels.setSize(w, h);
    this.composer?.setSize(w, h);
    this.composer?.setPixelRatio(this.lv.pixelRatio);
    if (!this.touched && !this.camAnim) {
      const f = this.fit(this.rest);
      this.camera.position.copy(f.position);
      this.controls.target.copy(f.target);
    }
  }

  private loop = (now: number) => {
    this.raf = requestAnimationFrame(this.loop);
    if (!this.visible || document.visibilityState !== "visible") {
      this.last = now;
      return;
    }
    const cap = this.gfx.fpsCap;
    const min = cap ? 1000 / cap - 1.5 : 0;
    if (now - this.last < min) return;
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    this.clock += dt;
    this.measure(dt);
    if (this.mode === "cinematic" && !this.reduced && this.clock >= this.cine.next) this.cut();
    if (this.camAnim) {
      const a = this.camAnim;
      a.p = Math.min(1, a.p + dt * a.rate);
      const e = a.rate < 1 ? a.p * a.p * (3 - 2 * a.p) : 1 - (1 - a.p) ** 3; // dollies ease in and out
      this.camera.position.lerpVectors(a.from, a.to, e);
      this.controls.target.lerpVectors(a.tFrom, a.tTo, e);
      if (a.p >= 1) this.camAnim = null;
    }
    this.controls.update(dt);
    this.view.update(dt, this.clock, this);
    if (this.composer) this.composer.render(dt);
    else this.renderer.render(this.scene, this.camera);
    if (this.gfx.labels) this.labels.render(this.scene, this.camera);
  };

  /** Auto quality: step down after ~2 s of slow frames, up after ~6 s of headroom. */
  private measure(dt: number) {
    this.frames++;
    this.acc += dt;
    if (this.acc < 1) return;
    this.fps = Math.round(this.frames / this.acc);
    this.frames = 0;
    this.acc = 0;
    this.onFps?.(this.fps, this.tier);
    if (this.gfx.quality !== "auto") return;
    const target = this.gfx.fpsCap || 60;
    const i = ORDER.indexOf(this.tier);
    if (this.fps < target * 0.72) {
      this.fast = 0;
      if (++this.slow >= 2 && i > 0) {
        this.slow = 0;
        this.tier = ORDER[i - 1];
        this.apply(this.gfx, true);
      }
    } else if (this.fps >= target * 0.95) {
      this.slow = 0;
      if (++this.fast >= 6 && i < ORDER.length - 2) {
        // Auto never climbs to Ultra on its own
        this.fast = 0;
        this.tier = ORDER[i + 1];
        this.apply(this.gfx, true);
      }
    } else {
      this.slow = this.fast = 0;
    }
  }

  private disposeTree(o: THREE.Object3D) {
    o.traverse((c) => {
      const m = c as THREE.Mesh;
      m.geometry?.dispose?.();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
      else mat?.dispose?.();
    });
  }

  private disposeRenderer() {
    this.renderer.dispose();
    this.renderer.forceContextLoss(); // browsers cap live WebGL contexts: give this one back now
    this.renderer.domElement.remove();
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.io.disconnect();
    this.mq.removeEventListener("change", this.onMotionPref);
    this.view.dispose?.();
    this.disposeTree(this.root);
    this.root.traverse((o) => {
      if (o instanceof CSS2DObject) o.element.remove();
    });
    this.composer?.dispose();
    this.controls.dispose();
    this.disposeRenderer();
    this.labels.domElement.remove();
  }
}

// ------------------------------------------------------------------ shared materials and helpers

export const col = (hex: string) => new THREE.Color(hex);

/** A soft additive glow sprite texture (generated, no assets). Shared by every scene: never disposed. */
let glowTex: THREE.Texture | null = null;
export function glowTexture(): THREE.Texture {
  if (glowTex) return glowTex;
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, "rgba(255,255,255,1)");
  r.addColorStop(0.18, "rgba(255,255,255,0.75)");
  r.addColorStop(0.45, "rgba(255,255,255,0.18)");
  r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r;
  g.fillRect(0, 0, 128, 128);
  glowTex = new THREE.CanvasTexture(c);
  glowTex.colorSpace = THREE.SRGBColorSpace;
  return glowTex;
}

export function glowSprite(color: THREE.ColorRepresentation, size: number, opacity = 1) {
  const s = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: glowTexture(), color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }),
  );
  s.scale.setScalar(size);
  return s;
}

/** Fresnel "membrane" shader: a dark core, a bright rim, and an inner charge that fills from the bottom. */
export function neuronMaterial(color: THREE.Color) {
  return new THREE.ShaderMaterial({
    transparent: true,
    uniforms: { uColor: { value: color.clone() }, uCharge: { value: 0 }, uFlash: { value: 0 }, uTime: { value: 0 } },
    vertexShader: /* glsl */ `
      varying vec3 vN; varying vec3 vV; varying vec3 vP;
      void main() {
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vP = position;
        vN = normalize(normalMatrix * normal);
        vV = normalize(-(viewMatrix * wp).xyz);
        gl_Position = projectionMatrix * viewMatrix * wp;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor; uniform float uCharge; uniform float uFlash; uniform float uTime;
      varying vec3 vN; varying vec3 vV; varying vec3 vP;
      void main() {
        float fr = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.2);
        float level = vP.y * 0.5 + 0.5;                     // 0 at the bottom of the soma, 1 at the top
        float wave = 0.03 * sin(vP.x * 9.0 + uTime * 4.0);  // the charge sloshes
        float filled = smoothstep(uCharge + wave + 0.04, uCharge + wave - 0.04, level);
        vec3 c = uColor * (0.12 + fr * 1.6) + uColor * filled * 0.9 + vec3(1.0) * uFlash * (0.6 + fr);
        float a = clamp(0.35 + fr * 0.8 + filled * 0.45 + uFlash, 0.0, 1.0);
        gl_FragColor = vec4(c, a);
      }`,
  });
}

/** Round, soft, additive points (signals, sparks, dust) with per-point colour and size. */
export function pointsMaterial(size = 1) {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexColors: true,
    uniforms: { uSize: { value: size }, uScale: { value: window.devicePixelRatio || 1 } },
    vertexShader: /* glsl */ `
      attribute float aSize; uniform float uSize; uniform float uScale;
      varying vec3 vColor;
      void main() {
        vColor = color;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = aSize * uSize * uScale * (120.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      varying vec3 vColor;
      void main() {
        vec2 d = gl_PointCoord - 0.5;
        float r = length(d);
        float a = smoothstep(0.5, 0.0, r);
        a *= a;
        if (a < 0.01) discard;
        gl_FragColor = vec4(vColor * (0.6 + a * 1.4), a);
      }`,
  });
}

/** A pool of short-lived particles (sparks, bursts, floating dust) on one draw call. */
export class Particles {
  points: THREE.Points;
  private pos: Float32Array;
  private vel: Float32Array;
  private colr: Float32Array;
  private base: Float32Array;
  private size: Float32Array;
  private life: Float32Array;
  private max: Float32Array;
  private next = 0;
  private live = 0; // how many may still be alive (skip the loop when none are)
  gravity = -2.2;
  drag = 1.6;

  constructor(public n: number, size = 1) {
    const g = new THREE.BufferGeometry();
    this.pos = new Float32Array(n * 3);
    this.vel = new Float32Array(n * 3);
    this.colr = new Float32Array(n * 3);
    this.base = new Float32Array(n * 3);
    this.size = new Float32Array(n);
    this.life = new Float32Array(n);
    this.max = new Float32Array(n).fill(1);
    g.setAttribute("position", new THREE.BufferAttribute(this.pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(this.colr, 3));
    g.setAttribute("aSize", new THREE.BufferAttribute(this.size, 1));
    this.points = new THREE.Points(g, pointsMaterial(size));
    this.points.frustumCulled = false;
  }

  emit(p: THREE.Vector3, v: THREE.Vector3, c: THREE.Color, life: number, size: number) {
    if (!this.n) return;
    const i = this.next;
    this.next = (this.next + 1) % this.n;
    this.pos.set([p.x, p.y, p.z], i * 3);
    this.vel.set([v.x, v.y, v.z], i * 3);
    this.base.set([c.r, c.g, c.b], i * 3);
    this.life[i] = life;
    this.max[i] = life;
    this.size[i] = size;
    this.live = this.n;
  }

  burst(p: THREE.Vector3, c: THREE.Color, count: number, speed: number, life = 0.9, size = 1.4) {
    const v = new THREE.Vector3();
    for (let k = 0; k < count; k++) {
      v.set(Math.random() - 0.5, Math.random() * 0.9 + 0.1, Math.random() - 0.5).normalize().multiplyScalar(speed * (0.4 + Math.random()));
      this.emit(p, v, c, life * (0.6 + Math.random() * 0.6), size * (0.5 + Math.random()));
    }
  }

  /** A burst in every direction (no upward bias), for scenes without a floor. */
  sphere(p: THREE.Vector3, c: THREE.Color, count: number, speed: number, life = 0.9, size = 1.4) {
    const v = new THREE.Vector3();
    for (let k = 0; k < count; k++) {
      v.randomDirection().multiplyScalar(speed * (0.3 + Math.random()));
      this.emit(p, v, c, life * (0.6 + Math.random() * 0.6), size * (0.5 + Math.random()));
    }
  }

  update(dt: number) {
    if (!this.live) return;
    const d = Math.exp(-this.drag * dt);
    let alive = 0;
    for (let i = 0; i < this.n; i++) {
      if (this.life[i] <= 0) {
        this.size[i] = 0;
        continue;
      }
      alive++;
      this.life[i] -= dt;
      const k = Math.max(0, this.life[i] / this.max[i]);
      const j = i * 3;
      this.vel[j] *= d;
      this.vel[j + 1] = this.vel[j + 1] * d + this.gravity * dt;
      this.vel[j + 2] *= d;
      this.pos[j] += this.vel[j] * dt;
      this.pos[j + 1] += this.vel[j + 1] * dt;
      this.pos[j + 2] += this.vel[j + 2] * dt;
      this.colr[j] = this.base[j] * k;
      this.colr[j + 1] = this.base[j + 1] * k;
      this.colr[j + 2] = this.base[j + 2] * k;
    }
    this.live = alive;
    const g = this.points.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.color.needsUpdate = true;
    (g.attributes.aSize as THREE.BufferAttribute).needsUpdate = true;
  }
}

/** Smoothly approach a target (frame-rate independent). */
export const approach = (cur: number, target: number, rate: number, dt: number) => cur + (target - cur) * (1 - Math.exp(-rate * dt));
