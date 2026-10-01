"""Canvas — draw on the panel live. Also the target for raw frames from the API and MCP."""

from __future__ import annotations

import base64
from typing import Any

import numpy as np

from ..engine.app import Action, App, AppSettings, register
from ..gfx import Frame, to_rgb
from ._kit import empty


@register
class Canvas(App):
    id = "canvas"
    name = "Canvas"
    description = "Pixel-paint straight onto the LEDs. Your drawing is saved."
    icon = "brush"
    category = "creative"
    Settings = AppSettings
    fps = 12.0  # only produces new frames when pixels change (frames are deduped)
    actions = (Action("clear", "Clear", "eraser"),)

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        saved = self.ctx.data.get("pixels")
        self.buf = Frame()
        if isinstance(saved, str):
            try:
                self.buf = Frame.from_bytes(base64.b64decode(saved))
            except ValueError:
                pass

    def _persist(self) -> None:
        self.ctx.data["pixels"] = base64.b64encode(self.buf.to_bytes()).decode()
        self.ctx.save()
        self.ctx.invalidate()

    def render(self, f: Frame, t: float) -> None:
        if "pixels" not in self.ctx.data:  # never painted: a calm hint instead of a dark panel
            empty(f, "CANVAS", "DRAW ME", icon="star")
            return
        f.px[:] = self.buf.px

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "paint":
            # {"pixels": [[x, y, "#rrggbb"], ...]}
            for x, y, c in payload.get("pixels", []):
                self.buf.set(int(x), int(y), to_rgb(c))
        elif name == "fill":
            self.buf.clear(to_rgb(payload.get("color", "#000000")))
        elif name == "clear":
            self.buf.clear()
        elif name == "load":
            # {"rgb": base64 of 3072 bytes} or {"rows": [...32 strings], "palette": {char: colour}}
            if "rgb" in payload:
                self.buf = Frame.from_bytes(base64.b64decode(payload["rgb"]))
            elif "rows" in payload:
                self.buf = frame_from_rows(payload["rows"], payload.get("palette", {}))
            else:
                raise ValueError("load needs 'rgb' or 'rows'")
        elif name == "get":
            return {"rgb": base64.b64encode(self.buf.to_bytes()).decode()}
        else:
            raise KeyError(name)
        self._persist()
        return {"ok": True}


def frame_from_rows(rows: list[str], palette: dict[str, str]) -> Frame:
    """Pixel art from up to 32 strings of up to 32 chars; '.' or ' ' = black."""
    if len(rows) > 32 or any(len(r) > 32 for r in rows):
        raise ValueError("pixel art must be at most 32x32")
    lut = {k: to_rgb(v) for k, v in palette.items()}
    px = np.zeros((32, 32, 3), dtype=np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in ". ":
                continue
            if ch not in lut:
                raise ValueError(f"character {ch!r} (row {y}) is not in the palette")
            px[y, x] = lut[ch]
    return Frame(px)
