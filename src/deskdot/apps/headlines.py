"""Headlines — Hacker News, Spaceflight News, DEV and Lobsters on the panel.

Layouts:

* ``card``   one story per screen: source badge, rank, age · score (small) and comments · points bar · title
  (smooth marquee, baked as a clip, or word-wrapped pages, streamed).
* ``big``    one hero number: the points in the `big` font, rank and comments above/below, title marquee.
* ``ticker`` a vertical news ticker scrolling through the whole list (baked as a clip).
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import PALETTE, Frame, Sprite, measure, scale, to_rgb
from ..gfx.color import RGB
from ..gfx.font import FONTS, marquee_x
from ..providers.headlines import FEEDS, SOURCES
from ._kit import compact_number, loading, offline
from .daily import font_can_draw, wrap_text

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)
SOURCE_COLORS: dict[str, RGB] = {
    "hn": (255, 102, 0),
    "space": PALETTE["sky"],
    "devto": (235, 235, 235),
    "lobsters": PALETTE["rose"],
}
BADGE_LETTER = {"hn": "Y", "space": "S", "devto": "D", "lobsters": "L"}
COMMENT = Sprite.parse(["####", "#..#", "####", "#..."], {"#": PALETTE["mute"]})
CLIP_FPS = 10  # the fastest clip rate verified on the panel: marquees and the ticker move 1 px per frame
MAX_FRAMES = 200  # per baked loop (GIF budget); longer loops take 2 px steps, still even


def hyphenate(title: str, width: int = 30) -> str:
    """Split words wider than the panel into hyphenated pieces ("SNAPDR- AGON"): `wrap_text` otherwise squeezes
    them into touching letters, which read as a smudge on the LEDs."""
    out = []
    for word in title.split():
        while measure(word) > width:
            cut = len(word) - 1
            while cut > 1 and measure(word[:cut] + "-") > width:
                cut -= 1
            out.append(word[:cut] + "-")
            word = word[cut:]
        out.append(word)
    return " ".join(out)


def wrapped_line(f: Frame, y: int, text: str, color: RGB, center: bool = False) -> None:
    """One wrapped title line. Words wider than the panel come back from `wrap_text` sized for touching
    letters, so draw those with spacing 0 (they ran past the right edge)."""
    sp = 1 if measure(text) <= 30 else 0
    if center:
        f.text_center(y, text, color, spacing=sp)
    else:
        f.text(1, y, text, color, spacing=sp)


def age_text(ts: float | None, now: float) -> str:
    if not ts:
        return ""
    s = max(0.0, now - ts)
    if s < 3600:
        return f"{max(1, int(s // 60))}M"
    if s < 86400:
        return f"{int(s // 3600)}H"
    return f"{int(s // 86400)}D"


class HeadlinesSettings(AppSettings):
    source: str = Choice("hn", SOURCES, title="Source", group="News")
    feed: str = Choice(
        "top",
        {f: f.title() for f in FEEDS},
        title="Feed",
        description="Hacker News: all five · DEV: top (day) / best (week) / new · Lobsters: hottest / active / newest",
        group="News",
    )
    count: int = Field(10, ge=1, le=30, title="Stories", json_schema_extra={"group": "News"})
    min_points: int = Field(
        0,
        ge=0,
        le=2000,
        title="Minimum points",
        description="Skip stories below this score (sources without scores ignore it)",
        json_schema_extra={"group": "News"},
    )
    layout: str = Choice(
        "card",
        {"card": "Story card", "big": "Big number", "ticker": "Vertical ticker"},
        title="Layout",
        group="Layout",
    )
    title_style: str = Choice(
        "marquee", {"marquee": "Marquee", "wrap": "Word-wrapped pages"}, title="Title", group="Layout"
    )
    rotate: int = Field(
        10,
        ge=3,
        le=120,
        title="Seconds per story",
        description="Minimum; a scrolling title always finishes its pass",
        json_schema_extra={"group": "Layout"},
    )
    speed: int = Field(12, ge=4, le=24, title="Scroll speed (px/s)", json_schema_extra={"group": "Layout"})
    colors: str = Choice(
        "source", {"source": "Source colour", "custom": "Custom"}, title="Accent", group="Colours"
    )
    accent: Color = Field("#ff6600", title="Custom accent", json_schema_extra={"group": "Colours"})
    text_color: Color = Field("#ffffff", title="Title", json_schema_extra={"group": "Colours"})


@register
class Headlines(App):
    id = "headlines"
    name = "Headlines"
    description = (
        "Hacker News, Spaceflight News, DEV and Lobsters: story cards, big points or a vertical ticker."
    )
    icon = "newspaper"
    category = "data"
    Settings = HeadlinesSettings
    fps = 2.0
    uses = ("headlines",)
    clip_colors = 32
    actions = (Action("next", "Next story", "skip-forward"),)
    _clock: ClassVar[Any] = staticmethod(time.monotonic)
    MAX_CLIP_FRAMES: ClassVar[int] = MAX_FRAMES

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.on_settings()

    # ------------------------------------------------------------ lifecycle / data
    def _provider(self) -> Any:
        try:
            return self.ctx.provider("headlines")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(self.settings.source, self.settings.feed, self.settings.count)

    def on_settings(self) -> None:
        self.idx = 0
        self.t0: float | None = None
        self.dur = 1.0
        self._skip = False
        self._tape: tuple[str, list[tuple[int, str, RGB, str]], int, list[int]] | None = None
        self.on_start()

    def stories(self) -> list[dict[str, Any]]:
        p = self._provider()
        if p is None or not p.value:
            return []
        key = p.key(self.settings.source, self.settings.feed)
        lst = (p.value.get(key) or [])[: self.settings.count]
        mp = self.settings.min_points
        if mp:
            lst = [s for s in lst if s.get("score") is None or s["score"] >= mp]
        return lst

    def accent(self) -> RGB:
        if self.settings.colors == "custom":
            return to_rgb(self.settings.accent)
        return SOURCE_COLORS.get(self.settings.source, PALETTE["amber"])

    # ------------------------------------------------------------ scheduling
    def _title_font(self, title: str) -> str:
        return "small" if self.settings.layout == "card" and font_can_draw(title, "small") else "tiny"

    @property
    def speed(self) -> int:
        """Marquee px/s: the setting, capped at the clip frame rate (1 px per frame, never uneven hops)."""
        return min(int(self.settings.speed), CLIP_FPS)

    def _pass(self, title: str) -> float:
        font = self._title_font(title)
        w = measure(title, font)
        return 3.0 if w <= 30 else self.hold + (w + 12) / self.speed

    @property
    def hold(self) -> float:
        """The marquee's pause at the start of each pass, in whole frames of the baked clip."""
        return round(1.2 * self.speed / 2) * 2 / self.speed  # even: also whole steps when frames move 2 px

    def _wrap_pages(self, title: str) -> list[list[str]]:
        lines = wrap_text(hyphenate(title), 30, "tiny")
        return [lines[i : i + 2] for i in range(0, len(lines), 2)] or [[""]]

    def story_seconds(self, s: dict[str, Any]) -> float:
        if self.settings.title_style == "wrap" and self.settings.layout == "card":
            return max(float(self.settings.rotate), 2.6 * len(self._wrap_pages(s["title"])))
        return max(float(self.settings.rotate), self._pass(s["title"]))

    def current(self) -> tuple[dict[str, Any] | None, float]:
        """The story on screen and seconds since it appeared (advances on its own clock)."""
        lst = self.stories()
        if not lst:
            return None, 0.0
        now = self._clock()
        if self.t0 is None or now < self.t0:
            self.t0, self.idx = now, 0
            self.dur = self.story_seconds(lst[0])
        if self._skip or now - self.t0 >= self.dur:
            self._skip = False
            self.idx = (self.idx + 1) % len(lst)
            self.t0 = now
        self.idx %= len(lst)
        s = lst[self.idx]
        self.dur = self.story_seconds(s)
        return s, now - self.t0

    # ------------------------------------------------------------ pieces
    def badge(self, f: Frame, x: int, y: int) -> None:
        c = self.accent()
        f.rect(x, y, 5, 5, c)
        f.text(x + 1, y, BADGE_LETTER.get(self.settings.source, "N"), BLACK)

    def head(self, f: Frame, s: dict[str, Any], now: float) -> None:
        self.badge(f, 1, 1)
        f.text(8, 1, f"#{s.get('rank', self.idx + 1)}", WHITE)
        age = age_text(s.get("time"), now)
        if age:
            f.text_right(30, 1, age, PALETTE["mute"])

    def title_line(self, f: Frame, s: dict[str, Any], t_in: float, y: int, font: str | None = None) -> None:
        title = s["title"]
        font = font or self._title_font(title)
        c = to_rgb(self.settings.text_color)
        w = measure(title, font)
        if w <= 30:
            f.text((32 - w) // 2, y, title, c, font=font)
            return
        x = marquee_x(title, t_in, 1, 30, font, self.speed, 12, self.hold)
        clip = (1, y, 30, y + FONTS[font].height - 1)
        f.text(x, y, title, c, font=font, clip=clip)
        f.text(x + w + 12, y, title, c, font=font, clip=clip)

    def comments(self, f: Frame, s: dict[str, Any], right: int, y: int, left: int = 1) -> None:
        """Comment count, right-aligned, with its bubble when there is room; nothing left of `left`."""
        n = s.get("comments")
        if n is None:
            return
        txt = compact_number(float(n)) if n >= 1000 else str(n)
        x = right - measure(txt) + 1
        if x < left:
            return  # it would run into the score: the score wins
        f.text_right(right, y, txt, PALETTE["mute"])
        if x - 5 >= left:
            f.sprite(COMMENT, x - 5, y)

    # ------------------------------------------------------------ layouts
    def draw_card(self, f: Frame, s: dict[str, Any], t_in: float, now: float) -> None:
        c = self.accent()
        self.head(f, s, now)
        score = s.get("score")
        lst = self.stories()
        if score is not None:
            txt = compact_number(float(score)) if score >= 10000 else str(score)
            end = f.text(1, 8, txt, WHITE, font="small")
            self.comments(f, s, 30, 10, left=end + 2)  # the bubble used to sit on top of the score
            top = max([x.get("score") or 0 for x in lst] + [1])
            f.rect(1, 17, 30, 1, PALETTE["shade"])
            f.rect(1, 17, max(1, round(30 * score / top)), 1, c)
        else:
            site = s.get("site") or ""
            f.text(1, 10, site if measure(site) <= 30 else site[:7], scale(c, 0.9))
            f.rect(1, 17, 30, 1, PALETTE["shade"])
            n = len(lst)
            seg = max(1, 30 // max(1, n))
            f.rect(1 + self.idx * seg, 17, seg, 1, c)
        if self.settings.title_style == "wrap":
            pages = self._wrap_pages(s["title"])
            k = min(len(pages) - 1, int(t_in / 2.6))
            y = 20 if len(pages[k]) > 1 else 23
            for ln in pages[k]:
                wrapped_line(f, y, ln, to_rgb(self.settings.text_color), center=True)
                y += 6
            if len(pages) > 1:
                for j in range(len(pages)):
                    f.set(31, 20 + 2 * j, c if j == k else scale(c, 0.4))
        else:
            font = self._title_font(s["title"])
            self.title_line(f, s, t_in, 21 if font == "small" else 23, font)

    def draw_big(self, f: Frame, s: dict[str, Any], t_in: float, now: float) -> None:
        c = self.accent()
        self.head(f, s, now)
        score = s.get("score")
        num = str(score) if score is not None else str(s.get("rank", self.idx + 1))
        if measure(num, "big") > 30:
            num = compact_number(float(num))
        font = (
            "big" if all(ch.isdigit() or ch == "." for ch in num) and measure(num, "big") <= 30 else "small"
        )
        f.text_center(8, num, WHITE if score is not None else c, font=font)
        label = "POINTS" if score is not None else f"OF {len(self.stories())}"
        if s.get("comments") is not None:
            end = f.text(1, 20, "PTS", scale(c, 0.85))
            self.comments(f, s, 30, 20, left=end + 2)
        else:
            f.text_center(20, label, scale(c, 0.85))
        f.hline(1, 26, 30, PALETTE["ink"])
        self.title_line(f, s, t_in, 26, "tiny")

    # ticker: glide to each story, hold, glide on (baked as a clip) ------------------------------------
    GLIDE_PX: ClassVar[int] = 1  # px per glide frame
    GLIDE_MS: ClassVar[int] = 1000 // CLIP_FPS  # 10 px/s in even 1 px steps (50 ms frames outran the panel)

    def _tape_lines(self) -> tuple[list[tuple[int, str, RGB, str]], int, list[int]]:
        """[(y, text, colour, align)] for the whole list, its total height and the offsets to hold at."""
        lst = self.stories()
        sig = json.dumps([(s["id"], s.get("score"), s["title"]) for s in lst])
        if self._tape and self._tape[0] == sig:
            return self._tape[1], self._tape[2], self._tape[3]
        c = self.accent()
        tc = to_rgb(self.settings.text_color)
        out: list[tuple[int, str, RGB, str]] = []
        stops: list[int] = []
        y = 0
        for s in lst[:6]:
            top = y
            meta = f"#{s.get('rank', 0)}"
            if s.get("score") is not None:
                meta += f" {compact_number(float(s['score'])) if s['score'] >= 10000 else s['score']}"
            out.append((y, meta, c, "left"))
            if s.get("comments") is not None and measure(meta) + 3 + measure(str(s["comments"])) <= 30:
                out.append((y, str(s["comments"]), PALETTE["mute"], "right"))  # only when it can't collide
            y += 7
            for ln in wrap_text(hyphenate(s["title"]), 30, "tiny"):
                out.append((y, ln, tc, "left"))
                y += 6
            out.append((y + 1, "", scale(c, 0.5), "rule"))
            y += 5
            stops.append(top)
            if y - top > 32:  # tall story: a second stop shows its end
                stops.append(y - 32)
        total = max(32, y)
        self._tape = (sig, out, total, stops)
        return out, total, stops

    def _ticker_timeline(self) -> list[tuple[int, float]]:
        """[(offset, seconds)]: every glide step, then one long hold per stop."""
        _lines, total, stops = self._tape_lines()
        hold = max(2.0, float(self.settings.rotate) / 2)
        step = max(self.GLIDE_PX, math.ceil(total / (MAX_FRAMES - len(stops))))  # holds count as frames
        out: list[tuple[int, float]] = []
        for k, a in enumerate(stops):
            b = stops[k + 1] if k + 1 < len(stops) else total  # the last glide wraps to the start
            out.append((a, hold))
            for off in range(a + step, b, step):
                out.append((off, self.GLIDE_MS / 1000))  # always 10 fps; long lists take 2 px steps
        return out

    def draw_ticker(self, f: Frame, t: float = 0.0, offset: int | None = None) -> None:
        lines, total, _stops = self._tape_lines()
        if offset is None:
            tl = self._ticker_timeline()
            period = sum(d for _o, d in tl) or 1.0
            tt = t % period
            offset = tl[-1][0]
            for o, d in tl:
                if tt < d:
                    offset = o
                    break
                tt -= d
        off = offset % total
        for rep in (0, total):
            for y, text, col, align in lines:
                yy = y - off + rep + 1
                if yy < -6 or yy > 31:
                    continue
                if align == "rule":
                    f.hline(8, yy, 16, col)
                elif align == "right":
                    f.text_right(30, yy, text, col)
                else:
                    wrapped_line(f, yy, text, col)

    # ------------------------------------------------------------ render
    def _placeholder(self, f: Frame, t: float) -> None:
        p = self._provider()
        label = {"hn": "HN", "space": "SPACE", "devto": "DEV", "lobsters": "LOBSTERS"}[self.settings.source]
        if p is not None and p.value and p.key(self.settings.source, self.settings.feed) in p.value:
            f.text_center(10, label, scale(self.accent(), 0.8))
            f.text_center(17, "NO NEWS", PALETTE["mute"])
        elif p is not None and p.error:
            offline(f, label, "OFFLINE")
        else:
            loading(f, t, label, self.accent())

    def paint(self, f: Frame, s: dict[str, Any], t_in: float, now: float) -> None:
        if self.settings.layout == "big":
            self.draw_big(f, s, t_in, now)
        else:
            self.draw_card(f, s, t_in, now)

    def render(self, f: Frame, t: float) -> None:
        if self.settings.layout == "ticker":
            if not self.stories():
                self._placeholder(f, t)
                return
            self.draw_ticker(f, t)
            return
        s, t_in = self.current()
        if s is None:
            self._placeholder(f, t)
            return
        self.paint(f, s, t_in, time.time())

    # ------------------------------------------------------------ clips
    def _clip_mode(self) -> bool:
        if not self.stories():
            return False
        if self.settings.layout == "ticker":
            return True
        return self.settings.title_style == "marquee" or self.settings.layout == "big"

    def kind(self) -> Kind:
        return "clip" if self._clip_mode() else "stream"

    def clip_key(self) -> str:
        if self.settings.layout == "ticker":
            lines, total, stops = self._tape_lines()
            return super().clip_key() + json.dumps([[ln[1] for ln in lines], total, stops])
        s, _ = self.current()
        if s is None:
            return super().clip_key()
        # age is coarse (minutes/hours), so it can live in the key without re-baking often
        return super().clip_key() + json.dumps(
            [s["id"], s.get("score"), s.get("comments"), age_text(s.get("time"), time.time())]
        )

    def clip_frames(self) -> Clip:
        if self.settings.layout == "ticker":
            frames, durs = [], []
            for off, secs in self._ticker_timeline():
                f = Frame()
                self.draw_ticker(f, offset=off)
                frames.append(f)
                durs.append(round(secs * 1000))
            return Clip(frames, durs)
        s, _ = self.current()
        if s is None:
            f = Frame()
            self._placeholder(f, 0.0)
            return Clip([f], [1000])
        secs = self._pass(s["title"])
        sp = self.speed
        px = max(1, math.ceil(secs * sp / self.MAX_CLIP_FRAMES))  # px per frame: 1, or 2 for very long titles
        n = max(1, round(secs * sp / px))
        dt = px / sp
        now = time.time()
        frames = []
        for i in range(n):
            f = Frame()
            # half a pixel into each step so int(phase * speed) is exact (float error gave 0/2 px hops)
            self.paint(f, s, (i + 0.5 / px) * dt, now)
            frames.append(f)
        return Clip(frames, [round(dt * 1000)] * n)

    # ------------------------------------------------------------ actions / status
    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "input":
            if str(payload.get("key", "")).lower() not in (
                "right",
                "arrowright",
                "down",
                "arrowdown",
                "a",
                " ",
            ):
                return self.status()
        elif name != "next":
            raise KeyError(name)
        self._skip = True
        try:
            self.ctx.invalidate()
        except Exception:
            pass
        return self.status()

    def status(self) -> dict[str, Any]:
        lst = self.stories()
        s = lst[self.idx % len(lst)] if lst else {}
        return {"stories": len(lst), "rank": s.get("rank"), "title": s.get("title"), "score": s.get("score")}
