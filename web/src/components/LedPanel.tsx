import { useEffect, useMemo, useRef, useState } from "react";
import { calibrator, toCalib } from "../lib/calib";
import { LOOK_HINT, LOOK_LABEL, LOOKS, matchesPanel, type PanelLook, useLook } from "../lib/look";
import { PAPER, crossFade, paperOf, usePaper } from "../lib/paper";
import { lastFrame, onFrame, pushFrame, useStore } from "../lib/store";
import { paint } from "../lib/ws";

type Props = {
  /** CSS size in px of the square panel; defaults to filling its container. */
  size?: number;
  paintable?: boolean;
  glow?: boolean;
  className?: string;
  /**
   * Pixel-perfect: every LED is a whole number of device pixels (the canvas snaps down to a multiple of 32),
   * and bloom is blurred at low resolution then upscaled — cheap enough for a very large Play-mode view.
   */
  crisp?: boolean;
  /** Force a look (e.g. the LED-accurate view); otherwise the viewer's remembered choice is used. */
  look?: PanelLook;
  /** Show the small Glow / Pixel / LED switch on hover (default: true). */
  lookSwitch?: boolean;
  /**
   * Never apply the panel colour calibration here (the calibration wizard's screen reference). Otherwise the
   * viewer's colour-match choice (lib/look.ts) decides whether the preview shows what the LEDs are sent.
   */
  raw?: boolean;
  /** Always draw the black LED device, even when light mode would draw the paper panel (a dark 3D scene). */
  device?: boolean;
};

const N = 32;

function hex(r: number, g: number, b: number) {
  return "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
}

/**
 * Draws the live frame as a physical LED matrix: recessed off-LEDs, lit LEDs
 * with a hot core, and bloom (the 32x32 frame upscaled + blurred, added on top).
 * In light mode it draws the paper panel instead (lib/paper.ts): a porcelain panel, every colour re-mapped to read on
 * it, and a halo that darkens (multiply) where the dark panel's bloom brightens. `raw` / `device` keep the dark device.
 */
