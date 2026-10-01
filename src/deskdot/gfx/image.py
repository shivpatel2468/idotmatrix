"""Media import (any image/GIF -> 32x32 frames) and GIF encoding for native playback."""

from __future__ import annotations

import io
from typing import Literal

import numpy as np
from PIL import Image, ImageSequence

from .color import calibrate
from .frame import Frame, H, W

Fit = Literal["contain", "cover", "stretch"]
MAX_CLIP_FRAMES = 64


def is_pixel_art(img: Image.Image) -> bool:
    """Small sources or few colours are treated as pixel art (nearest-neighbour, no calibration)."""
    if max(img.size) <= 64:
        return True
    small = img.convert("RGB").resize((64, 64), Image.Resampling.NEAREST)
    return len(small.getcolors(64 * 64) or []) <= 24


def fit_image(
    img: Image.Image,
    fit: Fit = "contain",
    pixel_art: bool | None = None,
    background: tuple[int, int, int] = (0, 0, 0),
) -> Image.Image:
    """Resize any image onto a 32x32 RGB canvas. Transparent areas become `background`."""
    rgba = img.convert("RGBA")
    # trim fully transparent borders so sprites fill the panel
    alpha = rgba.getchannel("A").point(lambda a: 255 if a > 8 else 0)
    bbox = alpha.getbbox()
    if bbox and bbox != (0, 0, *rgba.size):
        rgba = rgba.crop(bbox)
    pa = is_pixel_art(rgba) if pixel_art is None else pixel_art
    resample = Image.Resampling.NEAREST if pa else Image.Resampling.LANCZOS
    w, h = rgba.size
    if fit == "stretch":
        out = rgba.resize((W, H), resample)
    elif fit == "cover":
        s = max(W / w, H / h)
        nw, nh = max(W, round(w * s)), max(H, round(h * s))
        big = rgba.resize((nw, nh), resample)
        left, top = (nw - W) // 2, (nh - H) // 2
        out = big.crop((left, top, left + W, top + H))
    else:
        s = min(W / w, H / h)
        if pa and s >= 1:
            s = max(1, int(s))  # integer upscale keeps pixel art crisp
        nw, nh = max(1, min(W, round(w * s))), max(1, min(H, round(h * s)))
        small = rgba.resize((nw, nh), resample)
        out = Image.new("RGBA", (W, H), (*background, 255))
        out.alpha_composite(small, ((W - nw) // 2, (H - nh) // 2))
    canvas = Image.new("RGB", (W, H), background)
    canvas.paste(out, (0, 0), out)
    return canvas


def import_media(data: bytes, fit: Fit = "contain", profile: str = "auto") -> tuple[list[Frame], list[int]]:
    """Decode an image or animation into frames + per-frame durations (ms).

    profile: "auto" (calibrate photos, leave pixel art raw), "vibrant", "natural", "raw".
    """
    src = Image.open(io.BytesIO(data))
    pixel_art = is_pixel_art(src)
    prof = ("raw" if pixel_art else "vibrant") if profile == "auto" else profile
    frames: list[Frame] = []
    durations: list[int] = []
    for fr in ImageSequence.Iterator(src):
        img = fit_image(fr.copy(), fit, pixel_art)
        if prof != "raw":
            img = calibrate(img, prof)
        frames.append(Frame.from_image(img))
        durations.append(max(20, int(fr.info.get("duration", src.info.get("duration", 100)) or 100)))
    if len(frames) > MAX_CLIP_FRAMES:  # resample long animations, keeping total duration
        idx = np.linspace(0, len(frames) - 1, MAX_CLIP_FRAMES).round().astype(int)
        total = sum(durations)
        frames = [frames[i] for i in idx]
        durations = [max(20, total // MAX_CLIP_FRAMES)] * MAX_CLIP_FRAMES
    return frames, durations


def encode_gif(
    frames: list[Frame], durations_ms: list[int], dither: bool = False, max_colors: int = 256
) -> bytes:
    """Encode frames with ONE shared palette so colours never flicker between frames."""
    if not frames:
        raise ValueError("no frames")
    atlas = Image.new("RGB", (W, H * len(frames)))
    for i, f in enumerate(frames):
        atlas.paste(f.to_image(), (0, i * H))
    n_colors = len(atlas.getcolors(W * H * len(frames)) or []) or 256
    master = atlas.quantize(colors=min(max_colors, 256, max(2, n_colors)), method=Image.Quantize.MEDIANCUT)
    d = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    pal = [f.to_image().quantize(palette=master, dither=d) for f in frames]
    buf = io.BytesIO()
    pal[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=pal[1:],
        duration=[int(x) for x in durations_ms],
        loop=0,
        disposal=1,
        optimize=True,
    )
    return buf.getvalue()


#: Large GIFs upload slowly (~16 KB/s) and the panel decodes them sluggishly. Measured on hardware
#: 2026-09-24: a 91 KB 48-frame plasma played "a little laggy"; ~35 KB plays smoothly.
GIF_BUDGET = 40 * 1024


def encode_gif_budget(
    frames: list[Frame], durations_ms: list[int], max_colors: int = 256, budget: int = GIF_BUDGET
) -> bytes:
    """Encode, then shrink until the GIF fits the budget — the panel decodes bigger GIFs sluggishly and they take
    seconds to upload (docs/HARDWARE_PROTOCOL.md #5). First smaller palettes (down to 16 colours); if that is
    not enough, drop every other frame (merging durations, so playback time stays exact) and try again."""
    gif = encode_gif(frames, durations_ms, max_colors=max_colors)
    for colors in (64, 48, 32, 24, 16):
        if len(gif) <= budget or colors >= max_colors:
            if len(gif) <= budget:
                break
            continue
        gif = encode_gif(frames, durations_ms, max_colors=colors)
    while len(gif) > budget and len(frames) > 2:
        durations_ms = [a + b for a, b in zip(durations_ms[::2], [*durations_ms[1::2], 0], strict=False)]
        frames = frames[::2]
        gif = encode_gif(frames, durations_ms, max_colors=min(max_colors, 32))
    return gif
