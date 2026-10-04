"""Anki — cards due today (new / learning / review) with a progress bar, plus an optional word of the day.

Needs the AnkiConnect add-on. AnkiConnect's default port (8765) is DeskDot's own port, so this app talks to
**8766** by default: in Anki → Tools → Add-ons → AnkiConnect → Config set ``"webBindPort": 8766`` and
restart Anki. If the port answers but isn't AnkiConnect, the panel says PORT CLASH instead of guessing.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, scale
from ..gfx.color import RGB
from ..platforms import FEATURES
from ._kit import loading, unsupported
from ._radiator import WHITE, badge, glyph, offline_screen, provider

ACCENT: RGB = PALETTE["sky"]
# Anki's own colour language: new = blue, learning = red/orange, review = green
NEW: RGB = PALETTE["sky"]
LEARN: RGB = PALETTE["ember"]
REVIEW: RGB = PALETTE["ok"]
SPEED = 8.0  # marquee px/s = 1 px per frame at fps 8 (12 px/s at 4 fps jumped 3 px)


class AnkiSettings(AppSettings):
    host: str = Field("127.0.0.1", max_length=120, title="Host", json_schema_extra={"group": "AnkiConnect"})
    port: int = Field(
        8766,
        ge=1,
        le=65535,
        title="Port",
        description=(
            'AnkiConnect defaults to 8765, which DeskDot already uses. Set "webBindPort": 8766 in '
            "Anki → Tools → Add-ons → AnkiConnect → Config and restart Anki."
        ),
        json_schema_extra={"group": "AnkiConnect"},
    )
    key: str = Field(
        "",
        max_length=120,
        title="API key (optional)",
        description='Only if you set "apiKey" in AnkiConnect\'s config. Never logged.',
        json_schema_extra={"group": "AnkiConnect", "format": "password", "writeOnly": True},
    )
    deck: str = Field(
        "",
        max_length=120,
        title="Deck",
        description="Exact deck name, e.g. Japanese::Core 2k. Blank = all decks",
        json_schema_extra={"group": "Display"},
    )
    layout: str = Choice(
        "due", {"due": "Cards due", "word": "Word of the day"}, title="Layout", group="Display"
    )


@register
class Anki(App):
    id = "anki"
    name = "Anki"
    description = "Anki cards due today (new, learning, review) with progress, and a word of the day."
    icon = "layers"
    category = "productivity"
    Settings = AnkiSettings
    fps = 8.0  # only moving text changes frames; static screens are deduped
    uses = ("anki",)
    platforms = FEATURES["lan"]  # AnkiConnect: plain http on 127.0.0.1, browsers' origins refused
    web_reason = (
        "AnkiConnect answers plain http on your computer and only lets local pages call it; "
        "use the desktop, Raspberry Pi or Android app."
    )

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.on_settings()

    def on_start(self) -> None:
        p = provider(self.ctx, "anki")
        if p is not None and hasattr(p, "configure"):
            s = self.settings
            p.configure(s.host, s.port, s.key, s.deck, word=s.layout == "word")

    def on_settings(self) -> None:
        self.on_start()

    def _value(self) -> tuple[Any, dict[str, Any] | None]:
        p = provider(self.ctx, "anki")
        return p, (p.value if p is not None else None)

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        if not self.supported_here():
            unsupported(f, "ANKI")
            return
        _p, v = self._value()
        if v is None:
            loading(f, t, "ANKI", ACCENT)
            return
        state = v.get("state")
        if state == "off":
            self._off(f)
            return
        if state in ("conflict", "notanki"):
            self._clash(f, t, v)
            return
        if state == "nodeck":
            offline_screen(f, "anki", "ANKI", "NO DECK")
            return
        if state == "auth":
            offline_screen(f, "anki", "ANKI", "API KEY")
            return
        if state != "ok":
            offline_screen(f, "anki", "ANKI", "ERROR")
            return
        if int(v.get("due") or 0) == 0:
            self._done(f, t, v)
        elif self.settings.layout == "word":
            self._word(f, t, v)
        else:
            self._due(f, t, v)

    def _off(self, f: Frame) -> None:
        g = glyph("anki", PALETTE["dim"])
        f.sprite(g, (32 - g.w) // 2, 4)
        f.text_center(16, "ANKI", PALETTE["mute"])
        f.text_center(24, "CLOSED", PALETTE["dim"])

    def _clash(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        f.text_center(1, "PORT", PALETTE["amber"])
        f.text_center(8, str(v.get("port") or self.settings.port), WHITE, font="small")
        f.text_center(17, "CLASH" if v.get("state") == "conflict" else "NOT ANKI", PALETTE["amber"])
        hint = (
            "8765 IS DESKDOT - SET ANKICONNECT WEBBINDPORT 8766"
            if v.get("state") == "conflict"
            else "NO ANKICONNECT ON THIS PORT - CHECK WEBBINDPORT"
        )
        draw_marquee(f, hint, t, 1, 25, 30, PALETTE["mute"], speed=SPEED)

    def _counts(self, f: Frame, y: int, v: dict[str, Any]) -> None:
        """Three coloured columns: new · learning · review."""
        vals = [
            (int(v.get("new") or 0), NEW),
            (int(v.get("learn") or 0), LEARN),
            (int(v.get("review") or 0), REVIEW),
        ]
        for i, (n, c) in enumerate(vals):
            s = str(n) if n < 1000 else f"{n // 1000}K"
            cx = 1 + i * 10 + (9 - measure(s)) // 2
            f.text(cx, y, s, c if n else scale(c, 0.35))

    def _progress(self, f: Frame, y: int, v: dict[str, Any]) -> None:
        done, due = int(v.get("reviewed") or 0), int(v.get("due") or 0)
        frac = done / (done + due) if done + due else 0.0
        f.bar(1, y, 30, 2, frac, REVIEW, track=PALETTE["shade"])

    def _label(self, v: dict[str, Any]) -> str:
        deck = str(v.get("deck") or "")
        return (deck.split("::")[-1] or "ANKI").upper() if deck else "ANKI"

    def _due(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        draw_marquee(f, self._label(v), t, 1, 1, 30, PALETTE["mute"], speed=SPEED)
        g = glyph("anki", ACCENT)
        due = int(v.get("due") or 0)
        num = str(min(due, 9999))
        w = measure(num, "big")
        if due >= 1000:  # four big digits fill the width on their own
            f.text((32 - w) // 2, 8, num, WHITE, font="big")
        else:
            gap = 3
            x = (32 - (g.w + gap + w)) // 2
            f.sprite(g, x, 9)
            f.text(x + g.w + gap, 8, num, WHITE, font="big")
        self._counts(f, 21, v)
        self._progress(f, 28, v)

    def _word(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        f.text(1, 1, "WORD", PALETTE["dim"])
        f.text_right(30, 1, str(v.get("due") or 0), WHITE)
        word = str(v.get("word") or "") or "-"
        if measure(word, "small") <= 30:
            f.text_center(10, word, ACCENT, font="small")
        else:
            draw_marquee(f, word, t, 1, 11, 30, ACCENT, speed=SPEED)
        self._counts(f, 21, v)
        self._progress(f, 28, v)

    def _done(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        badge(f, 15, 9, 6, "pass", t)
        f.text_center(18, "ALL DONE" if measure("ALL DONE") <= 30 else "DONE", REVIEW)  # keep the 1 px margin
        n = int(v.get("reviewed") or 0)
        f.text_center(25, f"{n} TODAY" if n else self._label(v)[:8], PALETTE["mute"])

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        _p, v = self._value()
        v = v or {}
        return {
            "state": v.get("state", "unknown"),
            "due": v.get("due"),
            "new": v.get("new"),
            "learn": v.get("learn"),
            "review": v.get("review"),
            "reviewed_today": v.get("reviewed"),
            "port": self.settings.port,
            "key": "set" if self.settings.key else "",
        }
