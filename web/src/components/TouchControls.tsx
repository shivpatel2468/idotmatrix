import clsx from "clsx";
import { useRef, useState } from "react";
import { type TouchStyle, useControls } from "../lib/controls";
import { type GameKey, isPlayable, pressKey, releaseKey, setHoldDepth, usePressedKeys } from "../lib/gameInput";
import { appMeta, useStore } from "../lib/store";
import { SEAT_COLORS } from "./Multiplayer";

/**
 * On-screen controllers for touch screens (phones, tablets, touchscreen laptops): d-pad, floating joystick,
 * swipe pad and tap zones — the same concepts as the phone controller. Each drives one local player through the
 * shared controller in lib/gameInput.ts (held = auto-repeat, pressed keys light up).
 */
function current() {
  const s = useStore.getState();
  const app = s.state?.engine.current?.app;
  return app && isPlayable(appMeta(app)) ? app : null;
}

const capture = (e: React.PointerEvent) => {
  try {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); // release even if the finger slides off
  } catch {
    /* synthetic / already-ended pointer */
  }
};

/** One pad key: press on pointer down, release on up / cancel / lost capture. */
function PadKey({ k, player, label, cls = "" }: { k: GameKey; player: number; label: React.ReactNode; cls?: string }) {
  const down = usePressedKeys(player);
  return (
    <button
      className={clsx("padkey", cls)} aria-label={k} data-down={down.has(k) || undefined}
      onPointerDown={(e) => {
        e.preventDefault();
        const app = current();
        if (!app) return;
        pressKey(k, `pt:${e.pointerId}`, app, player);
        capture(e);
      }}
      onPointerUp={(e) => releaseKey(k, `pt:${e.pointerId}`, player)}
      onPointerCancel={(e) => releaseKey(k, `pt:${e.pointerId}`, player)}
      onLostPointerCapture={(e) => releaseKey(k, `pt:${e.pointerId}`, player)}
      onContextMenu={(e) => e.preventDefault()}
    >{label}</button>
  );
}

function ABButtons({ player }: { player: number }) {
  return (
    <div className="flex items-end gap-3 pb-2">
      <div className="flex flex-col items-center gap-1"><PadKey k="b" player={player} label="B" cls="padkey-round" /></div>
      <div className="-mt-10 flex flex-col items-center gap-1"><PadKey k="a" player={player} label="A" cls="padkey-round padkey-a" /></div>
    </div>
  );
}

/** A big d-pad and A/B. */
export function GamePad({ compact = false, player = 1 }: { compact?: boolean; player?: number }) {
  return (
    <div className={clsx("gamepad flex w-full select-none items-center justify-between", compact && "gamepad-compact")} aria-label="Game controls">
      <div className="grid grid-cols-3 gap-1.5">
        <span /><PadKey k="up" player={player} label="▲" /><span />
        <PadKey k="left" player={player} label="◀" /><span className="padhub" /><PadKey k="right" player={player} label="▶" />
        <span /><PadKey k="down" player={player} label="▼" /><span />
      </div>
      <ABButtons player={player} />
    </div>
  );
}

