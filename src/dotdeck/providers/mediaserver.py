"""Recently added media and now-streaming sessions from Plex or Jellyfin.

Plex (``X-Plex-Token`` header, JSON via ``Accept: application/json``):
    ``GET /library/recentlyAdded`` · posters via ``GET /photo/:/transcode?url=<thumb>&width=&height=`` ·
    sessions via ``GET /status/sessions``.
Jellyfin (API key sent as the ``X-Emby-Token`` header, never in the URL — the same key the docs pass as
``api_key``): ``GET /Users`` (to resolve the user) → ``GET /Users/{id}/Items/Latest`` · posters via
``GET /Items/{id}/Images/Primary`` · sessions via ``GET /Sessions``.

Posters are fetched once per item, decoded off the event loop, fitted to the panel and passed through
``color.calibrate`` exactly once (rule 9); the value carries ready-to-blit pixel arrays.
"""

from __future__ import annotations

import asyncio
import io
import time
from typing import Any

import numpy as np

from .base import Provider
from .radiator import base_url, panel_text, safe_error

DEFAULT_PORT = {"plex": 32400, "jellyfin": 8096}
ITEMS = 6  # recently added items kept
POSTERS = 3  # items that get artwork (the shelf shows three)
THUMB_W, THUMB_H = 10, 15


