"""Text Studio — compose the panel from layers you place by clicking on the studio preview.

Each layer is text or a live value (time, date, temperature, CPU, RAM, a crypto price) with its own
position, font, colour and effect. The studio edits `layers` directly on the LED preview; boxes
reported by `status()` drive its hit-testing, so what you click is exactly what's drawn.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import Frame, hsv, mix, scale
from ..gfx.font import FONTS, draw_marquee, measure
from ._kit import compact_number

Kind = Literal["text", "time", "seconds", "date", "month", "day", "weather", "cpu", "ram", "price"]
Effect = Literal["solid", "rainbow", "gradient", "pulse", "blink", "scroll", "glow"]


class Layer(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:6])
    kind: Kind = "text"
    text: str = Field("HELLO", max_length=120)
    x: int = Field(1, ge=-64, le=63)
    y: int = Field(1, ge=-16, le=31)
    font: Literal["tiny", "small", "big"] = "small"
    color: str = Field("#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    color2: str = Field("#ff00be", pattern=r"^#[0-9a-fA-F]{6}$")
    effect: Effect = "solid"
    align: Literal["left", "center", "right"] = "left"
    visible: bool = True


DEFAULT_LAYERS = [
    Layer(id="time", kind="time", text="", x=1, y=4, font="big", color="#ffffff"),
    Layer(id="date", kind="date", text="", x=0, y=18, font="tiny", color="#ff4818", align="center"),
    Layer(
        id="msg",
        kind="text",
        text="HAVE A GREAT DAY",
        x=0,
        y=25,
        font="tiny",
        color="#00dcff",
        effect="scroll",
        align="left",
    ),
]


class ComposerSettings(AppSettings):
    layers: list[Layer] = Field(
        default_factory=lambda: [lay.model_copy() for lay in DEFAULT_LAYERS],
        json_schema_extra={"format": "layers"},
    )
    background: str = Choice(
        "none",
        {"none": "Black", "solid": "Solid", "gradient": "Gradient", "border": "Border", "stars": "Twinkle"},
    )
    bg: Color = Field("#10061a", title="Background")
    bg2: Color = Field("#001428", title="Background 2")


@register
class Composer(App):
    id = "composer"
    name = "Text Studio"
    description = "Click the preview to place text and live values — drag, restyle, animate. Your own layout."
    icon = "text-cursor-input"
    category = "creative"
    Settings = ComposerSettings
    fps = 10.0  # frames are deduped: a layout without effects still costs nothing
    uses = ("system", "weather", "markets")

    def on_start(self) -> None:
        syms = [lay.text for lay in self.settings.layers if lay.kind == "price" and lay.text.strip()]
        if syms:
            self.ctx.provider("markets").want(*syms)

    on_settings = on_start

    # ----------------------------------------------------------------- values
    def resolve(self, lay: Layer) -> str:
        now = datetime.now()
        k = lay.kind
        if k == "time":
            return now.strftime("%H:%M")
        if k == "seconds":
            return now.strftime("%H:%M:%S")
        if k == "date":
            return now.strftime("%a %d").upper()
        if k == "month":
            return now.strftime("%d %b").upper()
        if k == "day":
            return now.strftime("%A").upper()
        if k == "weather":
            w = self.ctx.provider("weather").value
            return f"{w['temp']}°" if w else "--°"
        if k in ("cpu", "ram"):
            s = self.ctx.provider("system").value
            return f"{lay.text}{s[k]}%" if s else f"{lay.text}--%"
        if k == "price":
            sym = lay.text.strip().upper() or "BTC"
            d = (self.ctx.provider("markets").value or {}).get(sym)
            return f"{sym} {compact_number(d['price'])}" if d else f"{sym} ..."
        return lay.text

    def box(self, lay: Layer) -> tuple[int, int, int, int]:
        """(x, y, w, h) of the layer as drawn."""
        text = self.resolve(lay)
        font = lay.font if lay.font != "big" or all(c in "0123456789:.- " for c in text) else "small"
        w = measure(text, font)
        h = FONTS[font].height
        x = lay.x
        if lay.align == "center":
            x = (32 - w) // 2
        elif lay.align == "right":
            x = 31 - w
        if lay.effect == "scroll":
            x, w = (
                max(0, lay.x if lay.align == "left" else 0),
                32 - max(0, lay.x if lay.align == "left" else 0),
            )
        return x, lay.y, w, h

    # ----------------------------------------------------------------- render
    def _background(self, f: Frame, t: float) -> None:
        s = self.settings
        if s.background == "solid":
            f.clear(s.bg)
        elif s.background == "gradient":
            f.gradient_v(s.bg, s.bg2)
        elif s.background == "border":
            f.rect(0, 0, 32, 32, s.bg2 if s.bg2 != "#001428" else "#ff4818", fill=False)
        elif s.background == "stars":
            for i in range(14):
                x, y = (i * 37 + 5) % 32, (i * 53 + 11) % 32
                k = 0.2 + 0.8 * max(0.0, math.sin(t * 1.7 + i * 2.1))
                f.set(x, y, scale((200, 200, 255), k * 0.6))

    def render(self, f: Frame, t: float) -> None:
        self._background(f, t)
        for lay in self.settings.layers:
            if lay.visible:
                self._draw(f, t, lay)

    def _draw(self, f: Frame, t: float, lay: Layer) -> None:
        text = self.resolve(lay)
        if not text:
            return
        font = lay.font if lay.font != "big" or all(c in "0123456789:.- " for c in text) else "small"
        x, y, w, _h = self.box(lay)
        eff = lay.effect
        base = lay.color
        if eff == "pulse":
            base = scale(lay.color, 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 4)))
        elif eff == "blink" and int(t * 2) % 2:
            return
        elif eff == "glow":
            glow = scale(lay.color, 0.25 + 0.15 * math.sin(t * 3))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                f.text(x + dx, y + dy, text, glow, font=font)
        if eff == "scroll":
            # 10 px/s on the 10 fps tick: exactly one pixel per frame, an even rhythm (14 px/s at 6 fps
            # stepped 2, 2, 3 px and read as stutter)
            tick = math.floor(t * self.fps + 1e-6) / self.fps
            draw_marquee(f, text, tick, x, y, w, lay.color, font=font, speed=10)
            return
        if eff in ("rainbow", "gradient"):
            cur = x
            for ch in text:
                col = (
                    hsv(cur / 40 + t * 0.25)
                    if eff == "rainbow"
                    else mix(lay.color, lay.color2, (cur - x) / max(1, w))
                )
                cur = f.text(cur, y, ch, col, font=font) + 1
            return
        f.text(x, y, text, base, font=font)

    def status(self) -> dict[str, Any]:
        return {
            "boxes": [
                {"id": lay.id, "x": b[0], "y": b[1], "w": b[2], "h": b[3], "text": self.resolve(lay)}
                for lay in self.settings.layers
                if lay.visible
                for b in [self.box(lay)]
            ],
        }
