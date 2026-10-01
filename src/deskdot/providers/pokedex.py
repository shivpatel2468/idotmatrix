"""Pokémon data and sprites from PokéAPI (keyless, verified live 2026-09-24). Nothing is bundled.

* ``https://pokeapi.co/api/v2/pokemon/{id|name}`` — name, types, base stats, height/weight and
  ``sprites.front_default`` / ``front_shiny`` (96×96 pixel-art PNGs on raw.githubusercontent.com).
* ``https://pokeapi.co/api/v2/pokemon-species/{id}`` — the genus ("Mouse Pokémon"), best-effort.

Sprites are cropped to their opaque bounding box and reduced with a pixel-art-aware filter (box average, then
every pixel snapped back to the sprite's own palette) so they stay crisp at 32×32. Entries are cached in
memory (LRU, bounded).
"""

from __future__ import annotations

import asyncio
import io
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from .base import Provider

API = "https://pokeapi.co/api/v2"
CACHE = 48
# national-dex ranges per generation
GENERATIONS: dict[str, tuple[int, int]] = {
    "all": (1, 1025),
    "1": (1, 151),
    "2": (152, 251),
    "3": (252, 386),
    "4": (387, 493),
    "5": (494, 649),
    "6": (650, 721),
    "7": (722, 809),
    "8": (810, 905),
    "9": (906, 1025),
}
STAT_KEYS = ("hp", "attack", "defense", "special-attack", "special-defense", "speed")

# box sizes the app draws sprites at
SIZES: dict[str, tuple[int, int]] = {"hero": (30, 23), "small": (15, 15), "who": (30, 27)}


@dataclass
class Sprite32:
    """A prepared sprite: RGB pixels + opacity mask (h, w)."""

    px: np.ndarray
    mask: np.ndarray

    @property
    def w(self) -> int:
        return int(self.px.shape[1])

    @property
    def h(self) -> int:
        return int(self.px.shape[0])


