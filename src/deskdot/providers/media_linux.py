"""Linux now-playing backend (used by `media.MediaProvider` on Linux, including Raspberry Pi desktops).

Every Linux player that shows up in the desktop's media controls speaks **MPRIS** over the session D-Bus:
Spotify, Firefox / Chromium tabs (YouTube, YouTube Music…), VLC, Rhythmbox, mpv (with mpv-mpris), Elisa…
This backend reads it through **playerctl** (``sudo apt install playerctl``), a tiny CLI, so DeskDot needs no
D-Bus bindings: short-lived subprocesses through asyncio, with timeouts, never blocking the loop.

* Several players: a *playing* one wins over a paused one (the same rule as Windows / macOS).
* Album art: ``mpris:artUrl`` — an ``https://`` URL (Spotify, browsers) is downloaded by the provider; a
  ``file://`` path (local players) is read here.
* Without playerctl, or without a session bus (a headless Pi running as a system service), the provider reports a
  clear error and the Now Playing app shows its offline state.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from .media import Snapshot

log = logging.getLogger("deskdot.media.linux")

SEP = "\x1f"
FIELDS = (
    "{{status}}",
    "{{xesam:title}}",
    "{{xesam:artist}}",
    "{{xesam:album}}",
    "{{mpris:length}}",
    "{{position}}",
    "{{mpris:artUrl}}",
    "{{playerName}}",
)
FORMAT = SEP.join(FIELDS)
_CONTROL = {"toggle": "play-pause", "play": "play", "pause": "pause", "next": "next", "prev": "previous"}


def _micros(s: str) -> float:
    try:
        return max(0.0, float(s.strip() or 0) / 1e6)
    except ValueError:
        return 0.0


def parse_line(line: str, sampled: float | None = None) -> Snapshot | None:
    """One `playerctl metadata --format FORMAT` line -> Snapshot (None for a stopped / empty player)."""
    parts = line.rstrip("\n").split(SEP)
    if len(parts) < len(FIELDS):
        return None
    status, title, artist, album, length, position, art, player = parts[: len(FIELDS)]
    if not title.strip() or status.strip().lower() == "stopped":
        return None
    art = art.strip()
    return Snapshot(
        title=title.strip(),
        artist=artist.strip(),
        album=album.strip(),
        playing=status.strip().lower() == "playing",
        position=_micros(position),
        duration=_micros(length),
        app=player.strip(),
        sampled=sampled if sampled is not None else time.monotonic(),
        stamp=None,
        position_known=bool(position.strip()),
        art_url=art if art.startswith(("http://", "https://")) else None,
    )


class LinuxBackend:
    """MPRIS through playerctl."""

    def __init__(self) -> None:
        self._cli = shutil.which("playerctl")
        self._player: str | None = None
        self._art_path: str | None = None
        self._warned = False

    async def _run(self, *args: str, limit: float = 2.5) -> str | None:
        if not self._cli:
            raise RuntimeError("now playing on Linux needs playerctl (sudo apt install playerctl)")
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cli, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except (FileNotFoundError, PermissionError) as e:
            raise RuntimeError(f"cannot run playerctl: {e}") from e
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=limit)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return None
        if proc.returncode != 0:
            msg = err.decode("utf-8", "replace").strip()
            if "No players found" in msg or not msg:
                return ""
            if not self._warned:
                self._warned = True
                log.info("playerctl: %s", msg[:200])  # e.g. no session D-Bus (running as a system service)
            return ""
        return out.decode("utf-8", "replace")

    async def snapshot(self) -> Snapshot | None:
        t0 = time.monotonic()
        out = await self._run("--all-players", "metadata", "--format", FORMAT)
        sampled = (t0 + time.monotonic()) / 2
        best: tuple[Snapshot, str] | None = None
        for line in (out or "").splitlines():
            snap = parse_line(line, sampled)
            if snap is None:
                continue
            if snap.playing:
                best = (snap, line)
                break
            best = best or (snap, line)
        if best is None:
            self._player = self._art_path = None
            return None
        snap, line = best
        self._player = snap.app or None
        art = line.split(SEP)[6].strip()
        self._art_path = art if art.startswith("file://") else None
        return snap

    async def art(self) -> bytes | None:
        """Local cover files (file://…); http(s) art URLs travel on the snapshot and are downloaded upstream."""
        url = self._art_path
        if not url:
            return None
        path = Path(unquote(urlparse(url).path))
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError:
            return None

    async def control(self, action: str) -> bool:
        if action not in _CONTROL:
            raise KeyError(action)
        args = ["--player", self._player] if self._player else []
        return await self._run(*args, _CONTROL[action]) is not None


__all__ = ["FORMAT", "LinuxBackend", "parse_line"]
