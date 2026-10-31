"""Browser now-playing backend (used by `media.MediaProvider` in the web app, docs/WEB_APP.md).

A browser tab can't read the computer's media session, and the studio's own tab plays nothing, so the browser app
asks a *listening service* what you are playing, or takes the track you type in. The source is chosen in Now
Playing's settings ("In the browser" group, stored with the app's settings):

* **ListenBrainz** (`listenbrainz`): `GET https://api.listenbrainz.org/1/user/<name>/playing-now`, keyless and
  CORS-friendly. Works with anything that sends "playing now" to ListenBrainz (the Web Scrobbler browser extension,
  Pano Scrobbler on Android, many players). Cover art from the Cover Art Archive when the listen names a release.
* **Last.fm** (`lastfm`): `user.getRecentTracks` with your own free API key (last.fm/api/account/create); the
  newest track counts while Last.fm marks it "now playing". Spotify, Apple Music, YouTube Music (via Web Scrobbler)
  and most players can scrobble to Last.fm.
* **Typed in** (`manual`): the title and artist you enter; shows as playing until you clear the title.

No position comes from these services: the provider counts from the start of each track (`position_known=False`).
There are no transport controls (play / pause / next) in a tab. Answers are cached for `POLL_S` so the 1 s provider
tick never hammers an API.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

from .media import Snapshot

log = logging.getLogger("deskdot.media.web")

LISTENBRAINZ = "https://api.listenbrainz.org/1/user/{user}/playing-now"
LASTFM = "https://ws.audioscrobbler.com/2.0/"
COVER_ART = "https://coverartarchive.org/release/{mbid}/front-250"
#: seconds between two questions to a listening service (a track lasts minutes; both services ask for restraint)
POLL_S = 15.0
SOURCES = ("manual", "listenbrainz", "lastfm")


def settings_of(store: Any) -> dict[str, Any]:
    """Now Playing's stored settings (the browser source lives there, edited through the app's settings form)."""
    try:
        apps = store.section("apps")
    except Exception:
        return {}
    s = apps.get("nowplaying") if isinstance(apps, dict) else None
    return s if isinstance(s, dict) else {}


def parse_listenbrainz(j: Any) -> Snapshot | None:
    """`playing-now` answer → a Snapshot, or None when nothing is playing."""
    listens = ((j or {}).get("payload") or {}).get("listens") or []
    if not listens:
        return None
    meta = listens[0].get("track_metadata") or {}
    title = str(meta.get("track_name") or "").strip()
    if not title:
        return None
    info = meta.get("additional_info") or {}
    ms = info.get("duration_ms") or (info.get("duration") or 0) * 1000
    mbid = str(info.get("release_mbid") or "").strip()
    app = str(info.get("music_service_name") or info.get("media_player") or "listenbrainz")
    return Snapshot(
        title=title,
        artist=str(meta.get("artist_name") or "").strip(),
        album=str(meta.get("release_name") or "").strip(),
        playing=True,
        duration=float(ms or 0) / 1000.0,
        app=app,
        sampled=time.monotonic(),
        position_known=False,
        art_url=COVER_ART.format(mbid=mbid) if mbid else None,
    )


def parse_lastfm(j: Any) -> Snapshot | None:
    """`user.getRecentTracks` answer → a Snapshot while the newest track is "now playing", else None."""
    if isinstance(j, dict) and j.get("error"):
        raise RuntimeError(f"Last.fm: {j.get('message') or 'error ' + str(j['error'])}")
    tracks = ((j or {}).get("recenttracks") or {}).get("track") or []
    if isinstance(tracks, dict):
        tracks = [tracks]
    if not tracks:
        return None
    t = tracks[0]
    if str((t.get("@attr") or {}).get("nowplaying", "")).lower() != "true":
        return None
    title = str(t.get("name") or "").strip()
    if not title:
        return None

    def text(v: Any) -> str:
        return str((v or {}).get("#text") or "").strip() if isinstance(v, dict) else str(v or "").strip()

    art = ""
    for img in t.get("image") or []:  # small → extralarge; the biggest wins
        url = text(img)
        if url and "2a96cbd8b46e442fc41c2b86b821562f" not in url:  # Last.fm's grey star placeholder
            art = url
    return Snapshot(
        title=title,
        artist=text(t.get("artist")),
        album=text(t.get("album")),
        playing=True,
        app="lastfm",
        sampled=time.monotonic(),
        position_known=False,
        art_url=art or None,
    )


class WebBackend:
    """Now playing from a listening service or typed in (see the module docstring)."""

    can_control = False  # a tab can't press play / pause / next in another app
    player_art = False  # covers come from `art_url` (Last.fm, Cover Art Archive) or the iTunes lookup

    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self._cache: tuple[tuple[str, str, str], float, Snapshot | None] | None = None

    def _cfg(self) -> dict[str, Any]:
        return settings_of(getattr(self.hub, "store", None))

    async def snapshot(self) -> Snapshot | None:
        s = self._cfg()
        source = str(s.get("web_source") or "manual")
        if source not in SOURCES:
            source = "manual"
        if source == "manual":
            title = str(s.get("web_title") or "").strip()
            if not title:
                return None
            return Snapshot(
                title=title,
                artist=str(s.get("web_artist") or "").strip(),
                playing=True,
                app="typed in",
                sampled=time.monotonic(),
                position_known=False,
            )
        user = str(s.get("web_user") or "").strip()
        key = str(s.get("web_api_key") or "").strip()
        if not user:
            raise RuntimeError(f"set your {'Last.fm' if source == 'lastfm' else 'ListenBrainz'} user name")
        if source == "lastfm" and not key:
            raise RuntimeError("set your Last.fm API key (free: last.fm/api/account/create)")
        cfg = (source, user, key)
        now = time.monotonic()
        if self._cache and self._cache[0] == cfg and now - self._cache[1] < POLL_S:
            return self._cache[2]
        snap = await self._ask(source, user, key)
        self._cache = (cfg, now, snap)
        return snap

    async def _ask(self, source: str, user: str, key: str) -> Snapshot | None:
        http = self.hub.http
        if source == "listenbrainz":
            r = await http.get(LISTENBRAINZ.format(user=quote(user, safe="")))
            if r.status_code == 404:
                raise RuntimeError(f"ListenBrainz has no user {user!r}")
            r.raise_for_status()
            return parse_listenbrainz(r.json())
        r = await http.get(
            LASTFM,
            params={
                "method": "user.getrecenttracks",
                "user": user,
                "api_key": key,
                "format": "json",
                "limit": 1,
            },
        )
        if r.status_code in (400, 403):  # bad key / unknown user: Last.fm says which in the body
            try:
                return parse_lastfm(r.json())
            except ValueError:
                pass
        r.raise_for_status()
        return parse_lastfm(r.json())

    async def art(self) -> bytes | None:
        return None  # the provider downloads `art_url` (or asks iTunes) itself

    async def control(self, action: str) -> bool:
        return False
