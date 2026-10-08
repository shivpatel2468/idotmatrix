"""Small helpers shared by the 3.6.0 public-API apps (Aurora Watch, Bitcoin Network, Crypto Market, …).

Pure and cheap: they only read a provider's cached value and draw through `_kit`, so `render()` stays fast.
"""

from __future__ import annotations

import time
from typing import Any

from ..gfx import Frame
from ..gfx.color import ColorLike
from ._kit import loading, offline


def provider(ctx: Any, name: str) -> Any:
    """The provider `name`, or None in contexts without it (plugins, bare test contexts)."""
    try:
        return ctx.provider(name)
    except (KeyError, AttributeError):
        return None


def value_or_state(f: Frame, t: float, p: Any, label: str, color: ColorLike, detail: str = "OFFLINE") -> Any:
    """The provider's value, or None after drawing the loading / offline screen."""
    v = p.value if p is not None else None
    if v is None:
        if p is not None and p.error:
            offline(f, label, detail)
        else:
            loading(f, t, label, color)
    return v


def stale_dot(f: Frame, p: Any) -> None:
    """A single amber pixel bottom-left when the last refresh failed but old data is still shown."""
    if p is not None and p.error and p.value is not None:
        f.set(0, 31, (255, 170, 0))


def until(seconds: float) -> str:
    """Compact countdown for tiny text: '3D 4H', '5H 12M', '12M', 'NOW'."""
    s = max(0, int(seconds))
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    if d >= 1:
        return f"{d}D {h}H" if d < 10 else f"{d}D"
    if h >= 1:
        return f"{h}H {m}M"
    return f"{m}M" if m else "NOW"


def ago(seconds: float) -> str:
    """'12S', '4M', '3H', '2D' — how long ago."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}S"
    if s < 3600:
        return f"{s // 60}M"
    if s < 86400:
        return f"{s // 3600}H"
    return f"{s // 86400}D"


def local_hhmm(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def local_day(ts: float) -> str:
    return time.strftime("%a", time.localtime(ts)).upper()


def page(t: float, rotate: float, n: int) -> int:
    return int(t // max(1.0, rotate)) % max(1, n)
