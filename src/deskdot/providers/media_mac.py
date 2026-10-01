"""macOS now-playing backend (used by `media.MediaProvider` when `sys.platform == "darwin"`).

Sources, in priority order (a *playing* source always beats a paused one):

1. **Spotify** — AppleScript: title, artist, album, duration, position, state and the cover's `artwork url`.
2. **Music.app** (Apple Music / iTunes library) — AppleScript: the same fields; cover from `raw data of artwork 1`.
3. **nowplaying-cli** (optional, `brew install nowplaying-cli`) — anything that publishes to the system
   Now Playing widget: browsers (YouTube, YouTube Music, SoundCloud…), Podcasts, VLC, … Only used if it is on
   PATH. Note: on macOS 15.4+ Apple restricted the private MediaRemote API it relies on; it may return nothing.

Everything runs as short-lived subprocesses through asyncio (never blocking the loop), with timeouts.
Apps are only scripted when their process is already running (checked with `ps`), so polling never launches
Spotify/Music and never triggers "Where is Spotify?" dialogs.

Permissions: the first AppleScript call makes macOS ask *"<Terminal/Python> wants to control Spotify/Music"*
(System Settings → Privacy & Security → Automation). If it is denied, osascript fails with error -1743 and this
backend logs a hint and falls back to the next source.

Numbers from AppleScript are locale-formatted ("12,5" in many locales); the parsers accept both separators.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import re
import shutil
import time
from datetime import datetime

from .media import Snapshot

log = logging.getLogger("deskdot.media.mac")

SEP = "\x1f"  # AppleScript: character id 31

SPOTIFY_SCRIPT = """
if application "Spotify" is running then
  tell application "Spotify"
    set st to player state as string
    if st is "stopped" then return "stopped"
    set sep to character id 31
    set t to current track
    return st & sep & (name of t) & sep & (artist of t) & sep & (album of t) & sep & ((duration of t) as string) & sep & ((player position) as string) & sep & (artwork url of t) & sep & (id of t)
  end tell
end if
return "none"
""".strip()

MUSIC_SCRIPT = """
if application "Music" is running then
  tell application "Music"
    set st to player state as string
    if st is "stopped" then return "stopped"
    set sep to character id 31
    set nm to ""
    set ar to ""
    set al to ""
    set du to "0"
    set tid to ""
    try
      set t to current track
      set nm to name of t
      set ar to artist of t
      set al to album of t
      set du to (duration of t) as string
      set tid to persistent ID of t
    on error
      try
        set nm to current stream title
      end try
    end try
    return st & sep & nm & sep & ar & sep & al & sep & du & sep & ((player position) as string) & sep & "" & sep & tid
  end tell
