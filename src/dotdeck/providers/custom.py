"""Custom push apps (AWTRIX 3 compatible subset): anything can push a small "icon + value" screen by name.

`POST /api/custom/{name}` stores a `CustomApp`; while it is fresh (its `lifetime` has not run out) it joins the
playlist rotation and the built-in `custom` app renders it. Pushing the same name again replaces it (and
restarts its lifetime); an empty body or `DELETE` removes it. Entries persist in the store under
"custom_apps", with an absolute expiry, so a restart neither loses nor resurrects them.

This provider does no I/O: it is the shared, validated registry the engine and the `custom` app read.
"""

from __future__ import annotations

import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..gfx import PALETTE, to_hex
from ..gfx.icons import ICONS
from .base import Provider

NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_APPS = 24
ART_MAX = 16  # pixel-art icons up to 16 x 16


def color_hex(v: Any) -> str | None:
    """'#ff0000' / '#f00' / 'ember' / [255, 0, 0] -> '#ff0000'. None stays None."""
    if v is None or v == "":
        return None
    if isinstance(v, (list, tuple)):
        if len(v) != 3 or not all(isinstance(x, (int, float)) for x in v):
            raise ValueError("colour lists are [r, g, b]")
        return to_hex(tuple(int(x) for x in v))  # type: ignore[arg-type]
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in PALETTE:
            return to_hex(PALETTE[s.lower()])
        if re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", s):
            h = s.lstrip("#")
            h = "".join(c * 2 for c in h) if len(h) == 3 else h
            return "#" + h.lower()
    raise ValueError(f"bad colour {v!r}; use '#rrggbb', a palette name or [r, g, b]")


class CustomApp(BaseModel):
    """The accepted body. Field names follow AWTRIX 3 (`progressC`, `textCase`, `pushIcon`)."""

    model_config = ConfigDict(extra="ignore")

    text: str = Field("", max_length=500, description="the value / message; long text scrolls")
    icon: str | None = Field(None, description="a DotDeck icon name (GET /api/meta → icons)")
    rows: list[str] | None = Field(None, description="pixel-art icon, up to 16 rows of up to 16 chars")
    palette: dict[str, Any] | None = Field(None, description="colour per `rows` character; '.' is off")
    color: Any = Field(None, description="text colour: '#rrggbb', a palette name, or [r, g, b]")
    progress: int = Field(-1, ge=-1, le=100, description="0-100 draws a progress bar; -1 = none")
    progressC: Any = Field(None, description="progress bar colour")
    progressBC: Any = Field(None, description="progress bar background colour")
    duration: float = Field(10.0, ge=3, le=3600, description="seconds on screen per rotation")
    lifetime: float = Field(
        0.0, ge=0, le=30 * 86400, description="seconds until stale and removed; 0 = never"
    )
    textCase: int = Field(0, ge=0, le=2, description="0 default (upper), 1 upper, 2 as sent")
    rainbow: bool = False
    pushIcon: int = Field(0, ge=0, le=2, description="0 icon fixed · 1 icon scrolls with the text · 2 once")

    @field_validator("color", "progressC", "progressBC", mode="before")
    @classmethod
    def _color(cls, v: Any) -> str | None:
        return color_hex(v)

    @field_validator("icon")
    @classmethod
    def _icon(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if v not in ICONS:
            raise ValueError(f"unknown icon {v!r}; one of {sorted(ICONS)}")
        return v

    @model_validator(mode="after")
    def _art(self) -> CustomApp:
        if self.rows is None:
            return self
        if len(self.rows) > ART_MAX or any(len(r) > ART_MAX for r in self.rows):
            raise ValueError(f"pixel-art icons are at most {ART_MAX} x {ART_MAX}")
        pal = {k: color_hex(v) for k, v in (self.palette or {}).items()}
        missing = {ch for r in self.rows for ch in r if ch not in ". "} - set(pal)
        if missing:
            raise ValueError(f"palette has no colour for {sorted(missing)}")
        self.palette = pal
        return self

    @property
    def empty(self) -> bool:
        return not self.text and not self.icon and not self.rows


class CustomAppsProvider(Provider[dict[str, dict[str, Any]]]):
    name = "custom"
    interval = 3600.0  # nothing to fetch; the engine prunes on its own tick

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        stored = hub.store.get("custom_apps") or {}
        self.apps: dict[str, dict[str, Any]] = {}
        for name, d in stored.items() if isinstance(stored, dict) else []:
            try:
                app = CustomApp.model_validate(d)
            except Exception:
                continue  # stale schema: drop it
            self.apps[name] = {
                **app.model_dump(mode="json"),
                "pushed": d.get("pushed"),
                "expires": d.get("expires"),
            }
        self.value = self.apps
        self.updated = time.time()

    def _save(self) -> None:
        self.hub.store.set("custom_apps", self.apps)
        self.value = self.apps
        self.updated = time.time()
        self.hub.on_change(self.name)

    def push(self, name: str, app: CustomApp, now: float | None = None) -> dict[str, Any]:
        if not NAME.match(name):
            raise ValueError("custom app names are 1-32 characters: letters, digits, _ and -")
        if name not in self.apps and len(self.apps) >= MAX_APPS:
            raise ValueError(f"at most {MAX_APPS} custom apps; delete one first")
        now = time.time() if now is None else now
        entry = {
            **app.model_dump(mode="json"),
            "pushed": now,
            "expires": now + app.lifetime if app.lifetime else None,
        }
        self.apps[name] = entry
        self._save()
        return entry

    def remove(self, name: str) -> bool:
        if self.apps.pop(name, None) is None:
            return False
        self._save()
        return True

    def fresh(self, now: float | None = None) -> dict[str, dict[str, Any]]:
        """Drop expired apps (persisting the removal) and return the live ones."""
        now = time.time() if now is None else now
        stale = [n for n, d in self.apps.items() if d.get("expires") and d["expires"] <= now]
        if stale:
            for n in stale:
                del self.apps[n]
            self._save()
        return self.apps

    def listing(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        return [
            {
                "name": n,
                "text": d.get("text", ""),
                "icon": d.get("icon") or ("art" if d.get("rows") else None),
                "duration": d.get("duration"),
                "expires_in": round(d["expires"] - now) if d.get("expires") else None,
            }
            for n, d in self.fresh(now).items()
        ]

    async def fetch(self) -> dict[str, dict[str, Any]]:
        return self.fresh()
