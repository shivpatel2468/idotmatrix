"""Exact pixel-art avatars that map 1:1 onto the panel grid (keyless, verified live 2026-09-24).

* ``minecraft`` — ``https://mc-heads.net/avatar/{name}/8``: the 8×8 skin face with the hat layer (×4 = 32).
  Fallback: Mojang ``/users/profiles/minecraft/{name}`` → ``https://crafatar.com/avatars/{uuid}?size=8&overlay``.
* ``github`` — ``https://github.com/identicons/{user}.png``: a 420×420 PNG of a 5×5 grid (70 px cells, 35 px
  margin) reduced back to its 5×5 cells and one colour.
* ``dicebear`` — ``https://api.dicebear.com/9.x/pixel-art/png?seed={seed}&size=16``: a CC0 16×16 pixel-art
  character for any seed (×2 = 32).

Entries are tiny arrays, cached in memory.
"""

from __future__ import annotations

import asyncio
import colorsys
import io
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from .base import Provider

KINDS = {"mc": "minecraft", "gh": "github", "db": "dicebear"}
CACHE = 64
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,39}$")


@dataclass
class Avatar:
    source: str  # minecraft | github | dicebear
    name: str
    px: np.ndarray  # (h, w, 3) uint8 at the source's native grid
    mask: np.ndarray  # (h, w) bool, opaque cells


def parse_names(text: str, default: str = "minecraft") -> list[tuple[str, str]]:
    """'Notch, gh:torvalds, db:ada' → [('minecraft','Notch'), ('github','torvalds'), ('dicebear','ada')]."""
    out: list[tuple[str, str]] = []
    for raw in re.split(r"[,\n;]+", text):
        part = raw.strip()
        if not part:
            continue
        src = default
        if ":" in part:
            pre, _, rest = part.partition(":")
            src = KINDS.get(pre.strip().lower(), pre.strip().lower())
            part = rest.strip()
        if src not in KINDS.values() or not part:
            continue
        if src != "dicebear" and not NAME_RE.match(part):
            continue
        item = (src, part[:39])
        if item not in out:
            out.append(item)
    return out


def led_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """A web colour normalised for LEDs: full value, a little more saturation (identicons are pastel)."""
    h, s, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    r, g, b = colorsys.hsv_to_rgb(h, min(1.0, s * 1.35 + 0.1), 1.0)
    return round(r * 255), round(g * 255), round(b * 255)


def decode_minecraft(data: bytes) -> Avatar:
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.size != (8, 8):
        img = img.resize((8, 8), Image.Resampling.NEAREST)
    a = np.asarray(img)
    return Avatar("minecraft", "", a[..., :3].copy(), np.ones((8, 8), bool))


def decode_identicon(data: bytes) -> Avatar:
    """GitHub's identicon: sample the 5×5 cell centres; the background is (240, 240, 240)."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    cell, margin = w / 6, w / 12  # 420 → 70 px cells, 35 px margin
    grid = np.zeros((5, 5), bool)
    fg: tuple[int, int, int] | None = None
    for j in range(5):
        for i in range(5):
            c = img.getpixel((round(margin + cell * (i + 0.5)), round(margin + h / 6 * (j + 0.5))))
            if max(abs(int(v) - 240) for v in c) > 12:  # type: ignore[union-attr]
                grid[j, i] = True
                fg = fg or tuple(int(v) for v in c)  # type: ignore[union-attr, assignment]
    col = led_color(fg or (200, 200, 200))
    px = np.zeros((5, 5, 3), np.uint8)
    px[grid] = col
    return Avatar("github", "", px, grid)


def decode_dicebear(data: bytes) -> Avatar:
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.size != (16, 16):
        img = img.resize((16, 16), Image.Resampling.NEAREST)
    a = np.asarray(img)
    mask = a[..., 3] > 128
    px = a[..., :3].copy()
    px[~mask] = 0
    return Avatar("dicebear", "", px, mask)


class AvatarsProvider(Provider[dict[tuple[str, str], Avatar]]):
    """``value = {(source, name): Avatar}``. Apps call ``want([(source, name), …])``."""

    name = "avatars"
    interval = 6 * 3600.0  # skins change rarely
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.wanted: list[tuple[str, str]] = []
        self._cache: OrderedDict[tuple[str, str], Avatar] = OrderedDict()
        self._bad: set[tuple[str, str]] = set()

    def want(self, items: list[tuple[str, str]]) -> None:
        items = items[:24]
        if items != self.wanted:
            self.wanted = items
            if any(k not in self._cache and k not in self._bad for k in items):
                self.refresh()

    def failed(self, key: tuple[str, str]) -> bool:
        return key in self._bad

    def next_interval(self) -> float:
        pending = [k for k in self.wanted if k not in self._cache and k not in self._bad]
        return 1.0 if pending else self.interval

    async def _get(self, url: str) -> bytes:
        r = await self.hub.http.get(url)
        r.raise_for_status()
        if not r.headers.get("content-type", "image/").startswith("image/"):
            raise ValueError("not an image")
        return r.content

    async def _load(self, source: str, name: str) -> Avatar:
        if source == "minecraft":
            try:
                data = await self._get(f"https://mc-heads.net/avatar/{name}/8")
            except Exception:
                r = await self.hub.http.get(f"https://api.mojang.com/users/profiles/minecraft/{name}")
                r.raise_for_status()
                uuid = r.json()["id"]
                data = await self._get(f"https://crafatar.com/avatars/{uuid}?size=8&overlay")
            av = await asyncio.to_thread(decode_minecraft, data)
        elif source == "github":
            av = await asyncio.to_thread(
                decode_identicon, await self._get(f"https://github.com/identicons/{name}.png")
            )
        else:
            r = await self.hub.http.get(
                "https://api.dicebear.com/9.x/pixel-art/png", params={"seed": name, "size": 16}
            )
            r.raise_for_status()
            av = await asyncio.to_thread(decode_dicebear, r.content)
        av.name = name
        return av

    async def fetch(self) -> dict[tuple[str, str], Avatar]:
        todo = [k for k in self.wanted if k not in self._cache and k not in self._bad][:4]
        results = await asyncio.gather(*(self._load(*k) for k in todo), return_exceptions=True)
        errors = []
        for k, res in zip(todo, results, strict=True):
            if isinstance(res, BaseException):
                errors.append(f"{k[1]}: {type(res).__name__}")
                if "404" in str(res) or isinstance(res, (KeyError, ValueError)):
                    self._bad.add(k)
                continue
            self._cache[k] = res
        while len(self._cache) > CACHE:
            self._cache.popitem(last=False)
        if errors and not self._cache:
            raise RuntimeError("; ".join(errors)[:200])
        return dict(self._cache)