export function LedPanel({
  size,
  paintable = false,
  glow = true,
  className,
  crisp = false,
  look: forced,
  lookSwitch = true,
  raw = false,
  device = false,
}: Props) {
  const paper = usePaper() && !raw && !device;
  const saved = useLook((s) => s.look);
  const setLook = useLook((s) => s.setLook);
  const bloomAmt = useLook((s) => s.bloom); // "Sharpness": 0 = crisp, 0.5 = classic glow, 1 = soft
  const look = forced ?? saved;
  const match = useLook((s) => s.match);
  const calibRaw = useStore((s) => s.state?.settings.calibration);
  const calibKey = JSON.stringify(calibRaw ?? null);
  // the same maths as the engine (lib/calib.ts): the preview shows what the panel is actually sent
  const toPanel = useMemo(
    () => (raw || !matchesPanel(look, match) ? null : calibrator(toCalib(calibRaw))),
    [raw, look, match, calibKey],
  );
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const fade = useRef<HTMLCanvasElement>(null); // the old picture, fading out over the new one (theme switch)
  const paperWas = useRef<boolean | null>(null);
  const tiny = useRef<HTMLCanvasElement | null>(null);
  const [cssPx, setCssPx] = useState(0);
  const [px, setPx] = useState(size ?? 0);
  const [hover, setHover] = useState<[number, number] | null>(null);
  const hoverRef = useRef<[number, number] | null>(null);
  hoverRef.current = hover;
  const drawRef = useRef<((rgb: Uint8Array) => void) | null>(null);
  useEffect(() => drawRef.current?.(lastFrame), [hover]);

  // track container size
  useEffect(() => {
    if (size) return setPx(size);
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setPx(Math.floor(Math.min(e.contentRect.width, e.contentRect.height))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [size]);

  // draw each new frame — see "Performance rules" in docs/STUDIO_UI.md:
  //  - at most one draw per display refresh (frames that arrive within one vsync collapse to the newest), except the
  //    crisp Play-mode view, which draws straight from the socket callback for the lowest latency;
  //  - a frame identical to the one on screen is skipped (the engine re-sends unchanged frames on some apps);
  //  - nothing is drawn while the canvas is off screen or the page is hidden; the newest frame is drawn on return;
  //  - the LED look's unlit LEDs and housing are a cached layer: a frame only draws the lit LEDs.
  useEffect(() => {
    const canvas = cv.current;
    if (!canvas || !px) return;
    // light <-> dark: the old picture cross-fades into the new one (drawn at once below), not a cut
    if (paperWas.current !== null && paperWas.current !== paper) crossFade(canvas, fade.current);
    paperWas.current = paper;
    const sharp = crisp || look !== "led"; // square-pixel looks: every cell is a whole number of device pixels
    const dpr = sharp ? Math.min(3, window.devicePixelRatio || 1) : Math.min(2, window.devicePixelRatio || 1);
    canvas.width = canvas.height = sharp ? Math.max(N, Math.floor((px * dpr) / N) * N) : Math.round(px * dpr);
    setCssPx(sharp ? canvas.width / dpr : px);
    const ctx = canvas.getContext("2d", { alpha: false })!; // every look paints the whole canvas: no blending needed
    if (!tiny.current) {
      tiny.current = document.createElement("canvas");
      tiny.current.width = tiny.current.height = N;
    }
    const tctx = tiny.current.getContext("2d")!;
    const img = tctx.createImageData(N, N);
    const W = canvas.width;
    const cell = W / N;
    const inset = crisp ? Math.max(1, Math.round(cell * 0.13)) : cell * 0.13;
    const led = cell - inset * 2;
    const rad = led * 0.24;
    // crisp mode: bloom is blurred on a 4-px-per-LED canvas, then upscaled (a big blur at full size costs ms)
    const BS = N * 4;
    let bloom: CanvasRenderingContext2D | null = null;
    const glowK = bloomAmt / 0.5; // multiplies the glow look's bloom passes
    // the glow is always blurred small (4 px per LED) and scaled up: a big blur at full size costs milliseconds a frame
    if (glow && (crisp || look !== "pixel")) {
      const b = document.createElement("canvas");
      b.width = b.height = BS;
      bloom = b.getContext("2d")!;
    }

    // the 32×32 frame into the tiny canvas. Paper: the paper colours, unlit pixels transparent (the porcelain shows)
    const fillTiny = (rgb: Uint8Array) => {
      for (let i = 0; i < N * N; i++) {
        const r = rgb[i * 3], g = rgb[i * 3 + 1], b = rgb[i * 3 + 2];
        if (paper) {
          const p = paperOf((r << 16) | (g << 8) | b);
          img.data[i * 4] = p >> 16;
          img.data[i * 4 + 1] = (p >> 8) & 255;
          img.data[i * 4 + 2] = p & 255;
          img.data[i * 4 + 3] = Math.max(r, g, b) < 3 ? 0 : 255;
        } else {
          img.data[i * 4] = r;
          img.data[i * 4 + 1] = g;
          img.data[i * 4 + 2] = b;
          img.data[i * 4 + 3] = 255;
        }
      }
      tctx.putImageData(img, 0, 0);
    };
    // paper glow: the coloured frame, blurred small and multiplied in — a soft halo that darkens instead of blooming
    const halo = (passes: readonly (readonly [number, number])[], k: number) => {
      if (!bloom || k <= 0) return;
      ctx.imageSmoothingEnabled = true;
      ctx.globalCompositeOperation = "multiply";
      for (const [r, a] of passes) {
        bloom.globalCompositeOperation = "copy";
        bloom.filter = `blur(${4 * r}px)`;
        bloom.imageSmoothingEnabled = true;
        bloom.drawImage(tiny.current!, 0, 0, BS, BS);
        ctx.globalAlpha = Math.min(1, a * k);
        ctx.drawImage(bloom.canvas, 0, 0, W, W);
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
    };

    const drawPixels = (rgb: Uint8Array) => {
      // square pixels: the 32×32 frame scaled up with nearest-neighbour — crisp on any screen
      fillTiny(rgb);
      ctx.globalCompositeOperation = "source-over";
      ctx.filter = "none";
      ctx.globalAlpha = 1;
      if (paper) {
        ctx.fillStyle = PAPER.ground;
        ctx.fillRect(0, 0, W, W);
        if (look === "glow" && glow) halo([[0.7, 0.22], [2.2, 0.16]], glowK);
      }
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(tiny.current!, 0, 0, W, W);
      if (!paper && look === "glow" && glow && bloom && glowK > 0) {
        ctx.imageSmoothingEnabled = true;
        ctx.globalCompositeOperation = "lighter";
        for (const [r, a] of [[0.8, 0.28], [2.4, 0.2]] as const) {
          bloom.globalCompositeOperation = "copy";
          bloom.filter = `blur(${4 * r}px)`;
          bloom.imageSmoothingEnabled = true;
          bloom.drawImage(tiny.current!, 0, 0, BS, BS);
          ctx.globalAlpha = Math.min(1, a * glowK);
          ctx.drawImage(bloom.canvas, 0, 0, W, W);
        }
      }
    };

    // LED look: the housing and every unlit LED, drawn once per size (a frame then only draws the lit ones)
    let base: HTMLCanvasElement | null = null;
    if (look === "led") {
      base = document.createElement("canvas");
      base.width = base.height = W;
      const b = base.getContext("2d")!;
      b.fillStyle = paper ? PAPER.housing : "#060608";
      b.fillRect(0, 0, W, W);
      const dots = () => {
        b.beginPath();
        for (let i = 0; i < N * N; i++) b.roundRect((i % N) * cell + inset, Math.floor(i / N) * cell + inset, led, led, rad);
      };
      if (paper) {
        // porcelain: each unlit LED a shallow dimple — a hairline of shade above, the ground colour inside
        b.save();
        b.translate(0, -Math.max(0.5, cell * 0.04));
        b.fillStyle = "rgba(64, 48, 24, 0.10)";
        dots();
        b.fill();
        b.restore();
        b.fillStyle = PAPER.ground;
      } else b.fillStyle = "#15151b";
      dots();
      b.fill();
    }

    const shown = new Uint8Array(N * N * 3);
    const drawn = new Uint8Array(N * N * 3); // the frame on screen (to skip identical ones)
    let hasDrawn = false;
    const draw = (src: Uint8Array, force = false) => {
      if (!force && hasDrawn && src.length === drawn.length) {
        let same = true;
        for (let i = 0; i < src.length; i++) if (src[i] !== drawn[i]) { same = false; break; }
        if (same) return;
      }
      if (src.length === drawn.length) drawn.set(src);
      hasDrawn = true;
      const rgb = toPanel ? toPanel(src, shown) : src;
      if (look !== "led") {
        drawPixels(rgb);
        drawHover();
        return;
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.filter = "none";
      ctx.globalAlpha = 1;
      ctx.drawImage(base!, 0, 0);
      if (paper) {
        // ink dots in a light housing: the halo first (under the dots, so they stay crisp), then each lit LED
        fillTiny(rgb);
        if (glow) halo([[0.9, 0.2], [2.6, 0.1]], 1);
        for (let i = 0; i < N * N; i++) {
          if (!img.data[i * 4 + 3]) continue; // unlit: the cached housing
          const x = (i % N) * cell + inset;
          const y = Math.floor(i / N) * cell + inset;
          ctx.fillStyle = `rgb(${img.data[i * 4]},${img.data[i * 4 + 1]},${img.data[i * 4 + 2]})`;
          ctx.beginPath();
          ctx.roundRect(x, y, led, led, rad);
          ctx.fill();
        }
        drawHover();
        return;
      }
      for (let i = 0; i < N * N; i++) {
        const r = rgb[i * 3], g = rgb[i * 3 + 1], b = rgb[i * 3 + 2];
        img.data[i * 4] = r;
        img.data[i * 4 + 1] = g;
        img.data[i * 4 + 2] = b;
        img.data[i * 4 + 3] = 255;
        const lum = Math.max(r, g, b);
        if (lum < 6) continue; // unlit: already in the cached layer
        const x = (i % N) * cell + inset;
        const y = Math.floor(i / N) * cell + inset;
        ctx.beginPath();
        ctx.roundRect(x, y, led, led, rad);
        {
          // lift very dim LEDs slightly so they stay visible on a monitor, like they are in a room
          const k = lum < 40 ? 1 + (40 - lum) / 60 : 1;
          ctx.fillStyle = `rgb(${Math.min(255, r * k)},${Math.min(255, g * k)},${Math.min(255, b * k)})`;
          ctx.fill();
          if (lum > 90) {
            ctx.fillStyle = `rgba(255,255,255,${(lum / 255) * 0.22})`;
            const c = led * 0.3;
            ctx.beginPath();
            ctx.roundRect(x + (led - c) / 2, y + (led - c) / 2, c, c, c / 2);
            ctx.fill();
          }
        }
      }
      if (glow && bloom) {
        tctx.putImageData(img, 0, 0);
        ctx.imageSmoothingEnabled = true;
        ctx.globalCompositeOperation = "lighter";
        for (const [r, a] of [[0.9, 0.55], [2.6, 0.3]] as const) {
          bloom.globalCompositeOperation = "copy";
          bloom.filter = `blur(${4 * r}px)`;
          bloom.imageSmoothingEnabled = true;
          bloom.drawImage(tiny.current!, 0, 0, BS, BS);
          ctx.globalAlpha = a;
          ctx.drawImage(bloom.canvas, 0, 0, W, W);
        }
      } else if (glow) {
        tctx.putImageData(img, 0, 0);
        ctx.imageSmoothingEnabled = true;
        ctx.globalCompositeOperation = "lighter";
        ctx.filter = `blur(${cell * 0.9}px)`;
        ctx.globalAlpha = 0.55;
        ctx.drawImage(tiny.current!, 0, 0, W, W);
        ctx.filter = `blur(${cell * 2.6}px)`;
        ctx.globalAlpha = 0.3;
        ctx.drawImage(tiny.current!, 0, 0, W, W);
      }
      drawHover();
    };
    function drawHover() {
      const h = hoverRef.current;
      if (paintable && h) {
        ctx.globalCompositeOperation = "source-over";
        ctx.filter = "none";
        ctx.globalAlpha = 1;
        ctx.strokeStyle = paper ? "rgba(28,26,34,.8)" : "rgba(255,255,255,.85)";
        ctx.lineWidth = Math.max(1, dpr);
        ctx.strokeRect(h[0] * cell + 0.5, h[1] * cell + 0.5, cell - 1, cell - 1);
      }
    }
    // schedule: newest frame wins, one draw per vsync, none while off screen / hidden
    let pending: Uint8Array | null = null;
    let raf = 0;
    let onScreen = true;
    const flushDraw = () => {
      raf = 0;
      const f = pending;
      pending = null;
      if (f) draw(f);
    };
    const kick = () => {
      if (!raf && pending && onScreen && !document.hidden) raf = requestAnimationFrame(flushDraw);
    };
    const schedule = (src: Uint8Array) => {
      if (crisp && onScreen && !document.hidden) return draw(src); // Play mode: straight from the socket callback
      pending = src;
      kick();
    };
    const io = new IntersectionObserver(([e]) => {
      onScreen = e.isIntersecting;
      kick();
    });
    io.observe(canvas);
    document.addEventListener("visibilitychange", kick);
    drawRef.current = (f) => draw(f, true);
    draw(lastFrame, true); // the picture at once (a new look or theme shouldn't wait for the next frame)
    const off = onFrame(schedule);
    return () => {
      off();
      io.disconnect();
      document.removeEventListener("visibilitychange", kick);
      cancelAnimationFrame(raf);
    };
  }, [px, glow, paintable, crisp, look, bloomAmt, toPanel, paper]);

  // ------------------------------------------------------------- painting
  const drawing = useRef(false);
  const pending = useRef<Map<string, [number, number, string]>>(new Map());
  const raf = useRef(0);

  const cellAt = (e: React.PointerEvent): [number, number] | null => {
    const r = cv.current!.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * N);
    const y = Math.floor(((e.clientY - r.top) / r.height) * N);
    return x >= 0 && y >= 0 && x < N && y < N ? [x, y] : null;
  };

  const flush = () => {
    raf.current = 0;
    paint([...pending.current.values()]);
    pending.current.clear();
  };
  const queue = (x: number, y: number, c: string) => {
    pending.current.set(`${x},${y}`, [x, y, c]);
    // optimistic local echo so strokes feel instant
    const i = (y * N + x) * 3;
    const f = lastFrame.slice();
    f[i] = parseInt(c.slice(1, 3), 16);
    f[i + 1] = parseInt(c.slice(3, 5), 16);
    f[i + 2] = parseInt(c.slice(5, 7), 16);
    pushFrame(f);
    if (!raf.current) raf.current = requestAnimationFrame(flush);
  };

  const apply = (p: [number, number]) => {
    const { tool, brush, set, recent } = useStore.getState();
    const [x, y] = p;
    if (tool === "picker") {
      const i = (y * N + x) * 3;
      const c = hex(lastFrame[i], lastFrame[i + 1], lastFrame[i + 2]);
      set({ brush: c, tool: "pencil", recent: [c, ...recent.filter((r) => r !== c)].slice(0, 8) });
      return;
    }
    if (tool === "fill") {
      floodFill(x, y, brush).forEach(([fx, fy]) => pending.current.set(`${fx},${fy}`, [fx, fy, brush]));
      flush();
      return;
    }
    queue(x, y, tool === "eraser" ? "#000000" : brush);
  };

  // ------------------------------------------------------------- undo/redo & hotkeys
  const undoStack = useRef<Uint8Array[]>([]);
  const redoStack = useRef<Uint8Array[]>([]);

  useEffect(() => {
    if (!paintable) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) return;

      const key = e.key.toLowerCase();
      const { set } = useStore.getState();

      if (e.ctrlKey || e.metaKey) {
        if (key === "z") {
          e.preventDefault();
          if (undoStack.current.length > 0) {
            const prev = undoStack.current.pop()!;
            redoStack.current.push(lastFrame.slice());
            pushFrame(prev);
            const pixels: [number, number, string][] = [];
            for (let i = 0; i < N * N; i++) {
              pixels.push([i % N, Math.floor(i / N), hex(prev[i * 3], prev[i * 3 + 1], prev[i * 3 + 2])]);
            }
            paint(pixels);
          }
          return;
        }
        if (key === "y") {
          e.preventDefault();
          if (redoStack.current.length > 0) {
            const next = redoStack.current.pop()!;
            undoStack.current.push(lastFrame.slice());
            pushFrame(next);
            const pixels: [number, number, string][] = [];
            for (let i = 0; i < N * N; i++) {
              pixels.push([i % N, Math.floor(i / N), hex(next[i * 3], next[i * 3 + 1], next[i * 3 + 2])]);
            }
            paint(pixels);
          }
          return;
        }
      }

      if (key === "p") set({ tool: "pencil" });
      else if (key === "b") set({ tool: "fill" });
      else if (key === "e") set({ tool: "eraser" });
      else if (key === "v") set({ tool: "picker" });
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paintable]);

  const events = paintable
    ? {
        onPointerDown: (e: React.PointerEvent) => {
          const p = cellAt(e);
          if (!p) return;
          (e.target as Element).setPointerCapture(e.pointerId);
          drawing.current = true;
          // snapshot before stroke
          undoStack.current.push(lastFrame.slice());
          if (undoStack.current.length > 30) undoStack.current.shift();
          redoStack.current = [];
          apply(p);
        },
        onPointerMove: (e: React.PointerEvent) => {
          const p = cellAt(e);
          if (!p || (hover && p[0] === hover[0] && p[1] === hover[1])) return;
          setHover(p);
          if (drawing.current && useStore.getState().tool !== "fill") apply(p);
        },
        onPointerUp: () => (drawing.current = false),
        onPointerLeave: () => {
          drawing.current = false;
          setHover(null);
        },
      }
    : {};

  return (
    <div ref={wrap} className={`group/panel relative ${className ?? ""}`} style={size ? { width: size, height: size } : { width: "100%", height: "100%" }}>
      <canvas
        ref={cv}
        {...events}
        style={{ width: cssPx || px, height: cssPx || px, display: "block", margin: crisp || look !== "led" ? "0 auto" : undefined, cursor: paintable ? "crosshair" : "default", touchAction: "none" }}
        aria-label="Live LED panel preview"
        role="img"
      />
      {/* the previous picture while light <-> dark cross-fades (lib/paper.ts crossFade places and fades it) */}
      <canvas ref={fade} aria-hidden width={0} height={0} className="pointer-events-none absolute left-0 top-0 h-0 w-0 opacity-0" />
      {lookSwitch && !forced && (px || 0) >= 160 && (
        <div className="absolute bottom-2 left-1/2 z-10 flex -translate-x-1/2 gap-0.5 lg-badge rounded-full p-0.5 opacity-0 transition group-hover/panel:opacity-100 focus-within:opacity-100"
          role="radiogroup" aria-label="Preview style">
          {LOOKS.map((l) => (
            <button key={l} role="radio" aria-checked={look === l} title={LOOK_HINT[l]}
              onClick={(e) => { e.stopPropagation(); setLook(l); }}
              className={`rounded-full px-2.5 py-1 font-mono text-[9.5px] uppercase tracking-wider transition ${look === l ? "glass-lens text-ink-1" : "text-ink-3 hover:text-ink-1"}`}>
              {LOOK_LABEL[l]}
            </button>
          ))}
        </div>
      )}
      {paintable && hover && (
        <div className="pointer-events-none absolute right-3 top-3 font-mono text-[10px] tracking-widest text-ink-3">
          X{String(hover[0]).padStart(2, "0")} Y{String(hover[1]).padStart(2, "0")}
        </div>
      )}
    </div>
  );
}

function floodFill(x: number, y: number, color: string): [number, number][] {
  const at = (px: number, py: number) => {
    const i = (py * N + px) * 3;
    return (lastFrame[i] << 16) | (lastFrame[i + 1] << 8) | lastFrame[i + 2];
  };
  const target = at(x, y);
  if (target === parseInt(color.slice(1), 16)) return [];
  const out: [number, number][] = [];
  const seen = new Uint8Array(N * N);
  const stack: [number, number][] = [[x, y]];
  while (stack.length) {
    const [cx, cy] = stack.pop()!;
    if (cx < 0 || cy < 0 || cx >= N || cy >= N || seen[cy * N + cx] || at(cx, cy) !== target) continue;
    seen[cy * N + cx] = 1;
    out.push([cx, cy]);
    stack.push([cx + 1, cy], [cx - 1, cy], [cx, cy + 1], [cx, cy - 1]);
  }
  return out;
}