end if
return "none"
""".strip()

MUSIC_ART_SCRIPT = 'tell application "Music" to get raw data of artwork 1 of current track'

_CONTROL = {
    # action: (AppleScript verb, nowplaying-cli verb)
    "toggle": ("playpause", "togglePlayPause"),
    "play": ("play", "play"),
    "pause": ("pause", "pause"),
    "next": ("next track", "next"),
    "prev": ("previous track", "previous"),
}
_APP_NAME = {"spotify": "Spotify", "music": "Music"}
_NPCLI_PROPS = ("title", "artist", "album", "duration", "elapsedTime", "playbackRate", "timestamp")


def _num(s: str) -> float:
    """Parse an AppleScript number that may use a locale decimal comma ("12,5") or be empty/missing."""
    s = (s or "").strip().replace(" ", "").replace(" ", "")
    if not s or s in ("missing value", "null"):
        return 0.0
    s = s.replace(",", ".") if "," in s and "." not in s else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_player(out: str, app: str, sampled: float | None = None) -> Snapshot | None:
    """Parse the output of SPOTIFY_SCRIPT / MUSIC_SCRIPT. None when stopped / not running / garbled."""
    out = (out or "").strip("\r\n")
    if not out or out in ("none", "stopped") or SEP not in out:
        return None
    parts = out.split(SEP)
    parts += [""] * (8 - len(parts))
    raw_state, title, artist, album, dur_s, pos_s, art_url, _track_id = parts[:8]
    raw_state = raw_state.strip()
    # Spotify codes: kPSP playing, kPSp paused, kPSS stopped (case matters)
    state = {"kPSP": "playing", "kPSp": "paused", "kPSS": "stopped"}.get(raw_state, raw_state.lower())
    if state == "stopped" or not title.strip():
        return None
    dur = _num(dur_s)
    if app == "spotify" or dur > 36000:  # Spotify reports milliseconds
        dur /= 1000.0
    pos = _num(pos_s)
    art_url = art_url.strip()
    return Snapshot(
        title=title.strip(),
        artist="" if artist.strip() == "missing value" else artist.strip(),
        album="" if album.strip() == "missing value" else album.strip(),
        playing=state in ("playing", "fast forwarding", "rewinding"),
        position=max(0.0, pos),
        duration=max(0.0, dur),
        app=app,
        sampled=time.monotonic() if sampled is None else sampled,
        stamp=round(pos, 2),
        position_known=True,
        art_url=art_url if art_url.startswith("http") else None,
    )


def parse_nowplaying_cli(out: str, sampled: float | None = None) -> Snapshot | None:
    """Parse `nowplaying-cli get title artist album duration elapsedTime playbackRate timestamp` (one per line)."""
    lines = (out or "").splitlines()
    if len(lines) < 3:
        return None
    vals = dict(zip(_NPCLI_PROPS, (ln.strip() for ln in lines), strict=False))
    title = vals.get("title", "")
    if not title or title == "null":
        return None

    def clean(k: str) -> str:
        v = vals.get(k, "")
        return "" if v in ("null", "(null)") else v

    rate = _num(clean("playbackRate"))
    pos = _num(clean("elapsedTime"))
    playing = rate > 0
    stamp = clean("timestamp")
    if playing and stamp:  # elapsedTime is as of `timestamp`
        for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                ts = datetime.strptime(stamp.replace("Z", "+0000"), fmt)
                pos += max(0.0, (datetime.now(ts.tzinfo) - ts).total_seconds()) * (rate or 1.0)
                break
            except ValueError:
                continue
    return Snapshot(
        title=title,
        artist=clean("artist"),
        album=clean("album"),
        playing=playing,
        position=max(0.0, pos),
        duration=max(0.0, _num(clean("duration"))),
        app="nowplaying",
        sampled=time.monotonic() if sampled is None else sampled,
        stamp=stamp or round(pos, 1),
        position_known=bool(clean("elapsedTime")),
    )


def parse_applescript_data(out: str) -> bytes | None:
    """«data JPEG FFD8…» / «data tdta…» / «data PNGf…» -> raw bytes."""
    m = re.search(r"«data\s*(\w{4})([0-9A-Fa-f\s]+)»", out or "")
    if not m:
        return None
    try:
        return binascii.unhexlify(re.sub(r"\s+", "", m.group(2)))
    except (binascii.Error, ValueError):
        return None


class MacBackend:
    """Spotify / Music.app through osascript, everything else through nowplaying-cli (if installed)."""

    PS_TTL = 3.0

    def __init__(self) -> None:
        self._current: str | None = None  # "spotify" | "music" | "nowplaying"
        self._running: set[str] = set()
        self._running_at = 0.0
        self._npcli = shutil.which("nowplaying-cli")
        self._denied: set[str] = set()

    # ---------------------------------------------------------------- subprocess
    async def _run(self, *args: str, limit: float = 3.0) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except (FileNotFoundError, PermissionError) as e:
            log.debug("cannot run %s: %s", args[0], e)
            return None
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=limit)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            log.debug("%s timed out", args[0])
            return None
        if proc.returncode != 0:
            msg = err.decode("utf-8", "replace").strip()
            if "-1743" in msg or "Not authorized" in msg:
                if args[0] not in self._denied:
                    self._denied.add(args[0])
                    log.warning(
                        "macOS blocked Apple Events (%s). Allow it in System Settings → Privacy & Security → "
                        "Automation.",
                        msg[:120],
                    )
            else:
                log.debug("%s failed (%s): %s", args[0], proc.returncode, msg[:200])
            return None
        return out.decode("utf-8", "replace")

    async def _osascript(self, script: str, limit: float = 3.0) -> str | None:
        return await self._run("osascript", "-e", script, limit=limit)

    async def _running_apps(self) -> set[str]:
        now = time.monotonic()
        if now - self._running_at > self.PS_TTL:
            out = await self._run("ps", "-Axo", "comm=")
            names = {os.path.basename(ln.strip()) for ln in (out or "").splitlines() if ln.strip()}
            self._running = {k for k, v in _APP_NAME.items() if v in names}
            self._running_at = now
        return self._running

    # ---------------------------------------------------------------- backend API
    async def _read(self, source: str) -> Snapshot | None:
        t0 = time.monotonic()
        if source == "nowplaying":
            if not self._npcli:
                return None
            out = await self._run(self._npcli, "get", *_NPCLI_PROPS)
            return parse_nowplaying_cli(out or "", sampled=(t0 + time.monotonic()) / 2)
        script = SPOTIFY_SCRIPT if source == "spotify" else MUSIC_SCRIPT
        out = await self._osascript(script)
        return parse_player(out or "", source, sampled=(t0 + time.monotonic()) / 2)

    async def snapshot(self) -> Snapshot | None:
        running = await self._running_apps()
        order = [s for s in ("spotify", "music") if s in running]
        if self._npcli:
            order.append("nowplaying")
        paused: tuple[str, Snapshot] | None = None
        for src in order:
            snap = await self._read(src)
            if snap is None:
                continue
            if snap.playing:
                self._current = src
                return snap
            paused = paused or (src, snap)
        if paused:
            self._current = paused[0]
            return paused[1]
        self._current = None
        return None

    async def art(self) -> bytes | None:
        """Cover bytes for the current source (Spotify's comes as a URL on the snapshot instead)."""
        if self._current == "music":
            out = await self._osascript(MUSIC_ART_SCRIPT, limit=5.0)
            return parse_applescript_data(out or "")
        if self._current == "nowplaying" and self._npcli:
            out = await self._run(self._npcli, "get", "artworkData", limit=5.0)
            data = (out or "").strip()
            if data and data != "null":
                try:
                    return base64.b64decode(data, validate=False)
                except (binascii.Error, ValueError):
                    return None
        return None

    async def control(self, action: str) -> bool:
        if action not in _CONTROL:
            raise KeyError(action)
        verb, cli = _CONTROL[action]
        src = self._current
        if src is None:
            running = await self._running_apps()
            src = "spotify" if "spotify" in running else "music" if "music" in running else None
            if src is None and self._npcli:
                src = "nowplaying"
        if src in _APP_NAME:
            return await self._osascript(f'tell application "{_APP_NAME[src]}" to {verb}') is not None
        if src == "nowplaying" and self._npcli:
            return await self._run(self._npcli, cli) is not None
        return False


__all__ = ["MacBackend", "parse_applescript_data", "parse_nowplaying_cli", "parse_player"]
