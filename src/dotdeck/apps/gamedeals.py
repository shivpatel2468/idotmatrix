"""Game Deals — free-game giveaways (GamerPower) and the best discounts (CheapShark), one game per screen.

Layout: store tag chip (store colour) · hero ``FREE`` or ``-85%`` · price was/now or "ends in" countdown ·
title marquee. Each game's screen is a deterministic loop (the title marquee), so it is baked as a clip; the
clip changes when the rotation moves to the next game. A brand-new free game raises a notification (the first
fetch only arms it, and seen ids persist in the app's data).
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Clip, Kind, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale
from ..gfx.color import RGB
from ..providers.gamedeals import PLATFORMS, STORES
from ._kit import loading, offline
from .pokedex import bake

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)
MARQUEE_SPEED = 10.0  # = the clip fps: exactly 1 px per frame, at the panel's verified 10 fps
DOT_OFF: RGB = (84, 84, 100)  # PALETTE "shade" is black through the panel gamma
SEEN_MAX = 300


class GameDealsSettings(AppSettings):
    source: str = Choice(
        "both", {"giveaways": "Free giveaways", "deals": "Discounts", "both": "Both"}, title="Show"
    )
    platform: str = Choice("pc", PLATFORMS, title="Giveaways: platform", group="Filters")
    sort: str = Choice(
        "popularity",
        {"popularity": "Most popular", "date": "Newest", "value": "Highest value"},
        title="Giveaways: order",
        group="Filters",
    )
    store: str = Choice("any", STORES, title="Discounts: store", group="Filters")
    max_price: float = Field(
        0,
        ge=0,
        le=100,
        title="Discounts: max price ($)",
        description="0 = any",
        json_schema_extra={"group": "Filters"},
    )
    min_savings: int = Field(
        50, ge=0, le=99, title="Discounts: min savings %", json_schema_extra={"group": "Filters"}
    )
    count: int = Field(10, ge=1, le=30, title="Games in rotation", json_schema_extra={"group": "Filters"})
    rotate: int = Field(10, ge=4, le=120, title="Seconds per game", json_schema_extra={"group": "Display"})
    notify: bool = Field(True, title="Notify on new free games", json_schema_extra={"group": "Display"})


def fmt_price(v: float | None) -> str:
    """Dollar-less prices that fit two to a row: 4.99 → '4.99', 24.73 → '25' (≥ 10 drops the cents)."""
    if v is None:
        return ""
    if v == 0:
        return "0"
    return f"{v:.2f}" if v < 10 else f"{v:.0f}"


def fmt_left(seconds: float) -> str:
    """Countdown text: '6D 4H', '5H 12M', '9M', 'ENDED'."""
    if seconds <= 0:
        return "ENDED"
    m = int(seconds // 60)
    d, h = m // 1440, (m % 1440) // 60
    if d:
        return f"{d}D {h}H"
    if h:
        return f"{h}H {m % 60}M"
    return f"{max(1, m)}M"


@register
class GameDeals(App):
    id = "gamedeals"
    name = "Game Deals"
    description = "Free-game giveaways and the best PC game discounts, with store tags and countdowns."
    icon = "gamepad-2"
    category = "games"
    Settings = GameDealsSettings
    uses = ("gamedeals",)
    fps = 2.0
    clip_fps = MARQUEE_SPEED
    clip_colors = 32
    actions = (Action("next", "Next game", "skip-forward"), Action("refresh", "Refresh", "refresh-cw"))

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._clock = time.time
        self._offset = 0
        self._seen_update = -1.0

    # ------------------------------------------------------------ data
    def _provider(self) -> Any:
        try:
            return self.ctx.provider("gamedeals")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            s = self.settings
            p.want(s.source, s.platform, s.store, s.max_price, s.sort)

    def on_settings(self) -> None:
        self.on_start()

    def items(self) -> list[dict[str, Any]]:
        p = self._provider()
        v = (p.value if p is not None else None) or {}
        s = self.settings
        out: list[dict[str, Any]] = []
        now = self._clock()
        if s.source in ("giveaways", "both"):
            out += [g for g in v.get("giveaways") or [] if not g.get("ends") or g["ends"] > now]
        if s.source in ("deals", "both"):
            deals = [
                d
                for d in v.get("deals") or []
                if d["savings"] >= s.min_savings and (s.max_price <= 0 or (d["now"] or 0) <= s.max_price)
            ]
            if s.source == "both":  # interleave so discounts don't hide behind a long giveaway list
                gv, out = out, []
                for i in range(max(len(gv), len(deals))):
                    out += gv[i : i + 1] + deals[i : i + 1]
            else:
                out += deals
        self._check_new(p, v)
        return out[: s.count]

    def _check_new(self, p: Any, v: dict[str, Any]) -> None:
        """Notify once per new free giveaway. The very first fetch only arms (records what exists)."""
        if p is None or not v or v.get("updated") == self._seen_update:
            return
        self._seen_update = v.get("updated")  # type: ignore[assignment]
        free = [g for g in v.get("giveaways") or [] if g["kind"] == "free"]
        try:
            data = self.ctx.data
        except Exception:
            return
        seen = list(data.get("seen") or [])
        armed = bool(data.get("armed"))
        new = [g for g in free if g["id"] not in seen]
        if armed and self.settings.notify:
            for g in new[:2]:
                self.ctx.notify(
                    title="FREE GAME",
                    message=f"{g['title']} ({g['tag']})"[:60],
                    icon="gift",
                    color="#00ff8c",
                )
        if new or not armed:
            seen = (seen + [g["id"] for g in new])[-SEEN_MAX:]
            data["seen"] = seen
            data["armed"] = True
            try:
                self.ctx.save()
            except Exception:
                pass

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "next":
            self._offset += 1
        elif name == "refresh":
            p = self._provider()
            if p is not None:
                p.refresh()
        else:
            raise KeyError(name)
        self.ctx.invalidate()
        return self.status()

    def current(self) -> tuple[int, dict[str, Any] | None, int]:
        items = self.items()
        if not items:
            return 0, None, 0
        i = (int(self._clock() // self.settings.rotate) + self._offset) % len(items)
        return i, items[i], len(items)

    # ------------------------------------------------------------ output
    def _period(self, it: dict[str, Any]) -> float:
        w = measure(it["title"].upper())
        return 1.2 + (w + 12) / MARQUEE_SPEED if w > 30 else 1.0

    def kind(self) -> Kind:
        return "clip" if self.current()[1] is not None else "stream"

    def clip_key(self) -> str:
        i, it, n = self.current()
        if it is None:
            return super().clip_key() + "|none"
        return super().clip_key() + f"|{it['id']}|{i}/{n}|{self._left_text(it)}"

    def clip_frames(self) -> Clip:
        _i, it, _n = self.current()
        if it is None:
            f = Frame()
            self.render(f, 0.0)
            return Clip([f], [1000])
        return bake(self, self._period(it), fps=MARQUEE_SPEED, limit=160)

    def _left_text(self, it: dict[str, Any]) -> str:
        return fmt_left(it["ends"] - self._clock()) if it.get("ends") else ""

    def render(self, f: Frame, t: float) -> None:
        i, it, n = self.current()
        if it is None:
            p = self._provider()
            if p is not None and p.error:
                offline(f, "DEALS", "OFFLINE")
            elif p is not None and p.value is not None:
                f.text_center(10, "NO DEALS", PALETTE["mute"])
                f.text_center(18, "RIGHT NOW", PALETTE["mute"])
            else:
                loading(f, t, "DEALS", PALETTE["mint"])
            return
        self.card(f, it, t % self._period(it), i, n)
        p = self._provider()
        if p is not None and p.error:
            f.set(0, 31, PALETTE["amber"])

    def card(self, f: Frame, it: dict[str, Any], t: float, i: int, n: int) -> None:
        col: RGB = tuple(it["color"])  # type: ignore[assignment]
        # store chip
        tag = it["tag"]
        tw = measure(tag)
        f.rect(0, 0, tw + 3, 7, scale(col, 0.28))
        f.text(1, 1, tag, mix(col, WHITE, 0.3))
        # rotation position: one dim tick per game along the top-right, the current one lit
        if 1 < n <= 10 and tw + 5 + 2 * n <= 32:
            for k in range(n):
                f.set(31 - 2 * (n - 1 - k), 3, scale(col, 0.9) if k == i else DOT_OFF)
        # hero
        free = it["kind"] == "free"
        if free:
            hero_c = PALETTE["mint"]
            f.text_center(10, "FREE", hero_c, font="small")
            glow = scale(hero_c, 0.4)
            f.hline(7, 18, 18, glow)
        else:
            sav = int(it["savings"])
            hero_c = PALETTE["mint"] if sav >= 75 else PALETTE["lime"] if sav >= 50 else PALETTE["gold"]
            num = f"-{sav}"
            w = measure(num, "big") + 1 + measure("%")
            x = (32 - w) // 2
            x = f.text(x, 8, num, hero_c, font="big") + 1
            f.text(x, 13, "%", hero_c)
        # price / countdown row
        y = 20
        was = fmt_price(it.get("was"))
        if free:
            left = self._left_text(it) or ("GIVEAWAY" if not was else "")
            if left:
                c = PALETTE["amber"] if left not in ("GIVEAWAY",) else PALETTE["mute"]
                f.text(1, y, left, c)
            if was and measure(left) + measure(was) + 4 <= 30:
                self._struck(f, 30 - measure(was) + 1, y, was)
        else:
            now = fmt_price(it.get("now"))
            if was:
                self._struck(f, 1, y, was)
            f.text_right(30, y, now, WHITE)
        # title
        # half a frame in: int(phase * speed) is then exact, so the title moves 1 px every frame (no 0/2 hops)
        draw_marquee(f, it["title"].upper(), t + 0.5 / MARQUEE_SPEED, 1, 26, 30, WHITE, speed=MARQUEE_SPEED)

    @staticmethod
    def _struck(f: Frame, x: int, y: int, text: str) -> None:
        end = f.text(x, y, text, PALETTE["mute"])
        f.hline(x, y + 2, end - x - 1, scale(PALETTE["bad"], 0.9))

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        i, it, n = self.current()
        if not it:
            return {"games": 0}
        return {"games": n, "index": i, "title": it["title"], "store": it["store"], "url": it.get("url")}
