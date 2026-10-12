"""Now Playing drawing kit: the procedural layouts (cassette, VU meters, CD, radio dial, mosaic, waveform),
art styling (pixelated / posterised / dithered), generic source glyphs, song-change transitions and idle screens.

Pure functions over numpy arrays and `Frame` primitives. Anything per-track (styled art, mosaic tiles) is computed
once by the caller; these functions only compose. Nothing here does I/O.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance

from ..gfx import Frame, mix, scale, to_rgb
from ..gfx.font import fit, measure

RGB = tuple[int, int, int]

_Y, _X = np.mgrid[0:32, 0:32].astype(np.float32) + 0.5
_YI, _XI = np.mgrid[0:32, 0:32]
_R = np.hypot(_X - 16.0, _Y - 16.0)
_TH = np.arctan2(_Y - 16.0, _X - 16.0)


def bilinear(src: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    h, w = src.shape[:2]
    sx = np.clip(sx, 0, w - 1.001)
    sy = np.clip(sy, 0, h - 1.001)
    x0, y0 = sx.astype(np.int32), sy.astype(np.int32)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    a, b = src[y0, x0], src[y0, x0 + 1]
    c, d = src[y0 + 1, x0], src[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_io(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def rainbow(h: np.ndarray) -> np.ndarray:
    """Cheap smooth hue wheel (h in turns) -> RGB 0..1, shape (..., 3)."""
    return 0.5 + 0.5 * np.cos(2 * np.pi * (h[..., None] + np.array([0.0, 2 / 3, 1 / 3], np.float32)))


# ------------------------------------------------------------------------------------------- art styling
BAYER4 = (
    np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) + 0.5
) / 16 - 0.5


def adjust(img: Image.Image, contrast: float = 1.0, saturation: float = 1.0) -> Image.Image:
    if abs(contrast - 1.0) > 1e-3:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if abs(saturation - 1.0) > 1e-3:
        img = ImageEnhance.Color(img).enhance(saturation)
    return img


def _palette(img: Image.Image, n: int) -> np.ndarray:
    q = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.array(q.getpalette()[: n * 3], np.float32).reshape(-1, 3)  # type: ignore[index]
    return pal[: max(2, len(pal))]


def _nearest(px: np.ndarray, pal: np.ndarray) -> np.ndarray:
    d = ((px[:, :, None, :] - pal[None, None]) ** 2).sum(-1)
    return np.argmin(d, axis=-1)


def reduce_colors(img: Image.Image, n: int, dither: str = "none") -> Image.Image:
    """`img` reduced to its own `n` colours: flat (posterised), ordered Bayer 4×4 or error diffusion."""
    n = max(2, min(16, int(n)))
    pal = _palette(img, n)
    if dither == "diffusion":
        p = Image.new("P", (1, 1))
        flat = [int(v) for v in pal.reshape(-1)]
        p.putpalette(flat + flat[:3] * (256 - len(pal)))
        return img.quantize(palette=p, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
    px = np.asarray(img, np.float32)
    if dither == "bayer":
        d = np.sqrt(((pal[:, None] - pal[None]) ** 2).sum(-1))
        d[d == 0] = np.inf
        spread = float(np.median(d.min(axis=1))) if len(pal) > 1 else 64.0
        h, w = px.shape[:2]
        th = np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
        px = px + th[..., None] * min(spread, 96.0)
    return Image.fromarray(pal[_nearest(px, pal)].astype(np.uint8))


def stylise(img: Image.Image, size: int, style: str, colors: int = 6, dither: str = "bayer") -> Image.Image:
    """The cover at `size`² in an art style: smooth, pixelated (chunky blocks), posterised or dithered."""
    if style == "pixelated":
        n = max(4, size // 2) if size <= 16 else 16
        return img.resize((n, n), Image.Resampling.BOX).resize((size, size), Image.Resampling.NEAREST)
    base = img.resize((size, size), Image.Resampling.LANCZOS)
    if style == "posterised":
        return reduce_colors(base, colors, "none")
    if style == "dithered":
        return reduce_colors(base, colors, dither if dither != "none" else "bayer")
    return base


def mosaic_tiles(img: Image.Image, grid: int, colors: int, dither: str) -> Image.Image:
    """The cover as `grid`² tiles in `colors` colours (dithered across tiles if asked)."""
    small = img.resize((grid, grid), Image.Resampling.BOX)
    return reduce_colors(small, colors, dither)


# ------------------------------------------------------------------------------------------- source glyphs
_GLYPHS = {
    "note": (".####", ".#..#", ".#..#", "##.##", "##.##"),
    "web": (".###.", "#.#.#", "#####", "#.#.#", ".###."),
    "disc": (".###.", "#...#", "#.#.#", "#...#", ".###."),
}
GLYPHS = {k: np.array([[c == "#" for c in row] for row in v], bool) for k, v in _GLYPHS.items()}
_BROWSERS = {"chrome", "edge", "firefox", "brave", "opera", "arc", "safari"}
_LOCAL = {"vlc", "foobar", "media_player", "itunes"}


def source_kind(source: str) -> str:
    """Generic glyph for a source key: music service -> note, browser -> globe, local player -> disc.

    Deliberately no brand marks: the panel never draws a trademark logo."""
    if source in _BROWSERS:
        return "web"
    if source in _LOCAL:
        return "disc"
    return "note"


def draw_glyph(f: Frame, kind: str, x: int, y: int, color: Any) -> None:
    m = GLYPHS.get(kind, GLYPHS["note"])
    c = to_rgb(color)
    for yy, xx in zip(*np.nonzero(m), strict=True):
        f.set(x + int(xx), y + int(yy), c)


# ------------------------------------------------------------------------------------------- big text
@lru_cache(maxsize=512)
def scaled_mask(mask_key: tuple[str, str], k: int) -> np.ndarray:
    """Bitmap of text in `font`, each font pixel drawn as a k×k block (still 1-bit: no smoothing)."""
    from .nowplaying import text_mask

    m = text_mask(*mask_key)
    if k > 1:
        m = np.repeat(np.repeat(m, k, axis=0), k, axis=1)
    m.setflags(write=False)
    return m


def bounce_offset(travel: int, t: float, speed: float, hold: float = 1.2) -> int:
    """Ping-pong scroll: hold, scroll to the end, hold, scroll back. Whole pixels."""
    if travel <= 0:
        return 0
    run = travel / max(1.0, speed)
    ph = t % (2 * hold + 2 * run)
    if ph < hold:
        return 0
    if ph < hold + run:
        return min(travel, int((ph - hold) * speed))
    if ph < 2 * hold + run:
        return travel
    return max(0, travel - int((ph - 2 * hold - run) * speed))


@lru_cache(maxsize=512)
def pages(text: str, font: str, w: int) -> tuple[str, ...]:
    """Greedy word pages that each fit `w` px; a word wider than the box is shortened with an ellipsis."""
    out: list[str] = []
    cur = ""
    words: list[str] = []
    for tok in text.split():  # a separator ("·", "-") sticks to the word before it, never ends up alone
        if words and tok in ("·", "-", "|"):
            words[-1] += " " + tok
        else:
            words.append(tok)
    for word in words:
        cand = f"{cur} {word}" if cur else word
        if measure(cand, font) <= w:
            cur = cand
            continue
        if cur:
            out.append(cur)
        cur = word if measure(word, font) <= w else fit(word, w, font)
    if cur:
        out.append(cur)
    return tuple(p.rstrip(" ·-|") for p in out) or ("",)


# ------------------------------------------------------------------------------------------- transitions
_DISSOLVE = (np.random.default_rng(7).permutation(1024).reshape(32, 32).astype(np.float32) + 0.5) / 1024.0


def transition(old: np.ndarray, new: np.ndarray, kind: str, p: float) -> np.ndarray:
    """Blend the previous song's frame into the new one. `p` 0..1 (already eased by the caller where needed)."""
    p = max(0.0, min(1.0, p))
    if kind == "slide":
        off = round(32 * ease_io(p))
        out = np.empty_like(new)
        out[:, : 32 - off] = old[:, off:]
        out[:, 32 - off :] = new[:, :off]
        return out
    if kind == "zoom":  # the new picture grows out of the centre over the old one, which dims away
        z = max(1e-3, ease(p))
        sx = np.clip(((_X - 16) / z + 16).astype(np.int32), 0, 31)
        sy = np.clip(((_Y - 16) / z + 16).astype(np.int32), 0, 31)
        inside = (np.abs(_X - 16) <= 16 * z) & (np.abs(_Y - 16) <= 16 * z)
        under = (old.astype(np.float32) * (1 - 0.7 * p)).astype(np.uint8)
        return np.where(inside[..., None], new[sy, sx], under)
    # dissolve: LEDs switch over pixel by pixel in a fixed scattered order (reads crisper than a cross-fade)
    return np.where((p > _DISSOLVE)[..., None], new, old)


