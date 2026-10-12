/**
 * Paper thumbnails: the `<img>` previews of the panel (library tiles and AppRail cards — `.led-preview > img` — the
 * casino's game tiles, the launcher's `.lx-led > img`) drawn through the paper mapping while the paper panel is on
 * (lib/paper.ts). Nothing in those components changes: this module finds the images, decodes them itself (GIFs frame by
 * frame — a tiny decoder below — PNGs once), maps every frame through the cached colour map once, and lays a canvas
 * over each image (`canvas.paper-img`, CSS in index.css / launcher.css). The canvas cross-fades in over the image;
 * the image hides under it once the fade is done, and comes straight back when the paper panel is switched off.
 *
 * Cost: a GIF is fetched (the browser cache usually has it) and decoded once per URL; decoded frames are kept for the
 * 48 most recent URLs. One timer animates every visible canvas (IntersectionObserver), waking only when the next GIF
 * frame is due — no per-vsync loop. Nothing runs at all while the paper panel is off.
 */
import { isPaper, onPaper, paperRgba } from "./paper";

/** The images that are panel previews. */
const SELECTOR = ".led-preview > img, .lx-led > img";

type Decoded = { w: number; h: number; frames: ImageData[]; ends: number[]; total: number };

// ---------------------------------------------------------------- a small GIF decoder (89a / 87a, all disposals)
function lzw(min: number, data: Uint8Array, n: number): Uint8Array {
  const out = new Uint8Array(n);
  const clear = 1 << min, eoi = clear + 1;
  const prefix = new Uint16Array(4096), suffix = new Uint8Array(4096), stack = new Uint8Array(4097);
  for (let i = 0; i < clear; i++) suffix[i] = i;
  let size = min + 1, mask = (1 << size) - 1, next = eoi + 1;
  let old = -1, first = 0, bits = 0, datum = 0, pi = 0, op = 0;
  while (op < n) {
    while (bits < size) {
      if (pi >= data.length) return out;
      datum |= data[pi++] << bits;
      bits += 8;
    }
    let code = datum & mask;
    datum >>>= size;
    bits -= size;
    if (code === clear) {
      size = min + 1;
      mask = (1 << size) - 1;
      next = eoi + 1;
      old = -1;
      continue;
    }
    if (code === eoi) break;
    if (old === -1) {
      if (code >= clear) break; // corrupt
      out[op++] = suffix[code];
      old = first = code;
      continue;
    }
    const inCode = code;
    let sp = 0;
    if (code >= next) {
      stack[sp++] = first;
      code = old;
    }
    while (code > eoi) {
      stack[sp++] = suffix[code];
      code = prefix[code];
    }
    first = suffix[code];
    stack[sp++] = first;
    if (next < 4096) {
      prefix[next] = old;
      suffix[next] = first;
      next++;
      if (next === mask + 1 && size < 12) {
        size++;
        mask = (1 << size) - 1;
      }
    }
    old = inCode;
    while (sp > 0 && op < n) out[op++] = stack[--sp];
  }
  return out;
}

