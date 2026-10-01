"""Home Assistant entity: one entity's state with icon, unit, colour thresholds and a history sparkline.

Uses the `homeassistant` provider (REST: `/api/states/{entity}` every `poll` seconds, `/api/history/period` for
the sparkline). Configure the HA URL and a long-lived token in Settings → Integrations → Home Assistant.

Layout — "icon + one value" with a chart: tiny name row · 2× icon left, `small` value right with the unit
under it · sparkline across the bottom. Non-numeric states (on/off, open/closed…) show as a word, coloured
on/off.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import PALETTE, Frame, mix, scale, to_rgb
from ..gfx.font import fit, measure
from ..gfx.icons import draw_icon
from ._kit import compact_number, loading, offline

ICON_CHOICES = {
    "auto": "Automatic",
    "temp": "Thermometer",
    "drop": "Drop",
    "bolt": "Bolt",
    "sun": "Sun",
    "bulb": "Bulb",
    "battery": "Battery",
    "door": "Door",
    "lock": "Lock",
    "person": "Person",
    "home": "Home",
    "fire": "Flame",
    "none": "None",
}

ON_WORDS = {"on", "open", "home", "unlocked", "detected", "playing", "heat", "cool", "active", "true"}


def auto_icon(entity: str, device_class: str, mdi: str) -> str:
    """Pick a glyph from the entity's domain, device_class and mdi icon name."""
    domain = entity.split(".", 1)[0]
    dc = device_class.lower()
    hint = f"{dc} {mdi.lower()}"
    table = (
        (("temperature", "thermometer"), "temp"),
        (("humidity", "moisture", "water", "drop"), "drop"),
        (("power", "energy", "voltage", "current", "flash", "lightning"), "bolt"),
        (("battery",), "battery"),
        (("illuminance", "sun", "weather"), "sun"),
        (("door", "window", "garage", "opening"), "door"),
        (("motion", "occupancy", "presence", "person", "account"), "person"),
        (("smoke", "gas", "heat", "fire"), "fire"),
    )
    for words, icon in table:
        if any(w in hint for w in words):
            return icon
    return {"light": "bulb", "lock": "lock", "switch": "bolt", "person": "person", "sun": "sun"}.get(
        domain, "home"
    )


OPENING = ("door", "window", "garage_door", "garage", "opening")


def short_label(text: str, width: int = 30) -> str:
    """Whole words that fit ('LIVING ROOM TEMP' -> 'LIVING ROOM'), else an ellipsis cut."""
    words, out = text.split(), ""
    for w in words:
        trial = f"{out} {w}".strip()
        if measure(trial) > width:
            break
        out = trial
    return out or fit(text, width)


def state_word(state: str, device_class: str) -> str:
    s = state.lower()
    if device_class in OPENING and s in ("on", "off"):
        return "OPEN" if s == "on" else "SHUT"
    return state.replace("_", " ").upper()


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


class HassSettings(AppSettings):
    entity: str = Field("sensor.living_room_temperature", max_length=120, title="Entity id")
    label: str = Field("", max_length=24, title="Label", description="Empty = the entity's friendly name")
    icon: str = Choice("auto", ICON_CHOICES, title="Icon")
    unit: str = Field("", max_length=8, title="Unit", description="Empty = the unit Home Assistant reports")
    decimals: int = Field(1, ge=0, le=3, title="Decimals")
    color: Color = Field("#00dcff", title="Colour")
    warn_at: str = Field("", max_length=16, title="Amber at", description="Number; empty = off")
    alert_at: str = Field("", max_length=16, title="Red at", description="Number; empty = off")
    direction: str = Choice(
        "above", {"above": "At or above", "below": "At or below"}, title="Thresholds trigger"
    )
    poll: int = Field(15, ge=5, le=600, title="Refresh every (s)")
    history_h: int = Field(6, ge=0, le=48, title="History (hours)", description="0 hides the sparkline")


@register
class HassEntity(App):
    id = "hassentity"
    name = "Home Assistant"
    description = "Any Home Assistant entity: state, icon, unit, thresholds and a history sparkline."
    icon = "house"
    category = "data"
    Settings = HassSettings
    fps = 1.0
    uses = ("homeassistant",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._wanted: str | None = None

    def _want(self) -> None:
        s = self.settings
        p = self.ctx.provider("homeassistant")
        if self._wanted and self._wanted != s.entity:
            p.unwant(self._wanted)
        p.want(s.entity, float(s.poll), float(s.history_h))
        self._wanted = s.entity

    def on_start(self) -> None:
        self._want()

    def on_settings(self) -> None:
        self._want()

    # ------------------------------------------------------------ helpers
    def _color(self, value: float | None) -> tuple[int, int, int]:
        s = self.settings
        base = to_rgb(s.color)
        if value is None:
            return base
        above = s.direction == "above"
        for raw, col in ((s.alert_at, PALETTE["bad"]), (s.warn_at, PALETTE["warn"])):
            th = _num(raw)
            if th is not None and (value >= th if above else value <= th):
                return col
        return base

    def _fmt(self, v: float) -> str:
        if abs(v) >= 1000:
            return compact_number(v)
        return f"{v:.{self.settings.decimals}f}"

    # ------------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        p = self.ctx.provider("homeassistant")
        data = (p.value or {}).get(s.entity)
        if data is None:
            if p.error:
                detail = "SET UP" if "not set up" in p.error else ("TOKEN" if "401" in p.error else "OFFLINE")
                offline(f, "HASS", detail)
            else:
                loading(f, t, "HASS", to_rgb(s.color))
            return
        if data.get("missing"):
            offline(f, "HASS", "UNKNOWN")
            return
        value = data.get("value")
        color = self._color(value)
        label = (s.label or data.get("name") or s.entity).upper()
        f.text(1, 1, short_label(label), scale(to_rgb(s.color), 0.7))
        icon = (
            s.icon
            if s.icon != "auto"
            else auto_icon(s.entity, data.get("device_class", ""), data.get("icon", ""))
        )
        hist = [float(x) for x in data.get("history") or []]
        chart = s.history_h > 0 and len(hist) >= 2
        top = 8 if chart else 11
        off = value is None and str(data.get("state", "")).lower() not in ON_WORDS
        if icon != "none":
            draw_icon(f, icon, 1, top, scale(color, 0.35 if off else 0.9), 2)
        left = 13 if icon != "none" else 1
        if value is not None:
            text = self._fmt(float(value))
            font = "small" if measure(text, "small") <= 31 - left else "tiny"
            f.text_right(30, top + 1, text, (255, 255, 255), font=font)
            unit = (s.unit or data.get("unit") or "").upper()
            if unit:
                f.text_right(30, top + 10, fit(unit, 31 - left), scale(color, 0.85))
        else:
            word = state_word(str(data.get("state", "")), str(data.get("device_class", "")))
            wc = PALETTE["mute"] if off else color
            font = "small" if measure(word, "small") <= 31 - left else "tiny"
            f.text_right(30, top + 4, fit(word, 31 - left, font), wc, font=font)
        if chart:
            f.sparkline(1, 23, 30, 8, hist, color, fill=mix((0, 0, 0), color, 0.22))

    def status(self) -> dict[str, Any]:
        d = (self.ctx.provider("homeassistant").value or {}).get(self.settings.entity) or {}
        return {"entity": self.settings.entity, "state": d.get("state"), "unit": d.get("unit") or None}
