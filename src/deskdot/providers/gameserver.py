"""Block-game server status from mcsrvstat.us (``api.mcsrvstat.us/3/{address}``, keyless, CORS).

Works for Java edition servers and, with ``/bedrock/3/``, Bedrock ones. The API caches each server for ~1 minute
(5 min when it is offline), so polling faster is pointless. The server's 64×64 icon arrives inline as a base64
PNG and is shrunk to 16×16 here.

``value = {address: {online, players, max, version, motd, icon: np.ndarray (16, 16, 3) | None, names: [..]}}``.
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
import time
from typing import Any

import numpy as np
from PIL import Image

from .base import Endpoint, Provider
from .daily import clean_text

API = "https://api.mcsrvstat.us"
ADDRESS = re.compile(r"^[A-Za-z0-9.-]{1,253}(:\d{1,5})?$")


def clean_address(raw: str) -> str:
    a = raw.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    return a if ADDRESS.match(a) else ""


def decode_icon(data_uri: Any, size: int = 16) -> np.ndarray | None:
    if not isinstance(data_uri, str) or "base64," not in data_uri:
        return None
    try:
        raw = base64.b64decode(data_uri.split("base64,", 1)[1])
        img = Image.open(io.BytesIO(raw)).convert("RGBA").resize((size, size), Image.Resampling.BOX)
    except Exception:
        return None
    px = np.asarray(img, dtype=np.float32)
    rgb = px[..., :3] * (px[..., 3:4] / 255.0)  # transparent icon areas go dark
    return rgb.astype(np.uint8)


def parse_status(d: Any) -> dict[str, Any]:
    if not isinstance(d, dict) or "online" not in d:
        raise ValueError("mcsrvstat: unexpected shape")
    if not d.get("online"):
        return {"online": False, "players": 0, "max": 0, "version": "", "motd": "", "icon": None, "names": []}
    players = d.get("players") or {}
    motd = " ".join((d.get("motd") or {}).get("clean") or [])
    return {
        "online": True,
        "players": int(players.get("online") or 0),
        "max": int(players.get("max") or 0),
        "version": clean_text(d.get("version"), 30),
        "motd": clean_text(motd, 120),
        "icon": decode_icon(d.get("icon")),
        "names": [clean_text(p.get("name"), 16) for p in players.get("list") or [] if isinstance(p, dict)][
            :20
        ],
    }


class GameServerProvider(Provider[dict[str, Any]]):
    name = "gameserver"
    endpoints = (
        Endpoint("mcsrvstat.us Java", API + "/3/demo.mcstatus.io", check=parse_status),
        Endpoint(
            "mcsrvstat.us Bedrock", API + "/bedrock/3/demo.mcstatus.io", check=parse_status, role="optional"
        ),
    )
    interval = 120.0
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.servers: dict[str, str] = {}  # address -> "java" | "bedrock"

    def want(self, address: str, edition: str = "java") -> None:
        a = clean_address(address)
        if a and self.servers.get(a) != edition:
            self.servers[a] = edition
            while len(self.servers) > 4:
                self.servers.pop(next(iter(self.servers)))
            self.refresh()

    async def _one(self, address: str, edition: str) -> dict[str, Any]:
        path = "/bedrock/3/" if edition == "bedrock" else "/3/"
        r = await self.hub.http.get(API + path + address, timeout=15.0)
        r.raise_for_status()
        out = await asyncio.to_thread(parse_status, r.json())
        out["checked"] = time.time()
        return out

    async def fetch(self) -> dict[str, Any]:
        if not self.servers:
            return dict(self.value or {})
        items = list(self.servers.items())
        res = await asyncio.gather(*(self._one(a, e) for a, e in items), return_exceptions=True)
        out = {a: v for a, v in (self.value or {}).items() if a in self.servers}
        errors = []
        for (a, _e), v in zip(items, res, strict=True):
            if isinstance(v, BaseException):
                errors.append(f"{a}: {type(v).__name__}")
            else:
                out[a] = v
        if errors and len(errors) == len(items) and not out:
            raise RuntimeError("; ".join(errors))
        return out
