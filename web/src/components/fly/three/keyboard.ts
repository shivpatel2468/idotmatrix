import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { type FlyGfx, type FlyKey, KEY_GLYPH, type Shot, onPress, useFly } from "../../../lib/fly";
import { type FlyScene, type Host, Particles, approach, col, glowSprite } from "./host";

/** A fruit fly on a mechanical keyboard. Every spike of its descending neurons is a key press: it hops onto the
 *  key and stomps it; the giant fibre is its escape jump (key A). Between presses it walks with a procedural
 *  tripod gait, and when nothing happens it grooms. Its compound eyes show what it sees (the live 16×16 eye). */

const U = 0.92; // key pitch
const TOP = 0.46; // key-top height
const ROWS: string[][] = [
  ["Esc", "1", "2", "3", "4", "5"],
  ["Tab", "Q", "W", "E", "R", "T"],
  ["A", "S", "D", "F", "↑", "G"],
  ["Z", "X", "C", "←", "↓", "→"],
];
const ACTIVE: Record<string, FlyKey> = { "←": "left", "→": "right", "↑": "up", "↓": "down", A: "a" };
const HOME = new THREE.Vector3(); // between the arrows, set in build()

type Cap = {
  group: THREE.Group;
  cap: THREE.Mesh;
  legend: THREE.Mesh;
  glow: THREE.Sprite;
  key?: FlyKey;
  color: THREE.Color;
  down: number; // 0..1 how far pressed
  hold: number; // seconds left held down
  heat: number;
  rgb: THREE.Color; // glow after a press
  pos: THREE.Vector3;
  tex: THREE.CanvasTexture;
};

type Leg = {
  hip: THREE.Vector3; // in body space
  rest: THREE.Vector3; // foot rest offset in body space (y ignored)
  foot: THREE.Vector3; // planted world position
  from: THREE.Vector3;
  to: THREE.Vector3;
  step: number; // <0 planted, 0..1 stepping
  femur: THREE.Mesh;
  tibia: THREE.Mesh;
  tarsus: THREE.Mesh;
  side: number;
  group: 0 | 1; // tripod gait group
};

function legendTexture(text: string, ink: string, size = 128): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  g.clearRect(0, 0, size, size);
  g.fillStyle = ink;
  g.textAlign = "center";
  g.textBaseline = "middle";
  const big = text.length === 1;
  g.font = `${big ? 600 : 500} ${big ? size * 0.46 : size * 0.22}px "Martian Mono", "Cascadia Mono", monospace`;
  g.fillText(text, size / 2, size / 2 + (big ? 4 : 0));
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

const STYLE: Record<FlyGfx["board"], { cap: string; legend: string; caseC: string; caseM: number; caseR: number; rgb: boolean; glass: boolean }> = {
  midnight: { cap: "#1a1c25", legend: "#8b8fa6", caseC: "#20232d", caseM: 0.85, caseR: 0.32, rgb: false, glass: false },
  rgb: { cap: "#121318", legend: "#d8dbe8", caseC: "#0d0e12", caseM: 0.7, caseR: 0.4, rgb: true, glass: false },
  retro: { cap: "#d8cfb8", legend: "#4a463e", caseC: "#c9bfa6", caseM: 0.0, caseR: 0.7, rgb: false, glass: false },
  glass: { cap: "#b9d6ff", legend: "#f4f8ff", caseC: "#1c2230", caseM: 0.9, caseR: 0.18, rgb: true, glass: true },
};

const FLY_LOOK: Record<FlyGfx["fly"], { body: string; metal: number; rough: number; emissive: string; eye: string; opacity: number }> = {
  wild: { body: "#8a6236", metal: 0.05, rough: 0.45, emissive: "#000000", eye: "#b3121c", opacity: 1 },
  golden: { body: "#d9a441", metal: 1, rough: 0.22, emissive: "#2a1500", eye: "#ff2a1a", opacity: 1 },
  ghost: { body: "#cfe8ff", metal: 0, rough: 0.2, emissive: "#3a6a9a", eye: "#7ad7ff", opacity: 0.55 },
  chrome: { body: "#c8ccd6", metal: 1, rough: 0.08, emissive: "#000000", eye: "#ff2050", opacity: 1 },
  hornet: { body: "#1a8a44", metal: 0.55, rough: 0.22, emissive: "#05300f", eye: "#39ff7a", opacity: 1 },
  noir: { body: "#2a2a2c", metal: 0.35, rough: 0.3, emissive: "#000000", eye: "#ffcc33", opacity: 1 },
};

