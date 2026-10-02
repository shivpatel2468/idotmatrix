import { useEffect, useMemo, useRef, useState } from "react";
import { calibrator, toCalib } from "../lib/calib";
import { LOOK_HINT, LOOK_LABEL, LOOKS, matchesPanel, type PanelLook, useLook } from "../lib/look";
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
};

const N = 32;

function hex(r: number, g: number, b: number) {
  return "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
}

/**
 * Draws the live frame as a physical LED matrix: recessed off-LEDs, lit LEDs
 * with a hot core, and bloom (the 32x32 frame upscaled + blurred, added on top).
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
}: Props) {
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

  // draw on every frame
  useEffect(() => {
    const canvas = cv.current;
    if (!canvas || !px) return;
    const sharp = crisp || look !== "led"; // square-pixel looks: every cell is a whole number of device pixels
    const dpr = sharp ? Math.min(3, window.devicePixelRatio || 1) : Math.min(2, window.devicePixelRatio || 1);
    canvas.width = canvas.height = sharp ? Math.max(N, Math.floor((px * dpr) / N) * N) : Math.round(px * dpr);
    setCssPx(sharp ? canvas.width / dpr : px);
    const ctx = canvas.getContext("2d")!;
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
    if ((crisp || look === "glow") && glow) {
      const b = document.createElement("canvas");
      b.width = b.height = BS;
      bloom = b.getContext("2d")!;
    }

    const drawPixels = (rgb: Uint8Array) => {
      // square pixels: the 32×32 frame scaled up with nearest-neighbour — crisp on any screen
      for (let i = 0; i < N * N; i++) {
        img.data[i * 4] = rgb[i * 3];
        img.data[i * 4 + 1] = rgb[i * 3 + 1];
        img.data[i * 4 + 2] = rgb[i * 3 + 2];
        img.data[i * 4 + 3] = 255;
      }
      tctx.putImageData(img, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      ctx.filter = "none";
      ctx.globalAlpha = 1;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(tiny.current!, 0, 0, W, W);
      if (look === "glow" && glow && bloom && glowK > 0) {
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

    const shown = new Uint8Array(N * N * 3);
    const draw = (src: Uint8Array) => {
      const rgb = toPanel ? toPanel(src, shown) : src;
      if (look !== "led") {
        drawPixels(rgb);
        drawHover();
        return;
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.filter = "none";
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#060608";
      ctx.fillRect(0, 0, W, W);
      for (let i = 0; i < N * N; i++) {
        const r = rgb[i * 3], g = rgb[i * 3 + 1], b = rgb[i * 3 + 2];
        img.data[i * 4] = r;
        img.data[i * 4 + 1] = g;
        img.data[i * 4 + 2] = b;
        img.data[i * 4 + 3] = 255;
        const x = (i % N) * cell + inset;
        const y = Math.floor(i / N) * cell + inset;
        const lum = Math.max(r, g, b);
        ctx.beginPath();
        ctx.roundRect(x, y, led, led, rad);
        if (lum < 6) {
          ctx.fillStyle = "#15151b";
          ctx.fill();
        } else {
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
        ctx.strokeStyle = "rgba(255,255,255,.85)";
        ctx.lineWidth = Math.max(1, dpr);
        ctx.strokeRect(h[0] * cell + 0.5, h[1] * cell + 0.5, cell - 1, cell - 1);
      }
    }
    drawRef.current = draw;
    return onFrame(draw);
  }, [px, glow, paintable, crisp, look, bloomAmt, toPanel]);

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
      {lookSwitch && !forced && (px || 0) >= 160 && (
        <div className="absolute bottom-2 left-1/2 z-10 flex -translate-x-1/2 gap-0.5 rounded-full border border-white/10 bg-black/70 p-0.5 opacity-0 backdrop-blur transition group-hover/panel:opacity-100 focus-within:opacity-100"
          role="radiogroup" aria-label="Preview style">
          {LOOKS.map((l) => (
            <button key={l} role="radio" aria-checked={look === l} title={LOOK_HINT[l]}
              onClick={(e) => { e.stopPropagation(); setLook(l); }}
              className={`rounded-full px-2.5 py-1 font-mono text-[9.5px] uppercase tracking-wider transition ${look === l ? "bg-white/15 text-white" : "text-white/55 hover:text-white"}`}>
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
