/**
 * Glisse's press — the phone's glass keys stretch like iOS 26's glass buttons (docs/STUDIO_UI.md § Liquid Glass, R-STU-15).
 *
 * Adapted from Glisse by Kelvin Zhang (https://github.com/0kzh/glisse, MIT licence: docs/licenses/glisse.txt,
 * THIRD_PARTY_NOTICES.md): its spring (src/internal/spring.ts), its button press (src/internal/press.ts) and its menu
 * card's press (src/menu.tsx), as plain TypeScript.
 *
 *   key   a finger on a key grows it until its longer side is ~15 px bigger; dragging stretches it toward the finger
 *         (longer along the drag, thinner across) and leans it up to 8 px that way, with a rubber band; on release it
 *         springs back past its size and settles. A mouse press stays subtle (6 px).
 *   card  pressed, a menu card swells by 5 px and follows the finger a little (a rubber band that tops out at 7 px).
 *
 * Only the `scale` and `translate` properties move (compositor only; they compose with any `transform` the element
 * already has); springs run on requestAnimationFrame only while something moves, and stop at rest. Reduced motion and
 * hidden tabs jump straight to the end. One pointerdown listener serves every key (`installGlissePress`).
 */

// ------------------------------------------------------------------------------------------------- the spring

export interface Spring {
  set(target: number, instant?: boolean): void;
  tune(stiffness: number, damping: number): void;
  stop(): void;
}

interface SpringState {
  value: number;
  target: number;
  velocity: number;
  stiffness: number;
  damping: number;
  paint: (value: number) => void;
}

/** One step of a damped spring (exact, so any frame time is stable): returns the new value and velocity. */
export function advance(value: number, velocity: number, target: number, stiffness: number, damping: number, dt: number): [number, number] {
  const x = value - target;
  const v = velocity;
  const half = damping / 2;
  const disc = half * half - stiffness;
  if (Math.abs(disc) < 1e-4) {
    const decay = Math.exp(-half * dt);
    const b = v + half * x;
    return [target + decay * (x + b * dt), decay * (v - half * b * dt)];
  }
  if (disc > 0) {
    const root = Math.sqrt(disc);
    const r1 = -half + root;
    const r2 = -half - root;
    const a = (v - r2 * x) / (r1 - r2);
    const b = x - a;
    return [target + a * Math.exp(r1 * dt) + b * Math.exp(r2 * dt), a * r1 * Math.exp(r1 * dt) + b * r2 * Math.exp(r2 * dt)];
  }
  const omega = Math.sqrt(-disc);
  const decay = Math.exp(-half * dt);
  const cos = Math.cos(omega * dt);
  const sin = Math.sin(omega * dt);
  return [target + decay * (x * cos + ((v + half * x) / omega) * sin), decay * (v * cos - ((half * v + stiffness * x) / omega) * sin)];
}

const moving = new Set<SpringState>();
let frame = 0;
let last = 0;
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function tick(time: number) {
  frame = 0;
  const dt = Math.min(0.1, Math.max(0, (time - last) / 1000));
  last = time;
  for (const s of moving) {
    [s.value, s.velocity] = advance(s.value, s.velocity, s.target, s.stiffness, s.damping, dt);
    if (Math.abs(s.value - s.target) < 1e-4 && Math.abs(s.velocity) < 1e-3) {
      s.value = s.target;
      s.velocity = 0;
      moving.delete(s);
    }
    s.paint(s.value);
  }
  if (moving.size) frame = requestAnimationFrame(tick);
}

export function createSpring(value: number, stiffness: number, damping: number, paint: (value: number) => void): Spring {
  const s: SpringState = { value, target: value, velocity: 0, stiffness, damping, paint };
  return {
    set(target, instant = false) {
      s.target = target;
      if (instant || document.hidden || reduced()) {
        s.value = target;
        s.velocity = 0;
        moving.delete(s);
        paint(target);
        return;
      }
      moving.add(s);
      if (!frame) {
        last = Number(document.timeline?.currentTime ?? performance.now());
        frame = requestAnimationFrame(tick);
      }
    },
    tune(k, c) {
      s.stiffness = k;
      s.damping = c;
    },
    stop: () => void moving.delete(s),
  };
}

// --------------------------------------------------------------------------------------------- the key's press

export interface Feel {
  /** How many px the longer side grows while pressed. */
  grow: number;
  press: readonly [number, number];
  release: readonly [number, number];
}
/** A mouse press stays subtle. */
export const POINTER: Feel = { grow: 6, press: [417.6, 29.2], release: [230, 23.7] };
/** A finger gets the iOS 26 glass button: ~15 px bigger, and a bounce past its size on release. */
export const TOUCH: Feel = { grow: 15, press: [515, 27.3], release: [250, 11.8] };

/** Where a pressed key heads: [scaleX, scaleY, translateX, translateY] for a finger `dx`, `dy` from where it landed. */
export function pressTarget(width: number, height: number, dx: number, dy: number, feel: Feel): [number, number, number, number] {
  const base = 1 + feel.grow / Math.max(width, height);
  const aspect = width / height;
  const ax = dx / aspect;
  const length = Math.hypot(ax, dy);
  if (!length) return [base, base, 0, 0];
  const nx = ax / length;
  const ny = dy / length;
  const rubber = 1 - 1 / (1 + length / height / (5 * aspect));
  const stretch = 1 + (6 / height) * rubber * Math.abs(Math.abs(nx) - Math.abs(ny));
  const horizontal = Math.abs(nx) > Math.abs(ny);
  return [base * (horizontal ? stretch : 1 / stretch), base * (horizontal ? 1 / stretch : stretch), nx * 8 * rubber, ny * 8 * rubber];
}

