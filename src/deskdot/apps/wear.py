"""What to Wear — one big icon for the next few hours: umbrella, jacket, sunglasses, T-shirt, scarf or snow boots.

Picked from the `wear` provider (Open-Meteo hourly forecast, keyless) with thresholds you can tune, in this
order: snow → boots, rain likely → umbrella, freezing → scarf, cool → jacket, strong sun → sunglasses, else a
T-shirt. Beside the icon: temperature (store units), rain chance and peak UV; underneath, the reason. The icon
animates, so the screen is a baked clip that re-bakes only when the forecast summary changes.
"""

from __future__ import annotations

import json
import math
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Kind, register
from ..gfx import PALETTE, Frame, Sprite, mix, scale
from ..gfx.color import RGB
from ._kit import loading, offline

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
RAIN_C: RGB = PALETTE["sky"]
UV_C: RGB = PALETTE["gold"]

ITEMS: dict[str, tuple[str, RGB]] = {  # icon -> (caption, colour)
    "boots": ("SNOWY", (200, 230, 255)),
    "umbrella": ("RAINY", PALETTE["sky"]),
    "scarf": ("COLD", PALETTE["cyan"]),
    "jacket": ("CHILLY", PALETTE["violet"]),
    "sunglasses": ("SUNNY", PALETTE["gold"]),
    "tshirt": ("WARM", PALETTE["mint"]),
}

FRAMES = 24  # clip_seconds * clip_fps: every motion below is whole pixels (or coverage) per loop frame
LEVELS = 8  # coverage quantisation for slow falling flakes (keeps the GIF palette small)


