import { useEffect, useRef, useState } from "react";
import { useStore } from "../lib/store";
import { TIPS } from "../lib/tips";
import { Doors } from "./boot/doors";

const MIN_INTRO_MS = 2600; // long enough for the logo to build and strike
const OFFLINE_MS = 2500; // the engine has been gone this long: close the doors (the outro)

/**
 * Intro / outro. Two doors with an LED-matrix face cover the studio while it connects; the idotmatrix logo builds
 * across their seam and strikes like neon. When the engine, the app catalogue and the first state are in, the
 * lock flares and the doors slide apart onto the studio. If the engine goes away later, they slide shut again.
 */
export function Boot() {
  const meta = useStore((s) => s.meta);
  const state = useStore((s) => s.state);
  const link = useStore((s) => s.link);
  const cvL = useRef<HTMLCanvasElement>(null);
  const cvR = useRef<HTMLCanvasElement>(null);
  const doorL = useRef<HTMLDivElement>(null);
  const doorR = useRef<HTMLDivElement>(null);
  const shine = useRef<HTMLDivElement>(null);
  const doors = useRef<Doors | null>(null);
  const [phase, setPhase] = useState<"intro" | "opening" | "open" | "closing">("intro");
  const [tip, setTip] = useState(() => Math.floor(Math.random() * TIPS.length));
  const start = useRef(performance.now());
  const lastOpen = useRef(performance.now());
  if (link === "open") lastOpen.current = performance.now();

  const steps = [
    { label: "Waking the engine", ok: link === "open" },
    { label: "Loading apps", ok: !!meta },
    { label: "Reading the panel", ok: !!state },
  ];
  const progress = steps.filter((s) => s.ok).length / steps.length;
  const shut = phase === "intro" || phase === "closing";

  useEffect(() => {
    if (!shut) return;
    const t = setInterval(() => setTip((i) => (i + 1) % TIPS.length), 2800);
    return () => clearInterval(t);
  }, [shut]);

  // the canvas runs only while the doors are on screen
  useEffect(() => {
    if (phase === "open") return;
    const c = cvL.current;
    const c2 = cvR.current;
    if (!c || !c2) return;
    let d = doors.current;
    if (d?.left !== c) {
      d = new Doors(c, c2, phase === "closing");
      if (phase === "closing") d.slide(0); // the outro: in from the sides
    }
    doors.current = d;
    d.resize();
    const onResize = () => d.resize();
    window.addEventListener("resize", onResize);
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const pose = d.frame(dt);
      // the halves slide apart 50/50, tilting back a touch and dimming as they go
      const o = pose.open;
      const tilt = Math.sin(o * Math.PI) * 9;
      const css = (dir: -1 | 1) =>
        `translate3d(${dir * o * 104}%, 0, 0) perspective(1400px) rotateY(${-dir * tilt}deg) scale(${1 - o * 0.06})`;
      if (doorL.current) {
        doorL.current.style.transform = css(-1);
        doorL.current.style.filter = `brightness(${1 - o * 0.45})`;
      }
      if (doorR.current) {
        doorR.current.style.transform = css(1);
        doorR.current.style.filter = `brightness(${1 - o * 0.45})`;
      }
      if (shine.current) shine.current.style.opacity = String(Math.min(1, pose.crack) * (1 - o) * 1.2);
      if (d.open >= 1 && d.idle) setPhase((p) => (p === "opening" ? "open" : p));
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, [phase]);

  // intro → open, once everything is in and the logo has had its moment
  useEffect(() => {
    if (phase !== "intro" || progress < 1) return;
    const wait = Math.max(0, MIN_INTRO_MS - (performance.now() - start.current));
    const t = setTimeout(() => {
      setPhase("opening");
      doors.current?.slide(1);
    }, wait);
    return () => clearTimeout(t);
  }, [phase, progress]);

  // outro: the engine went away → shut the doors; it's back → open them again
  useEffect(() => {
    if (phase === "open" && link !== "open") {
      // reconnect attempts flip between "connecting" and "closed"; time from when the link was last up
      const t = setTimeout(() => {
        if (useStore.getState().link === "open") return;
        setPhase("closing");
      }, Math.max(0, OFFLINE_MS - (performance.now() - lastOpen.current)));
      return () => clearTimeout(t);
    }
    if (phase === "closing" && link === "open" && meta && state) {
      start.current = performance.now() - MIN_INTRO_MS + 900;
      setPhase("intro");
    }
  }, [phase, link, meta, state]);

  // the studio behind the doors eases forward as they open
  useEffect(() => {
    document.body.dataset.boot = phase;
  }, [phase]);

  if (phase === "open") return null;
  return (
    <div className="boot fixed inset-0 z-[100]" data-phase={phase} aria-busy={shut} aria-label="Starting the idotmatrix studio">
      <div ref={shine} className="boot-shine" />
      <div ref={doorL} className="boot-door boot-door-l"><canvas ref={cvL} /></div>
      <div ref={doorR} className="boot-door boot-door-r"><canvas ref={cvR} /></div>
      <div className="boot-ui pointer-events-none absolute inset-x-0 top-[calc(42%+min(6.2vw,110px)+46px)] mx-auto flex w-[min(560px,88vw)] flex-col items-center gap-6">
        <div className="engrave !text-[9px] !tracking-[0.42em] !text-ink-3">DeskDot studio · all in one for your iDotMatrix</div>
        <div className="w-full">
          <div className="h-[3px] overflow-hidden rounded-full bg-white/[0.06]">
            <div className="boot-bar h-full rounded-full transition-all duration-500" style={{ width: `${Math.max(8, progress * 100)}%` }} />
          </div>
          <div className="mt-3 flex justify-between gap-2">
            {steps.map((s) => (
              <span key={s.label} className="engrave flex items-center gap-1.5 !text-[8.5px]">
                <span className="led" data-on={s.ok ? "ok" : "warn"} /> {s.label}
              </span>
            ))}
          </div>
        </div>
        <p key={tip} className="min-h-[3em] max-w-md animate-rise text-center text-[13px] leading-relaxed text-ink-2">
          <span className="engrave mr-2 !text-ember">Tip</span>
          {TIPS[tip]}
        </p>
        {link !== "open" && (phase === "closing" || link === "closed") && (
          <p className="text-center font-mono text-[11px] text-warn">
            {phase === "closing" ? "The engine stopped." : "Engine not reachable."} Start it with <code>uv run deskdot serve</code>
          </p>
        )}
      </div>
    </div>
  );
}