/** Every frame of a GIF, composited (disposal, transparency, interlace) into RGBA, with its end time in ms. */
export function decodeGif(buf: Uint8Array): Omit<Decoded, "frames"> & { frames: Uint8ClampedArray[] } | null {
  const sig = String.fromCharCode(...buf.subarray(0, 6));
  if (sig !== "GIF89a" && sig !== "GIF87a") return null;
  const w = buf[6] | (buf[7] << 8), h = buf[8] | (buf[9] << 8);
  if (!w || !h || w * h > 1 << 20) return null;
  let p = 13;
  let gct: Uint8Array | null = null;
  if (buf[10] & 0x80) {
    const n = 3 << ((buf[10] & 7) + 1);
    gct = buf.subarray(p, p + n);
    p += n;
  }
  const canvas = new Uint8ClampedArray(w * h * 4); // transparent = an unlit LED
  const frames: Uint8ClampedArray[] = [];
  const ends: number[] = [];
  let t = 0, delay = 0, disposal = 0, trans = -1;
  const blocks = () => {
    const parts: Uint8Array[] = [];
    let len = 0;
    while (p < buf.length) {
      const n = buf[p++];
      if (!n) break;
      parts.push(buf.subarray(p, p + n));
      len += n;
      p += n;
    }
    const out = new Uint8Array(len);
    let o = 0;
    for (const s of parts) {
      out.set(s, o);
      o += s.length;
    }
    return out;
  };
  while (p < buf.length) {
    const b = buf[p++];
    if (b === 0x3b) break; // trailer
    if (b === 0x21) {
      const label = buf[p++];
      if (label === 0xf9 && buf[p] >= 4) {
        const f = buf[p + 1];
        disposal = (f >> 2) & 7;
        delay = (buf[p + 2] | (buf[p + 3] << 8)) * 10;
        trans = f & 1 ? buf[p + 4] : -1;
      }
      blocks();
      continue;
    }
    if (b !== 0x2c) break; // unknown block: stop with what we have
    const fx = buf[p] | (buf[p + 1] << 8), fy = buf[p + 2] | (buf[p + 3] << 8);
    const fw = buf[p + 4] | (buf[p + 5] << 8), fh = buf[p + 6] | (buf[p + 7] << 8);
    const flags = buf[p + 8];
    p += 9;
    let ct = gct;
    if (flags & 0x80) {
      const n = 3 << ((flags & 7) + 1);
      ct = buf.subarray(p, p + n);
      p += n;
    }
    const min = buf[p++];
    const idx = lzw(min, blocks(), fw * fh);
    const saved = disposal === 3 ? canvas.slice() : null;
    // interlaced rows come in four passes
    const rows: number[] = [];
    if (flags & 0x40) for (const [s, step] of [[0, 8], [4, 8], [2, 4], [1, 2]]) for (let y = s; y < fh; y += step) rows.push(y);
    else for (let y = 0; y < fh; y++) rows.push(y);
    if (ct) {
      for (let r = 0; r < fh; r++) {
        const y = fy + rows[r];
        if (y >= h) continue;
        for (let x = 0; x < fw; x++) {
          const X = fx + x;
          if (X >= w) continue;
          const c = idx[r * fw + x];
          if (c === trans || c * 3 + 2 >= ct.length) continue;
          const o = (y * w + X) * 4;
          canvas[o] = ct[c * 3];
          canvas[o + 1] = ct[c * 3 + 1];
          canvas[o + 2] = ct[c * 3 + 2];
          canvas[o + 3] = 255;
        }
      }
    }
    frames.push(canvas.slice());
    t += delay >= 20 ? delay : 100; // browsers play 0–10 ms delays at 100 ms
    ends.push(t);
    if (disposal === 2) {
      for (let y = fy; y < Math.min(h, fy + fh); y++) canvas.fill(0, (y * w + fx) * 4, (y * w + Math.min(w, fx + fw)) * 4);
    } else if (saved) canvas.set(saved);
    delay = 0;
    disposal = 0;
    trans = -1;
  }
  return frames.length ? { w, h, frames, ends, total: t } : null;
}

// ---------------------------------------------------------------- decode + map, cached per URL
const cache = new Map<string, Promise<Decoded | null>>();
const KEEP = 48;

async function load(url: string): Promise<Decoded | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const buf = new Uint8Array(await res.arrayBuffer());
    let raw: { w: number; h: number; frames: Uint8ClampedArray[]; ends: number[]; total: number } | null = decodeGif(buf);
    if (!raw) {
      // a still (the launcher's live frame.png?scale=8): the browser decodes it; a whole-number upscale of the 32×32
      // panel is sampled back down to 32×32 (the canvas is shown pixelated anyway — 4 KB instead of 256 KB)
      const bmp = await createImageBitmap(new Blob([buf]));
      const k = bmp.width === bmp.height && bmp.width > 32 && bmp.width % 32 === 0 ? bmp.width / 32 : 1;
      const c = document.createElement("canvas");
      c.width = bmp.width / k;
      c.height = bmp.height / k;
      const g = c.getContext("2d", { willReadFrequently: true })!;
      g.imageSmoothingEnabled = false;
      g.drawImage(bmp, 0, 0, c.width, c.height);
      bmp.close?.();
      raw = { w: c.width, h: c.height, frames: [g.getImageData(0, 0, c.width, c.height).data], ends: [1], total: 0 };
    }
    const frames = raw.frames.map((px) => {
      paperRgba(px);
      return new ImageData(px as Uint8ClampedArray<ArrayBuffer>, raw.w, raw.h);
    });
    return { w: raw.w, h: raw.h, frames, ends: raw.ends, total: raw.total };
  } catch {
    return null; // the plain image stays on screen
  }
}

function decoded(url: string) {
  let d = cache.get(url);
  if (d) cache.delete(url); // re-insert: most recent last
  else d = load(url);
  cache.set(url, d);
  while (cache.size > KEEP) cache.delete(cache.keys().next().value!);
  return d;
}

