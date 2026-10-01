"""Now playing: title, artist, position, album art and a colour palette from whatever is playing.

Backends (picked by `sys.platform`):

* **Windows** — Global System Media Transport Controls (GSMTC). Covers Spotify, YouTube / YouTube Music in
  Chrome / Edge / Firefox, Apple Music, Media Player, VLC, … When several apps have a session, the one that is
  *playing* wins (the "current" session is often a paused tab).
* **macOS** — `media_mac.MacBackend`: AppleScript for Spotify and Music.app, `nowplaying-cli` (if installed)
  for browsers and everything else.

Position is kept on our own monotonic clock and only re-anchored when the player reports something new
(a timeline update, a seek, play/pause, a new track). Windows refreshes its timeline only every few seconds,
so this is what keeps lyric sync tight and jitter-free.

Album art: the player's own thumbnail when it has one, else a downloaded artwork URL (Spotify on macOS), else
an iTunes Search lookup (keyless). Art is fetched once per track, decoded once, and reduced to a small LED
palette (`palette`) that apps use for theming.
"""

from __future__ import annotations

import asyncio
import colorsys
import hashlib
import io
import logging
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import numpy as np

from .base import Provider

log = logging.getLogger("dotdeck.media")

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _Manager,
    )
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _Status,
    )
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions

    AVAILABLE = sys.platform == "win32"
except ImportError:  # non-Windows or winrt missing
    AVAILABLE = False

RGB = tuple[int, int, int]
ITUNES = "https://itunes.apple.com/search"
DEFAULT_PALETTE: list[RGB] = [(255, 72, 24), (255, 170, 0), (255, 0, 190)]
_SEEK_JUMP = 1.5  # s of disagreement that always re-anchors the clock (a seek)
_JITTER = 0.25  # s of disagreement ignored on routine timeline refreshes


def _seconds(v: Any) -> float:
    if isinstance(v, timedelta):
        return v.total_seconds()
    if isinstance(v, (int, float)):
        return float(v) / 1e7  # 100 ns ticks
    return 0.0


# ------------------------------------------------------------------------------------------- model
@dataclass
class Snapshot:
    """One reading from a backend. `position` is valid at `sampled` (time.monotonic())."""

    title: str
    artist: str = ""
    album: str = ""
    playing: bool = False
    position: float = 0.0
    duration: float = 0.0
    app: str = ""  # raw source id: AUMID on Windows, app / bundle name on macOS
    sampled: float = 0.0
    stamp: Any = None  # backend's timeline marker: changes when the player publishes a fresh position
    position_known: bool = True  # False = the player never reports a position (we count from track start)
    art_url: str | None = None


class Backend(Protocol):
    async def snapshot(self) -> Snapshot | None: ...
    async def art(self) -> bytes | None: ...
    async def control(self, action: str) -> bool: ...


# ------------------------------------------------------------------------------------------- sources
_SOURCES: tuple[tuple[str, str, str], ...] = (
    # (substring of the lower-cased app id, source key, label)
    ("cinhimbnkkaeohfgghhklpknlkffjgod", "youtube_music", "YT MUSIC"),  # YouTube Music PWA (Chrome/Edge)
    ("youtube music", "youtube_music", "YT MUSIC"),
    ("youtubemusic", "youtube_music", "YT MUSIC"),
    ("spotify", "spotify", "SPOTIFY"),
    ("applemusic", "apple_music", "APPLE MUSIC"),
    ("com.apple.music", "apple_music", "APPLE MUSIC"),
    ("itunes", "apple_music", "ITUNES"),
    ("zunemusic", "media_player", "MEDIA PLAYER"),
    ("microsoft.media.player", "media_player", "MEDIA PLAYER"),
    ("tidal", "tidal", "TIDAL"),
    ("deezer", "deezer", "DEEZER"),
    ("amazon", "amazon_music", "AMAZON MUSIC"),
    ("soundcloud", "soundcloud", "SOUNDCLOUD"),
    ("pandora", "pandora", "PANDORA"),
    ("foobar", "foobar", "FOOBAR"),
    ("vlc", "vlc", "VLC"),
    ("msedge", "edge", "EDGE"),
    ("edge", "edge", "EDGE"),
    ("chrome", "chrome", "CHROME"),
    ("308046b0af4a39cb", "firefox", "FIREFOX"),  # Firefox's AUMID hash
    ("firefox", "firefox", "FIREFOX"),
    ("brave", "brave", "BRAVE"),
    ("opera", "opera", "OPERA"),
    ("arc", "arc", "ARC"),
    ("safari", "safari", "SAFARI"),
)
BROWSERS = {"chrome", "edge", "firefox", "brave", "opera", "arc", "safari"}


