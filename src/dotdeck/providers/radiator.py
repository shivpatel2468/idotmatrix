"""Shared plumbing for the "information radiator" providers (CI, uptime, OBS, printer, media server, Anki).

* `EventLog` — a tiny, bounded log of discrete transitions (build broke, site down, print done). Providers
  append; apps consume the entries newer than the sequence number they last saw and turn them into
  ``ctx.notify`` overlays. Transitions are only recorded once a source is *armed* (after its first
  successful observation), so starting the engine never replays stale alerts.
* `redact` / `safe_error` — every error string that can reach a log line or the studio goes through
  these, so tokens, API keys and passwords are never logged.
* `Backoff` — capped exponential retry delay for sources that are often simply not running.
"""

from __future__ import annotations

import re
import time
from typing import Any

from .daily import clean_text

MAX_EVENTS = 24
HOST_RE = re.compile(r"^[A-Za-z0-9.\-_\[\]:]{1,253}$")


def redact(text: str, *secrets: str) -> str:
    """Replace every non-empty secret (and its URL-encoded form) in `text` with ``***``."""
    from urllib.parse import quote

    out = str(text)
    for s in secrets:
        if s and len(s) >= 3:
            out = out.replace(s, "***").replace(quote(s, safe=""), "***")
    return out


def safe_error(e: BaseException, *secrets: str, limit: int = 160) -> str:
    """A short, secret-free description of an exception (``TypeName: message``)."""
    msg = str(e).split("\nFor more information")[0]  # httpx appends a docs URL
    return redact(f"{type(e).__name__}: {msg}" if msg else type(e).__name__, *secrets)[:limit]


def mask(secret: str) -> str:
    """For status(): never the secret itself, only whether one is set."""
    return "set" if secret else ""


def panel_text(raw: Any, limit: int = 120) -> str:
    """Web text -> upper-case ASCII the bitmap fonts can draw."""
    return clean_text(raw, limit)


def clean_host(raw: str, default: str = "127.0.0.1") -> str:
    """'http://octopi.local:5000/' -> 'octopi.local:5000' style host (scheme/path stripped)."""
    h = raw.strip()
    h = re.sub(r"^[a-z]+://", "", h, flags=re.I)
    h = h.split("/")[0]
    return h or default


def base_url(host: str, port: int | None = None, default_scheme: str = "http") -> str:
    """Build ``scheme://host[:port]`` from a user string that may or may not carry a scheme or port."""
    raw = host.strip().rstrip("/")
    m = re.match(r"^(https?)://", raw, flags=re.I)
    scheme = m.group(1).lower() if m else default_scheme
    rest = raw[m.end() :] if m else raw
    rest = rest.split("/")[0] or "127.0.0.1"
    has_port = bool(re.search(r":\d+$", rest)) and not rest.endswith("]")
    if port and not has_port:
        rest = f"{rest}:{port}"
    return f"{scheme}://{rest}"


class EventLog:
    """Mixin: ``events`` (newest last) with a monotonically increasing ``seq``."""

    def _init_events(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.seq = 0

    def _emit(self, kind: str, **data: Any) -> None:
        self.seq += 1
        self.events.append({"seq": self.seq, "kind": kind, "time": time.time(), **data})
        del self.events[:-MAX_EVENTS]

    def events_since(self, seq: int) -> list[dict[str, Any]]:
        return [e for e in self.events if e["seq"] > seq]


class Backoff:
    """2, 4, 8 … `cap` seconds; `reset()` after a success."""

    def __init__(self, first: float = 2.0, cap: float = 60.0) -> None:
        self.first, self.cap = first, cap
        self.fails = 0

    def fail(self) -> float:
        self.fails += 1
        return self.delay

    @property
    def delay(self) -> float:
        return 0.0 if self.fails == 0 else min(self.cap, self.first * 2 ** (self.fails - 1))

    def reset(self) -> None:
        self.fails = 0