/** Floating thumbstick: the base appears where the thumb lands; dead zone, 4- or 8-way, deeper = faster repeat. */
export function Joystick({ compact = false, player = 1 }: { compact?: boolean; player?: number }) {
  const ways = useControls((s) => s.ways);
  const deadzone = useControls((s) => s.deadzone);
  const zone = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: number; ox: number; oy: number; keys: Set<GameKey> } | null>(null);
  const [stick, setStick] = useState<{ ox: number; oy: number; dx: number; dy: number } | null>(null);
  const R = compact ? 44 : 52;

  const update = (dx: number, dy: number) => {
    const d = drag.current;
    const app = current();
    if (!d || !app) return;
    const mag = Math.min(1, Math.hypot(dx, dy) / R);
    const dz = Math.max(0.2, deadzone);
    const want = new Set<GameKey>();
    const depth = mag < dz ? 0 : (mag - dz) / (1 - dz);
    if (mag >= dz) {
      const ang = Math.atan2(dy, dx); // screen coords: +y is down
      if (ways === 4) {
        want.add(Math.abs(dx) >= Math.abs(dy) ? (dx < 0 ? "left" : "right") : dy < 0 ? "up" : "down");
      } else {
        const oct = Math.round(ang / (Math.PI / 4)); // -4..4
        const map: Record<number, GameKey[]> = {
          0: ["right"], 1: ["right", "down"], 2: ["down"], 3: ["down", "left"], 4: ["left"], [-4]: ["left"],
          [-3]: ["left", "up"], [-2]: ["up"], [-1]: ["up", "right"],
        };
        map[oct].forEach((k) => want.add(k));
      }
    }
    want.forEach((k) => (d.keys.has(k) ? setHoldDepth(k, player, depth) : pressKey(k, `js:${d.id}`, app, player, depth)));
    d.keys.forEach((k) => !want.has(k) && releaseKey(k, `js:${d.id}`, player));
    d.keys = want;
  };
  const end = () => {
    const d = drag.current;
    if (!d) return;
    d.keys.forEach((k) => releaseKey(k, `js:${d.id}`, player));
    drag.current = null;
    setStick(null);
  };
  const clamp = (dx: number, dy: number) => {
    const m = Math.hypot(dx, dy);
    return m > R ? [(dx / m) * R, (dy / m) * R] : [dx, dy];
  };

  return (
    <div className={clsx("gamepad flex w-full select-none items-center justify-between gap-3", compact && "gamepad-compact")} aria-label="Joystick">
      <div ref={zone} className="stickzone relative flex-1" style={{ height: compact ? 150 : 176 }}
        onPointerDown={(e) => {
          e.preventDefault();
          if (drag.current) return;
          const r = zone.current!.getBoundingClientRect();
          const ox = e.clientX - r.left;
          const oy = e.clientY - r.top;
          drag.current = { id: e.pointerId, ox, oy, keys: new Set() };
          capture(e);
          setStick({ ox, oy, dx: 0, dy: 0 });
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d || d.id !== e.pointerId) return;
          const r = zone.current!.getBoundingClientRect();
          const [dx, dy] = clamp(e.clientX - r.left - d.ox, e.clientY - r.top - d.oy);
          setStick({ ox: d.ox, oy: d.oy, dx, dy });
          update(dx, dy);
        }}
        onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end} onContextMenu={(e) => e.preventDefault()}>
        {stick ? (
          <>
            <span className="stick-base" style={{ left: stick.ox, top: stick.oy, width: R * 2, height: R * 2 }} />
            <span className="stick-knob" style={{ left: stick.ox + stick.dx, top: stick.oy + stick.dy }} />
          </>
        ) : (
          <span className="pointer-events-none absolute inset-0 grid place-items-center text-center font-mono text-[10px] uppercase tracking-[0.14em] text-ink-4">
            Thumb anywhere here · {ways}-way
          </span>
        )}
      </div>
      <ABButtons player={player} />
    </div>
  );
}