def crop_opaque(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    bbox = rgba.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return rgba.crop(bbox) if bbox else rgba


def pixel_downscale(rgba: Image.Image, box: tuple[int, int]) -> Sprite32:
    """Fit a pixel-art sprite into `box` (w, h) keeping it crisp.

    Integer scales use nearest-neighbour (exact). Otherwise: box-filter average, alpha threshold, then snap each
    pixel to the nearest colour of the sprite's own palette — no new in-between colours, no blur.
    """
    w, h = rgba.size
    s = min(box[0] / w, box[1] / h)
    if s >= 1:
        s = float(int(s))  # integer upscale: exact pixels
        ow, oh = int(w * s), int(h * s)
        small = rgba.resize((ow, oh), Image.Resampling.NEAREST)
        a = np.asarray(small)
        return Sprite32(a[..., :3].copy(), a[..., 3] > 128)
    ow, oh = max(1, round(w * s)), max(1, round(h * s))
    src = np.asarray(rgba)
    opaque = src[..., 3] > 128
    pal = (
        np.unique(src[opaque][:, :3], axis=0).astype(np.int32) if opaque.any() else np.zeros((1, 3), np.int32)
    )
    small = np.asarray(rgba.resize((ow, oh), Image.Resampling.BOX)).astype(np.int32)
    mask = small[..., 3] >= 110
    rgb = small[..., :3]  # Pillow resizes RGBA premultiplied, so edge colours aren't darkened
    d = ((rgb[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(axis=3)
    snapped = pal[d.argmin(axis=2)].astype(np.uint8)
    snapped[~mask] = 0
    return Sprite32(snapped, mask)


def prepare_sprite(data: bytes) -> dict[str, Sprite32]:
    img = crop_opaque(Image.open(io.BytesIO(data)))
    return {k: pixel_downscale(img, box) for k, box in SIZES.items()}


def display_name(name: str) -> str:
    """'mr-mime' → 'MR MIME', 'nidoran-f' → 'NIDORAN F', 'ho-oh' → 'HO-OH'."""
    n = str(name or "").upper()
    if n in ("HO-OH", "PORYGON-Z", "JANGMO-O", "HAKAMO-O", "KOMMO-O"):
        return n
    return n.replace("-", " ")


def parse_pokemon(p: dict[str, Any]) -> dict[str, Any]:
    stats = {s["stat"]["name"]: int(s["base_stat"]) for s in p.get("stats") or []}
    types = [t["type"]["name"] for t in sorted(p.get("types") or [], key=lambda t: t.get("slot", 0))]
    sp = p.get("sprites") or {}
    return {
        "id": int(p["id"]),
        "name": display_name(p.get("name", "")),
        "types": types,
        "stats": [stats.get(k, 0) for k in STAT_KEYS],
        "height": int(p.get("height") or 0),  # decimetres
        "weight": int(p.get("weight") or 0),  # hectograms
        "sprite_url": sp.get("front_default"),
        "shiny_url": sp.get("front_shiny"),
    }


def parse_genus(species: dict[str, Any]) -> str:
    for g in species.get("genera") or []:
        if (g.get("language") or {}).get("name") == "en":
            return re.sub(r"\s*Pok[eé]mon$", "", str(g.get("genus") or ""), flags=re.I).upper()
    return ""


def normalize_key(v: str | int) -> str:
    """User input → PokéAPI path key: '25', '#025' → '25'; 'Mr. Mime' → 'mr-mime'."""
    s = str(v).strip().lower().lstrip("#")
    if s.isdigit():
        return str(int(s))
    s = s.replace(".", "").replace("'", "").replace("♀", "-f").replace("♂", "-m")
    return re.sub(r"[\s_]+", "-", s)


class PokedexProvider(Provider[dict[int, dict[str, Any]]]):
    """``value = {id: entry}``; an entry carries ``sprites`` / ``shiny`` dicts of `Sprite32` per size.

    Apps call ``want(key)`` with a dex number or name and read ``get(key)``.
    """

    name = "pokedex"
    interval = 3600.0
    retry = 20.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._wanted: list[str] = []
        self._names: dict[str, int] = {}
        self._bad: dict[str, float] = {}
        self._cache: OrderedDict[int, dict[str, Any]] = OrderedDict()

    def want(self, *keys: str | int) -> None:
        new = False
        for k in keys:
            nk = normalize_key(k)
            if not nk:
                continue
            if nk in self._wanted:
                self._wanted.remove(nk)
            self._wanted.append(nk)
            if self.get(nk) is None and self._bad.get(nk, 0) < time.time():
                new = True
        del self._wanted[:-8]
        if new:
            self.refresh()

    def get(self, key: str | int) -> dict[str, Any] | None:
        nk = normalize_key(key)
        pid = int(nk) if nk.isdigit() else self._names.get(nk)
        e = self._cache.get(pid) if pid is not None else None
        if e is not None:
            self._cache.move_to_end(pid)  # type: ignore[arg-type]
        return e

    def failed(self, key: str | int) -> bool:
        return self._bad.get(normalize_key(key), 0) > time.time()

    def next_interval(self) -> float:
        return 1.0 if any(self.get(k) is None and not self.failed(k) for k in self._wanted) else self.interval

    async def _load(self, key: str) -> dict[str, Any]:
        r = await self.hub.http.get(f"{API}/pokemon/{key}")
        if r.status_code == 404:
            self._bad[key] = time.time() + 3600
            raise ValueError(f"no pokemon {key!r}")
        r.raise_for_status()
        e = parse_pokemon(r.json())
        genus = ""
        try:
            rs = await self.hub.http.get(f"{API}/pokemon-species/{e['id']}")
            if rs.status_code == 200:
                genus = parse_genus(rs.json())
        except Exception:
            pass
        e["genus"] = genus
        for field, url in (("sprites", e["sprite_url"]), ("shiny", e["shiny_url"] or e["sprite_url"])):
            if not url:
                e[field] = None
                continue
            ri = await self.hub.http.get(url)
            ri.raise_for_status()
            e[field] = await asyncio.to_thread(prepare_sprite, ri.content)
        return e

    async def fetch(self) -> dict[int, dict[str, Any]]:
        errors: list[str] = []
        for key in reversed(self._wanted):  # newest wish first
            if self.get(key) is not None or self.failed(key):
                continue
            try:
                e = await self._load(key)
            except Exception as ex:
                errors.append(f"{key}: {type(ex).__name__}: {ex}")
                if key not in self._bad:
                    self._bad[key] = time.time() + 60
                continue
            self._cache[e["id"]] = e
            self._names[normalize_key(e["name"])] = e["id"]
            if not key.isdigit():
                self._names[key] = e["id"]
            while len(self._cache) > CACHE:
                self._cache.popitem(last=False)
            break  # one pokémon per fetch keeps requests polite; next_interval() comes back quickly
        if errors and not self._cache:
            raise RuntimeError("; ".join(errors)[:200])
        return dict(self._cache)