export class KeyboardScene implements FlyScene {
  bloomThreshold = 0.72;
  private caps: Cap[] = [];
  private byKey: Partial<Record<FlyKey, Cap>> = {};
  private fly = new THREE.Group(); // position = body centre
  private body = new THREE.Group(); // bob / dip / lean
  private legs: Leg[] = [];
  private wings: { pivot: THREE.Group; flap: THREE.Group; mat: THREE.ShaderMaterial; side: number }[] = [];
  private eyeMats: THREE.ShaderMaterial[] = [];
  private eyeTex = new THREE.DataTexture(new Uint8Array(16 * 16 * 4), 16, 16);
  private shadow!: THREE.Mesh;
  private sparks!: Particles;
  private ripples: { mesh: THREE.Mesh; life: number }[] = [];
  private floaters: { s: THREE.Sprite; life: number; v: number }[] = [];
  private bolt: { line: THREE.Line; life: number } | null = null;
  private target = new THREE.Vector3();
  private hop: { from: THREE.Vector3; to: THREE.Vector3; t: number; dur: number; height: number; key?: FlyKey } | null = null;
  private jump = 0; // escape-jump timer (s), > 0 while airborne
  private dip = 0;
  private buzz = 0; // wing activity 0..1
  private lastPress = -10;
  private yaw = 0;
  private time = 0;
  private host: Host | null = null;
  private unsub: (() => void) | null = null;
  private env: THREE.Texture | null = null;
  private q = new THREE.Quaternion();
  private up = new THREE.Vector3(0, 1, 0);

  camKey = "camKeys" as const;
  deps: (keyof FlyGfx)[] = ["fly", "flySize", "wingShimmer", "board"];

  frame(mode: Shot) {
    const t = new THREE.Vector3(0.7, -0.5, 0.4);
    const p: Record<Shot, THREE.Vector3> = {
      orbit: new THREE.Vector3(4.2, 5, 8.4),
      front: new THREE.Vector3(0.7, 3.6, 8.2),
      top: new THREE.Vector3(0.71, 9.5, 1.4),
      close: new THREE.Vector3(HOME.x + 2.6, 2.4, HOME.z + 3.2),
    };
    return { target: mode === "close" ? HOME.clone().setY(0.9) : t, position: p[mode] };
  }

