import { useEffect, useLayoutEffect, useRef } from "react";
import { type MobileTab, useStore } from "../lib/store";
import {
  type Spring,
  dragTarget,
  isDrag,
  nearestTab,
  releaseTab,
  settled,
  slotWidth,
  slotX,
  springEasing,
  springStep,
  stretch,
} from "../lib/tabDrag";
import { Icon } from "./Icon";
import { glisse } from "../lib/glisse";

export const TABS: [MobileTab, string, string][] = [
  ["panel", "Panel", "monitor-play"],
  ["apps", "Apps", "layout-grid"],
  ["play", "Presets", "list-music"],
  ["tune", "Settings", "sliders-horizontal"],
];

const media = (q: string) => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q) : null);
const reduced = media("(prefers-reduced-motion: reduce)");
const linearEasing = typeof CSS !== "undefined" && CSS.supports?.("animation-timing-function", "linear(0, 1)");

/**
 * Phones: the bottom tab bar — a floating capsule of Liquid Glass with a lens ("bubble") behind the open tab.
 * Tap a tab and the bubble springs over; or press anywhere on the bar and drag: the bubble follows the finger with a
 * spring (squashing as it moves), lights the tab under it, and on release snaps to the nearest tab and opens it.
 *
 * Hot path: transform and opacity only, written straight to the DOM (no React render per pointer move). While a
 * finger drags, a spring runs on requestAnimationFrame; a tap or a release hands the rest of the move to a compositor
 * animation (WAAPI, the same spring as a linear() easing), so the tab's own render can't stall it. Nothing runs at
 * rest. Reduced motion: the bubble just moves.
 */