/** A menu card follows a finger with this much give: tops out at 7 px. */
export const resistance = (v: number) => Math.sign(v) * 7 * (1 - Math.exp((-Math.abs(v) * 0.12) / 7));

type Press = { el: HTMLElement; springs: Spring[]; value: number[] };
const presses = new WeakMap<HTMLElement, Press>();

function pressOf(el: HTMLElement): Press {
  let p = presses.get(el);
  if (p) return p;
  const value = [1, 1, 0, 0];
  const paint = () => {
    const rest = value[0] === 1 && value[1] === 1 && value[2] === 0 && value[3] === 0;
    el.style.scale = rest ? "" : `${value[0]} ${value[1]}`;
    el.style.translate = rest ? "" : `${value[2]}px ${value[3]}px`;
  };
  const springs = value.map((v0, i) =>
    createSpring(v0, ...POINTER.release, (next) => {
      value[i] = next;
      paint();
    }),
  );
  p = { el, springs, value };
  presses.set(el, p);
  return p;
}

const aim = (p: Press, next: number[], [k, c]: readonly [number, number]) =>
  p.springs.forEach((s, i) => {
    s.tune(k, c);
    s.set(next[i] ?? 0);
  });

/** Presses `el` like a Glisse glass button until the pointer lifts; returns nothing (it cleans up itself). */
export function pressKey(el: HTMLElement, e: PointerEvent) {
  if (!e.isPrimary || e.button !== 0 || (el as HTMLButtonElement).disabled) return;
  const p = pressOf(el);
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) return;
  const feel = e.pointerType === "mouse" ? POINTER : TOUCH;
  const id = e.pointerId;
  const x0 = e.clientX;
  const y0 = e.clientY;
  const track = (ev: PointerEvent) => {
    el.style.setProperty("--lg-x", `${((ev.clientX - box.left) / box.width) * 100}%`);
    el.style.setProperty("--lg-y", `${((ev.clientY - box.top) / box.height) * 100}%`);
    aim(p, pressTarget(box.width, box.height, ev.clientX - x0, ev.clientY - y0, feel), feel.press);
  };
  const move = (ev: PointerEvent) => ev.pointerId === id && track(ev);
  const end = (ev?: Event) => {
    if (ev instanceof PointerEvent && ev.pointerId !== id) return;
    delete el.dataset.pressed;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    window.removeEventListener("blur", end);
    aim(p, [1, 1, 0, 0], feel.release);
  };
  el.dataset.pressed = "";
  window.addEventListener("pointermove", move, { passive: true });
  window.addEventListener("pointerup", end);
  window.addEventListener("pointercancel", end);
  window.addEventListener("blur", end);
  track(e);
}

/** Glisse's menu card press on `card` (a popover menu): swells and follows the finger with a rubber band. */
export function cardPress(card: HTMLElement | null): () => void {
  if (!card) return () => {};
  const offset = { scale: 1, x: 0, y: 0 };
  const paint = () => {
    card.style.scale = offset.scale === 1 ? "" : String(offset.scale);
    card.style.translate = offset.x || offset.y ? `${offset.x}px ${offset.y}px` : "";
  };
  const scale = createSpring(1, 650, 36, (v) => ((offset.scale = v), paint()));
  const x = createSpring(0, 600, 30, (v) => ((offset.x = v), paint()));
  const y = createSpring(0, 600, 30, (v) => ((offset.y = v), paint()));
  let g: { id: number; x: number; y: number } | null = null;
  const down = (e: PointerEvent) => {
    if (!e.isPrimary || e.button !== 0) return;
    g = { id: e.pointerId, x: e.clientX, y: e.clientY };
    card.dataset.pressed = "";
    scale.set(1 + 5 / Math.max(card.offsetWidth, card.offsetHeight, 200));
  };
  const move = (e: PointerEvent) => {
    if (!g || e.pointerId !== g.id) return;
    x.set(resistance(e.clientX - g.x), true);
    y.set(resistance(e.clientY - g.y), true);
  };
  const end = (e: PointerEvent) => {
    if (!g || e.pointerId !== g.id) return;
    g = null;
    delete card.dataset.pressed;
    scale.set(1);
    x.set(0);
    y.set(0);
  };
  card.addEventListener("pointerdown", down);
  window.addEventListener("pointermove", move, { passive: true });
  window.addEventListener("pointerup", end);
  window.addEventListener("pointercancel", end);
  return () => {
    [scale, x, y].forEach((s) => s.stop());
    card.removeEventListener("pointerdown", down);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    card.style.removeProperty("scale");
    card.style.removeProperty("translate");
  };
}

/** The keys that stretch on the phone: Glisse's buttons (`.key` and its variants) and the theme key. */
export const PRESS_SELECTOR = ".key, .theme-fab-key";

let installed = false;
/** One listener for every glass key on the phone layout (below the `md` breakpoint, as `usePhone`). */
export function installGlissePress() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  const phone = matchMedia("(max-width: 767.98px)");
  document.addEventListener(
    "pointerdown",
    (e) => {
      if (!phone.matches) return;
      const el = (e.target as Element | null)?.closest?.<HTMLElement>(PRESS_SELECTOR);
      if (el && !el.closest(".tabbar")) pressKey(el, e);
    },
    { capture: true, passive: true },
  );
}
