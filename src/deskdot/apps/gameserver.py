"""Game Server — players online on a Java or Bedrock edition block-game server, with its icon and message.

Data: mcsrvstat.us (keyless; providers/gameserver.py). Set the server's address (``play.example.net`` or
``host:port``). The server's own 64×64 icon is shown shrunk to 16×16; the message of the day scrolls underneath.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, scale
from ..gfx.color import RGB
from ..providers.gameserver import clean_address
from . import _feed
from ._kit import MUTE, compact_number, label, setup

GRASS: RGB = (90, 200, 60)
DIRT: RGB = (140, 90, 40)


def block_icon(f: Frame, x: int, y: int) -> None:
    """A 16×16 grass block for servers without an icon."""
    f.rect(x, y, 16, 16, DIRT)
    f.rect(x, y, 16, 5, GRASS)
    for i in range(0, 16, 3):
        f.set(x + i, y + 5 + (i % 2), GRASS)
        f.set(x + (i * 7) % 16, y + 9 + (i % 5), scale(DIRT, 0.7))


class GameServerSettings(AppSettings):
    address: str = Field(
        "", max_length=80, title="Server address", description="e.g. play.example.net or host:25565"
    )
    edition: str = Choice("java", {"java": "Java edition", "bedrock": "Bedrock edition"}, title="Edition")


@register
class GameServer(App):
    id = "gameserver"
    name = "Game Server"
    description = (
        "Players online on your Java or Bedrock block-game server, with its icon and message of the day."
    )
    icon = "server"
    category = "data"
    Settings = GameServerSettings
    fps = 4.0
    uses = ("gameserver",)
    preview_patch: ClassVar[dict[str, Any]] = {"address": "demo.mcstatus.io"}

    def on_start(self) -> None:
        p = _feed.provider(self.ctx, "gameserver")
        if p is not None and self.settings.address:
            p.want(self.settings.address, self.settings.edition)

    def on_settings(self) -> None:
        self.on_start()

    def render(self, f: Frame, t: float) -> None:
        addr = clean_address(self.settings.address)
        if not addr:
            setup(f, "SERVER", "SET ADDRESS", GRASS)
            return
        p = _feed.provider(self.ctx, "gameserver")
        d = _feed.value_or_state(f, t, p, "SERVER", GRASS)
        if d is None:
            return
        s = d.get(addr)
        if s is None:
            from ._kit import loading

            loading(f, t, "SERVER", GRASS)
            return
        icon = s.get("icon")
        if isinstance(icon, np.ndarray):
            f.blit(icon, 1, 1)
        else:
            block_icon(f, 1, 1)
        online = s.get("online")
        dot = PALETTE["ok"] if online else PALETTE["bad"]
        f.circle(26, 4, 2, dot if online or int(t * 2) % 2 else scale(dot, 0.4))
        f.text(19, 10, "ON" if online else "OFF", dot)
        if online:
            n = compact_number(s["players"]) if s["players"] >= 1000 else str(s["players"])
            label(f, 18, n, PALETTE["white"], font="small")
            label(f, 26, s.get("motd") or s.get("version") or addr.upper(), MUTE, t)
        else:
            label(f, 19, addr.upper(), MUTE, t)
            label(f, 26, "OFFLINE", PALETTE["bad"])
        _feed.stale_dot(f, p)

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "gameserver")
        s = ((p.value if p is not None else None) or {}).get(clean_address(self.settings.address)) or {}
        return {"online": s.get("online"), "players": s.get("players"), "max": s.get("max")}
