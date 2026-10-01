"""Rain radar around you from RainViewer's public weather maps (no key).

``https://api.rainviewer.com/public/weather-maps.json`` lists the past ~2 hours of composite radar frames
(10-minute steps, plus ``nowcast`` frames when RainViewer publishes them). For each frame we fetch ONE
coordinate-centred tile ``{host}{path}/256/{z}/{lat}/{lon}/2/0_1.png`` (max zoom 7; RainViewer now serves only
the "Universal Blue" scheme, so the colours are decoded back to dBZ with its published colour table and the app
paints its own LED palettes). Decoding happens here, off the event loop; apps get 32×32 arrays.

A basemap for the same window comes from the Open-Meteo elevation API (16×16 samples, sea = 0 m), cached per
place and zoom; if that fails the coarse world land mask is used. Radar coverage (RainViewer's coverage tile)
marks areas no radar can see. No third-party map imagery is used.

``value = {"home", "zoom", "frames": [{"time", "kind", "dbz": int16 (32, 32) (NONE = no echo), "snow": bool
(32, 32)}], "land": bool (32, 32), "elev": float32 (32, 32) | None, "nocov": bool (32, 32) | None, "generated"}``
"""

from __future__ import annotations

import asyncio
import io
import math
import time
from typing import Any

import numpy as np

from .base import Provider

MAPS = "https://api.rainviewer.com/public/weather-maps.json"
TILE = "{host}{path}/256/{z}/{lat:.4f}/{lon:.4f}/2/0_1.png"
COVERAGE = "{host}/v2/coverage/0/256/{z}/{lat:.4f}/{lon:.4f}/0/0_0.png"
ELEVATION = "https://api.open-meteo.com/v1/elevation"

GRID = 32
TILE_PX = 256
CELL = TILE_PX // GRID  # 8 tile pixels per LED
ZOOMS = (3, 4, 5, 6, 7)
NONE = -128  # "no echo" in the dbz grids
MAX_FRAMES = 16
ELEV_GRID = 16  # elevation samples per side (256 points = 256 Open-Meteo calls, once per place/zoom)

# RainViewer "Universal Blue" (scheme 2) colour table, RGBA, dBZ -10 … 74 in 1 dB steps
# (from https://www.rainviewer.com/files/rainviewer_api_colors_table.csv)
_RAIN = (
    "63615914 66635a19 69665c1e 6c685d24 6f6b5f29 726e612e 75706234 78736439 7c75653e 7f786744 827b6949 "
    "857d6a4e 88806c54 8b826d59 8e856f5e 92887164 9e93756e aa9e7978 b6a97e82 c2b4828c cec08796 d2c48ba0 "
    "d6c88faa dacc93b4 ded097be 88ddeeff 6cd1ebff 51c5e8ff 36bae5ff 1baee2ff 00a3e0ff 009ad5ff 0091caff "
    "0088bfff 007fb4ff 0077aaff 0070a3ff 00699cff 006295ff 005b8eff 005588ff 005180ff 004e78ff 004a70ff "
    "004768ff ffee00ff ffe000ff ffd200ff ffc500ff ffb700ff ffaa00ff ff9f00ff ff9500ff ff8b00ff ff8100ff "
    "ff4400ff f23600ff e62800ff d91b00ff cd0d00ff c10000ff a80000ff 8f0000ff 760000ff 5d0000ff ffaaffff "
    "ff9fffff ff95ffff ff8bffff ff81ffff ff77ffff ff6cffff ff62ffff ff58ffff ff4effff ffffffff ffffffff "
    "ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff"
)
_SNOW = (
    "cfffff00 ceffff0c cdffff19 ccffff26 cbffff33 cbffff3f caffff4c c9ffff59 c8ffff66 c7ffff72 c7ffff7f "
    "c6ffff8c c5ffff99 c4ffffa5 c3ffffb2 c3ffffbf c2ffffcc c1ffffd8 c0ffffe5 bffffff2 bfffffff b8f8ffff "
    "b2f2ffff abebffff a5e5ffff 9fdfffff 98d8ffff 92d2ffff 8bcbffff 85c5ffff 7fbfffff 78b8ffff 72b2ffff "
    "6babffff 65a5ffff 5f9fffff 5b9bffff 5898ffff 5595ffff 5292ffff 4f8fffff 4b8bffff 4888ffff 4585ffff "
    "4282ffff 3f7fffff 3b7bffff 3878ffff 3575ffff 3272ffff 2f6fffff 2b6bffff 2868ffff 2565ffff 2262ffff "
    "1f5fffff 1b5bffff 1858ffff 1555ffff 1252ffff 0f4fffff 0c4bffff 0948ffff 0645ffff 0242ffff 003fffff "
    "003bffff 0038ffff 0035ffff 0032ffff 002fffff 002bffff 0028ffff 0025ffff 0022ffff 001fffff 001bffff "
    "0018ffff 0015ffff 0012ffff 000fffff 000cffff 0009ffff 0006ffff 0002ffff"
)
DBZ_MIN = -10


