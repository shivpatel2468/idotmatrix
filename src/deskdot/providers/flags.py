"""Country flags from flagcdn.com (Flagpedia's CDN; keyless, CORS) for the World Flags app.

``flagcdn.com/en/codes.json`` gives ISO 3166 codes and English names (US states, ``us-ca`` etc., are dropped);
``flagcdn.com/w80/{cc}.png`` is a small PNG of each flag, downscaled here to fit 30×20 LEDs. Flags are flat
design colours, so they are not photo-calibrated. (REST Countries, the obvious source, now needs an API key.)

``value = {"names": {cc: NAME}, "flags": {cc: np.ndarray (h, w, 3) uint8}}``; apps call ``want(*codes)``.
"""

from __future__ import annotations

import asyncio
import io
import time
from typing import Any

import numpy as np
from PIL import Image

from .base import Endpoint, Provider
from .daily import clean_text

CODES = "https://flagcdn.com/en/codes.json"
PNG = "https://flagcdn.com/w80/{cc}.png"
MAX_W, MAX_H = 30, 20
CACHE = 24


def parse_codes(d: Any) -> dict[str, str]:
    if not isinstance(d, dict) or not d:
        raise ValueError("flagcdn: unexpected shape")
    return {
        str(k).lower(): clean_text(v, 40)
        for k, v in d.items()
        if isinstance(k, str) and len(k) == 2 and k.isalpha() and k.lower() not in ("eu", "un")
    }


def decode_flag(data: bytes, max_w: int = MAX_W, max_h: int = MAX_H) -> np.ndarray:
    """PNG bytes -> (h, w, 3) uint8 fitted inside max_w×max_h, aspect kept (BOX filter keeps stripes crisp)."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    k = min(max_w / img.width, max_h / img.height)
    w, h = max(4, round(img.width * k)), max(3, round(img.height * k))
    return np.asarray(img.resize((w, h), Image.Resampling.BOX), dtype=np.uint8)


class FlagsProvider(Provider[dict[str, Any]]):
    name = "flags"
    endpoints = (
        Endpoint("flagcdn country names", CODES, check=parse_codes),
        Endpoint("flagcdn flag PNG", PNG.format(cc="jp"), check=decode_flag, body="bytes"),
    )
    interval = 30.0  # only loads what is wanted; names refresh daily
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.wanted: list[str] = []
        self._names: tuple[float, dict[str, str]] | None = None
        self._flags: dict[str, np.ndarray] = {}

    def want(self, *codes: str) -> None:
        new = [c.lower() for c in codes if c and c.lower() not in self._flags]
        self.wanted = [c.lower() for c in codes if c][:6]
        if new:
            self.refresh()

    def announce(self, old: Any, new: dict[str, Any]) -> bool:
        return old is None or set(old.get("flags", {})) != set(new.get("flags", {}))

    async def _png(self, cc: str) -> np.ndarray:
        r = await self.hub.http.get(PNG.format(cc=cc))
        r.raise_for_status()
        return await asyncio.to_thread(decode_flag, r.content)

    async def fetch(self) -> dict[str, Any]:
        if not self._names or time.time() - self._names[0] > 86400:
            r = await self.hub.http.get(CODES)
            r.raise_for_status()
            self._names = (time.time(), parse_codes(r.json()))
        names = self._names[1]
        todo = [c for c in self.wanted if c in names and c not in self._flags]
        res = await asyncio.gather(*(self._png(c) for c in todo), return_exceptions=True)
        for c, img in zip(todo, res, strict=True):
            if isinstance(img, np.ndarray):
                self._flags[c] = img
        while len(self._flags) > CACHE:
            self._flags.pop(next(iter(self._flags)))
        return {"names": names, "flags": dict(self._flags)}