/** Swipe pad: swipe to move (hold at the end of a swipe to keep repeating), tap for A. */
export function SwipePad({ compact = false, player = 1 }: { compact?: boolean; player?: number }) {
  const t = useRef<{ id: number; x: number; y: number; at: number; key: GameKey | null } | null>(null);
  const [dir, setDir] = useState<GameKey | null>(null);
  const TH = 26;
  const src = (id: number) => `sw:${id}`;
  const end = (tap: boolean) => {
    const d = t.current;
    if (!d) return;
    const app = current();
    if (d.key) releaseKey(d.key, src(d.id), player);
    else if (tap && app && performance.now() - d.at < 320) {
      pressKey("a", src(d.id), app, player);
      releaseKey("a", src(d.id), player);
    }
    t.current = null;
    setDir(null);
  };
  const glyph: Record<GameKey, string> = { up: "▲", down: "▼", left: "◀", right: "▶", a: "A", b: "B" };
  return (
    <div className={clsx("gamepad flex w-full select-none items-center justify-between gap-3", compact && "gamepad-compact")} aria-label="Swipe pad">
      <div className="stickzone relative grid flex-1 place-items-center" style={{ height: compact ? 150 : 176 }}
        onPointerDown={(e) => {
          e.preventDefault();
          if (t.current) return;
          t.current = { id: e.pointerId, x: e.clientX, y: e.clientY, at: performance.now(), key: null };
          capture(e);
        }}
        onPointerMove={(e) => {
          const d = t.current;
          const app = current();
          if (!d || d.id !== e.pointerId || !app) return;
          const dx = e.clientX - d.x;
          const dy = e.clientY - d.y;
          if (Math.hypot(dx, dy) < TH) return;
          const k: GameKey = Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? "left" : "right") : dy < 0 ? "up" : "down";
          if (k !== d.key) {
            if (d.key) releaseKey(d.key, src(d.id), player);
            pressKey(k, src(d.id), app, player);
            d.key = k;
            setDir(k);
          }
          d.x = e.clientX; // re-anchor: a new swipe from here changes direction
          d.y = e.clientY;
        }}
        onPointerUp={() => end(true)} onPointerCancel={() => end(false)} onLostPointerCapture={() => end(false)}
        onContextMenu={(e) => e.preventDefault()}>
        <span className={clsx("pointer-events-none font-mono text-[10px] uppercase tracking-[0.14em]", dir ? "text-ember text-[28px]" : "text-ink-4")}>
          {dir ? glyph[dir] : "Swipe to move · tap for A"}
        </span>
      </div>
      <div className="flex flex-col items-center gap-1 pb-2"><PadKey k="b" player={player} label="B" cls="padkey-round" /></div>
    </div>
  );
}

/** Tap zones: hold the left or right half to steer (racers, paddles), A/B below. */
export function TapZones({ compact = false, player = 1 }: { compact?: boolean; player?: number }) {
  const down = usePressedKeys(player);
  const zone = (k: "left" | "right", label: string) => (
    <button className="tapzone" data-down={down.has(k) || undefined} aria-label={k}
      onPointerDown={(e) => {
        e.preventDefault();
        const app = current();
        if (!app) return;
        pressKey(k, `tz:${e.pointerId}`, app, player);
        capture(e);
      }}
      onPointerUp={(e) => releaseKey(k, `tz:${e.pointerId}`, player)}
      onPointerCancel={(e) => releaseKey(k, `tz:${e.pointerId}`, player)}
      onLostPointerCapture={(e) => releaseKey(k, `tz:${e.pointerId}`, player)}
      onContextMenu={(e) => e.preventDefault()}>{label}</button>
  );
  return (
    <div className={clsx("gamepad flex w-full select-none flex-col gap-3", compact && "gamepad-compact")} aria-label="Tap zones">
      <div className="grid grid-cols-2 gap-2" style={{ height: compact ? 120 : 150 }}>
        {zone("left", "◀")}
        {zone("right", "▶")}
      </div>
      <div className="flex justify-center gap-6"><ABButtons player={player} /></div>
    </div>
  );
}

/** The chosen on-screen controller for `player`, with a seat-coloured label when several players share the screen. */
export function TouchControl({ style, player = 1, compact = false, label = false }: {
  style: TouchStyle; player?: number; compact?: boolean; label?: boolean;
}) {
  const C = { dpad: GamePad, joystick: Joystick, swipe: SwipePad, tap: TapZones }[style];
  return (
    <div className="flex flex-col gap-2">
      {label && (
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: SEAT_COLORS[player], boxShadow: `0 0 10px ${SEAT_COLORS[player]}` }} />
          <span className="engrave">Player {player} · on-screen</span>
        </div>
      )}
      <C compact={compact} player={player} />
    </div>
  );
}
