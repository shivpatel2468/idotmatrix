"""Photo Frame sources: public-domain art, nature photos and animals (all keyless, verified live 2026-09-24).

Sources:

* ``met`` — The Met open access: ``/public/collection/v1/search?hasImages=true&isHighlight=true&q=…`` then
  ``/objects/{id}`` → ``primaryImageSmall`` (~70 KB JPEG).
* ``cleveland`` — Cleveland Museum of Art open access (CC0): ``/api/artworks/?has_image=1&cc0=1&type=Painting``
  → ``images.web.url``.
* ``picsum`` — Lorem Picsum: ``/v2/list`` then ``/id/{id}/{w}/{h}`` (Unsplash photos, author credited).
* ``dogs`` (dog.ceo, optional breed), ``cats`` (cataas.com), ``foxes`` (randomfox.ca), ``ducks`` (random-d.uk).

Dead end: the Art Institute of Chicago metadata API answers, but its IIIF image server sits behind a
Cloudflare browser challenge (HTTP 403 for any non-browser client), so it can't be used.

Every photo is decoded, smart-cropped, LANCZOS-downscaled and colour-calibrated **once**, in a worker thread,
into a 32×32 still plus a short Ken-Burns loop. Apps only blit ready-made arrays.
"""

from __future__ import annotations

import asyncio
import io
import itertools
import math
import random
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from ..gfx.color import calibrate
from .base import Provider

SOURCES: dict[str, str] = {
    "met": "The Met",
    "cleveland": "Cleveland Museum",
    "picsum": "Picsum photos",
    "dogs": "Dogs",
    "cats": "Cats",
    "foxes": "Foxes",
    "ducks": "Ducks",
}
ART = ("met", "cleveland")
MET = "https://collectionapi.metmuseum.org/public/collection/v1"
CLEVELAND = "https://openaccess-api.clevelandart.org/api/artworks/"
PICSUM = "https://picsum.photos"
QUEUE = 8  # photos kept (ring buffer)
PREFETCH = 3  # unseen photos the provider tries to keep ready
KB_FRAMES = 24  # Ken-Burns loop length (frames)
KB_ZOOM = 1.35  # tightest zoom of the loop
WORK = 256  # decode/working size of the long edge
IMG_TIMEOUT = 15.0


@dataclass
class Photo:
    seq: int
    source: str
    title: str
    artist: str
    still: np.ndarray  # (32, 32, 3) uint8, calibrated
    kb: list[np.ndarray] = field(default_factory=list)  # Ken-Burns loop frames, calibrated
    key: str = ""  # source-specific identity (dedupe)