# ------------------------------------------------------------------------------------------- cassette
SHELLS: dict[str, RGB] = {"classic": (52, 50, 60), "chrome": (120, 122, 138), "red": (150, 30, 36)}
_REEL_X = (10.5, 21.5)
_REEL_Y = 19.5


def cassette(
    f: Frame, title: str, t: float, angle: float, prog: float, shell: RGB, label: RGB, ink: RGB, accent: RGB,
    marquee: Any,
) -> None:  # fmt: skip
    """A compact cassette: label with the title, a window with two turning reels whose tape packs trade size."""
    edge = mix(shell, (255, 255, 255), 0.25)
    f.rect(0, 3, 32, 26, shell)
    f.hline(1, 3, 30, edge)
    for x, y in ((0, 3), (31, 3), (0, 28), (31, 28)):
        f.set(x, y, (0, 0, 0))
    for x, y in ((1, 4), (30, 4), (1, 27), (30, 27)):
        f.set(x, y, scale(shell, 0.45))  # screws
    # label: side letter + the title
    f.rect(2, 5, 28, 7, label)
    f.text(3, 6, "A", accent)
    f.vline(7, 5, 7, scale(label, 0.7))
    marquee(f, title, t, 9, 6, ink, 20)
    # window
    f.rect(5, 13, 22, 13, (8, 8, 12))
    f.rect(6, 14, 20, 11, (14, 12, 12))
    px = f.px.astype(np.float32)
    for i, cx in enumerate(_REEL_X):
        pack = 2.6 + 3.0 * ((1 - prog) if i == 0 else prog)
        dx, dy = _X - cx, _Y - _REEL_Y
        r = np.hypot(dx, dy)
        win = (_XI >= 6) & (_XI <= 25) & (_YI >= 14) & (_YI <= 24)
        tape = win & (r < pack) & (r >= 2.4)
        shade = 0.82 + 0.18 * np.cos(r * 3.0)
        px[tape] = np.array([118, 70, 36], np.float32) * shade[tape][:, None]
        hub = (r < 2.4) & win
        th = np.arctan2(dy, dx) - angle
        notch = (r > 0.9) & (np.cos(3 * th) > 0.72)
        px[hub] = np.where(
            notch[hub][:, None], np.array([24, 24, 30], np.float32), np.array([210, 210, 222], np.float32)
        )
        px[(r < 0.9) & win] = (24, 24, 30)
    f.px[:] = np.clip(px, 0, 255).astype(np.uint8)
    # tape path along the bottom of the window and the head slot
    f.hline(8, 25, 16, (90, 54, 28))
    f.rect(8, 26, 16, 2, scale(shell, 0.75))
    f.set(11, 27, (0, 0, 0))
    f.set(20, 27, (0, 0, 0))