def soft_dot(f: Frame, x: int, y: float, c: RGB) -> None:
    """A dot at a fractional row: the two rows it straddles lit in proportion (smooth slow fall)."""
    y0 = int(y // 1)
    a = round((y - y0) * LEVELS) / LEVELS
    f.set(x, y0, scale(c, 1 - a))
    if a > 0:
        f.set(x, y0 + 1, scale(c, a))


DROP = Sprite.parse([".#.", ".#.", "###", "###", ".#."], {"#": RAIN_C})


class WearSettings(AppSettings):
    icon: str = Choice(
        "auto",
        {
            "auto": "From forecast",
            "umbrella": "Umbrella",
            "jacket": "Jacket",
            "sunglasses": "Sunglasses",
            "tshirt": "T-shirt",
            "scarf": "Scarf",
            "boots": "Snow boots",
        },
        title="Icon",
        description="Leave on 'From forecast'; the others pin one icon (handy for testing).",
    )
    hours: int = Field(6, ge=2, le=12, title="Look ahead (hours)", json_schema_extra={"group": "Thresholds"})
    rain_chance: int = Field(
        50, ge=10, le=100, title="Umbrella from rain chance (%)", json_schema_extra={"group": "Thresholds"}
    )
    scarf_below: int = Field(
        5, ge=-20, le=20, title="Scarf below (feels-like °C)", json_schema_extra={"group": "Thresholds"}
    )
    jacket_below: int = Field(
        15, ge=-10, le=30, title="Jacket below (feels-like °C)", json_schema_extra={"group": "Thresholds"}
    )
    uv_from: int = Field(
        6, ge=1, le=12, title="Sunglasses from UV index", json_schema_extra={"group": "Thresholds"}
    )


def choose(d: dict[str, Any], s: WearSettings) -> str:
    """The one thing to wear, from a provider summary."""
    if d.get("snow_cm", 0) > 0 or (d.get("snow_code") and d.get("temp_min", 10) <= 1):
        return "boots"
    if d.get("rain_prob", 0) >= s.rain_chance or d.get("rain_mm", 0) >= 1.0:
        return "umbrella"
    if d.get("feels_min", 20) < s.scarf_below:
        return "scarf"
    if d.get("feels_min", 20) < s.jacket_below:
        return "jacket"
    if d.get("uv_max", 0) >= s.uv_from and d.get("day", True):
        return "sunglasses"
    return "tshirt"


# ----------------------------------------------------------------------------------- icons (16×16)
def _rows(f: Frame, x: int, y: int, rows: list[str], pal: dict[str, RGB]) -> None:
    f.sprite(Sprite.parse(rows, pal), x, y)


def icon_umbrella(f: Frame, x: int, y: int, ph: float) -> None:
    n = round(ph * FRAMES)
    for i in range(5):  # rain around the canopy
        col = 1 + i * 3 + (i % 2)
        top = 3 if col in (1, 2, 13, 14, 15) else 0
        off = (0, 7, 3, 9, 5)[i]
        dy = (n + off) % 12 if top else ((n + off) // 3) % 4
        f.set(x + col, y + top + dy, scale(RAIN_C, 0.9))
        f.set(x + col, y + top + dy - 1, scale(RAIN_C, 0.45))
    _rows(
        f,
        x,
        y + 3,
        [
            "......####......",
            "....##ww####....",
            "..##ww########..",
            ".#ww##########b.",
            "##############bb",
            "#.bb..bb..bb..b#",
            ".......h........",
            ".......h........",
            ".......h........",
            ".......h........",
            ".......h........",
            ".....h.h........",
            ".....hhh........",
        ],
        {"#": (255, 40, 90), "w": (255, 150, 180), "b": (170, 0, 50), "h": (170, 170, 190)},
    )


def icon_jacket(f: Frame, x: int, y: int, ph: float) -> None:
    _rows(
        f,
        x,
        y + 1,
        [
            ".....######.....",
            "....#h....h#....",
            "..###h....h###..",
            ".####.#..#.####.",
            "#####.#zz#.#####",
            "#####.#..#.#####",
            "####p.#zz#.p####",
            "####..#..#..####",
            "####..#zz#..####",
            "d###..#..#..###d",
            "d###..#zz#..###d",
            ".###..#..#..###.",
            ".###pp#zz#pp###.",
            ".###..####..###.",
        ],
        {
            "#": (140, 60, 255),
            "h": (220, 200, 255),
            "z": (200, 200, 220),
            "p": (90, 30, 180),
            "d": (70, 20, 140),
        },
    )
    zy = y + 5 + round((0.5 - 0.5 * math.cos(ph * math.tau)) * 8)  # the zip pull slides up and down
    f.set(x + 7, zy, WHITE)
    f.set(x + 8, zy, WHITE)


def icon_tshirt(f: Frame, x: int, y: int, ph: float) -> None:
    _rows(
        f,
        x,
        y + 2,
        [
            "...####..####...",
            ".######..######.",
            "#######..#######",
            "################",
            "##.##########.##",
            "...##########...",
            "...##########...",
            "...##########...",
            "...##########...",
            "...##########...",
            "...##########...",
            "...##########...",
        ],
        {"#": (0, 220, 130)},
    )
    k = 0.75 + 0.25 * math.sin(ph * math.tau * 2)  # a heart that beats on the chest
    _rows(f, x + 6, y + 7, [".#.#.", "#####", ".###.", "..#.."], {"#": scale((255, 40, 90), k)})


def icon_sunglasses(f: Frame, x: int, y: int, ph: float) -> None:
    cx, cy = x + 8, y + 3
    f.circle(cx, cy, 2, UV_C)
    swap = int(ph * 4) % 2  # rays swap bright/dim twice per loop
    for i in range(8):
        a = i / 8 * math.tau
        f.set(
            round(cx + math.cos(a) * 4),
            round(cy + math.sin(a) * 4),
            scale(UV_C, 0.9 if (i + swap) % 2 else 0.5),
        )
    _rows(
        f,
        x,
        y + 8,
        [
            "#..............#",
            ".#............#.",
            "..############..",
            ".#llllll##llllll",
            ".#llllll..llllll",
            "..llllll..llllll",
            "...llll....llll.",
        ],
        {"#": (255, 170, 0), "l": (80, 60, 130)},  # lenses: dark, but still lit through the panel gamma
    )
    gx = round(ph * 24) - 4  # a glint sweeps across the lenses
    for k in range(3):
        for lens in (2, 10):
            px = gx + k
            if 0 <= px - lens < 6:
                f.set(x + px, y + 13 - k, (200, 200, 255))


def icon_scarf(f: Frame, x: int, y: int, ph: float) -> None:
    stripe = [(0, 220, 255), (255, 255, 255), (0, 150, 200)]
    for row in range(4):  # the wrap
        for c in range(1, 15):
            f.set(x + c, y + 3 + row, stripe[((c + row) // 2) % 3] if row not in (0, 3) else stripe[2])
    for i in range(9):  # the hanging tail, fluttering
        wob = round(math.sin(ph * math.tau * 2 - i * 0.6) * min(2.0, i * 0.35))
        c = stripe[(i // 2) % 3]
        f.rect(x + 9 + wob, y + 7 + i, 4, 1, c)
    for k in range(4):  # fringe
        wob = round(math.sin(ph * math.tau * 2 - 9 * 0.6) * 2)
        f.set(x + 9 + wob + k, y + 16 if k % 2 else y + 15, stripe[1])
    for i in range(3):
        soft_dot(f, x + 1 + i * 3, y + 9 + ((ph + i * 0.33) % 1.0) * 7, (200, 220, 255))


def icon_boots(f: Frame, x: int, y: int, ph: float) -> None:
    for i in range(6):  # snow
        sx = (i * 5 + 2) % 16
        sy = ((ph + i * 0.21) % 1.0) * 16
        if not (3 <= sx <= 13 and sy >= 3):
            soft_dot(f, x + sx, y + sy, (220, 230, 255))
    _rows(
        f,
        x,
        y + 3,
        [
            "...wwwwwwww.....",
            "...wwwwwwww.....",
            "....######......",
            "....######......",
            "....######......",
            "....#l####......",
            "....######......",
            "....########....",
            "....##########..",
            "...###########..",
            "...###########..",
            "..ssssssssssss..",
        ],
        {"w": (240, 240, 250), "#": (170, 90, 30), "l": (230, 150, 60), "s": (60, 50, 50)},
    )


ICONS = {
    "umbrella": icon_umbrella,
    "jacket": icon_jacket,
    "tshirt": icon_tshirt,
    "sunglasses": icon_sunglasses,
    "scarf": icon_scarf,
    "boots": icon_boots,
}


@register
class Wear(App):
    id = "wear"
    name = "What to Wear"
    description = "One big icon for the next hours — umbrella, jacket, shades, T-shirt, scarf or snow boots."
    icon = "shirt"
    category = "data"
    Settings = WearSettings
    fps = 6.0
    uses = ("wear",)
    clip_seconds = 3.0
    clip_fps = 8.0
    clip_colors = 48

    def _data(self) -> tuple[Any, dict[str, Any] | None]:
        try:
            p = self.ctx.provider("wear")
        except KeyError:
            return None, None
        return p, p.value

    def kind(self) -> Kind:
        return "clip"

    def on_start(self) -> None:
        p, _ = self._data()
        if p is not None and hasattr(p, "want"):
            p.want(self.settings.hours)

    def on_settings(self) -> None:
        self.on_start()

    def item(self, d: dict[str, Any] | None) -> str:
        if self.settings.icon != "auto":
            return self.settings.icon
        return choose(d, self.settings) if d else "tshirt"

    def clip_key(self) -> str:
        _, d = self._data()
        summary = None
        if d:
            summary = [
                self.item(d),
                round(d.get("temp", 0)),
                round(d.get("rain_prob", 0)),
                round(d.get("uv_max", 0)),
            ]
        return json.dumps([self.settings.model_dump(mode="json"), summary, d and d.get("unit")])

    def render(self, f: Frame, t: float) -> None:
        p, d = self._data()
        ph = (t / self.clip_seconds) % 1.0
        if d is None and self.settings.icon == "auto":
            if p is None or p.error:
                offline(f, "WEAR", "OFFLINE")
            else:
                loading(f, t, "WEAR", RAIN_C)
            return
        item = self.item(d)
        ix, iy = (0, 1) if d else (8, 3)  # no data: the icon is the hero, centred
        ICONS[item](f, ix, iy, ph)
        caption, col = ITEMS[item]
        if d:
            unit = d.get("unit", "C")
            temp = d["temp"] * 9 / 5 + 32 if unit == "F" else d["temp"]
            f.text_right(30, 2, f"{round(temp)}°", WHITE, font="small")
            prob = round(d.get("rain_prob", 0))
            f.sprite(DROP, 17, 11)
            f.text_right(30, 11, f"{prob}%" if prob < 100 else "100", RAIN_C)
            f.text_right(30, 18, f"UV {round(d.get('uv_max', 0))}", UV_C)
        f.text_center(25, caption, mix(col, WHITE, 0.2))

    def status(self) -> dict[str, Any]:
        _, d = self._data()
        if not d:
            return {}
        return {
            "wear": self.item(d),
            "temp_c": d.get("temp"),
            "feels_min_c": d.get("feels_min"),
            "rain_chance": d.get("rain_prob"),
            "uv_max": d.get("uv_max"),
            "hours": d.get("hours"),
        }