def classify_source(app: str, title: str = "", artist: str = "") -> tuple[str, str]:
    """(source key, short label) for a raw app id, e.g. 'Spotify.exe' -> ('spotify', 'SPOTIFY')."""
    a = (app or "").lower()
    for needle, key, label in _SOURCES:
        if needle in a:
            if key in BROWSERS and artist.lower().endswith(" - topic"):
                return "youtube_music", "YT MUSIC"  # YouTube's auto-generated music channels
            return key, label
    if not a:
        return "other", "MUSIC"
    tail = a.replace("\\", "/").rsplit("/", 1)[-1].split("!")[0].removesuffix(".exe")
    tail = tail.rsplit(".", 1)[-1] if "." in tail else tail
    return "other", (tail[:12].upper() or "MUSIC")


# ------------------------------------------------------------------------------------------- art / palette
def decode_art(data: bytes, size: int = 128) -> Any:
    """Square-crop and resize cover bytes to a PIL RGB image (`size`²), or None if undecodable."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.draft("RGB", (size * 2, size * 2))  # fast JPEG downscale on decode
        img = img.convert("RGB")
    except Exception:
        return None
    w, h = img.size
    if w < 2 or h < 2:
        return None
    if w > h * 1.15:  # video thumbnail: trim letterbox bars (rows of near-black) before squaring
        arr = np.asarray(img.resize((64, 64)), dtype=np.float32).mean(axis=2)
        rows = np.where(arr.mean(axis=1) > 12)[0]
        top, bottom = (rows[0], rows[-1] + 1) if len(rows) else (0, 64)
        y0, y1 = int(top * h / 64), int(bottom * h / 64)
        if y1 - y0 >= h * 0.4:
            img = img.crop((0, y0, w, y1))
            w, h = img.size
    m = min(w, h)
    img = img.crop(((w - m) // 2, (h - m) // 2, (w - m) // 2 + m, (h - m) // 2 + m))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def _rgb_to_hsv(a: np.ndarray) -> np.ndarray:
    """Vectorised RGB (0..1, [..., 3]) -> HSV (0..1)."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=-1), a.min(axis=-1)
    d = mx - mn
    s = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0.0)
    dz = np.maximum(d, 1e-6)
    h = np.where(mx == r, ((g - b) / dz) % 6, np.where(mx == g, (b - r) / dz + 2, (r - g) / dz + 4)) / 6.0
    h = np.where(d > 1e-6, h, 0.0)
    return np.stack([h, s, mx], axis=-1)


def led_color(rgb: tuple[float, float, float] | np.ndarray, min_sat: float = 0.55) -> RGB:
    """Normalise a colour for LEDs: full value, saturation lifted to at least `min_sat` (unless ~grey)."""
    r, g, b = (float(x) / 255.0 for x in rgb)
    h, s, _ = colorsys.rgb_to_hsv(r, g, b)
    s2 = 0.0 if s < 0.08 else min(1.0, max(min_sat, s * 1.15))
    rr, gg, bb = colorsys.hsv_to_rgb(h, s2, 1.0)
    return round(rr * 255), round(gg * 255), round(bb * 255)