def _table() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(rgba (N, 4) float, dbz (N,), snow (N,)) for nearest-colour decoding."""
    cols, dbz, snow = [], [], []
    for is_snow, raw in ((False, _RAIN), (True, _SNOW)):
        for i, hx in enumerate(raw.split()):
            if int(hx[6:8], 16) == 0:  # fully transparent = no echo
                continue
            cols.append([int(hx[k : k + 2], 16) for k in (0, 2, 4, 6)])
            dbz.append(DBZ_MIN + i)
            snow.append(is_snow)
    return np.array(cols, dtype=np.float32), np.array(dbz, dtype=np.int16), np.array(snow, dtype=bool)


_COLS, _DBZ, _SNOWF = _table()


# ---------------------------------------------------------------------------- geometry (Web Mercator)
def world_px(lat: float, lon: float, z: int) -> tuple[float, float]:
    """(lat, lon) -> global pixel at zoom z with 256 px tiles."""
    n = TILE_PX * 2**z
    lat = max(-85.0511, min(85.0511, lat))
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def world_latlon(x: float, y: float, z: int) -> tuple[float, float]:
    n = TILE_PX * 2**z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lat, (lon + 180.0) % 360.0 - 180.0


def window_center(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Tile centre that puts `home` at the middle of LED (15, 15) instead of on the 15/16 seam."""
    x, y = world_px(lat, lon, z)
    return world_latlon(x + CELL / 2, y + CELL / 2, z)


def cell_latlon(lat: float, lon: float, z: int, n: int = GRID) -> tuple[np.ndarray, np.ndarray]:
    """Latitude/longitude of the centres of an n×n grid over the window centred via `window_center`."""
    cx, cy = world_px(*window_center(lat, lon, z), z)
    step = TILE_PX / n
    lats = np.zeros((n, n))
    lons = np.zeros((n, n))
    for j in range(n):
        for i in range(n):
            la, lo = world_latlon(cx - TILE_PX / 2 + (i + 0.5) * step, cy - TILE_PX / 2 + (j + 0.5) * step, z)
            lats[j, i], lons[j, i] = la, lo
    return lats, lons


