"""Tuning knobs for the fruit-fly brain (docs/FLY_BRAIN.md): one `FlyConfig` shared by every `FlyBrain`.

The engine loads it from the store (state.json key "fly") at start-up and the studio changes it through
`PATCH /api/fly/config`. The defaults are the brain's original constants, so an untouched config behaves exactly as
before. Brains read `current()` on every step, so a change applies at once to every game the fly plays; the Fly
Brain app's baked loop includes the config in its clip key, so it re-bakes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

TUNING = ("phototaxis", "looming", "motion", "leak", "threshold", "refractory", "noise", "escape", "lure")


class FlyConfig(BaseModel):
    phototaxis: float = Field(
        0.3, ge=0.0, le=1.0, title="Phototaxis", description="Pull towards light per step"
    )
    looming: float = Field(
        1.0, ge=0.0, le=3.0, title="Looming", description="LPLC2 gain: how strongly expansion is felt"
    )
    motion: float = Field(
        1.0, ge=0.0, le=3.0, title="Optomotor", description="How much wide-field motion (HS/VS) steers"
    )
    leak: float = Field(
        0.8, ge=0.3, le=0.99, title="Leak", description="Membrane potential kept per step (memory)"
    )
    threshold: float = Field(1.0, ge=0.3, le=3.0, title="Spike threshold")
    refractory: int = Field(2, ge=0, le=10, title="Refractory steps", description="Rest after each spike")
    noise: float = Field(
        0.06, ge=0.0, le=0.5, title="Spontaneous noise", description="Random drive: twitchiness"
    )
    escape: float = Field(
        1.0, ge=0.0, le=3.0, title="Escape", description="Giant-fibre sensitivity (the A key)"
    )
    lure: float = Field(
        1.0, ge=0.0, le=3.0, title="Smell (lure)", description="How strongly the game's goal cue attracts"
    )
    preset: str = Field("default", title="Preset")


DEFAULT = FlyConfig()


def _preset(pid: str, name: str, description: str, **kw: Any) -> dict[str, Any]:
    cfg = FlyConfig(**{**DEFAULT.model_dump(), **kw, "preset": pid})
    return {"id": pid, "name": name, "description": description, "config": cfg.model_dump()}


PRESETS: list[dict[str, Any]] = [
    _preset("default", "Default", "The brain as modelled: balanced light-seeking, escapes and smell."),
    _preset(
        "calm",
        "Calm",
        "Slow and steady: a high threshold, little noise, rarely jumps.",
        phototaxis=0.22,
        threshold=1.4,
        refractory=3,
        noise=0.02,
        escape=0.5,
        leak=0.85,
    ),
    _preset(
        "curious",
        "Curious",
        "Drawn to every light and every smell; explores more.",
        phototaxis=0.5,
        lure=1.6,
        noise=0.1,
        motion=0.6,
    ),
    _preset(
        "twitchy",
        "Twitchy",
        "Noisy, quick to fire and easy to startle.",
        noise=0.3,
        threshold=0.7,
        refractory=1,
        looming=1.8,
        escape=1.8,
        leak=0.7,
    ),
    _preset(
        "hunter",
        "Hunter",
        "Follows its nose: a strong lure, steady aim, ignores distractions.",
        phototaxis=0.45,
        lure=2.4,
        noise=0.02,
        motion=0.4,
        refractory=1,
        looming=0.6,
    ),
    _preset(
        "daredevil",
        "Daredevil",
        "Fast and fearless: fires often, barely escapes.",
        phototaxis=0.6,
        threshold=0.8,
        refractory=0,
        noise=0.08,
        escape=0.25,
        looming=0.5,
        lure=1.4,
    ),
]
PRESET_IDS = {p["id"] for p in PRESETS}

_current = DEFAULT
_version = 0


def current() -> FlyConfig:
    return _current


def version() -> int:
    """Bumped on every change (cheap cache key)."""
    return _version


def set_current(cfg: FlyConfig) -> FlyConfig:
    global _current, _version
    _current = cfg
    _version += 1
    return cfg


def tuning_key(cfg: FlyConfig | None = None) -> tuple[float, ...]:
    c = cfg or _current
    return tuple(float(getattr(c, k)) for k in TUNING)


def _label(cfg: FlyConfig) -> FlyConfig:
    """Name the preset the values match, else "custom"."""
    key = tuning_key(cfg)
    for p in PRESETS:
        if tuning_key(FlyConfig(**p["config"])) == key:
            return cfg.model_copy(update={"preset": p["id"]})
    return cfg.model_copy(update={"preset": "custom"})


def merge(base: FlyConfig, patch: dict[str, Any]) -> FlyConfig:
    """Apply a partial update. A known `preset` id loads that preset first; other fields then override it.
    Raises pydantic.ValidationError on out-of-range values, ValueError on an unknown preset."""
    data = base.model_dump()
    pid = patch.get("preset")
    if pid is not None and pid != "custom":
        p = next((p for p in PRESETS if p["id"] == pid), None)
        if p is None:
            raise ValueError(f"unknown preset {pid!r}")
        data = dict(p["config"])
    data.update({k: v for k, v in patch.items() if k in TUNING})
    return _label(FlyConfig.model_validate(data))


def load(raw: Any) -> FlyConfig:
    """From the store: stored values may be stale or invalid — keep the valid ones, drop the rest."""
    if not isinstance(raw, dict):
        return DEFAULT
    data = DEFAULT.model_dump()
    for k in TUNING:
        if k in raw:
            try:
                FlyConfig.model_validate({**data, k: raw[k]})
                data[k] = raw[k]
            except ValidationError:
                pass
    return _label(FlyConfig.model_validate(data))