# ------------------------------------------------------------------------------------ image pipeline
def saliency(img: Image.Image) -> np.ndarray:
    """A cheap 'where is the subject' map: edge energy + colourfulness, lightly blurred (float32, HxW)."""
    g = img.convert("L").filter(ImageFilter.FIND_EDGES)
    e = np.asarray(g, np.float32)
    hsv = np.asarray(img.convert("HSV"), np.float32)
    sat = hsv[..., 1] * (hsv[..., 2] / 255.0)
    m = e / (e.max() or 1.0) + 0.6 * sat / (sat.max() or 1.0)
    m[:2, :] = m[-2:, :] = 0  # frame edges of scans are often borders, not subjects
    m[:, :2] = m[:, -2:] = 0
    blurred = Image.fromarray(np.clip(m * 127, 0, 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(3))
    return np.asarray(blurred, np.float32)


def smart_square(img: Image.Image, mode: str = "smart") -> tuple[int, int, int, int]:
    """The best square crop box: slides a square along the long axis and keeps the most salient window."""
    w, h = img.size
    side = min(w, h)
    if w == h:
        return 0, 0, w, h
    if mode == "center":
        x, y = (w - side) // 2, (h - side) // 2
        return x, y, x + side, y + side
    sal = saliency(img)
    prof = sal.sum(axis=0) if w > h else sal.sum(axis=1)
    csum = np.concatenate([[0.0], np.cumsum(prof)])
    n = len(prof) - side + 1
    scores = csum[side : side + n] - csum[:n]
    pos = np.arange(n, dtype=np.float32)
    centre = (n - 1) / 2
    prior = 1.0 - 0.18 * (np.abs(pos - centre) / max(1.0, centre))  # gentle centre bias
    if w < h:  # portraits: faces sit high; bias slightly upwards
        prior *= 1.0 - 0.08 * pos / max(1.0, n - 1)
    best = int(np.argmax(scores * prior))
    return (best, 0, best + side, side) if w > h else (0, best, side, best + side)


def _focus(img: Image.Image) -> tuple[float, float]:
    """Saliency centroid of a square image, in 0..1 coordinates (pulled towards the centre)."""
    sal = saliency(img)
    tot = float(sal.sum())
    if tot <= 0:
        return 0.5, 0.5
    ys, xs = np.mgrid[: sal.shape[0], : sal.shape[1]]
    fx = float((xs * sal).sum() / tot) / sal.shape[1]
    fy = float((ys * sal).sum() / tot) / sal.shape[0]
    return 0.5 + (fx - 0.5) * 0.7, 0.5 + (fy - 0.5) * 0.7


def ken_burns(sq: Image.Image, profile: str, n: int = KB_FRAMES, zoom: float = KB_ZOOM) -> list[np.ndarray]:
    """A seamless zoom-in / zoom-out loop towards the subject: n calibrated 32×32 frames."""
    side = sq.size[0]
    fx, fy = _focus(sq)
    out: list[np.ndarray] = []
    for i in range(n):
        k = 0.5 - 0.5 * math.cos(2 * math.pi * i / n)  # 0 → 1 → 0, eased at both ends
        win = side / (1 + (zoom - 1) * k)
        cx = side / 2 + (fx * side - side / 2) * k
        cy = side / 2 + (fy * side - side / 2) * k
        x0 = min(max(0.0, cx - win / 2), side - win)
        y0 = min(max(0.0, cy - win / 2), side - win)
        fr = sq.resize((96, 96), Image.Resampling.LANCZOS, box=(x0, y0, x0 + win, y0 + win))
        fr = fr.filter(ImageFilter.MedianFilter(3)).resize((32, 32), Image.Resampling.LANCZOS)
        out.append(np.asarray(calibrate(fr, profile), np.uint8).copy())
    return out


def _reduce(sq: Image.Image, size: int) -> Image.Image:
    """LANCZOS to 3× the target, a 3×3 median to kill texture noise that would sparkle on LEDs, then LANCZOS."""
    mid = sq.resize((size * 3, size * 3), Image.Resampling.LANCZOS).filter(ImageFilter.MedianFilter(3))
    return mid.resize((size, size), Image.Resampling.LANCZOS)


def prepare(
    data: bytes, framing: str = "smart", profile: str = "vibrant", kb: bool = True, zoom: float = 1.0
) -> tuple[np.ndarray, list[np.ndarray]]:
    """Decode → orient → reduce → square crop (smart / centre / letterbox) → auto-levels → 32×32 → calibrate.

    `zoom` < 1 crops tighter around the subject (animal photos read better with the subject larger).
    """
    img = Image.open(io.BytesIO(data))
    if img.format == "JPEG":
        img.draft("RGB", (WORK * 2, WORK * 2))  # decode at reduced scale: fast and memory-light
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((WORK, WORK), Image.Resampling.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)  # dark varnished paintings otherwise vanish on LEDs
    if framing == "fit":
        w, h = img.size
        side = max(w, h)
        sq = Image.new("RGB", (side, side))
        sq.paste(img, ((side - w) // 2, (side - h) // 2))
    else:
        sq = img.crop(smart_square(img, framing))
        if zoom < 1.0:
            side = sq.size[0]
            fx, fy = _focus(sq) if framing == "smart" else (0.5, 0.5)
            ns = side * zoom
            x0 = min(max(0.0, fx * side - ns / 2), side - ns)
            y0 = min(max(0.0, fy * side - ns / 2), side - ns)
            sq = sq.crop((round(x0), round(y0), round(x0 + ns), round(y0 + ns)))
    still = np.asarray(calibrate(_reduce(sq, 32), profile), np.uint8).copy()
    frames = ken_burns(sq, profile) if kb and framing != "fit" else []
    return still, frames


# ------------------------------------------------------------------------------------ parsers
def clean_title(s: str, n: int = 80) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:n]


def artist_name(display: str) -> str:
    """'Vincent van Gogh (Dutch, 1853–1890)' → 'Vincent van Gogh'."""
    s = str(display or "").split("\n")[0]
    return clean_title(s.split(" (")[0], 40)


def parse_met_object(o: dict[str, Any]) -> tuple[str, str, str] | None:
    """Met object → (image url, title, artist), or None when it has no usable image."""
    url = o.get("primaryImageSmall") or ""
    if not url:
        return None
    return url, clean_title(o.get("title", "")), artist_name(o.get("artistDisplayName", ""))


def parse_cleveland(payload: dict[str, Any]) -> list[tuple[str, str, str]]:
    out = []
    for a in payload.get("data") or []:
        url = (((a.get("images") or {}).get("web") or {}).get("url")) or ""
        if not url:
            continue
        creators = a.get("creators") or []
        artist = artist_name(creators[0].get("description", "")) if creators else ""
        out.append((url, clean_title(a.get("title", "")), artist))
    return out


def picsum_url(item: dict[str, Any], long_edge: int = 320) -> str:
    w, h = int(item.get("width") or 1), int(item.get("height") or 1)
    s = long_edge / max(w, h)
    return f"{PICSUM}/id/{item['id']}/{max(32, round(w * s))}/{max(32, round(h * s))}"


def dog_breed_from_url(url: str) -> str:
    """'https://images.dog.ceo/breeds/retriever-golden/n02099601_1.jpg' → 'GOLDEN RETRIEVER'."""
    m = re.search(r"/breeds/([^/]+)/", url)
    if not m:
        return "DOG"
    parts = m.group(1).split("-")
    return " ".join(reversed(parts)).upper()


def dog_api_url(breed: str) -> str:
    """'' → any breed; 'husky' / 'golden retriever' / 'retriever/golden' → breed endpoint."""
    b = breed.strip().lower()
    if not b:
        return "https://dog.ceo/api/breeds/image/random"
    if "/" not in b:
        words = b.replace("-", " ").split()
        b = f"{words[-1]}/{' '.join(words[:-1])}" if len(words) >= 2 else words[0]
        b = b.replace(" ", "")
    return f"https://dog.ceo/api/breed/{b}/images/random"


def parse_sources(v: Sequence[str]) -> list[str]:
    return [s for s in v if s in SOURCES] or ["picsum"]


# ------------------------------------------------------------------------------------ provider
class PhotosProvider(Provider[list[Photo]]):
    """``value`` is a list of ready `Photo`s (oldest first, at most ``QUEUE``).

    Apps call ``want(sources, …)`` and ``seen(seq)``; the provider keeps ``PREFETCH`` unseen photos ready.
    """

    name = "photos"
    interval = 30.0
    retry = 20.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.sources: list[str] = ["picsum"]
        self.breed = ""
        self.query = "painting"
        self.framing = "smart"
        self.profile = "vibrant"
        self._seq = itertools.count(1)
        self._seen: set[int] = set()
        self._rr = 0
        self._met_ids: dict[str, tuple[float, list[int]]] = {}
        self._cle_total: int | None = None
        self._picsum: list[dict[str, Any]] = []
        self._fails: dict[str, int] = {}
        self._skip_until: dict[str, float] = {}
        self._rng = random.Random()

    # ------------------------------------------------------------ interface
    def want(
        self,
        sources: Sequence[str],
        breed: str = "",
        query: str = "painting",
        framing: str = "smart",
        profile: str = "vibrant",
    ) -> None:
        src = parse_sources(sources)
        render_changed = (framing, profile) != (self.framing, self.profile)
        changed = src != self.sources or breed != self.breed or query != self.query or render_changed
        self.sources, self.breed, self.query = src, breed, query or "painting"
        self.framing, self.profile = framing, profile
        if changed:
            keep = [p for p in (self.value or []) if p.source in src and not render_changed]
            if self.value is not None:
                self.value = keep
            self._skip_until.clear()
            self.refresh()

    def seen(self, seq: int) -> None:
        if seq not in self._seen:
            self._seen.add(seq)
            if self.unseen() < PREFETCH:
                self.refresh()

    def unseen(self) -> int:
        return sum(1 for p in self.value or [] if p.seq not in self._seen)

    def next_interval(self) -> float:
        return 2.0 if self.unseen() < PREFETCH else self.interval

    def announce(self, old: list[Photo] | None, new: list[Photo]) -> bool:
        return [p.seq for p in old or []] != [p.seq for p in new]

    # ------------------------------------------------------------ fetching
    async def _json(self, url: str, **params: Any) -> Any:
        r = await self.hub.http.get(url, params=params or None)
        r.raise_for_status()
        return r.json()

    async def _bytes(self, url: str) -> bytes:
        r = await self.hub.http.get(url, timeout=IMG_TIMEOUT)
        r.raise_for_status()
        if not r.headers.get("content-type", "image/").startswith("image/"):
            raise ValueError(f"not an image: {r.headers.get('content-type')}")
        return r.content

    async def _pick(self, source: str) -> tuple[str, str, str, str]:
        """→ (image url, title, artist, key) for one random item of `source`."""
        rng = self._rng
        if source == "met":
            q = self.query
            cached = self._met_ids.get(q)
            if not cached or time.time() - cached[0] > 6 * 3600:
                d = await self._json(f"{MET}/search", hasImages="true", isHighlight="true", q=q)
                ids = list(d.get("objectIDs") or [])
                if not ids:
                    raise ValueError(f"met: nothing for {q!r}")
                cached = self._met_ids[q] = (time.time(), ids)
            for oid in rng.sample(cached[1], min(4, len(cached[1]))):
                got = parse_met_object(await self._json(f"{MET}/objects/{oid}"))
                if got:
                    return (*got, f"met:{oid}")
            raise ValueError("met: no public image")
        if source == "cleveland":
            if self._cle_total is None:
                d = await self._json(CLEVELAND, has_image=1, cc0=1, type="Painting", limit=1)
                self._cle_total = int((d.get("info") or {}).get("total") or 1000)
            skip = rng.randrange(max(1, self._cle_total))
            d = await self._json(CLEVELAND, has_image=1, cc0=1, type="Painting", limit=1, skip=skip)
            items = parse_cleveland(d)
            if not items:
                raise ValueError("cleveland: empty page")
            return (*items[0], f"cle:{skip}")
        if source == "picsum":
            if not self._picsum:
                self._picsum = list(await self._json(f"{PICSUM}/v2/list", page=rng.randint(1, 10), limit=100))
            item = self._picsum.pop(rng.randrange(len(self._picsum)))
            return picsum_url(item), "", clean_title(item.get("author", ""), 40), f"picsum:{item['id']}"
        if source == "dogs":
            d = await self._json(dog_api_url(self.breed))
            if d.get("status") != "success":
                raise ValueError(f"dog.ceo: {d.get('message')}")
            url = str(d["message"])
            return url, dog_breed_from_url(url), "", f"dog:{url}"
        if source == "cats":
            d = await self._json("https://cataas.com/cat", json="true")
            url = str(d.get("url") or f"https://cataas.com/cat/{d['id']}")
            return f"{url}{'&' if '?' in url else '?'}width=320", "CAT", "", f"cat:{d.get('id')}"
        if source == "foxes":
            d = await self._json("https://randomfox.ca/floof/")
            return str(d["image"]), "FOX", "", f"fox:{d['image']}"
        if source == "ducks":
            d = await self._json("https://random-d.uk/api/v2/random")
            url = str(d["url"]).replace("http://", "https://", 1)
            return url, "DUCK", "", f"duck:{url}"
        raise ValueError(source)

    async def _one(self, source: str) -> Photo:
        url, title, artist, key = await self._pick(source)
        if any(p.key == key for p in self.value or []):
            url, title, artist, key = await self._pick(source)  # one retry on a duplicate
        data = await self._bytes(url)
        zoom = 1.0 if source in ART else 0.85
        still, kb = await asyncio.to_thread(prepare, data, self.framing, self.profile, True, zoom)
        return Photo(next(self._seq), source, title, artist, still, kb, key)

    async def fetch(self) -> list[Photo]:
        photos = list(self.value or [])
        now = time.time()
        errors: list[str] = []
        order = self.sources[self._rr % len(self.sources) :] + self.sources[: self._rr % len(self.sources)]
        self._rr += 1
        for source in order:
            if self._skip_until.get(source, 0) > now:
                continue
            try:
                photo = await self._one(source)
            except Exception as e:
                n = self._fails[source] = self._fails.get(source, 0) + 1
                self._skip_until[source] = now + min(600.0, self.retry * 2 ** (n - 1))
                errors.append(f"{source}: {type(e).__name__}: {e}"[:90])
                continue
            self._fails.pop(source, None)
            photos.append(photo)
            # drop the oldest *seen* photos first; never evict unseen ones unless the ring is full of them
            while len(photos) > QUEUE:
                old = next((p for p in photos if p.seq in self._seen), photos[0])
                photos.remove(old)
            live = {p.seq for p in photos}
            self._seen &= live
            return photos
        if photos and not errors:
            return photos
        raise RuntimeError("; ".join(errors)[:200] or "all sources backing off")