export function TabBar() {
  const tab = useStore((s) => s.mobileTab);
  const running = useStore((s) => s.state?.engine.mode === "playlist");
  const set = useStore((s) => s.set);
  const nav = useRef<HTMLElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);
  const g = useRef({
    slot: 0,
    spring: { x: 0, v: 0 } as Spring,
    target: 0,
    raf: 0,
    last: 0,
    anim: null as Animation | null,
    press: null as null | { id: number; x0: number; y0: number; grab: number; dragging: boolean },
    lastMove: { x: 0, t: 0, v: 0 },
    near: -1,
    swallowClick: false,
  });
  const index = Math.max(0, TABS.findIndex(([id]) => id === tab));

  const pick = (id: MobileTab) => {
    // tapping the open tab again scrolls it back to the top (the iOS / Android convention)
    if (id === useStore.getState().mobileTab) document.querySelector(".phone-scroll, .phone-stage")?.scrollTo({ top: 0, behavior: "smooth" });
    else set({ mobileTab: id });
  };

  /** Write the bubble's transform: position, squash / stretch, and the lift while held. */
  const paint = (x: number, v: number, held: boolean) => {
    const b = bubble.current;
    if (!b) return;
    const { sx, sy } = reduced?.matches ? { sx: 1, sy: 1 } : stretch(v);
    const lift = held ? 1.06 : 1;
    b.style.transform = `translate3d(${x.toFixed(2)}px,0,0) scale(${(sx * lift).toFixed(4)},${(sy * lift).toFixed(4)})`;
  };

  /** Light the tab under the bubble while it moves (data-near), without a React render. */
  const markNear = (i: number) => {
    const s = g.current;
    if (s.near === i) return;
    s.near = i;
    nav.current?.querySelectorAll<HTMLElement>(".tabbar-btn").forEach((el, j) => {
      if (i === j) el.dataset.near = "true";
      else delete el.dataset.near;
    });
  };

  const stopAnim = () => {
    const s = g.current;
    if (s.anim) {
      // freeze where the compositor has it, then take over from there
      const m = bubble.current ? new DOMMatrix(getComputedStyle(bubble.current).transform) : null;
      s.anim.cancel();
      s.anim = null;
      if (m) s.spring = { x: m.m41, v: 0 };
    }
    cancelAnimationFrame(s.raf);
    s.raf = 0;
  };

  /** Hand the move to the compositor: from where the bubble is to `to`, keeping its velocity. */
  const glide = (to: number) => {
    const s = g.current;
    const b = bubble.current;
    stopAnim();
    const from = s.spring.x;
    s.target = to;
    s.spring = { x: to, v: 0 };
    markNear(-1);
    if (!b) return;
    if (reduced?.matches || Math.abs(to - from) < 0.5) return paint(to, 0, false);
    paint(to, 0, false); // the resting state the animation lands on
    const v0 = s.lastMove.v / (to - from || 1);
    const { easing, ms } = springEasing(Math.max(-12, Math.min(12, v0)));
    const dist = Math.abs(to - from);
    const sq = Math.min(0.16, dist / 1400); // a longer jump stretches more
    s.anim = b.animate(
      [
        { transform: `translate3d(${from}px,0,0) scale(1,1)` },
        { transform: `translate3d(${from + (to - from) * 0.5}px,0,0) scale(${1 + sq},${1 - sq * 0.55})`, offset: 0.28 },
        { transform: `translate3d(${to}px,0,0) scale(1,1)` },
      ],
      linearEasing ? { duration: ms, easing, composite: "replace" } : { duration: 420, easing: "cubic-bezier(0.34, 1.56, 0.5, 1)" },
    );
    s.anim.onfinish = () => (s.anim = null);
    s.lastMove.v = 0;
  };

  /** The drag loop: the spring chases the finger every frame; stops itself once at rest. */
  const loop = (now: number) => {
    const s = g.current;
    s.raf = 0;
    const dt = Math.min(0.05, (now - (s.last || now)) / 1000);
    s.last = now;
    s.spring = reduced?.matches ? { x: s.target, v: 0 } : springStep(s.spring, s.target, dt);
    paint(s.spring.x, s.spring.v, !!s.press?.dragging);
    markNear(nearestTab(s.spring.x, s.slot, TABS.length));
    if (s.press?.dragging || !settled(s.spring, s.target)) s.raf = requestAnimationFrame(loop);
  };
  const kick = () => {
    const s = g.current;
    if (!s.raf) {
      s.last = performance.now();
      s.raf = requestAnimationFrame(loop);
    }
  };

  // measure the slots (and keep the bubble on its tab when the bar resizes: rotation, split screen)
  useLayoutEffect(() => {
    const el = nav.current;
    if (!el) return;
    const measure = () => {
      const s = g.current;
      const cs = getComputedStyle(el);
      const inner = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      s.slot = slotWidth(inner, TABS.length);
      el.style.setProperty("--tab-slot", `${s.slot}px`);
      if (!s.press) {
        stopAnim();
        const i = Math.max(0, TABS.findIndex(([id]) => id === useStore.getState().mobileTab));
        s.target = slotX(i, s.slot);
        s.spring = { x: s.target, v: 0 };
        paint(s.target, 0, false);
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => {
      ro.disconnect();
      stopAnim();
    };
  }, []);

  // Glisse's glass: the bar bends what scrolls under it (one ray), the bubble is a small lens with the colour split
  useEffect(() => {
    const off = [glisse(nav.current, { lens: "ray" }), glisse(bubble.current, { rim: false, lens: "split" })];
    return () => off.forEach((f) => f());
  }, []);

  // the open tab changed (a tap, a release, or elsewhere — the "now showing" strip opens Panel): spring over
  useEffect(() => {
    const s = g.current;
    const to = slotX(index, s.slot);
    if (s.slot && !s.press?.dragging && Math.abs(s.target - to) > 0.5) glide(to); // a release already glides there
  }, [index]); // eslint-disable-line react-hooks/exhaustive-deps

  const localX = (e: React.PointerEvent) => {
    const el = nav.current!;
    const r = el.getBoundingClientRect();
    return e.clientX - r.left - el.clientLeft - parseFloat(getComputedStyle(el).paddingLeft);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const s = g.current;
    const x = localX(e);
    // grabbed on the bubble: keep the finger where it took hold; elsewhere: the bubble centres under the finger
    const onBubble = x >= s.spring.x && x <= s.spring.x + s.slot;
    s.press = { id: e.pointerId, x0: e.clientX, y0: e.clientY, grab: onBubble ? x - s.spring.x : s.slot / 2, dragging: false };
    s.lastMove = { x: e.clientX, t: e.timeStamp, v: 0 };
    s.swallowClick = false;
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const s = g.current;
    const p = s.press;
    if (!p || p.id !== e.pointerId) return;
    if (!p.dragging) {
      if (!isDrag(e.clientX - p.x0, e.clientY - p.y0)) return;
      p.dragging = true;
      nav.current?.setPointerCapture(e.pointerId);
      nav.current?.setAttribute("data-drag", "true");
      stopAnim();
    }
    const dtm = Math.max(1, e.timeStamp - s.lastMove.t);
    const v = ((e.clientX - s.lastMove.x) / dtm) * 1000;
    s.lastMove = { x: e.clientX, t: e.timeStamp, v: s.lastMove.v * 0.6 + v * 0.4 };
    s.target = dragTarget(localX(e), p.grab, s.slot, TABS.length);
    kick();
  };

  const finish = (e: React.PointerEvent, cancelled: boolean) => {
    const s = g.current;
    const p = s.press;
    if (!p || p.id !== e.pointerId) return;
    s.press = null;
    if (!p.dragging) return; // a plain tap: the button's click handles it
    nav.current?.removeAttribute("data-drag");
    s.swallowClick = true; // the click that follows a drag must not open the tab where the finger lifted
    setTimeout(() => (s.swallowClick = false), 0);
    cancelAnimationFrame(s.raf);
    s.raf = 0;
    const cur = Math.max(0, TABS.findIndex(([id]) => id === useStore.getState().mobileTab));
    const to = cancelled ? cur : releaseTab(s.spring.x, s.lastMove.v, s.slot, TABS.length);
    s.lastMove.v = s.spring.v;
    glide(slotX(to, s.slot));
    if (to !== cur) pick(TABS[to][0]);
  };

  return (
    <nav ref={nav} className="tabbar" aria-label="Sections"
      onPointerDown={onPointerDown} onPointerMove={onPointerMove}
      onPointerUp={(e) => finish(e, false)} onPointerCancel={(e) => finish(e, true)}>
      <span ref={bubble} className="tabbar-bubble" aria-hidden><i className="tabbar-bubble-fill" /><i className="tabbar-bubble-rim" /></span>
      {TABS.map(([id, label, icon]) => (
        <button key={id} onClick={() => !g.current.swallowClick && pick(id)} aria-current={tab === id ? "page" : undefined} className="tabbar-btn">
          <span className="tabbar-pill">
            <Icon name={icon} size={21} duo={tab === id} strokeWidth={tab === id ? 1.9 : 1.7} />
            {id === "play" && running && <span className="led absolute right-2 top-0.5 !h-[6px] !w-[6px]" data-on="ok" />}
          </span>
          {label}
        </button>
      ))}
    </nav>
  );
}