  build(host: Host) {
    this.host = host;
    const th = host.theme;
    const lv = host.lv;
    const gfx = host.gfx;
    const root = host.root;
    const st = STYLE[gfx.board];
    const seg = lv.segments;
    const tier = host.tier;

    // ---------------------------------------------------------------- light & environment
    this.env?.dispose();
    this.env = null;
    if (tier !== "low") {
      const pm = new THREE.PMREMGenerator(host.renderer);
      this.env = pm.fromScene(new RoomEnvironment(), 0.04).texture;
      pm.dispose();
    }
    host.scene.environment = this.env;
    host.scene.environmentIntensity = 0.35;
    host.scene.fog = new THREE.FogExp2(col(th.fog), 0.025);
    root.add(new THREE.HemisphereLight(0xbfd4ff, 0x1a1020, tier === "low" ? 0.9 : 0.3));
    const sun = new THREE.DirectionalLight(0xffffff, tier === "low" ? 1.8 : 1.25);
    sun.position.set(4, 9, 6);
    if (lv.shadows) {
      sun.castShadow = true;
      sun.shadow.mapSize.set(tier === "ultra" ? 2048 : 1024, tier === "ultra" ? 2048 : 1024);
      sun.shadow.camera.left = -7;
      sun.shadow.camera.right = 7;
      sun.shadow.camera.top = 5;
      sun.shadow.camera.bottom = -5;
      sun.shadow.bias = -0.0004;
      sun.shadow.radius = 4;
    }
    root.add(sun);
    const rim = new THREE.PointLight(col(th.accent), 25, 18);
    rim.position.set(-4, 3, -4);
    root.add(rim);

    // ---------------------------------------------------------------- the keyboard
    const cols = ROWS[0].length;
    const w = cols * U + 0.5;
    const d = ROWS.length * U + 0.5;
    const caseM = new THREE.MeshStandardMaterial({ color: col(st.caseC), metalness: st.caseM, roughness: st.caseR });
    const kbCase = new THREE.Mesh(new RoundedBoxGeometry(w, 0.5, d, 4, 0.18), caseM);
    kbCase.position.y = -0.2;
    kbCase.receiveShadow = true;
    kbCase.castShadow = lv.shadows;
    root.add(kbCase);
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.3, d - 0.3), new THREE.MeshStandardMaterial({ color: 0x07070a, roughness: 0.9 }));
    plate.rotation.x = -Math.PI / 2;
    plate.position.y = 0.055;
    plate.receiveShadow = true;
    root.add(plate);
    // the desk: a soft pool of light that fades into the fog
    const desk = new THREE.Mesh(
      new THREE.CircleGeometry(16, 64),
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        uniforms: { uColor: { value: col(th.accent) } },
        vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
        fragmentShader: "uniform vec3 uColor; varying vec2 vUv; void main(){ float r = length(vUv-0.5)*2.0; gl_FragColor = vec4(mix(uColor*0.05, vec3(0.0), smoothstep(0.0,1.0,r)), smoothstep(1.0,0.2,r)*0.8); }",
      }),
    );
    desk.rotation.x = -Math.PI / 2;
    desk.position.y = -0.46;
    root.add(desk);

    const capGeo = new RoundedBoxGeometry(U * 0.86, 0.38, U * 0.86, Math.max(2, Math.round(seg / 8)), 0.11);
    const legendGeo = new THREE.PlaneGeometry(U * 0.72, U * 0.72);
    this.caps = [];
    this.byKey = {};
    ROWS.forEach((row, r) =>
      row.forEach((label, c) => {
        const key = ACTIVE[label];
        const color = key ? col(th[key === "a" ? "gf" : key]) : col(th.accent);
        const capMat = st.glass && (tier === "high" || tier === "ultra")
          ? new THREE.MeshPhysicalMaterial({ color: col(st.cap), metalness: 0, roughness: 0.08, transmission: 0.92, thickness: 0.4, ior: 1.45, emissive: color, emissiveIntensity: 0 })
          : new THREE.MeshPhysicalMaterial({
            color: key && gfx.board !== "retro" ? col(st.cap).lerp(color, 0.12) : col(key && gfx.board === "retro" ? "#9a9488" : st.cap),
            roughness: st.glass ? 0.15 : 0.55, metalness: 0, clearcoat: st.glass ? 1 : 0.25, clearcoatRoughness: 0.4,
            transparent: st.glass, opacity: st.glass ? 0.6 : 1, emissive: color, emissiveIntensity: 0,
          });
        const cap = new THREE.Mesh(capGeo, capMat);
        cap.castShadow = lv.shadows;
        cap.receiveShadow = lv.shadows;
        const tex = legendTexture(label, key ? `#${color.getHexString()}` : st.legend);
        const legend = new THREE.Mesh(legendGeo, new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false, color: 0xffffff }));
        legend.rotation.x = -Math.PI / 2;
        legend.position.y = 0.195;
        const group = new THREE.Group();
        const pos = new THREE.Vector3((c - (cols - 1) / 2) * U, 0.25, (r - (ROWS.length - 1) / 2) * U);
        group.position.copy(pos);
        group.add(cap, legend);
        const glow = glowSprite(color, 1.9, 0);
        glow.position.set(pos.x, 0.12, pos.z);
        root.add(group, glow);
        const k: Cap = { group, cap, legend, glow, key, color, down: 0, hold: 0, heat: 0, pos, tex, rgb: new THREE.Color() };
        this.caps.push(k);
        if (key) this.byKey[key] = k;
      }),
    );
    HOME.copy(this.byKey.up!.pos).add(this.byKey.down!.pos).multiplyScalar(0.5);
    HOME.y = 0;

    // ---------------------------------------------------------------- the fly
    this.fly = new THREE.Group();
    this.body = new THREE.Group();
    this.fly.add(this.body);
    this.fly.scale.setScalar(gfx.flySize * 1.05);
    root.add(this.fly);
    const look = FLY_LOOK[gfx.fly];
    const chitin = new THREE.MeshPhysicalMaterial({
      color: col(look.body), metalness: look.metal, roughness: look.rough, clearcoat: 0.8, clearcoatRoughness: 0.25,
      sheen: 0.6, sheenColor: col("#ffd9a0"), emissive: col(look.emissive), transparent: look.opacity < 1, opacity: look.opacity,
    });
    const dark = new THREE.MeshPhysicalMaterial({ color: 0x1a120c, roughness: 0.5, clearcoat: 0.5, transparent: look.opacity < 1, opacity: look.opacity });
    const sph = (r: number) => new THREE.SphereGeometry(r, seg, Math.max(8, Math.round(seg * 0.75)));
    const add = (m: THREE.Mesh) => {
      m.castShadow = lv.shadows;
      this.body.add(m);
      return m;
    };
    const thorax = add(new THREE.Mesh(sph(1), chitin));
    thorax.scale.set(0.42, 0.36, 0.48);
    // abdomen with dark tergite bands
    const bands = document.createElement("canvas");
    bands.width = 8;
    bands.height = 128;
    const bg = bands.getContext("2d")!;
    for (let y = 0; y < 128; y++) {
      const band = Math.sin((y / 128) * Math.PI * 9) > 0.35 && y > 18 && y < 112;
      bg.fillStyle = band ? "#2a1a10" : "#ffffff";
      bg.fillRect(0, y, 8, 1);
    }
    const bandTex = new THREE.CanvasTexture(bands);
    bandTex.colorSpace = THREE.SRGBColorSpace;
    const abdomenMat = chitin.clone();
    abdomenMat.map = bandTex;
    const abdomen = add(new THREE.Mesh(sph(1), abdomenMat));
    abdomen.scale.set(0.36, 0.62, 0.33);
    abdomen.rotation.x = Math.PI / 2 - 0.25;
    abdomen.position.set(0, -0.05, -0.72);
    const head = add(new THREE.Mesh(sph(1), chitin));
    head.scale.set(0.3, 0.26, 0.24);
    head.position.set(0, 0.06, 0.5);
    // compound eyes: hexagonal facets, a fresnel sheen, and the live eye image glowing through them
    this.eyeTex.needsUpdate = true;
    this.eyeTex.magFilter = THREE.LinearFilter;
    this.eyeMats = [];
    for (const side of [-1, 1]) {
      const m = new THREE.ShaderMaterial({
        uniforms: { uBase: { value: col(look.eye) }, uGlow: { value: col(th.eye) }, uEye: { value: this.eyeTex }, uAct: { value: 0 }, uTime: { value: 0 } },
        vertexShader: /* glsl */ `
          varying vec2 vUv; varying vec3 vN; varying vec3 vV;
          void main(){ vUv = uv; vec4 wp = modelMatrix*vec4(position,1.0); vN = normalize(normalMatrix*normal); vV = normalize(-(viewMatrix*wp).xyz); gl_Position = projectionMatrix*viewMatrix*wp; }`,
        fragmentShader: /* glsl */ `
          uniform vec3 uBase; uniform vec3 uGlow; uniform sampler2D uEye; uniform float uAct; uniform float uTime;
          varying vec2 vUv; varying vec3 vN; varying vec3 vV;
          vec2 hexCell(vec2 p){ vec2 r = vec2(1.0,1.732); vec2 h = r*0.5; vec2 a = mod(p,r)-h; vec2 b = mod(p-h,r)-h; return dot(a,a)<dot(b,b)?a:b; }
          void main(){
            vec2 p = vUv*vec2(46.0,24.0);
            vec2 c = hexCell(p);
            float edge = smoothstep(0.32,0.5,length(c)*1.25);
            float fr = pow(1.0-abs(dot(normalize(vN),normalize(vV))),2.0);
            vec3 seen = texture2D(uEye, vec2(fract(vUv.x*2.0), vUv.y)).rgb;
            vec3 col = uBase*(0.55+0.45*(1.0-edge)) + vec3(1.0,0.85,0.8)*fr*0.35;
            col += uGlow*seen*(0.6+uAct*1.6)*(1.0-edge);
            col *= 1.0 - edge*0.55;
            gl_FragColor = vec4(col,1.0);
          }`,
      });
      this.eyeMats.push(m);
      const eye = add(new THREE.Mesh(sph(1), m));
      eye.scale.set(0.2, 0.25, 0.22);
      eye.position.set(side * 0.24, 0.1, 0.52);
    }
    // antennae with aristae
    for (const side of [-1, 1]) {
      const a = add(new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.03, 0.18, 6), dark));
      a.position.set(side * 0.07, 0.14, 0.72);
      a.rotation.set(0.9, 0, side * 0.3);
      const ar = add(new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.008, 0.3, 4), dark));
      ar.position.set(side * 0.12, 0.24, 0.8);
      ar.rotation.set(0.4, 0, side * 0.9);
    }
    // bristles on the thorax (macrochaetae), the fly's tell-tale hairs
    for (let i = 0; i < 10; i++) {
      const b = add(new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.01, 0.22, 3), dark));
      const ang = (i / 10) * Math.PI - Math.PI / 2;
      b.position.set(Math.sin(ang) * 0.3, 0.3, -0.05 + Math.cos(ang) * 0.12);
      b.rotation.set(-0.9, 0, Math.sin(ang) * 0.5);
    }

    // wings: thin-film iridescence with veins
    this.wings = [];
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    shape.quadraticCurveTo(0.55, 0.42, 1.45, 0.24);
    shape.quadraticCurveTo(1.72, 0.02, 1.45, -0.17);
    shape.quadraticCurveTo(0.7, -0.28, 0, 0);
    const wingGeo = new THREE.ShapeGeometry(shape, 24);
    wingGeo.rotateX(-Math.PI / 2);
    for (const side of [-1, 1]) {
      const mat = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        uniforms: { uTime: { value: 0 }, uShimmer: { value: gfx.wingShimmer ? 1 : 0 }, uBlur: { value: 0 } },
        vertexShader: /* glsl */ `
          varying vec3 vP; varying vec3 vN; varying vec3 vV;
          void main(){ vP = position; vec4 wp = modelMatrix*vec4(position,1.0); vN = normalize(normalMatrix*normal); vV = normalize(-(viewMatrix*wp).xyz); gl_Position = projectionMatrix*viewMatrix*wp; }`,
        fragmentShader: /* glsl */ `
          uniform float uTime; uniform float uShimmer; uniform float uBlur;
          varying vec3 vP; varying vec3 vN; varying vec3 vV;
          void main(){
            float ndv = abs(dot(normalize(vN), normalize(vV)));
            // veins: longitudinal (L1–L5) and two cross-veins
            float x = vP.x; float z = -vP.z;
            float vein = 0.0;
            for (int i = 1; i <= 5; i++){ float fi = float(i); float line = z - (fi-3.0)*0.07*(0.3+x*0.6); vein += smoothstep(0.012,0.0,abs(line))*step(0.05,x); }
            vein += smoothstep(0.012,0.0,abs(x-0.55))*step(abs(z),0.2) + smoothstep(0.012,0.0,abs(x-0.95))*step(abs(z),0.16);
            float hue = fract(ndv*1.7 + x*0.45 + uTime*0.03);
            vec3 film = 0.55 + 0.45*cos(6.2831*(hue + vec3(0.0,0.33,0.67)));
            vec3 base = mix(vec3(0.75,0.82,0.9), film, uShimmer);
            float a = (0.10 + (1.0-ndv)*0.35 + vein*0.45) * (1.0 - uBlur*0.55);
            gl_FragColor = vec4(base*(0.8+vein*0.2) + vec3(vein*0.08), a);
          }`,
      });
      const pivot = new THREE.Group();
      pivot.position.set(side * 0.18, 0.26, -0.05);
      const flap = new THREE.Group();
      flap.add(new THREE.Mesh(wingGeo, mat));
      pivot.add(flap);
      this.body.add(pivot);
      this.wings.push({ pivot, flap, mat, side });
    }

    // six legs: femur + tibia + tarsus, solved by 2-bone IK every frame
    this.legs = [];
    const segGeo = new THREE.CylinderGeometry(0.03, 0.022, 1, 6);
    segGeo.translate(0, 0.5, 0);
    const hips: [number, number, number, number, 0 | 1][] = [
      // x, z (body space), rest x, rest z, gait group
      [0.16, 0.25, 0.62, 0.72, 0], [0.2, 0.0, 0.88, 0.05, 1], [0.17, -0.22, 0.68, -0.7, 0],
    ];
    for (const side of [-1, 1])
      hips.forEach(([hx, hz, rx, rz, g], i) => {
        const mk = () => {
          const m = new THREE.Mesh(segGeo, dark);
          m.castShadow = lv.shadows;
          this.fly.add(m);
          return m;
        };
        const leg: Leg = {
          hip: new THREE.Vector3(side * hx, -0.18, hz),
          rest: new THREE.Vector3(side * rx, 0, rz),
          foot: new THREE.Vector3(),
          from: new THREE.Vector3(),
          to: new THREE.Vector3(),
          step: -1,
          femur: mk(),
          tibia: mk(),
          tarsus: mk(),
          side,
          group: (side < 0 ? g : ((1 - g) as 0 | 1)),
        };
        void i;
        this.legs.push(leg);
      });

    // a soft contact shadow (cheap and always on)
    const sc = document.createElement("canvas");
    sc.width = sc.height = 64;
    const sg = sc.getContext("2d")!;
    const grad = sg.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, "rgba(0,0,0,0.55)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    sg.fillStyle = grad;
    sg.fillRect(0, 0, 64, 64);
    this.shadow = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 2.2), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(sc), transparent: true, depthWrite: false }));
    this.shadow.rotation.x = -Math.PI / 2;
    root.add(this.shadow);

    this.sparks = new Particles(Math.round(700 * lv.particles), 1);
    this.sparks.gravity = -6;
    root.add(this.sparks.points);
    this.ripples = [];
    this.floaters = [];
    this.bolt = null;

    // start at home with the feet planted
    this.target.copy(HOME);
    this.fly.position.set(HOME.x, TOP + 0.5, HOME.z);
    this.hop = null;
    this.jump = 0;
    this.updateMatrices();
    for (const l of this.legs) {
      l.foot.copy(this.restWorld(l));
      l.step = -1;
    }
    this.unsub?.();
    this.unsub = onPress((p) => this.press(p.key));
  }

  private updateMatrices() {
    this.fly.rotation.y = this.yaw;
    this.fly.updateMatrixWorld(true);
  }

  private restWorld(l: Leg): THREE.Vector3 {
    const p = l.rest.clone();
    p.applyAxisAngle(this.up, this.yaw).multiplyScalar(this.fly.scale.x).add(this.fly.position);
    p.y = TOP - 0.02;
    return p;
  }

  /** The brain fired a key: hop onto it and stomp (or, for the giant fibre, leap). */
  private press(k: FlyKey) {
    const cap = this.byKey[k];
    if (!cap) return;
    this.lastPress = this.time;
    if (k === "a") {
      this.jump = 0.75;
      this.buzz = 1;
      this.keyDown(cap, 1.2);
      this.lightning(cap);
      return;
    }
    const to = cap.pos.clone().setY(0);
    const from = this.fly.position.clone().setY(0);
    const dist = from.distanceTo(to);
    this.hop = { from, to, t: 0, dur: 0.09 + dist * 0.035, height: 0.18 + dist * 0.12, key: k };
    this.buzz = Math.max(this.buzz, 0.45);
  }

  private keyDown(cap: Cap, power = 1) {
    cap.down = 0.2;
    cap.hold = 0.07 * power;
    cap.heat = 1;
    const th = this.host!;
    const top = cap.pos.clone().setY(TOP);
    this.sparks.burst(top, cap.color, Math.round(30 * th.lv.particles * power) + 4, 3.4 * power, 0.8, 1.5);
    // a ripple across the plate
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.42, 0.5, 48),
      new THREE.MeshBasicMaterial({ color: cap.color, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(cap.pos.x, 0.07, cap.pos.z);
    th.root.add(ring);
    this.ripples.push({ mesh: ring, life: 1 });
    // the key's glyph floats up and fades
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: legendTexture(KEY_GLYPH[cap.key!], "#ffffff"), color: cap.color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    s.position.copy(top).add(new THREE.Vector3(0, 0.4, 0));
    s.scale.setScalar(0.9);
    th.root.add(s);
    this.floaters.push({ s, life: 1, v: 1.6 });
  }

  private lightning(cap: Cap) {
    const th = this.host!;
    if (this.bolt) {
      th.root.remove(this.bolt.line);
      this.bolt.line.geometry.dispose();
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(16 * 3), 3));
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: cap.color, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
    line.frustumCulled = false;
    th.root.add(line);
    this.bolt = { line, life: 0.45 };
  }

  update(dt: number, t: number, host: Host) {
    this.time = t;
    const snap = useFly.getState().snap;
    const driving = snap.driving !== false;

    // ---- the live eye image on the compound eyes
    if (snap.eye) {
      const data = (this.eyeTex.image as { data: Uint8Array }).data;
      let sum = 0;
      for (let i = 0; i < 256; i++) {
        const v = snap.eye[i] ?? 0;
        sum += v;
        // flip vertically: texture row 0 is the bottom
        const r = 15 - Math.floor(i / 16);
        const j = (r * 16 + (i % 16)) * 4;
        data[j] = data[j + 1] = data[j + 2] = v;
        data[j + 3] = 255;
      }
      this.eyeTex.needsUpdate = true;
      for (const m of this.eyeMats) {
        m.uniforms.uAct.value = approach(m.uniforms.uAct.value, Math.min(1, sum / 256 / 90), 4, dt);
        m.uniforms.uTime.value = t;
      }
    }

    // ---- body motion: hops between keys, the escape leap, idle drift home
    const idle = t - this.lastPress;
    if (this.hop) {
      const h = this.hop;
      h.t = Math.min(1, h.t + dt / h.dur);
      const e = h.t < 0.5 ? 2 * h.t * h.t : 1 - (-2 * h.t + 2) ** 2 / 2;
      this.fly.position.x = h.from.x + (h.to.x - h.from.x) * e;
      this.fly.position.z = h.from.z + (h.to.z - h.from.z) * e;
      this.fly.position.y = TOP + 0.5 + Math.sin(h.t * Math.PI) * h.height;
      if (h.t >= 1) {
        const cap = h.key ? this.byKey[h.key] : undefined;
        if (cap) this.keyDown(cap);
        this.dip = 1;
        this.hop = null;
      }
    } else {
      if (idle > 2.6) {
        // wander back to the middle of the arrow cluster
        this.fly.position.x = approach(this.fly.position.x, HOME.x, 1.2, dt);
        this.fly.position.z = approach(this.fly.position.z, HOME.z, 1.2, dt);
      }
      let y = TOP + 0.5;
      if (this.jump > 0) {
        this.jump = Math.max(0, this.jump - dt);
        const p = 1 - this.jump / 0.75;
        y += Math.sin(p * Math.PI) * 2.6; // the giant-fibre escape: straight up, then back down
        if (this.jump === 0) this.dip = 1.2;
      }
      this.fly.position.y = approach(this.fly.position.y, y, this.jump > 0 ? 30 : 14, dt);
    }
    this.dip = Math.max(0, this.dip - dt * 5);
    // face the camera-side of the board, turned a little towards where it's heading
    const head = this.hop ? Math.atan2(this.hop.to.x - this.hop.from.x, this.hop.to.z - this.hop.from.z + 2.5) : 0;
    this.yaw = approach(this.yaw, head * 0.7, 6, dt);
    this.updateMatrices();
    const groom = driving ? Math.max(0, Math.min(1, (idle - 1.4) * 1.5)) : 1;
    this.body.position.y = -this.dip * 0.16 + Math.sin(t * 2.2) * 0.012;
    this.body.rotation.x = this.dip * 0.22 + groom * 0.12 + (this.jump > 0 ? -0.3 : 0);
    this.body.rotation.z = Math.sin(t * 1.3) * 0.02;

    // ---- wings: folded at rest, buzzing when busy, full strokes in the air
    this.buzz = Math.max(this.jump > 0 ? 1 : 0, this.buzz - dt * 1.2);
    const air = this.jump > 0 || !!this.hop;
    for (const wg of this.wings) {
      const fold = wg.side < 0 ? 1.92 : 1.22; // yaw: tips back over the abdomen
      const open = wg.side < 0 ? 2.5 : 0.64;
      const spread = Math.min(1, this.buzz * 1.4);
      wg.pivot.rotation.y = fold + (open - fold) * spread;
      const freq = air ? 55 : 30;
      const amp = this.buzz * (air ? 0.9 : 0.35);
      wg.flap.rotation.z = Math.sin(t * freq) * amp + amp * 0.3;
      wg.flap.rotation.x = 0.08;
      wg.mat.uniforms.uTime.value = t;
      wg.mat.uniforms.uBlur.value = Math.min(1, amp * 1.4);
    }

    // ---- legs: tripod gait, plus grooming (front legs rub together) when idle
    const scale = this.fly.scale.x;
    const stepping = [false, false];
    for (const l of this.legs) if (l.step >= 0) stepping[l.group] = true;
    for (let i = 0; i < this.legs.length; i++) {
      const l = this.legs[i];
      const rest = this.restWorld(l);
      const front = i % 3 === 0;
      if (this.jump > 0) {
        // dangling in the air
        l.foot.lerp(rest.clone().setY(this.fly.position.y - 0.55 * scale), 1 - Math.exp(-12 * dt));
        l.step = -1;
      } else if (l.step >= 0) {
        l.step = Math.min(1, l.step + dt / 0.085);
        l.foot.lerpVectors(l.from, l.to, l.step);
        l.foot.y += Math.sin(l.step * Math.PI) * 0.22 * scale;
        if (l.step >= 1) l.step = -1;
      } else if (front && groom > 0 && !this.hop) {
        // grooming: both front feet come up under the head and rub
        const local = new THREE.Vector3(l.side * (0.08 + Math.sin(t * 14) * 0.05), -0.05, 0.62).applyAxisAngle(this.up, this.yaw).multiplyScalar(scale).add(this.fly.position);
        l.foot.lerp(local, 1 - Math.exp(-10 * dt * groom));
      } else if (l.foot.distanceTo(rest) > 0.32 * scale && !stepping[1 - l.group]) {
        l.from.copy(l.foot);
        l.to.copy(rest);
        l.step = 0;
        stepping[l.group] = true;
      } else if (l.foot.y > TOP + 0.02) {
        l.foot.y = approach(l.foot.y, TOP - 0.02, 12, dt); // land after grooming or a jump
      }
      this.solveLeg(l);
    }

    // ---- keys: springs, heat, the RGB wave
    const rgb = STYLE[host.gfx.board].rgb;
    for (const k of this.caps) {
      // held for a beat, then it springs back up
      if (k.hold > 0) k.hold -= dt;
      else k.down = approach(k.down, 0, 16, dt);
      k.group.position.y = k.pos.y - k.down;
      k.heat = Math.max(0, k.heat - dt * 2.2);
      const m = k.cap.material as THREE.MeshPhysicalMaterial;
      let glow = k.heat * 1.1;
      let gcol = k.color;
      if (rgb) {
        const hue = (k.pos.x * 0.06 - t * 0.12 + k.pos.z * 0.03) % 1;
        gcol = k.rgb.setHSL((hue + 1) % 1, 0.9, 0.55);
        glow = Math.max(glow, 0.14);
      } else if (k.key) {
        glow = Math.max(glow, 0.06);
      }
      m.emissive.copy(k.heat > 0.05 ? k.color : gcol);
      m.emissiveIntensity = glow;
      k.glow.material.color.copy(k.heat > 0.05 ? k.color : gcol);
      k.glow.material.opacity = Math.min(0.8, glow * 0.45);
      (k.legend.material as THREE.MeshBasicMaterial).color.setScalar(0.85 + k.heat * 1.6);
    }

    // ---- effects
    this.sparks.update(dt);
    for (const r of this.ripples) {
      r.life -= dt * 1.8;
      r.mesh.scale.setScalar(1 + (1 - r.life) * 2.4);
      (r.mesh.material as THREE.MeshBasicMaterial).opacity = Math.max(0, r.life) * 0.9;
      if (r.life <= 0) this.drop(r.mesh);
    }
    this.ripples = this.ripples.filter((r) => r.life > 0);
    for (const f of this.floaters) {
      f.life -= dt * 1.2;
      f.s.position.y += f.v * dt;
      f.v *= Math.exp(-2 * dt);
      f.s.material.opacity = Math.max(0, f.life);
      f.s.scale.setScalar(0.9 + (1 - f.life) * 0.5);
      if (f.life <= 0) {
        f.s.material.map?.dispose();
        this.drop(f.s);
      }
    }
    this.floaters = this.floaters.filter((f) => f.life > 0);
    if (this.bolt) {
      const b = this.bolt;
      b.life -= dt;
      const a = this.byKey.a!.pos.clone().setY(TOP);
      const from = this.fly.position.clone();
      const pos = b.line.geometry.attributes.position as THREE.BufferAttribute;
      for (let i = 0; i < 16; i++) {
        const u = i / 15;
        const jit = Math.sin(u * Math.PI) * 0.35;
        pos.setXYZ(i, from.x + (a.x - from.x) * u + (Math.random() - 0.5) * jit, from.y + (a.y - from.y) * u + (Math.random() - 0.5) * jit, from.z + (a.z - from.z) * u + (Math.random() - 0.5) * jit);
      }
      pos.needsUpdate = true;
      (b.line.material as THREE.LineBasicMaterial).opacity = Math.max(0, b.life / 0.45) * (0.6 + Math.random() * 0.4);
      if (b.life <= 0) {
        this.drop(b.line);
        this.bolt = null;
      }
    }
    this.shadow.position.set(this.fly.position.x, TOP + 0.005, this.fly.position.z - 0.15);
    const lift = this.fly.position.y - (TOP + 0.5);
    this.shadow.scale.setScalar(scale * Math.max(0.35, 1 - lift * 0.25));
    (this.shadow.material as THREE.MeshBasicMaterial).opacity = Math.max(0.15, 1 - lift * 0.3);
  }

  private drop(o: THREE.Object3D) {
    this.host?.root.remove(o);
    const m = o as THREE.Mesh;
    m.geometry?.dispose();
    (m.material as THREE.Material)?.dispose();
  }

  /** Two-bone IK: hip → knee → foot, the knee bending up and outwards, then a short tarsus to the ground. */
  private solveLeg(l: Leg) {
    const s = this.fly.scale.x;
    const hip = l.hip.clone().applyMatrix4(this.body.matrixWorld);
    const foot = l.foot.clone().add(new THREE.Vector3(0, 0.05 * s, 0));
    const a = 0.42 * s;
    const b = 0.5 * s;
    const toFoot = foot.clone().sub(hip);
    const d = Math.min(a + b - 0.001, Math.max(Math.abs(a - b) + 0.001, toFoot.length()));
    const dir = toFoot.normalize();
    const out = new THREE.Vector3(l.side, 0, 0).applyAxisAngle(this.up, this.yaw);
    const pole = out.multiplyScalar(0.6).add(this.up).normalize();
    const perp = pole.sub(dir.clone().multiplyScalar(pole.dot(dir))).normalize();
    const cosA = (a * a + d * d - b * b) / (2 * a * d);
    const sinA = Math.sqrt(Math.max(0, 1 - cosA * cosA));
    const knee = hip.clone().add(dir.clone().multiplyScalar(a * cosA)).add(perp.multiplyScalar(a * sinA));
    const tip = hip.clone().add(dir.multiplyScalar(d));
    this.place(l.femur, hip, knee, 1);
    this.place(l.tibia, knee, tip, 0.8);
    this.place(l.tarsus, tip, l.foot, 0.55);
  }

  /** Stretch a unit cylinder (in the fly's space) from world point p0 to p1. */
  private place(m: THREE.Mesh, p0: THREE.Vector3, p1: THREE.Vector3, thick: number) {
    const inv = this.fly.matrixWorld.clone().invert();
    const a = p0.clone().applyMatrix4(inv);
    const b = p1.clone().applyMatrix4(inv);
    const d = b.clone().sub(a);
    const len = d.length();
    m.position.copy(a);
    this.q.setFromUnitVectors(this.up, d.normalize());
    m.quaternion.copy(this.q);
    m.scale.set(thick, len, thick);
  }

  dispose() {
    this.unsub?.();
    this.env?.dispose();
    for (const k of this.caps) k.tex.dispose();
  }
}