def process_poster(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Image bytes -> (32×32 cover crop, 10×15 thumb), both calibrated for LEDs. Blocking: run in a thread."""
    from PIL import Image, ImageOps

    from ..gfx.color import calibrate
    from ..gfx.image import fit_image

    img = Image.open(io.BytesIO(data))
    img.load()
    rgb = img.convert("RGB")
    cover = calibrate(fit_image(rgb, "cover", pixel_art=False), "vibrant")
    thumb = calibrate(ImageOps.fit(rgb, (THUMB_W, THUMB_H), Image.Resampling.LANCZOS), "vibrant")
    return np.asarray(cover, dtype=np.uint8).copy(), np.asarray(thumb, dtype=np.uint8).copy()


# ---------------------------------------------------------------------------- parsers
def _plex_item(m: dict[str, Any]) -> dict[str, Any]:
    kind = str(m.get("type") or "")
    title, sub, thumb = str(m.get("title") or ""), "", m.get("thumb")
    if kind == "episode":
        s, e = m.get("parentIndex"), m.get("index")
        title = str(m.get("grandparentTitle") or title)
        sub = (
            f"S{int(s):02d}E{int(e):02d}"
            if isinstance(s, int) and isinstance(e, int)
            else str(m.get("title") or "")
        )
        thumb = m.get("grandparentThumb") or m.get("parentThumb") or thumb
    elif kind == "season":
        title = str(m.get("parentTitle") or title)
        sub = str(m.get("title") or "SEASON")
        thumb = m.get("thumb") or m.get("parentThumb")
    elif kind == "album":
        sub = str(m.get("parentTitle") or "")
    elif kind == "movie":
        sub = str(m.get("year") or "")
    return {
        "id": str(m.get("ratingKey") or m.get("key") or title),
        "title": panel_text(title, 80),
        "sub": panel_text(sub, 40),
        "kind": {"episode": "TV", "season": "TV", "show": "TV", "movie": "MOVIE", "album": "MUSIC"}.get(
            kind, kind.upper()[:5]
        ),
        "added": m.get("addedAt"),
        "art": thumb,
    }


def parse_plex_recent(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mc = payload.get("MediaContainer") or {}
    return [_plex_item(m) for m in (mc.get("Metadata") or [])[:ITEMS] if isinstance(m, dict)]


def parse_plex_sessions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in (payload.get("MediaContainer") or {}).get("Metadata") or []:
        title = m.get("grandparentTitle") or m.get("title") or ""
        dur, off = m.get("duration"), m.get("viewOffset")
        out.append(
            {
                "user": panel_text((m.get("User") or {}).get("title") or "?", 16),
                "title": panel_text(title, 60),
                "state": str((m.get("Player") or {}).get("state") or "playing"),
                "progress": (off / dur) if isinstance(off, (int, float)) and dur else None,
            }
        )
    return out


def _jf_item(m: dict[str, Any]) -> dict[str, Any]:
    kind = str(m.get("Type") or "")
    title, sub = str(m.get("Name") or ""), ""
    art_id = m.get("Id") if (m.get("ImageTags") or {}).get("Primary") else None
    if kind == "Episode":
        title = str(m.get("SeriesName") or title)
        s, e = m.get("ParentIndexNumber"), m.get("IndexNumber")
        sub = (
            f"S{int(s):02d}E{int(e):02d}"
            if isinstance(s, int) and isinstance(e, int)
            else str(m.get("Name") or "")
        )
        if m.get("SeriesPrimaryImageTag") and m.get("SeriesId"):
            art_id = m.get("SeriesId")
    elif kind == "Series":
        n = m.get("ChildCount") or (m.get("UserData") or {}).get("UnplayedItemCount")
        sub = f"{n} NEW" if n else "SERIES"
    elif kind == "MusicAlbum":
        sub = str(m.get("AlbumArtist") or "")
    else:
        sub = str(m.get("ProductionYear") or "")
    return {
        "id": str(m.get("Id") or title),
        "title": panel_text(title, 80),
        "sub": panel_text(sub, 40),
        "kind": {
            "Episode": "TV",
            "Series": "TV",
            "Season": "TV",
            "Movie": "MOVIE",
            "MusicAlbum": "MUSIC",
        }.get(kind, kind.upper()[:5]),
        "added": m.get("DateCreated"),
        "art": art_id,
    }


def parse_jellyfin_latest(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_jf_item(m) for m in (payload or [])[:ITEMS] if isinstance(m, dict)]


def parse_jellyfin_sessions(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in payload or []:
        item = s.get("NowPlayingItem")
        if not item:
            continue
        ticks, pos = item.get("RunTimeTicks"), (s.get("PlayState") or {}).get("PositionTicks")
        out.append(
            {
                "user": panel_text(s.get("UserName") or "?", 16),
                "title": panel_text(item.get("SeriesName") or item.get("Name") or "", 60),
                "state": "paused" if (s.get("PlayState") or {}).get("IsPaused") else "playing",
                "progress": (pos / ticks) if isinstance(pos, (int, float)) and ticks else None,
            }
        )
    return out


# ---------------------------------------------------------------------------- provider
class MediaServerProvider(Provider[dict[str, Any]]):
    """``value = {"server", "items": [{id, title, sub, kind, cover, thumb}], "sessions": [...]}``."""

    name = "mediaserver"
    interval = 300.0
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.kind, self.host, self.port, self.token, self.user = "plex", "", 0, "", ""
        self.sessions = True
        self._art: dict[str, tuple[np.ndarray, np.ndarray] | None] = {}
        self._uid: str | None = None

    def configure(
        self, kind: str, host: str, port: int, token: str, user: str = "", sessions: bool = True
    ) -> None:
        cfg = (kind, host.strip(), int(port), token, user.strip())
        self.sessions = sessions
        if cfg != (self.kind, self.host, self.port, self.token, self.user):
            self.kind, self.host, self.port, self.token, self.user = cfg
            self._art.clear()
            self._uid = None
            self.value = None
            self.refresh()

    def next_interval(self) -> float:
        return 60.0 if self.sessions else self.interval

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        def key(d: dict[str, Any] | None) -> Any:
            d = d or {}
            return (
                [i["id"] for i in d.get("items", [])],
                [(s["user"], s["title"], s["state"]) for s in d.get("sessions", [])],
            )

        return key(old) != key(new)

    @property
    def url(self) -> str:
        return base_url(self.host, self.port or DEFAULT_PORT.get(self.kind, 32400))

    def _headers(self) -> dict[str, str]:
        if self.kind == "plex":
            return {"X-Plex-Token": self.token, "Accept": "application/json"}
        return {"X-Emby-Token": self.token, "Accept": "application/json"}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        r = await self.hub.http.get(self.url + path, params=params, headers=self._headers())
        if r.status_code in (401, 403):
            raise PermissionError("the server rejected the token")
        r.raise_for_status()
        return r

    async def _poster(self, item: dict[str, Any]) -> tuple[np.ndarray, np.ndarray] | None:
        art = item.get("art")
        if not art:
            return None
        if self.kind == "plex":
            path, params = (
                "/photo/:/transcode",
                {"url": art, "width": 96, "height": 144, "minSize": 1, "upscale": 1},
            )
        else:
            path, params = f"/Items/{art}/Images/Primary", {"fillWidth": 96, "fillHeight": 144, "quality": 90}
        r = await self._get(path, params)
        return await asyncio.to_thread(process_poster, r.content)

    async def _plex(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        r = await self._get(
            "/library/recentlyAdded", {"X-Plex-Container-Start": 0, "X-Plex-Container-Size": ITEMS}
        )
        items = parse_plex_recent(r.json())
        sessions: list[dict[str, Any]] = []
        if self.sessions:
            sessions = parse_plex_sessions((await self._get("/status/sessions")).json())
        return items, sessions

    async def _jellyfin(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if self._uid is None:
            users = (await self._get("/Users")).json() or []
            want = self.user.lower()
            pick = next(
                (u for u in users if want and str(u.get("Name", "")).lower() == want),
                users[0] if users else None,
            )
            if not pick:
                raise LookupError("no Jellyfin user")
            self._uid = str(pick["Id"])
        r = await self._get(
            f"/Users/{self._uid}/Items/Latest",
            {
                "Limit": ITEMS,
                "Fields": "ProductionYear,DateCreated,ChildCount",
                "EnableImageTypes": "Primary",
            },
        )
        items = parse_jellyfin_latest(r.json())
        sessions: list[dict[str, Any]] = []
        if self.sessions:
            sessions = parse_jellyfin_sessions(
                (await self._get("/Sessions", {"activeWithinSeconds": 960})).json()
            )
        return items, sessions

    async def fetch(self) -> dict[str, Any]:
        if not self.host or not self.token:
            return {"server": self.kind, "state": "unset", "items": [], "sessions": []}
        try:
            items, sessions = await (self._plex() if self.kind == "plex" else self._jellyfin())
        except PermissionError:
            return {"server": self.kind, "state": "auth", "items": [], "sessions": []}
        except Exception as e:
            raise RuntimeError(safe_error(e, self.token)) from None
        for it in items[:POSTERS]:
            if it["id"] not in self._art:
                try:
                    self._art[it["id"]] = await self._poster(it)
                except Exception:
                    self._art[it["id"]] = None  # no artwork: the app draws a placeholder
        keep = {it["id"] for it in items}
        self._art = {k: v for k, v in self._art.items() if k in keep}
        for it in items:
            art = self._art.get(it["id"])
            it["cover"], it["thumb"] = art if art else (None, None)
            it.pop("art", None)
        return {
            "server": self.kind,
            "state": "ok",
            "items": items,
            "sessions": sessions,
            "fetched": time.time(),
        }
