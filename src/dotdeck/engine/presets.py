"""Presets: one-tap playlists — every game in sequence, all the pets, a desk dashboard, a chill mix…

Built-in presets are generated from the app registry, so a new app joins its category's preset automatically.
Apps that need the user's own setup first (a repo list, a Home Assistant token, an OBS password…) or that only
make sense interactively (camera, screen mirror, canvas) are left out of the generated presets. Users can also
save the current playlist as their own preset (stored in `state.json` under "presets").
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .app import REGISTRY

# apps that show nothing useful until configured, or are interactive / take over the computer
EXCLUDE = {
    "activeapp", "agent", "anki", "calendar", "camera", "canvas", "ci", "composer", "custom", "eyebreak",
    "gallery", "hassentity", "mediaserver", "mirror", "native", "obs", "onair", "printer", "text", "uptime",
}  # fmt: skip

CATEGORY_PRESETS: dict[str, tuple[str, str, float]] = {  # category -> (name, icon, seconds per app)
    "games": ("All games", "gamepad-2", 45.0),
    "pets": ("Pets & characters", "paw-print", 40.0),
    "time": ("Clocks & time", "clock", 20.0),
    "data": ("Live data", "activity", 15.0),
    "media": ("Media", "music", 20.0),
    "creative": ("Creative & art", "palette", 25.0),
    "ambient": ("Ambient", "sparkles", 45.0),
    "productivity": ("Focus & desk", "briefcase", 20.0),
}

CURATED: dict[str, tuple[str, str, list[tuple[str, float]]]] = {
    "dashboard": (
        "Desk dashboard",
        "layout-dashboard",
        [("clock", 20), ("weather", 15), ("stocks", 15), ("currency", 12), ("headlines", 20), ("sky", 12)],
    ),
    "chill": (
        "Chill",
        "coffee",
        [("petworld", 90), ("loops", 40), ("ambient", 40), ("photoframe", 45), ("pet", 60)],
    ),
    "planet": (
        "Planet & space",
        "globe",
        [
            ("daynight", 20),
            ("space", 25),
            ("quakes", 20),
            ("rainradar", 20),
            ("airquality", 15),
            ("planets", 20),
        ],
    ),
}


def _available(app_id: str) -> bool:
    cls = REGISTRY.get(app_id)
    return cls is not None and not getattr(cls, "hidden", False)


def builtin_presets() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pid, (name, icon, items) in CURATED.items():
        its = [{"app": a, "duration": float(d)} for a, d in items if _available(a)]
        if its:
            out.append({"id": pid, "name": name, "icon": icon, "builtin": True, "items": its})
    for cat, (name, icon, secs) in CATEGORY_PRESETS.items():
        apps = sorted(
            (
                aid
                for aid, cls in REGISTRY.items()
                if cls.category == cat and aid not in EXCLUDE and _available(aid)
            ),
            key=lambda aid: REGISTRY[aid].name.lower(),
        )
        if apps:
            out.append(
                {
                    "id": f"cat-{cat}",
                    "name": name,
                    "icon": icon,
                    "builtin": True,
                    "items": [{"app": a, "duration": secs} for a in apps],
                }
            )
    everything = [
        {"app": aid, "duration": CATEGORY_PRESETS.get(cls.category, ("", "", 20.0))[2]}
        for aid, cls in sorted(REGISTRY.items(), key=lambda kv: (kv[1].category, kv[1].name.lower()))
        if aid not in EXCLUDE and _available(aid)
    ]
    out.append(
        {"id": "everything", "name": "Everything", "icon": "infinity", "builtin": True, "items": everything}
    )
    return out


def user_presets(store: Any) -> list[dict[str, Any]]:
    saved = store.get("presets") or {}
    out = []
    for pid, p in saved.items():
        items = [it for it in p.get("items", []) if _available(str(it.get("app")))]
        out.append(
            {
                "id": pid,
                "name": p.get("name", pid),
                "icon": p.get("icon", "list-music"),
                "builtin": False,
                "items": items,
            }
        )
    return out


def all_presets(store: Any) -> list[dict[str, Any]]:
    return [*user_presets(store), *builtin_presets()]


def find(store: Any, preset_id: str) -> dict[str, Any] | None:
    return next((p for p in all_presets(store) if p["id"] == preset_id), None)


def save(store: Any, name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "preset"
    pid = f"my-{slug}-{uuid.uuid4().hex[:4]}"
    saved = dict(store.get("presets") or {})
    saved[pid] = {"name": name[:40], "icon": "list-music", "items": items}
    store.set("presets", saved)
    return {"id": pid, "name": name[:40], "icon": "list-music", "builtin": False, "items": items}


def delete(store: Any, preset_id: str) -> bool:
    saved = dict(store.get("presets") or {})
    if preset_id not in saved:
        return False
    del saved[preset_id]
    store.set("presets", saved)
    return True
