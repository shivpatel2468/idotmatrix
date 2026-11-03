import { useEffect, useRef, useState } from "react";
import { introDone, nativeIntro } from "../lib/android";
import { type IntroTheme, getIntroTheme, onIntroTheme } from "../lib/intro";
import { useStore } from "../lib/store";
import { TIPS } from "../lib/tips";
import { CircuitDoors } from "./boot/circuit";
import { CoinGate } from "./boot/coin";
import { OgIntro } from "./boot/og";
import { type DoorPose, SunsetDoors } from "./boot/sunset";

const MIN_INTRO_MS: Record<IntroTheme, number> = { sunset: 2600, circuit: 2600, coin: 3300, og: 1700, off: 0 };
const OFFLINE_MS = 2500; // the engine has been gone this long: close the doors (the outro)
const FADE_MS = 650; // OG / Off themes fade instead of opening doors

type DoorScene = {
  readonly left: HTMLCanvasElement;
  open: number;
  readonly idle: boolean;
  resize(): void;
  slide(to: 0 | 1): void;
  frame(dt: number): DoorPose;
  /** The engine is in: a scene that waits for it (Coin Gate's coin) may play its build-up now. */
  arm?(): void;
};

/** Themes drawn as a sealed scene that opens; "coin" draws its own gate halves on one full-screen canvas. */
const isDoors = (t: IntroTheme) => t === "sunset" || t === "circuit" || t === "coin";

/**
 * Intro / outro, in the theme picked in Settings → Display (lib/intro.ts):
 * - Sunset / Circuit: a sealed scene covers the studio while it connects; the DeskDot logo builds and strikes;
 *   when the engine, the app catalogue and the first state are in, the scene splits and the halves glide apart 50/50.
 * - Coin Gate: an arcade cabinet; a silver coin drops in, CREDIT 1, and the heavy toothed gate grinds open. It draws
 *   both gate halves itself on one canvas (no CSS doors) and waits for the engine before the coin drops.
 * - OG: the original — LEDs fly in and settle into the wordmark — then a fade.
 * - Off: just the progress, then a quick fade.
 * If the engine goes away later, the intro comes back (the outro) and leaves again when it's back.
 *
 * Inside the Android app the app plays its own short LED intro natively (MainActivity / IntroView) from the very first
 * frame: here the studio shows nothing of its own, opens the moment it is ready and tells the app (introDone), which
 * hands over. Later outros in the app are the compact fade with a kind line, never the big scenes; a replay from
 * Settings still previews the chosen theme.
 */