# ------------------------------------------------------------------------------------------- VU meters
_VU_MAX = math.radians(34)


def vu_needles(f: Frame, levels: tuple[float, float], face: RGB, peak_on: tuple[bool, bool]) -> None:
    """Two backlit analogue meters ("VU" and a scale arc with a red zone) with needles pivoting below the face;
    the levels are already smoothed by the caller (VU ballistics)."""
    needle = (8, 4, 0)
    scale_ink = mix(face, (20, 10, 0), 0.82)
    red = (255, 34, 20)
    for i, x0 in enumerate((0, 17)):
        for y in range(0, 18):  # backlit face, brighter at the top
            f.hline(x0, y, 15, scale(face, 1.0 - y * 0.022))
        cx, cy = x0 + 7, 20
        f.text(x0 + 4, 1, "VU", scale(face, 0.45))
        f.set(x0 + 13, 1, red if peak_on[i] else scale(face, 0.55))  # peak lamp
        for k in range(41):  # the scale arc, red past 0 dB (70 %)
            a = -_VU_MAX + 2 * _VU_MAX * k / 40
            f.set(round(cx + 12 * math.sin(a)), round(cy - 12 * math.cos(a)), red if k > 28 else scale_ink)
        ang = -_VU_MAX + 2 * _VU_MAX * max(0.0, min(1.05, levels[i]))
        f.line(round(cx + 4 * math.sin(ang)), round(cy - 4 * math.cos(ang)),
               round(cx + 13.4 * math.sin(ang)), round(cy - 13.4 * math.cos(ang)), needle)  # fmt: skip
    f.rect(0, 17, 32, 5, (0, 0, 0))  # the plate over the pivots
    f.rect(6, 18, 3, 1, (70, 70, 82))
    f.rect(23, 18, 3, 1, (70, 70, 82))