// ---------------------------------------------------------------- one canvas over each preview image
type Slot = { img: HTMLImageElement; cv: HTMLCanvasElement; url: string; dec: Decoded | null; shown: number; visible: boolean };
const slots = new Map<HTMLImageElement, Slot>();
const epoch = performance.now();
let timer = 0;
let io: IntersectionObserver | null = null;
let mo: MutationObserver | null = null;

const frameAt = (d: Decoded, now: number) => {
  if (d.frames.length < 2 || d.total <= 0) return 0;
  const t = (now - epoch) % d.total;
  let i = 0;
  while (i < d.ends.length - 1 && t >= d.ends[i]) i++;
  return i;
};

function paint(s: Slot, now: number) {
  const d = s.dec;
  if (!d) return;
  const i = frameAt(d, now);
  if (i === s.shown) return;
  s.shown = i;
  if (s.cv.width !== d.w || s.cv.height !== d.h) {
    s.cv.width = d.w;
    s.cv.height = d.h;
  }
  s.cv.getContext("2d")!.putImageData(d.frames[i], 0, 0);
}

/** Wake when the next frame of any visible animated canvas is due (no per-vsync loop). */
function schedule() {
  clearTimeout(timer);
  timer = 0;
  if (!isPaper() || document.hidden) return;
  const now = performance.now();
  let soonest = Infinity;
  for (const s of slots.values()) {
    if (!s.img.isConnected) {
      drop(s);
      continue;
    }
    if (!s.visible || !s.dec || s.dec.frames.length < 2) continue;
    paint(s, now);
    const d = s.dec;
    const t = (now - epoch) % d.total;
    soonest = Math.min(soonest, d.ends[s.shown] - t);
  }
  if (soonest < Infinity) timer = window.setTimeout(schedule, Math.max(16, soonest + 1));
}

function drop(s: Slot) {
  io?.unobserve(s.cv);
  s.cv.remove();
  slots.delete(s.img);
}

function attach(img: HTMLImageElement) {
  const url = img.currentSrc || img.src;
  if (!url) return;
  let s = slots.get(img);
  if (s && s.url === url) return;
  if (!s) {
    const cv = document.createElement("canvas");
    cv.className = "paper-img";
    cv.setAttribute("aria-hidden", "true");
    img.after(cv);
    s = { img, cv, url, dec: null, shown: -1, visible: true };
    slots.set(img, s);
    io?.observe(cv);
  }
  const slot = s;
  slot.url = url;
  // a new picture for the same image (the launcher's live frame): the old one stays up until the new one is ready
  decoded(url).then((d) => {
    if (slot.url !== url || !slots.has(img)) return;
    if (!d) {
      // can't map it: show the plain image
      slot.dec = null;
      delete slot.cv.dataset.ready;
      delete img.dataset.paper;
      return;
    }
    slot.dec = d;
    slot.shown = -1;
    paint(slot, performance.now());
    slot.cv.dataset.ready = "";
    img.dataset.paper = "ready"; // CSS hides the image under the canvas once the fade is done
    schedule();
  });
}

function scan(root: ParentNode) {
  if (root instanceof HTMLImageElement) {
    if (root.matches(SELECTOR)) attach(root);
    return;
  }
  root.querySelectorAll?.<HTMLImageElement>(SELECTOR).forEach(attach);
}

function start() {
  io ??= new IntersectionObserver((es) => {
    for (const e of es) for (const s of slots.values()) if (s.cv === e.target) s.visible = e.isIntersecting;
    schedule();
  });
  for (const s of slots.values()) io.observe(s.cv);
  mo = new MutationObserver((ms) => {
    for (const m of ms) {
      if (m.type === "attributes") {
        if (m.target instanceof HTMLImageElement && m.target.matches(SELECTOR)) attach(m.target);
        continue;
      }
      m.addedNodes.forEach((n) => n.nodeType === 1 && scan(n as Element));
      m.removedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        for (const s of [...slots.values()]) if (!s.img.isConnected) drop(s);
      });
    }
  });
  mo.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
  scan(document);
  schedule();
}

function stop() {
  mo?.disconnect();
  mo = null;
  clearTimeout(timer);
  timer = 0;
  // the canvases stay (CSS fades them out over the images); their frames are kept for a quick switch back
}

let installed = false;
/** Start following the preview images (idempotent). Call once at startup, after `installPaper()`. */
export function installPaperImages() {
  if (installed || typeof document === "undefined" || !document.body) return;
  installed = true;
  const sync = () => (isPaper() ? (mo ? schedule() : start()) : stop());
  onPaper(sync);
  document.addEventListener("visibilitychange", schedule);
  sync();
}