export function Boot() {
  const meta = useStore((s) => s.meta);
  const state = useStore((s) => s.state);
  const link = useStore((s) => s.link);
  const [chosen, setTheme] = useState<IntroTheme>(() => getIntroTheme());
  const inApp = useRef(nativeIntro()).current;
  const [firstBoot, setFirstBoot] = useState(inApp); // the app's native intro covers this one
  const [preview, setPreview] = useState(false); // a replay from Settings
  // in the app: the studio's own scenes only as a preview; the first boot is the app's, outros are the compact fade
  const theme: IntroTheme = inApp && !preview ? "off" : chosen;
  const cvL = useRef<HTMLCanvasElement>(null);
  const cvR = useRef<HTMLCanvasElement>(null);
  const cvOg = useRef<HTMLCanvasElement>(null);
  const cvCoin = useRef<HTMLCanvasElement>(null);
  const doorL = useRef<HTMLDivElement>(null);
  const doorR = useRef<HTMLDivElement>(null);
  const shine = useRef<HTMLDivElement>(null);
  const doors = useRef<DoorScene | null>(null);
  const [phase, setPhase] = useState<"intro" | "opening" | "open" | "closing">("intro");
  const [tip, setTip] = useState(() => Math.floor(Math.random() * TIPS.length));
  const start = useRef(performance.now());
  const replaying = useRef(false);
  const lastOpen = useRef(performance.now());
  if (link === "open") lastOpen.current = performance.now();

  const steps = [
    { label: "Waking the engine", ok: link === "open" },
    { label: "Loading apps", ok: !!meta },
    { label: "Reading the panel", ok: !!state },
  ];
  const progress = steps.filter((s) => s.ok).length / steps.length;
  const shut = phase === "intro" || phase === "closing";

  // the theme can change in Settings, and Settings can replay the intro as a preview
  useEffect(() => onIntroTheme(() => setTheme(getIntroTheme())), []);
  useEffect(() => {
    const replay = () => {
      replaying.current = true;
      setPreview(true);
      setPhase("closing");
    };
    window.addEventListener("deskdot:replay-intro", replay);
    return () => window.removeEventListener("deskdot:replay-intro", replay);
  }, []);

  useEffect(() => {
    if (!shut) return;
    const t = setInterval(() => setTip((i) => (i + 1) % TIPS.length), 2800);
    return () => clearInterval(t);
  }, [shut]);

  // door themes: the canvas runs only while the doors are on screen
  useEffect(() => {
    if (phase === "open" || !isDoors(theme)) return;
    const coin = theme === "coin";
    const c = coin ? cvCoin.current : cvL.current;
    const c2 = cvR.current;
    if (!c || (!coin && !c2)) return;
    let d = doors.current;
    if (d?.left !== c) {
      const closing = phase === "closing";
      d = coin ? new CoinGate(c, closing) : theme === "circuit" ? new CircuitDoors(c, c2!, closing) : new SunsetDoors(c, c2!, closing);
      if (closing) d.slide(0); // the outro: in from the sides
    }
    doors.current = d;
    if (phase === "intro") d.arm?.();
    d.resize();
    const scene = d;
    const onResize = () => scene.resize();
    window.addEventListener("resize", onResize);
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const pose = scene.frame(dt);
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
      // a soft light through the crack — kept modest so it never blooms over the logo
      if (shine.current) shine.current.style.opacity = String(Math.min(1, pose.crack) * (1 - o) * 0.85);
      if (scene.open >= 1 && scene.idle) setPhase((p) => (p === "opening" ? "open" : p));
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, [phase, theme]);

  // OG theme: the wordmark canvas
  useEffect(() => {
    if (phase === "open" || theme !== "og" || !cvOg.current) return;
    const og = new OgIntro(cvOg.current);
    const onResize = () => og.resize();
    window.addEventListener("resize", onResize);
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      og.frame();
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, [phase === "open", theme]); // eslint-disable-line react-hooks/exhaustive-deps

  // the app's intro is on screen: open as soon as everything is in, then let the app hand over (after a paint)
  useEffect(() => {
    if (!firstBoot || progress < 1) return;
    setPhase("open");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      setFirstBoot(false);
      introDone();
    }));
  }, [firstBoot, progress]);

  // intro → open, once everything is in and the intro has had its moment
  useEffect(() => {
    if (firstBoot || phase !== "intro" || progress < 1) return;
    const wait = Math.max(0, MIN_INTRO_MS[theme] - (performance.now() - start.current));
    const t = setTimeout(() => {
      setPreview(false);
      setPhase("opening");
      if (isDoors(theme)) doors.current?.slide(1);
    }, wait);
    return () => clearTimeout(t);
  }, [firstBoot, phase, progress, theme]);

  // fade themes: opening is a fade, then gone
  useEffect(() => {
    if (phase !== "opening" || isDoors(theme)) return;
    const t = setTimeout(() => setPhase("open"), FADE_MS);
    return () => clearTimeout(t);
  }, [phase, theme]);

  // outro: the engine went away → bring the intro back; it's back → leave again
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
      // a replay from Settings plays the whole intro; a reconnect gets a shorter one
      start.current = replaying.current ? performance.now() + 1200 : performance.now() - MIN_INTRO_MS[theme] + 900;
      replaying.current = false;
      setPhase("intro");
    }
  }, [phase, link, meta, state, theme]);

  // the studio behind eases forward as the intro leaves
  useEffect(() => {
    document.body.dataset.boot = phase;
  }, [phase]);

  if (phase === "open") return null;
  // the app's own intro covers the first boot: nothing to draw here (its errors are the app's to show)
  if (firstBoot) return <div className="fixed inset-0 z-[100] bg-chassis-0" aria-busy aria-label="Opening DeskDot" />;
  if (inApp && !preview) {
    // the engine on this phone went away for a moment (it restarts itself): a calm line, no steps, no commands
    return (
      <div className="boot boot-fade fixed inset-0 z-[100] grid place-items-center bg-chassis-0" data-phase={phase} aria-busy={shut} aria-label="Reconnecting"
        style={{ opacity: phase === "opening" ? 0 : 1, transition: `opacity ${FADE_MS}ms ease` }}>
        <p className="max-w-[18rem] animate-rise text-center text-[14px] leading-relaxed text-ink-2">
          One moment — DeskDot is getting back on its feet. Your panel keeps its picture.
        </p>
      </div>
    );
  }
  const offline = link !== "open" && (phase === "closing" || link === "closed") && (
    <p className="text-center font-mono text-[11px] text-warn">
      {phase === "closing" ? "The engine stopped." : "Engine not reachable."} Start it with <code>uv run deskdot serve</code>
    </p>
  );
  const status = (
    <>
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
      {offline}
    </>
  );

  if (!isDoors(theme)) {
    // OG and Off: a dark screen that fades away
    return (
      <div className="boot boot-fade fixed inset-0 z-[100] grid place-items-center bg-chassis-0" data-phase={phase} aria-busy={shut} aria-label="Starting the DeskDot studio"
        style={{ opacity: phase === "opening" ? 0 : 1, transition: `opacity ${FADE_MS}ms ease` }}>
        <div className="flex w-[min(560px,90vw)] flex-col items-center gap-8">
          {theme === "og" && <canvas ref={cvOg} className="max-w-full" />}
          {status}
        </div>
      </div>
    );
  }
  const caption = <div className="engrave !text-[9px] !tracking-[0.42em] !text-ink-3">DeskDot studio · all in one for your iDotMatrix</div>;
  if (theme === "coin") {
    return (
      <div className="boot fixed inset-0 z-[100]" data-phase={phase} aria-busy={shut} aria-label="Starting the DeskDot studio">
        <canvas ref={cvCoin} className="absolute left-0 top-0 block" />
        <div className="boot-ui boot-glass pointer-events-none absolute inset-x-0 top-[71%] mx-auto flex w-[min(560px,88vw)] flex-col items-center gap-5">
          {caption}
          {status}
        </div>
      </div>
    );
  }
  return (
    <div className="boot fixed inset-0 z-[100]" data-phase={phase} aria-busy={shut} aria-label="Starting the DeskDot studio">
      <div ref={shine} className="boot-shine" />
      <div ref={doorL} className="boot-door boot-door-l"><canvas ref={cvL} /></div>
      <div ref={doorR} className="boot-door boot-door-r"><canvas ref={cvR} /></div>
      <div className={`boot-ui pointer-events-none absolute inset-x-0 mx-auto flex w-[min(560px,88vw)] flex-col items-center gap-6 ${theme === "sunset" ? "top-[67%] boot-glass" : "top-[calc(42%+min(6.2vw,110px)+46px)]"}`}>
        {caption}
        {status}
      </div>
    </div>
  );
}