def upsample_elevation(e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """n×n elevation samples (sea = 0 m) -> 32×32 (elevation, land) by bilinear interpolation."""
    n = e.shape[0]
    pos = (np.arange(GRID) + 0.5) * n / GRID - 0.5
    i0 = np.clip(np.floor(pos).astype(int), 0, n - 1)
    i1 = np.clip(i0 + 1, 0, n - 1)
    w = np.clip(pos - i0, 0.0, 1.0)

    def interp(a: np.ndarray) -> np.ndarray:
        rows = a[i0] * (1 - w)[:, None] + a[i1] * w[:, None]
        return rows[:, i0] * (1 - w)[None, :] + rows[:, i1] * w[None, :]

    land = interp((e != 0.0).astype(np.float32)) >= 0.5
    return interp(np.maximum(e, 0.0)).astype(np.float32), land


def km_per_led(lat: float, z: int) -> float:
    return 40075.016686 * math.cos(math.radians(lat)) / (TILE_PX * 2**z) * CELL


# ---------------------------------------------------------------------------- decoding
def decode_rgba(rgba: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(H, W, 4) uint8 Universal Blue pixels -> (dbz int16 with NONE, snow bool), nearest table colour."""
    flat = rgba.reshape(-1, 4)
    keys = flat.view(np.uint32).ravel()
    uniq, inv = np.unique(keys, return_inverse=True)
    ucol = uniq.view(np.uint8).reshape(-1, 4).astype(np.float32)
    d = ((ucol[:, None, :] - _COLS[None, :, :]) ** 2 * np.array([1, 1, 1, 0.5], np.float32)).sum(-1)
    best = d.argmin(1)
    udbz = np.where(ucol[:, 3] < 8, NONE, _DBZ[best]).astype(np.int16)
    usnow = np.where(ucol[:, 3] < 8, False, _SNOWF[best])
    shape = rgba.shape[:2]
    return udbz[inv].reshape(shape), usnow[inv].reshape(shape)


def downsample(dbz: np.ndarray, snow: np.ndarray, pct: float = 0.9) -> tuple[np.ndarray, np.ndarray]:
    """256×256 -> 32×32: each LED shows the `pct` percentile of its 8×8 block (needs ~10 % coverage)."""
    h, w = dbz.shape
    b = dbz.reshape(h // CELL, CELL, w // CELL, CELL).transpose(0, 2, 1, 3).reshape(h // CELL, w // CELL, -1)
    k = min(b.shape[2] - 1, round(pct * (b.shape[2] - 1)))
    cell = np.partition(b, k, axis=2)[:, :, k].astype(np.int16)
    s = snow.reshape(h // CELL, CELL, w // CELL, CELL).transpose(0, 2, 1, 3).reshape(h // CELL, w // CELL, -1)
    echo = b != NONE
    snow_frac = (s & echo).sum(2) / np.maximum(1, echo.sum(2))
    return cell, (snow_frac > 0.5) & (cell != NONE)


def decode_tile(png: bytes) -> tuple[np.ndarray, np.ndarray]:
    """A radar tile PNG -> 32×32 (dbz, snow). Blocking (PIL): call through asyncio.to_thread."""
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGBA")
    if img.size != (TILE_PX, TILE_PX):
        img = img.resize((TILE_PX, TILE_PX), Image.Resampling.NEAREST)
    return downsample(*decode_rgba(np.asarray(img, dtype=np.uint8).copy()))


def decode_coverage(png: bytes) -> np.ndarray:
    """Coverage tile (opaque black = no radar) -> 32×32 bool 'not covered'."""
    from PIL import Image

    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"), dtype=np.uint8)[..., 3]
    h, w = a.shape
    blocks = (a > 128).reshape(GRID, h // GRID, GRID, w // GRID).mean(axis=(1, 3))
    return blocks > 0.5


def land_from_mask(lat: float, lon: float, z: int) -> np.ndarray:
    """Fallback basemap: sample the coarse world land mask at every LED centre."""
    from ..gfx.worldmap import land

    m = land(128, 64)
    lats, lons = cell_latlon(lat, lon, z)
    xs = np.clip(((lons + 180.0) / 360.0 * 128).astype(int), 0, 127)
    ys = np.clip(((90.0 - lats) / 180.0 * 64).astype(int), 0, 63)
    return m[ys, xs]


def parse_maps(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """weather-maps.json -> (host, [{"time", "path", "kind": "past"|"nowcast"}]) oldest first."""
    host = str(payload.get("host") or "https://tilecache.rainviewer.com")
    radar = payload.get("radar") or {}
    frames = []
    for kind in ("past", "nowcast"):
        for fr in radar.get(kind) or []:
            if isinstance(fr, dict) and fr.get("path") and fr.get("time"):
                frames.append({"time": float(fr["time"]), "path": str(fr["path"]), "kind": kind})
    frames.sort(key=lambda f: f["time"])
    return host, frames[-MAX_FRAMES:]


# ---------------------------------------------------------------------------- provider
class RainRadarProvider(Provider[dict[str, Any]]):
    name = "rainradar"
    interval = 300.0  # new radar frames every 10 minutes
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.zoom = 6
        self._tiles: dict[tuple[str, int, float, float], tuple[np.ndarray, np.ndarray]] = {}
        self._base: dict[tuple[int, float, float], dict[str, Any]] = {}

    def want(self, zoom: int) -> None:
        z = int(zoom) if int(zoom) in ZOOMS else 6
        if z != self.zoom:
            self.zoom = z
            self.refresh()

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        def key(d: dict[str, Any] | None) -> Any:
            return (d or {}).get("zoom"), [f["time"] for f in (d or {}).get("frames") or []]

        return key(old) != key(new)

    async def _get(self, url: str, **kw: Any) -> Any:
        r = await self.hub.http.get(url, **kw)
        r.raise_for_status()
        return r

    async def _basemap(self, host: str, lat: float, lon: float, z: int) -> dict[str, Any]:
        key = (z, round(lat, 3), round(lon, 3))
        cached = self._base.get(key)
        if cached and (cached["elev"] is not None or time.time() < cached["retry"]):
            return cached
        base: dict[str, Any] = {"land": None, "elev": None, "nocov": None, "retry": time.time() + 600}
        lats, lons = await asyncio.to_thread(cell_latlon, lat, lon, z, ELEV_GRID)
        try:
            n = ELEV_GRID * ELEV_GRID
            elev = np.zeros(n, dtype=np.float32)
            flat_la, flat_lo = lats.ravel(), lons.ravel()
            for i in range(0, n, 100):  # sequential: Open-Meteo counts every coordinate as one call
                r = await self._get(
                    ELEVATION,
                    params={
                        "latitude": ",".join(f"{v:.4f}" for v in flat_la[i : i + 100]),
                        "longitude": ",".join(f"{v:.4f}" for v in flat_lo[i : i + 100]),
                    },
                )
                vals = r.json().get("elevation") or []
                elev[i : i + len(vals)] = np.asarray(vals, dtype=np.float32)[: n - i]
            base["elev"], base["land"] = upsample_elevation(elev.reshape(ELEV_GRID, ELEV_GRID))
        except Exception:  # elevation is optional: fall back to the coarse world mask
            base["land"] = await asyncio.to_thread(land_from_mask, lat, lon, z)
        try:
            clat, clon = window_center(lat, lon, z)
            r = await self._get(COVERAGE.format(host=host, z=z, lat=clat, lon=clon))
            base["nocov"] = await asyncio.to_thread(decode_coverage, r.content)
        except Exception:
            base["nocov"] = None
        self._base[key] = base  # a fallback basemap is retried after 10 min (elevation may be rate limited)
        return base

    async def fetch(self) -> dict[str, Any]:
        loc = await self.hub.location()
        lat, lon, z = float(loc["lat"]), float(loc["lon"]), self.zoom
        host, frames = parse_maps((await self._get(MAPS)).json())
        if not frames:
            raise RuntimeError("no radar frames")
        clat, clon = window_center(lat, lon, z)
        sem = asyncio.Semaphore(4)

        async def tile(fr: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
            key = (fr["path"], z, round(clat, 4), round(clon, 4))
            if key not in self._tiles:
                async with sem:
                    r = await self._get(TILE.format(host=host, path=fr["path"], z=z, lat=clat, lon=clon))
                self._tiles[key] = await asyncio.to_thread(decode_tile, r.content)
            return self._tiles[key]

        results = await asyncio.gather(*(tile(fr) for fr in frames), return_exceptions=True)
        out = []
        for fr, res in zip(frames, results, strict=True):
            if isinstance(res, BaseException):
                continue
            out.append({"time": fr["time"], "kind": fr["kind"], "dbz": res[0], "snow": res[1]})
        if not out:
            raise RuntimeError("radar tiles unavailable")
        live = {(fr["path"], z, round(clat, 4), round(clon, 4)) for fr in frames}
        self._tiles = {k: v for k, v in self._tiles.items() if k in live}
        base = await self._basemap(host, lat, lon, z)
        return {
            "home": loc,
            "zoom": z,
            "km_per_led": km_per_led(lat, z),
            "frames": out,
            "generated": time.time(),
            **{k: base[k] for k in ("land", "elev", "nocov")},
        }