def vu_ladders(
    f: Frame, levels: tuple[float, float], peaks: tuple[float, float], hues: tuple[RGB, RGB, RGB]
) -> None:
    """Two LED ladder meters (L / R): green -> amber -> red segments with a peak-hold segment."""
    lo, mid, hi = hues
    n = 13
    for i, y in enumerate((5, 13)):
        f.text(1, y, "LR"[i], (120, 120, 140))
        lit = round(max(0.0, min(1.0, levels[i])) * n)
        pk = min(n - 1, round(max(0.0, min(1.0, peaks[i])) * n) - 1)
        for k in range(n):
            c = lo if k < 8 else mid if k < 11 else hi
            x = 5 + k * 2
            col = c if k < lit else scale(c, 0.16)
            if k == pk and pk >= lit:
                col = mix(c, (255, 255, 255), 0.2)
            f.rect(x, y, 1, 5, col)


# ------------------------------------------------------------------------------------------- CD
_CD_EDGE = np.clip(15.7 - _R, 0, 1)
_A_MIRROR = np.clip(6.9 - _R, 0, 1)
_A_HUB = np.clip(4.8 - _R, 0, 1)
_A_HOLE = np.clip(2.2 - _R, 0, 1)


def cd(
    f: Frame, art: np.ndarray | None, pal: list[RGB], angle: float, t: float, shine: bool, k: float
) -> None:
    """A compact disc with the cover printed on it, spinning with the song, a clear hub and a rainbow sheen."""
    ca, sa = math.cos(angle), math.sin(angle)
    dx, dy = _X - 16.0, _Y - 16.0
    if art is not None:
        u = 16 + dx * ca + dy * sa - 0.5
        v = 16 - dx * sa + dy * ca - 0.5
        surf = bilinear(art, u, v) * k
    else:
        c0, c1 = np.array(pal[0], np.float32), np.array(pal[1 % len(pal)], np.float32)
        band = (np.cos(_TH - angle) * 0.5 + 0.5)[..., None]
        surf = (c0 * band + c1 * (1 - band)) * (0.35 + 0.25 * (_R / 16))[..., None] * k
    # layered rings with soft (anti-aliased) edges: hard-edged small circles read as cogs on 32 px
    out = surf.astype(np.float32)
    silver = 120 + 50 * np.cos(2 * (_TH + 0.6))
    mirror = np.stack([silver, silver, silver * 1.08], -1)
    for layer, a in ((mirror, _A_MIRROR), (np.array([52, 54, 64], np.float32), _A_HUB), (0.0, _A_HOLE)):
        out = out * (1 - a[..., None]) + layer * a[..., None]
    if shine:
        phi = 0.7 + 0.35 * math.sin(t * 0.4)
        lobe = np.maximum(0.0, np.cos(2 * (_TH - phi))) ** 10 * (_R > 4.6)
        sheen = rainbow(_R / 14.0 + 0.15) * 150.0
        out += sheen * lobe[..., None]
    out *= _CD_EDGE[..., None]
    f.px[:] = np.clip(out, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------------------------------- radio
FM = (88.0, 108.0)
AM = (530.0, 1700.0)


def station(track: str, band: str) -> float:
    """A stable, plausible frequency for a track (odd tenths on FM, 10 kHz steps on AM)."""
    h = 0
    for ch in track:
        h = (h * 131 + ord(ch)) & 0xFFFFFF
    if band == "am":
        return 540.0 + (h % 116) * 10.0
    return 88.1 + (h % 100) * 0.2


_DIAL = {  # band: (labels [(text, value)], tick step, major ticks)
    "fm": ((("90", 90.0), ("100", 100.0)), 2.0, (90.0, 100.0)),
    "am": ((("60", 600.0), ("120", 1200.0)), 100.0, (600.0, 1200.0)),
}


def _dial_x(v: float, lo: float, hi: float) -> int:
    return round(1 + (max(lo, min(hi, v)) - lo) / (hi - lo) * 29)


def radio_dial(
    f: Frame, freq: float, band: str, tuning: float, playing: bool, lamp: RGB, needle: RGB
) -> None:
    """Backlit tuning scale (y 0..12) with a red needle, then the frequency readout and signal bars."""
    lo, hi = AM if band == "am" else FM
    labels, step, majors = _DIAL["am" if band == "am" else "fm"]
    f.rect(0, 0, 32, 13, scale(lamp, 0.2 if playing else 0.1))
    f.hline(0, 0, 32, scale(lamp, 0.34 if playing else 0.16))
    ink = scale(lamp, 0.95 if playing else 0.5)
    for txt, v in labels:
        w = measure(txt)
        f.text(max(1, min(31 - w, _dial_x(v, lo, hi) - w // 2)), 2, txt, ink)
    v = math.ceil(lo / step) * step
    while v <= hi + 1e-6:
        tall = any(abs(v - mj) < 1e-6 for mj in majors)
        f.vline(_dial_x(v, lo, hi), 8 if tall else 10, 4 if tall else 2, ink if tall else scale(ink, 0.55))
        v += step
    f.vline(_dial_x(freq, lo, hi), 1, 12, needle)
    # readout + signal strength (no bars while the needle is still travelling)
    f.text(1, 15, f"{freq:.0f}" if band == "am" else f"{freq:.1f}", scale(lamp, 0.95 if playing else 0.5))
    bars = 0 if tuning < 1 else 4 if playing else 1
    for k in range(4):
        f.rect(23 + k * 2, 18 - k, 1, 2 + k, scale(lamp, 0.9) if k < bars else (44, 36, 26))


# ------------------------------------------------------------------------------------------- mosaic
@lru_cache(maxsize=4)
def _order(g: int) -> tuple[np.ndarray, np.ndarray]:
    """A fixed scattered order of the g² tiles: (order per tile as a g×g grid, tile index per step)."""
    perm = np.random.default_rng(3).permutation(g * g)
    order = np.empty(g * g, np.float32)
    order[perm] = np.arange(g * g, dtype=np.float32)
    return order.reshape(g, g), perm


def mosaic(f: Frame, tiles: np.ndarray, t: float, reveal: float, glint: bool) -> None:
    """Cover tiles with dark grout (8×8) or plain blocks (16×16). Tiles appear in a scattered order on a new
    cover; one tile at a time catches a glint."""
    g = tiles.shape[0]
    cell = 32 // g
    n = g * g
    order, perm = _order(g)
    k = np.clip((reveal * (n + 6) - order) / 6.0, 0.0, 1.0)
    col = tiles.astype(np.float32) * k[..., None]
    if glint and reveal >= 1.0:
        step = t * 2.5
        jy, jx = divmod(int(perm[int(step) % n]), g)
        a = 0.45 * math.sin(math.pi * (step % 1.0))
        col[jy, jx] = col[jy, jx] * (1 - a) + np.array([255, 255, 255], np.float32) * a * 0.8
    img = np.repeat(np.repeat(col, cell, 0), cell, 1)
    if cell >= 4:
        grout = ((_YI % cell) == cell - 1) | ((_XI % cell) == cell - 1)
        img[grout] = 0
    f.px[:] = np.clip(img, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------------------------------- waveform
def waveform(f: Frame, amps: np.ndarray, pal: list[RGB], style: str, top: int = 8, bottom: int = 29) -> None:
    """Scrolling waveform history, newest column on the right (older columns fade): mirrored bars around the
    centre line, or a trace zig-zagging between the envelope's top and bottom like an oscilloscope."""
    mid = (top + bottom) // 2
    half = (bottom - top) // 2
    c0 = np.array(pal[0], np.float32)
    c1 = np.array(pal[1 % len(pal)], np.float32)
    n = len(amps)
    prev: int | None = None
    heights: list[int] = []
    fades: list[float] = []
    for i, a in enumerate(amps):
        x = 31 - n + i
        age = (n - 1 - i) / max(1, n - 1)
        fade = 0.3 + 0.7 * (1 - age) ** 0.8
        h = round(max(0.0, min(1.0, float(a))) * half)
        if style == "line":
            y = mid - h if i % 2 == 0 else mid + h
            c = tuple(int(v) for v in (c0 * (1 - age) + c1 * age) * fade)
            if prev is not None:
                f.line(x - 1, prev, x, y, c)
            else:
                f.set(x, y, c)
            prev = y
            continue
        heights.append(h)
        fades.append(fade)
    if style == "line" or not n:
        return
    # mirrored bars, vectorised: a pixel is lit when it's within its column's height of the centre line
    xs = slice(31 - n, 31)
    dy = np.abs(_YI[:, xs] - mid)
    lit = dy <= np.asarray(heights)[None, :]
    k = (dy / max(1, half)).astype(np.float32)[..., None]
    col = (c0 * (1 - k) + c1 * k) * np.asarray(fades, np.float32)[None, :, None]
    region = f.px[:, xs]
    region[lit] = np.clip(col[lit], 0, 255).astype(np.uint8)


# ------------------------------------------------------------------------------------------- idle screens
def idle_waves(f: Frame, t: float, a: RGB, b: RGB) -> None:
    """A calm standby visualizer: two slow sine ribbons."""
    for k, (c, amp, sp, ph) in enumerate(((a, 5.0, 0.9, 0.0), (b, 3.5, -0.6, 1.7))):
        prev = None
        for x in range(32):
            y = 16 + amp * math.sin(x * 0.32 + t * sp + ph) * (0.7 + 0.3 * math.sin(t * 0.3 + k))
            yi = round(y)
            col = scale(c, 0.55 if k == 0 else 0.35)
            if prev is not None:
                f.line(x - 1, prev, x, yi, col)
            prev = yi


def idle_silence(f: Frame, t: float, accent: RGB) -> None:
    """A sleeping note: zZ drift up from it, and a flat line with a slow blip travelling along."""
    f.text(9, 12, "♪", scale(accent, 0.55), font="small")
    for k in range(3):
        ph = (t / 3.6 + k / 3) % 1.0
        x = round(16 + ph * 9)
        y = round(13 - ph * 11)
        c = scale(accent, 0.6 * math.sin(math.pi * ph))
        f.text(x, y, "Z" if k % 2 else "z", c)
    f.hline(1, 25, 30, (34, 34, 46))
    bx = round(1 + ((t / 5.0) % 1.0) * 29)
    f.set(bx, 24, scale(accent, 0.5))
    f.set(bx, 25, scale(accent, 0.8))


def idle_wall(f: Frame, covers: list[np.ndarray], t: float, k: float) -> None:
    """Recent covers as a wall (each `covers` entry is already the tile size); the newest top-left and a slow
    highlight walking across the tiles."""
    n = len(covers)
    cell = covers[0].shape[0]
    per = 32 // cell
    hi = int(t / 2.5) % n
    for i, c in enumerate(covers[: per * per]):
        y, x = divmod(i, per)
        lv = k * (1.0 if i == hi else 0.55)
        f.px[y * cell : (y + 1) * cell, x * cell : (x + 1) * cell] = (c.astype(np.float32) * lv).astype(
            np.uint8
        )