def extract_palette(img: Any, n: int = 5) -> list[RGB]:
    """3–`n` dominant, saturated, LED-normalised colours of an image (PIL image or HxWx3 uint8 array).

    Weighted k-means on a 32×32 downscale in a hue-circular space: dark and grey pixels barely count, so the
    palette is the art's *colour*, not its shadows. Most dominant first. Deterministic.
    """
    if not isinstance(img, np.ndarray):
        from PIL import Image

        img = np.asarray(img.convert("RGB").resize((32, 32), Image.Resampling.BILINEAR))
    px = img.reshape(-1, 3).astype(np.float32) / 255.0
    if len(px) > 1024:
        px = px[:: len(px) // 1024 + 1]
    hsv = _rgb_to_hsv(px)
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    w = (s**1.5) * v * (v > 0.12)
    colourful = float(w.sum())
    if colourful < 4.0:  # (nearly) greyscale art
        return [(255, 236, 210), (150, 150, 170), (255, 120, 60)]
    feat = np.stack([np.cos(2 * np.pi * h) * s, np.sin(2 * np.pi * h) * s, v * 0.6], axis=1)
    k = min(6, max(2, int((w > 0.05).sum() // 20)))
    # farthest-point init from the heaviest pixel (deterministic)
    centers = [feat[int(np.argmax(w))]]
    for _ in range(k - 1):
        d = np.min([((feat - c) ** 2).sum(axis=1) for c in centers], axis=0) * (w > 0.02)
        centers.append(feat[int(np.argmax(d))])
    cen = np.array(centers)
    for _ in range(8):
        lab = np.argmin(((feat[:, None, :] - cen[None]) ** 2).sum(axis=2), axis=1)
        for j in range(k):
            m = (lab == j) & (w > 0)
            if m.any():
                cen[j] = (feat[m] * w[m, None]).sum(axis=0) / max(1e-6, w[m].sum())
    lab = np.argmin(((feat[:, None, :] - cen[None]) ** 2).sum(axis=2), axis=1)
    clusters: list[tuple[float, RGB]] = []
    for j in range(k):
        m = lab == j
        wt = float(w[m].sum())
        if wt <= 0.02 * colourful:
            continue
        mean = (px[m] * w[m, None]).sum(axis=0) / max(1e-6, w[m].sum()) * 255.0
        clusters.append((wt, led_color(mean)))
    # colourful clusters first (by weight), greys only if nothing else is left
    clusters.sort(key=lambda c: (max(c[1]) - min(c[1]) < 30, -c[0]))
    out: list[RGB] = []
    for _, c in clusters:
        if out and max(c) - min(c) < 30 and len(out) >= 3:
            break
        hc = colorsys.rgb_to_hsv(*(x / 255 for x in c))
        dup = False
        for o in out:
            ho = colorsys.rgb_to_hsv(*(x / 255 for x in o))
            dh = min(abs(hc[0] - ho[0]), 1 - abs(hc[0] - ho[0]))
            if dh < 0.05 and abs(hc[1] - ho[1]) < 0.3:
                dup = True
                break
        if not dup:
            out.append(c)
        if len(out) >= n:
            break
    base = colorsys.rgb_to_hsv(*(x / 255 for x in out[0]))
    shift = 0.08
    while len(out) < 3:  # pad with analogous hues so themes always have 3 colours
        hh = (base[0] + shift) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hh, max(0.55, base[1]), 1.0)
        out.append((round(r * 255), round(g * 255), round(b * 255)))
        shift = -shift * 1.6
    return out


# ------------------------------------------------------------------------------------------- Windows
class WinBackend:
    """GSMTC via winrt. Picks the playing session when several apps have one."""

    def __init__(self) -> None:
        self._mgr: Any = None
        self._session: Any = None
        self._props: Any = None

    async def _manager(self) -> Any:
        if self._mgr is None:
            self._mgr = await _Manager.request_async()
        return self._mgr

    def _pick(self, mgr: Any) -> Any:
        current = mgr.get_current_session()
        try:
            sessions = list(mgr.get_sessions())
        except Exception:
            sessions = []
        if not sessions:
            return current

        def rank(s: Any) -> tuple[int, int]:
            try:
                st = s.get_playback_info().playback_status
            except Exception:
                st = None
            cur = (
                1
                if current is not None and s.source_app_user_model_id == current.source_app_user_model_id
                else 0
            )
            return (2 if st == _Status.PLAYING else 1 if st == _Status.PAUSED else 0, cur)

        return max(sessions, key=rank)

    async def snapshot(self) -> Snapshot | None:
        mgr = await self._manager()
        s = self._pick(mgr)
        self._session = s
        if s is None:
            return None
        props = await s.try_get_media_properties_async()
        self._props = props
        if props is None or not props.title:
            return None
        playing = s.get_playback_info().playback_status == _Status.PLAYING
        tl = s.get_timeline_properties()
        pos = _seconds(tl.position) - _seconds(tl.start_time)
        dur = _seconds(tl.end_time) - _seconds(tl.start_time)
        upd = tl.last_updated_time
        known = isinstance(upd, datetime) and upd.year > 1971
        mono = time.monotonic()
        if playing and known:
            now = datetime.now(upd.tzinfo) if upd.tzinfo else datetime.now()
            pos += max(0.0, (now - upd).total_seconds())
        if dur > 0:
            pos = min(pos, dur)
        known = known and (pos > 0 or dur > 0)
        return Snapshot(
            title=props.title,
            artist=props.artist or "",
            album=props.album_title or "",
            playing=playing,
            position=max(0.0, pos),
            duration=max(0.0, dur),
            app=s.source_app_user_model_id or "",
            sampled=mono,
            stamp=(upd, _seconds(tl.position)) if known else None,
            position_known=known,
        )

    async def art(self) -> bytes | None:
        props = self._props
        if props is None:
            return None
        ref = props.thumbnail
        if ref is None:
            return None
        try:
            stream = await ref.open_read_async()
            size = int(stream.size)
            if not size:
                return None
            buf = Buffer(size)
            await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
            reader = DataReader.from_buffer(buf)
            out = bytearray(buf.length)
            reader.read_bytes(out)
            return bytes(out)
        except Exception as e:
            log.debug("album art read failed: %s", e)
            return None

    async def control(self, action: str) -> bool:
        mgr = await self._manager()
        s = self._session or self._pick(mgr)
        if s is None:
            return False
        op = {
            "toggle": s.try_toggle_play_pause_async,
            "play": s.try_play_async,
            "pause": s.try_pause_async,
            "next": s.try_skip_next_async,
            "prev": s.try_skip_previous_async,
        }.get(action)
        if op is None:
            raise KeyError(action)
        return bool(await op())


def make_backend() -> Backend | None:
    if sys.platform == "win32" and AVAILABLE:
        return WinBackend()
    if sys.platform == "darwin":
        from .media_mac import MacBackend

        return MacBackend()
    return None


# ------------------------------------------------------------------------------------------- provider
class MediaProvider(Provider[dict[str, Any]]):
    name = "media"
    interval = 1.0
    retry = 5.0

    def __init__(self, hub: Any, backend: Backend | None = None) -> None:
        super().__init__(hub)
        self._backend: Backend | None = backend
        self._backend_made = backend is not None
        self._track: str | None = None
        self.art: bytes | None = None  # raw image bytes of the current cover
        self.art_id: str | None = None
        self.art_image: Any = None  # decoded, square 128×128 PIL image of `art` (None without art)
        self.art_source: str | None = None  # "player" | "url" | "itunes"
        self.palette: list[RGB] = list(DEFAULT_PALETTE)
        self.source, self.source_label = "other", "MUSIC"
        self._pos = 0.0
        self._pos_at = 0.0  # monotonic time `_pos` was sampled
        self._playing = False
        self._duration = 0.0
        self._stamp: Any = None
        self._art_task: asyncio.Task[None] | None = None
        self._itunes: OrderedDict[str, bytes | None] = OrderedDict()
        self._url_art: OrderedDict[str, bytes | None] = OrderedDict()

    @property
    def backend(self) -> Backend | None:
        if not self._backend_made:
            self._backend_made = True
            self._backend = make_backend()
        return self._backend

    @property
    def position(self) -> float:
        """Playback position in seconds, extrapolated to *now*."""
        if not self._playing:
            return self._pos
        p = self._pos + (time.monotonic() - self._pos_at)
        return min(p, self._duration) if self._duration > 0 else p

    # ------------------------------------------------------------------ clock
    def _sync(self, snap: Snapshot, new_track: bool) -> None:
        now = time.monotonic()
        reported = snap.position + ((now - snap.sampled) if snap.playing and snap.sampled else 0.0)
        ours = self.position
        state_changed = snap.playing != self._playing
        stamp_changed = snap.stamp != self._stamp
        if new_track and not snap.position_known:
            self._pos, self._pos_at = 0.0, now  # count from track start
        elif new_track or (state_changed and snap.position_known):
            self._pos, self._pos_at = reported, now
        elif state_changed:
            self._pos, self._pos_at = ours, now  # freeze / resume our own count
        elif snap.position_known:
            diff = abs(reported - ours)
            if diff > _SEEK_JUMP or (stamp_changed and diff > _JITTER):
                self._pos, self._pos_at = reported, now
        self._playing, self._stamp, self._duration = snap.playing, snap.stamp, snap.duration

    # ------------------------------------------------------------------ fetch
    async def fetch(self) -> dict[str, Any]:
        be = self.backend
        if be is None:
            raise RuntimeError("media info needs Windows (winrt) or macOS")
        snap = await be.snapshot()
        if snap is None or not snap.title:
            self._playing = False
            return {"active": False}
        track = f"{snap.title}\x1f{snap.artist}"
        new_track = track != self._track
        self._sync(snap, new_track)
        if new_track:
            self._track = track
            self.source, self.source_label = classify_source(snap.app, snap.title, snap.artist)
            self._reset_art()
            if self._art_task and not self._art_task.done():
                self._art_task.cancel()
            self._art_task = asyncio.get_running_loop().create_task(self._load_art(track, snap))
        return {
            "active": True,
            "title": snap.title,
            "artist": snap.artist,
            "album": snap.album,
            "playing": snap.playing,
            "position": self.position,
            "duration": snap.duration,
            "app": snap.app,
            "is_spotify": self.source == "spotify",
            "source": self.source,
            "source_label": self.source_label,
            "art_id": self.art_id,
            "art_source": self.art_source,
            "palette": [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in self.palette],
            "track": track,
        }

    def _reset_art(self) -> None:
        self.art = self.art_id = self.art_image = self.art_source = None
        self.palette = list(DEFAULT_PALETTE)

    async def _set_art(self, track: str, data: bytes, source: str) -> bool:
        img = await asyncio.to_thread(decode_art, data)
        if img is None or track != self._track:
            return False
        pal = await asyncio.to_thread(extract_palette, img)
        if track != self._track:
            return False
        self.art, self.art_image, self.palette, self.art_source = data, img, pal, source
        self.art_id = hashlib.sha1(data).hexdigest()[:12]
        self.refresh()
        return True

    async def _load_art(self, track: str, snap: Snapshot) -> None:
        """Player art (retried: browsers attach it late, Spotify sometimes sends the previous cover first),
        then the artwork URL, then iTunes."""
        be = self.backend
        try:
            got: bytes | None = None
            for delay in (0.0, 1.5, 2.5):
                if delay:
                    await asyncio.sleep(delay)
                if track != self._track or be is None:
                    return
                data = await be.art()
                if data and data != got and await self._set_art(track, data, "player"):
                    got = data
                if got and delay >= 1.5:
                    return  # confirmed on a second read
            if got:
                return
            if snap.art_url:
                data = await self._download(snap.art_url, self._url_art)
                if data and await self._set_art(track, data, "url"):
                    return
            data = await self._itunes_art(snap.title, snap.artist)
            if data:
                await self._set_art(track, data, "itunes")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("art lookup failed for %s: %s", snap.title, e)

    async def _download(self, url: str, cache: OrderedDict[str, bytes | None]) -> bytes | None:
        if url in cache:
            return cache[url]
        try:
            r = await self.hub.http.get(url)
            data = r.content if r.status_code == 200 and r.content else None
        except Exception as e:
            log.debug("art download failed: %s", e)
            return None  # not cached: retry next time
        cache[url] = data
        while len(cache) > 64:
            cache.popitem(last=False)
        return data

    async def _itunes_art(self, title: str, artist: str) -> bytes | None:
        """Cover from the iTunes Search API (keyless), upscaled to 600×600. Cached, misses too."""
        from .lyrics import normalize_track

        t, a = normalize_track(title, artist)
        term = f"{a} {t}".strip()
        if not term:
            return None
        if term in self._itunes:
            return self._itunes[term]
        try:
            r = await self.hub.http.get(ITUNES, params={"term": term, "entity": "song", "limit": 1})
            r.raise_for_status()
            results = r.json().get("results") or []
        except Exception as e:
            log.debug("itunes lookup failed: %s", e)
            return None
        url = (results[0].get("artworkUrl100") or "") if results else ""
        data = None
        if url:
            big = url.replace("100x100bb", "600x600bb").replace("100x100", "600x600")
            data = await self._download(big, self._url_art) or await self._download(url, self._url_art)
        self._itunes[term] = data
        while len(self._itunes) > 64:
            self._itunes.popitem(last=False)
        return data

    async def control(self, action: str) -> bool:
        be = self.backend
        if be is None:
            return False
        ok = bool(await be.control(action))
        self.refresh()
        return ok
