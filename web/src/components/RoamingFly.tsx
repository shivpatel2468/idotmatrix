import { useEffect, useRef, useState } from "react";
import { flyCanPilot, flyTakeOver, useFly } from "../lib/fly";
import { appMeta, useStore } from "../lib/store";

/**
 * A fruit fly that lives on the screen. It darts about, hovers, lands, walks and grooms; it gets curious about a
 * slow cursor and escapes a fast one (a swat). Click it and it dives into the panel and takes over the game there
 * (or starts its own Fly Brain app): the side drawers close and its brain opens beside the panel. While it plays,
 * it's inside the panel; take the game back and it flies out again.
 */

type Mode = "fly" | "hover" | "land" | "walk" | "groom" | "escape" | "dive" | "inside" | "emerge";

const SIZE = 136; // sprite canvas (CSS px)
const ZOOM = 2.25; // the fly is drawn in a ~24-unit body space, scaled up

function drawFly(g: CanvasRenderingContext2D, t: number, s: { wing: number; buzz: number; walk: number; groom: number; air: number }) {
  const c = SIZE / 2;
  g.clearRect(0, 0, SIZE, SIZE);
  g.save();
  g.translate(c, c);
  g.scale(ZOOM, ZOOM);
  // the sprite faces +x
  // ---- legs (under everything): tucked in flight, a tripod gait when walking, front pair rubbing when grooming
  g.strokeStyle = "#1a120b";
  g.lineCap = "round";
  g.lineWidth = 1.3;
  const legs: [number, number, number][] = [
    [5, 3.2, 0.9], [0.5, 3.8, 1.55], [-4, 3.2, 2.3], // x on body, y offset, angle (one side; mirrored)
  ];
  for (const side of [-1, 1])
    legs.forEach(([lx, ly, a], i) => {
      const phase = (i % 2 === 0) === (side > 0) ? 0 : Math.PI;
      let ang = a + Math.sin(s.walk * 14 + phase) * 0.35 * Math.min(1, s.walk > 0 ? 1 : 0);
      let reach = 9 - s.air * 3.5;
      if (i === 0 && s.groom > 0) {
        ang = 0.25 + Math.sin(t * 22 + (side > 0 ? 0 : 1.6)) * 0.3;
        reach = 6.5;
      }
      if (s.air > 0.5) ang = a + 0.6; // trailing back in flight
      const kx = lx + Math.cos(ang) * reach * 0.55;
      const ky = side * (ly + Math.sin(ang) * reach * 0.55);
      const fx = kx + Math.cos(ang + 0.5 * -1) * reach * 0.6 - (i === 2 ? 2 : 0);
      const fy = ky + side * Math.abs(Math.sin(ang + 0.4)) * reach * 0.55;
      g.beginPath();
      g.moveTo(lx, side * ly * 0.6);
      g.lineTo(kx, ky);
      g.lineTo(fx, fy);
      g.stroke();
    });
  // ---- wings: iridescent, folded over the abdomen at rest, a blur of strokes in flight
  const drawWing = (side: number, spread: number, alpha: number) => {
    g.save();
    g.rotate(side * (Math.PI - 0.35 - spread));
    g.globalAlpha = alpha;
    const wg = g.createLinearGradient(0, 0, 17, 0);
    wg.addColorStop(0, "rgba(190,230,255,0.55)");
    wg.addColorStop(0.45, "rgba(255,150,240,0.4)");
    wg.addColorStop(0.75, "rgba(150,255,200,0.35)");
    wg.addColorStop(1, "rgba(255,230,140,0.25)");
    g.fillStyle = wg;
    g.beginPath();
    g.ellipse(9, side * 0.6, 9.5, 3.6, side * 0.08, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = "rgba(255,255,255,0.45)";
    g.lineWidth = 0.6;
    g.stroke();
    g.strokeStyle = "rgba(60,40,30,0.35)";
    g.beginPath();
    for (const v of [-1.4, 0.2, 1.6]) {
      g.moveTo(1, v * 0.4);
      g.quadraticCurveTo(9, v * 1.2, 17, v * 0.9);
    }
    g.stroke();
    g.restore();
  };
  if (s.buzz > 0.05) {
    // motion blur: the stroke smeared over several positions
    for (let k = 0; k < 4; k++) {
      const sp = 0.25 + (0.5 + 0.5 * Math.sin(t * 90 + k * 1.6)) * 1.0 * s.buzz;
      drawWing(-1, sp, 0.32);
      drawWing(1, sp, 0.32);
    }
  } else {
    drawWing(-1, s.wing * 0.15, 0.9);
    drawWing(1, s.wing * 0.15, 0.9);
  }
  // ---- abdomen with dark bands
  const ab = g.createLinearGradient(-14, 0, -2, 0);
  ab.addColorStop(0, "#5a3a1c");
  ab.addColorStop(1, "#b08550");
  g.fillStyle = ab;
  g.beginPath();
  g.ellipse(-7, 0, 7.5, 4.4, 0, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = "rgba(40,22,10,0.75)";
  for (const bx of [-11.5, -8.3, -5.2]) {
    g.beginPath();
    g.ellipse(bx, 0, 1, 4.1 - Math.abs(bx + 7) * 0.25, 0, 0, Math.PI * 2);
    g.fill();
  }
  // ---- thorax (with a sheen) and head
  const th = g.createRadialGradient(1.5, -1.5, 0.5, 2, 0, 5.5);
  th.addColorStop(0, "#e2c08a");
  th.addColorStop(0.5, "#9a6e3c");
  th.addColorStop(1, "#4b301a");
  g.fillStyle = th;
  g.beginPath();
  g.ellipse(2.5, 0, 5, 4.2, 0, 0, Math.PI * 2);
  g.fill();
  g.strokeStyle = "rgba(25,15,8,0.8)";
  g.lineWidth = 0.6;
  for (const by of [-2.5, -1, 1, 2.5]) {
    g.beginPath();
    g.moveTo(1, by);
    g.lineTo(-0.5, by * 1.5);
    g.stroke();
  }
  g.fillStyle = "#6b4a28";
  g.beginPath();
  g.ellipse(8.2, 0, 2.6, 3.3, 0, 0, Math.PI * 2);
  g.fill();
  // ---- big red compound eyes with a glint
  for (const side of [-1, 1]) {
    const eg = g.createRadialGradient(9, side * 2.4, 0.3, 9, side * 2.4, 3);
    eg.addColorStop(0, "#ff5a4a");
    eg.addColorStop(0.6, "#b3121c");
    eg.addColorStop(1, "#4a0508");
    g.fillStyle = eg;
    g.beginPath();
    g.ellipse(8.8, side * 2.5, 2.6, 2.2, 0, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "rgba(255,255,255,0.8)";
    g.beginPath();
    g.arc(9.6, side * 2.5 - 0.8, 0.55, 0, Math.PI * 2);
    g.fill();
  }
  g.restore();
}

export function RoamingFly() {
  const roam = useFly((s) => s.gfx.roam);
  const flying = useFly((s) => s.snap.active && s.snap.driving !== false);
  const cur = useStore((s) => s.state?.engine.current?.app);
  useStore((s) => s.meta);
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const shadow = useRef<HTMLDivElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const mode = useRef<Mode>("fly");
  const inside = useRef(false);
  const [hint, setHint] = useState(false);
  const label = flyCanPilot(cur) ? `Let me play ${appMeta(cur)?.name ?? "this"}` : "Let me play";

  // the fly is playing → it's inside the panel; when it stops, it flies back out
  useEffect(() => {
    if (flying && mode.current !== "dive") {
      mode.current = "inside";
      inside.current = true;
    } else if (!flying && inside.current) {
      inside.current = false;
      mode.current = "emerge";
    }
  }, [flying]);

  useEffect(() => {
    if (!roam) return;
    const el = wrap.current!;
    const c = cv.current!;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = c.height = SIZE * dpr;
    const g = c.getContext("2d")!;
    g.scale(dpr, dpr);
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const W = () => window.innerWidth;
    const H = () => window.innerHeight;
    const rnd = (a: number, b: number) => a + Math.random() * (b - a);
    const st = {
      x: W() * 0.75, y: H() * 0.3, vx: 0, vy: 0, heading: 0, h: 1, // h: height above the screen 0..1
      tx: W() * 0.5, ty: H() * 0.5, until: 0, wing: 0, buzz: 1, walk: 0, groom: 0, scale: 1, visible: 1,
    };
    const mouse = { x: -999, y: -999, speed: 0, t: 0 };
    const onMove = (e: PointerEvent) => {
      const now = performance.now();
      const dt = Math.max(1, now - mouse.t);
      mouse.speed = mouse.speed * 0.6 + (Math.hypot(e.clientX - mouse.x, e.clientY - mouse.y) / dt) * 1000 * 0.4;
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.t = now;
    };
    window.addEventListener("pointermove", onMove, { passive: true });

    const pickTarget = () => {
      // anywhere on the display, a little in from the edges
      st.tx = rnd(40, W() - 40);
      st.ty = rnd(70, H() - 40);
    };
    const panel = () => {
      const b = document.querySelector(".bezel")?.getBoundingClientRect();
      return b ? { x: b.left + b.width / 2, y: b.top + b.height / 2, r: b.width } : { x: W() / 2, y: H() / 2, r: 300 };
    };
    pickTarget();
    let raf = 0;
    let last = performance.now();
    let t = 0;
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (document.visibilityState !== "visible") {
        last = now;
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      t += dt;
      const booted = document.body.dataset.boot === "open" || document.body.dataset.boot === undefined;
      const m = mode.current;
      const dx = mouse.x - st.x;
      const dy = mouse.y - st.y;
      const md = Math.hypot(dx, dy);
      const curious = md < 90 && mouse.speed < 900 && m !== "dive" && m !== "inside" && m !== "emerge";
      if (md < 150 && mouse.speed > 1500 && (m === "hover" || m === "land" || m === "walk" || m === "groom" || m === "fly")) {
        // a swat: escape away from the hand, fast (the giant-fibre escape!)
        mode.current = "escape";
        const a = Math.atan2(-dy, -dx) + rnd(-0.5, 0.5);
        st.tx = Math.min(W() - 30, Math.max(30, st.x + Math.cos(a) * rnd(280, 420)));
        st.ty = Math.min(H() - 30, Math.max(60, st.y + Math.sin(a) * rnd(280, 420)));
      }

      const seek = (speed: number, accel: number, wobble: number) => {
        const ax = st.tx - st.x;
        const ay = st.ty - st.y;
        const d = Math.hypot(ax, ay) || 1;
        const want = Math.min(speed, d * 4);
        const wx = (ax / d) * want + Math.sin(t * 9) * wobble * -ay / d;
        const wy = (ay / d) * want + Math.sin(t * 9) * wobble * ax / d;
        st.vx += (wx - st.vx) * Math.min(1, accel * dt);
        st.vy += (wy - st.vy) * Math.min(1, accel * dt);
        return d;
      };
      const approach = (v: number, to: number, r: number) => v + (to - v) * Math.min(1, r * dt);

      if (still && m !== "dive" && m !== "inside") {
        // reduced motion: it just sits in the corner
        mode.current = "land";
        st.tx = W() - 70;
        st.ty = H() - 120;
      }

      switch (mode.current) {
        case "fly":
        case "escape": {
          const esc = mode.current === "escape";
          const d = seek(esc ? 1100 : rnd(380, 520), esc ? 14 : 5, esc ? 30 : 90);
          st.h = approach(st.h, 1, 3);
          st.buzz = 1;
          if (d < 24) {
            const r = Math.random();
            mode.current = r < 0.4 ? "hover" : r < 0.75 ? "land" : "fly";
            st.until = t + (mode.current === "hover" ? rnd(0.5, 1.8) : rnd(2, 5));
            if (mode.current === "fly") pickTarget();
          }
          break;
        }
        case "hover": {
          st.vx = approach(st.vx, Math.sin(t * 3.1) * 20, 4);
          st.vy = approach(st.vy, Math.cos(t * 2.3) * 16, 4);
          st.h = approach(st.h, 0.85, 3);
          st.buzz = 1;
          if (curious) st.until = Math.max(st.until, t + 0.4);
          if (t > st.until) {
            mode.current = "fly";
            pickTarget();
          }
          break;
        }
        case "land":
        case "walk":
        case "groom": {
          st.h = approach(st.h, 0, 6);
          st.vx = approach(st.vx, 0, 8);
          st.vy = approach(st.vy, 0, 8);
          st.buzz = st.h > 0.15 ? 1 : 0;
          if (st.h < 0.05 && mode.current === "land") mode.current = Math.random() < 0.5 ? "walk" : "groom";
          if (mode.current === "walk") {
            // a few slow steps, turning now and then
            if (Math.random() < dt * 0.8) st.heading += rnd(-1.2, 1.2);
            st.vx = Math.cos(st.heading) * 26;
            st.vy = Math.sin(st.heading) * 26;
            if (Math.random() < dt * 0.4) mode.current = "groom";
          } else if (mode.current === "groom" && Math.random() < dt * 0.35) mode.current = "walk";
          if (curious) st.until = Math.max(st.until, t + 0.6);
          if (t > st.until || st.x < 20 || st.x > W() - 20 || st.y < 60 || st.y > H() - 20) {
            mode.current = "fly";
            pickTarget();
          }
          break;
        }
        case "dive": {
          // spiral into the middle of the panel and shrink into it
          const p = panel();
          st.tx = p.x;
          st.ty = p.y;
          const d = seek(900, 8, 160);
          st.buzz = 1;
          st.scale = approach(st.scale, d < 140 ? 0 : 1, d < 140 ? 7 : 2);
          if (st.scale < 0.05) {
            mode.current = "inside";
            inside.current = true;
            st.visible = 0;
          }
          break;
        }
        case "inside":
          st.visible = 0;
          st.scale = 0;
          break;
        case "emerge": {
          const p = panel();
          if (st.visible === 0) {
            st.x = p.x;
            st.y = p.y;
            st.visible = 1;
            pickTarget();
          }
          st.scale = approach(st.scale, 1, 4);
          seek(600, 6, 60);
          st.buzz = 1;
          if (st.scale > 0.95) mode.current = "fly";
          break;
        }
      }
      if (mode.current !== "walk") {
        const sp = Math.hypot(st.vx, st.vy);
        if (sp > 30) st.heading = Math.atan2(st.vy, st.vx);
      }
      if (curious && st.h < 0.95) st.heading = approach(st.heading, Math.atan2(dy, dx), 3); // it looks at you
      st.x += st.vx * dt;
      st.y += st.vy * dt;
      st.walk = mode.current === "walk" ? t : 0;
      st.groom = mode.current === "groom" ? 1 : 0;

      drawFly(g, t, { wing: 0, buzz: st.buzz, walk: st.walk, groom: st.groom, air: st.h });
      const vis = booted ? st.visible : 0;
      const sc = (1 + st.h * 0.14) * st.scale;
      el.style.opacity = String(vis);
      el.style.transform = `translate3d(${st.x - SIZE / 2}px, ${st.y - SIZE / 2 - st.h * 6}px, 0) rotate(${st.heading}rad) scale(${sc})`;
      const sh = shadow.current!;
      sh.style.opacity = String(vis * (0.55 - st.h * 0.3) * st.scale);
      sh.style.transform = `translate3d(${st.x - 30 + st.h * 22}px, ${st.y - 15 + st.h * 34}px, 0) scale(${(1 + st.h * 0.6) * st.scale})`;
      sh.style.filter = `blur(${2 + st.h * 6}px)`;
      const tp = tip.current;
      if (tp) {
        tp.style.transform = `translate3d(${st.x + 44}px, ${st.y - 56}px, 0)`;
        tp.style.opacity = curious && vis ? "1" : "0";
      }
      if (curious !== hintRef.current) {
        hintRef.current = curious;
        setHint(curious);
      }
    };
    const hintRef = { current: false };
    raf = requestAnimationFrame(frame);
    clickRef.current = () => {
      if (mode.current === "dive" || mode.current === "inside") return;
      mode.current = "dive";
      flyTakeOver();
    };
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", onMove);
    };
  }, [roam]);

  const clickRef = useRef<() => void>(() => {});
  if (!roam) return null;
  return (
    <>
      <div ref={shadow} className="roam-shadow" aria-hidden />
      <div ref={wrap} className="roam-fly" role="button" tabIndex={-1} aria-label="A fruit fly. Click it and it plays the game on the panel"
        onClick={() => clickRef.current()}>
        <canvas ref={cv} style={{ width: SIZE, height: SIZE }} />
      </div>
      <div ref={tip} className="roam-tip" aria-hidden={!hint}>
        <b>🪰 {label}</b>
        <span>click me</span>
      </div>
    </>
  );
}
