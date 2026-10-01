"""Daily Dose — quotes, jokes, facts, advice and "on this day" in one rotating card.

Every item gets a source tag (a 5×5 icon drawn from scratch plus a tiny label) and its text either as
**pages** (word-wrapped, auto-fitted: `small` when the whole item fits, `tiny` otherwise; streamed, one frame
per page) or as a **marquee** (one smooth pass, baked as a clip). Quotes carry an author line; two-part jokes
show the setup, a drum-roll pause, then the punchline in its own colour.

The text-layout helpers here (`flow_pages`, `font_can_draw`, `Page`) are shared by Trivia and Headlines.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import PALETTE, Frame, Sprite, measure, scale, to_rgb
from ..gfx.color import RGB
from ..gfx.font import FONTS, draw_marquee, marquee_x
from ..providers.daily import SOURCES
from ._kit import loading, offline

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)


# ============================================================================ shared text layout
def font_can_draw(text: str, font: str) -> bool:
    glyphs = FONTS[font].glyphs
    return all(ch.upper() in glyphs for ch in text)


LINE_PITCH = {"tiny": 6, "small": 9}


def _split_word(word: str, room: int, font: str) -> tuple[str, str] | None:
    """Break at an existing natural hyphen if one exists and fits `room`."""
    for k in range(len(word) - 2, 1, -1):
        if word[k - 1] == "-" and measure(word[:k], font) <= room:
            return word[:k], word[k:]
    return None


def wrap_text(text: str, width: int = 30, font: str = "tiny") -> list[str]:
    """Greedy word wrap. Words are kept intact without synthetic hyphens; only existing hyphens are split."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        cand = f"{line} {word}" if line else word
        if measure(cand, font) <= width:
            line = cand
            continue
        if line and "-" in word:
            room = width - (measure(line + " ", font) + 1)
            cut = _split_word(word, room, font)
            if cut:
                lines.append(f"{line} {cut[0]}")
                word = cut[1]
                line = ""
        if line:
            lines.append(line)
            line = ""
        if measure(word, font) <= width:
            line = word
            continue
        if "-" in word:
            cut = _split_word(word, width, font)
            if cut:
                lines.append(cut[0])
                word = cut[1]
        if font == "tiny" and measure(word, font, spacing=0) <= width:
            line = word
            continue
        while measure(word, font, spacing=0) > width:
            cut = len(word)
            while cut > 1 and measure(word[:cut], font, spacing=0) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        line = word
    if line:
        lines.append(line)
    return lines


@dataclass
class Page:
    """One screen of text: lines of (text, role), the font, and how long it stays up."""

    lines: list[tuple[str, str]] = field(default_factory=list)
    font: str = "tiny"
    dur: float = 3.0
    kind: str = "text"  # "text" | "pause"


def reading_time(lines: list[tuple[str, str]], pace: float = 1.0) -> float:
    words = sum(len(t.split()) for t, _r in lines)
    return max(2.2, 1.0 + 0.36 * words) * pace


def flow_pages(
    parts: list[tuple[str, str]],
    width: int = 30,
    rows: int = 4,
    font: str = "tiny",
    pace: float = 1.0,
    keep_together: tuple[str, ...] = ("author",),
) -> list[Page]:
    """Wrap `parts` [(text, role)] into pages of at most `rows` lines.

    Body lines are balanced across the pages (4+4+1 becomes 3+3+3) so no page is left with an orphaned
    word; parts whose role is in `keep_together` (the author line) are never split and go on the last page
    when they fit, else on a page of their own.
    """
    body: list[tuple[str, str]] = []
    tail: list[tuple[str, str]] = []
    for text, role in parts:
        lines = [(ln, role) for ln in wrap_text(text, width, font)]
        (tail if role in keep_together else body).extend(lines)
    pages: list[Page] = []
    if body:
        n = math.ceil(len(body) / rows)
        base, extra = divmod(len(body), n)
        i = 0
        for k in range(n):
            size = base + (1 if k < extra else 0)
            pages.append(Page(body[i : i + size], font))
            i += size
    for k in range(0, len(tail), rows):
        chunk = tail[k : k + rows]
        if pages and k == 0 and len(pages[-1].lines) + len(chunk) <= rows:
            pages[-1].lines.extend(chunk)
        else:
            pages.append(Page(chunk, font))
    for p in pages:
        p.dur = reading_time(p.lines, pace)
    return pages


# ============================================================================ source art
# 5×5 icons, one colour each; silhouettes first (docs/DISPLAY_DESIGN.md §7)
ICON_ROWS: dict[str, list[str]] = {
    "quote": [".#..#", "#..#.", "##.##", "##.##", "....."],
    "qotd": ["#.#.#", ".###.", "##.##", ".###.", "#.#.#"],
    "dad": [".###.", "#.#.#", "#####", "#...#", ".###."],
    "fact": [".###.", "#...#", "#...#", ".#.#.", ".###."],
    "fact_today": [".###.", "#...#", "#...#", ".#.#.", ".###."],
    "advice": ["#####", "#...#", "#####", ".#...", "#...."],
    "cat": ["#...#", "##.##", "#####", "#.#.#", ".###."],
    "joke": ["..#..", ".#.#.", "#...#", ".#.#.", "..#.."],
    "chuck": ["..#..", "#####", ".###.", ".#.#.", "#...#"],
    "kanye": ["#.#.#", "#####", "#.#.#", "#####", "....."],
    "history": ["#####", ".###.", "..#..", ".#.#.", "#####"],
}
ICONS = {k: Sprite.parse(v, {"#": WHITE}) for k, v in ICON_ROWS.items()}
SOURCE_COLORS: dict[str, RGB] = {
    "quote": PALETTE["amber"],
    "qotd": PALETTE["gold"],
    "dad": PALETTE["lime"],
    "fact": PALETTE["cyan"],
    "fact_today": PALETTE["sky"],
    "advice": PALETTE["mint"],
    "cat": PALETTE["rose"],
    "joke": PALETTE["violet"],
    "chuck": PALETTE["red"],
    "kanye": PALETTE["magenta"],
    "history": PALETTE["ember"],
}


def draw_icon(f: Frame, name: str, x: int, y: int, color: RGB) -> None:
    sp = ICONS.get(name)
    if sp is None:
        return
    for yy in range(sp.h):
        for xx in range(sp.w):
            if sp.mask[yy, xx]:
                f.set(x + xx, y + yy, color)


# ============================================================================ settings
def _src(default: bool, title: str) -> Any:
    return Field(default, title=title, json_schema_extra={"group": "Sources"})


class DailySettings(AppSettings):
    quote: bool = _src(True, "Random quote")
    qotd: bool = _src(False, "Quote of the day")
    dad: bool = _src(True, "Dad joke")
    fact: bool = _src(True, "Useless fact")
    fact_today: bool = _src(False, "Useless fact of the day")
    advice: bool = _src(True, "Advice")
    cat: bool = _src(False, "Cat fact")
    joke: bool = _src(True, "Programming & pun jokes")
    chuck: bool = _src(False, "Chuck Norris")
    kanye: bool = _src(False, "Kanye")
    history: bool = _src(True, "On this day")
    order: str = Choice("cycle", {"cycle": "In turn", "shuffle": "Shuffle"}, title="Order", group="Sources")
    style: str = Choice(
        "pages",
        {"pages": "Pages", "lyrics": "Spotify Lyrics", "marquee": "Marquee"},
        title="Style",
        group="Layout",
    )
    font: str = Choice(
        "auto", {"auto": "Auto fit", "small": "Small", "tiny": "Tiny"}, title="Font", group="Layout"
    )
    rotate: int = Field(
        14,
        ge=5,
        le=180,
        title="Seconds per item",
        description="Minimum; long items stay until they have been read",
        json_schema_extra={"group": "Layout"},
    )
    pace: str = Choice(
        "normal", {"slow": "Slow", "normal": "Normal", "fast": "Fast"}, title="Reading pace", group="Layout"
    )
    speed: int = Field(12, ge=6, le=24, title="Marquee speed (px/s)", json_schema_extra={"group": "Layout"})
    show_icon: bool = Field(True, title="Source icon", json_schema_extra={"group": "Layout"})
    show_author: bool = Field(True, title="Author line", json_schema_extra={"group": "Layout"})
    colors: str = Choice(
        "source", {"source": "Per source", "custom": "Custom accent"}, title="Tag colours", group="Colours"
    )
    accent: Color = Field("#ffaa00", title="Custom accent", json_schema_extra={"group": "Colours"})
    text_color: Color = Field("#ffffff", title="Text", json_schema_extra={"group": "Colours"})
    punch_color: Color = Field("#ffd600", title="Punchline", json_schema_extra={"group": "Colours"})


PACE = {"slow": 1.4, "normal": 1.0, "fast": 0.72}
PAUSE_SECONDS = 1.4
MQ_FPS = 10


# ============================================================================ the app
@register
class Daily(App):
    id = "daily"
    name = "Daily Dose"
    description = (
        "Quotes, dad jokes, useless facts, advice, cat facts, pun jokes and on-this-day, in rotation."
    )
    icon = "quote"
    category = "productivity"
    Settings = DailySettings
    fps = 4.0
    uses = ("daily",)
    clip_colors = 32
    actions = (Action("next", "Next", "skip-forward"),)

    MAX_CLIP_FRAMES: ClassVar[int] = 360  # ~100 B per text frame: 360 frames fit the 40 KB GIF budget
    _clock: ClassVar[Any] = staticmethod(time.monotonic)  # scheduling clock (tests and sheets override it)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._rng = random.Random()
        self.on_settings()

    # ------------------------------------------------------------ lifecycle
    @property
    def sources(self) -> list[str]:
        return [s for s in SOURCES if getattr(self.settings, s, False)]

    def _provider(self) -> Any:
        try:
            return self.ctx.provider("daily")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(self.sources)

    def on_settings(self) -> None:
        self._item: dict[str, Any] | None = None
        self._pages: list[Page] = []
        self._t0 = 0.0
        self._dur = 0.0
        self._turn = -1
        self._skip = False
        self._layout_key = ""
        self.on_start()

    # ------------------------------------------------------------ colours
    def accent(self, source: str) -> RGB:
        if self.settings.colors == "custom":
            return to_rgb(self.settings.accent)
        return SOURCE_COLORS.get(source, PALETTE["amber"])

    # ------------------------------------------------------------ scheduling
    def _next_item(self) -> dict[str, Any] | None:
        p = self._provider()
        if p is None:
            return None
        ready = [s for s in self.sources if p.has(s)]
        if not ready:
            return None
        if self.settings.order == "shuffle":
            last = self._item["source"] if self._item else None
            pool = [s for s in ready if s != last] or ready
            src = self._rng.choice(pool)
        else:
            order = self.sources
            src = ready[0]
            for k in range(1, len(order) + 1):
                cand = order[(self._turn + k) % len(order)]
                if cand in ready:
                    src = cand
                    self._turn = (self._turn + k) % len(order)
                    break
        return p.take(src)

    def _advance(self) -> None:
        now = self._clock()
        force, self._skip = self._skip, False
        stale = self._item is None or now < self._t0 or now - self._t0 >= self._dur
        if not (stale or force):
            return
        it = self._next_item()
        if it is None and self._item is not None and not force:
            self._t0 = now  # nothing new yet: keep showing the current item
            return
        self._item = it
        self._t0 = now
        self._pages = self.pages_for(it) if it else []
        self._dur = self.item_duration(it) if it else 1.0

    # ------------------------------------------------------------ layout
    def _pace(self) -> float:
        return PACE.get(self.settings.pace, 1.0)

    def _fonts(self, text: str) -> list[str]:
        f = self.settings.font
        if f == "tiny" or not font_can_draw(text, "small"):
            return ["tiny"]
        if any(measure(w, "small") > 30 for w in text.split()):
            return ["tiny"]
        return ["small"] if f == "small" else ["small", "tiny"]

    def _author(self, it: dict[str, Any]) -> str:
        a = it.get("author") if self.settings.show_author else None
        return f"- {a}" if a else ""

    def _block(self, text: str, role: str, author: str = "") -> list[Page]:
        """Pages for one block of text (setup or punchline), auto-fitted."""
        pace = self._pace()
        for font in self._fonts(text):
            if font == "small":
                if any(measure(w, "small") > 30 for w in text.split()):
                    continue
                lines = wrap_text(text, 30, "small")
                auth = wrap_text(author, 30, "tiny") if author else []
                if len(lines) <= 2 and len(auth) <= 1:
                    page = Page([(ln, role) for ln in lines] + [(a, "author") for a in auth], "small")
                    page.dur = reading_time(page.lines, pace)
                    return [page]
                if self.settings.font != "small":
                    continue
                pages = flow_pages([(text, role)], 30, 2, "small", pace)
                if auth:
                    last = pages[-1]
                    if len(last.lines) <= 2 and len(auth) == 1:
                        last.lines.append((auth[0], "author"))
                    else:
                        pages += flow_pages([(author, "author")], 30, 4, "tiny", pace)
                return pages
        parts = [(text, role)] + ([(author, "author")] if author else [])
        return flow_pages(parts, 30, 4, "tiny", pace)

    def pages_for(self, it: dict[str, Any]) -> list[Page]:
        key = json.dumps([it.get("id"), self.settings.model_dump(mode="json")], sort_keys=True)
        if key == self._layout_key and self._pages:
            return self._pages
        punch = it.get("punchline")
        pages = self._block(it["text"], "text", "" if punch else self._author(it))
        if punch:
            pages.append(Page([], "tiny", PAUSE_SECONDS * self._pace(), "pause"))
            pages += self._block(punch, "punch")
        # the last page holds until the item's minimum time is reached
        total = sum(p.dur for p in pages)
        if total < self.settings.rotate:
            pages[-1].dur += self.settings.rotate - total
        self._layout_key = key
        return pages

    def item_duration(self, it: dict[str, Any]) -> float:
        if self.settings.style == "marquee":
            return max(float(self.settings.rotate), self.marquee_seconds(it))
        if self.settings.style == "lyrics":
            return max(float(self.settings.rotate), self.lyrics_seconds(it))
        return sum(p.dur for p in self.pages_for(it))

    # ------------------------------------------------------------ marquee timeline
    def _mq_font(self, text: str) -> str:
        return "small" if self.settings.font != "tiny" and font_can_draw(text, "small") else "tiny"

    def mq_speed(self) -> float:
        """Marquee px/s as baked: 1 px per clip frame, at most MQ_FPS frames/s (the panel's verified clip
        rate). A faster setting is capped rather than stepping 2 px, which judders on the LEDs."""
        return float(min(self.settings.speed, MQ_FPS))

    def _pass_seconds(self, text: str, font: str) -> float:
        w = measure(text, font)
        if w <= 30:
            return 3.5 * self._pace()
        return 1.2 + (w + 12) / self.mq_speed()

    def _segments(self, it: dict[str, Any]) -> list[tuple[str, str, str, float]]:
        """[(text, role, font, seconds)] played back to back: setup/punchline or just the text."""
        segs = []
        for text, role in ((it["text"], "text"), (it.get("punchline"), "punch")):
            if text:
                font = self._mq_font(text)
                segs.append((text, role, font, self._pass_seconds(text, font)))
        return segs

    def marquee_seconds(self, it: dict[str, Any]) -> float:
        return sum(s[3] for s in self._segments(it)) + (0.8 if it.get("punchline") else 0.0)

    # ------------------------------------------------------------ drawing
    def draw_header(self, f: Frame, it: dict[str, Any], page: int = 0, pages: int = 1) -> None:
        src = it["source"]
        c = self.accent(src)
        x = 1
        if self.settings.show_icon:
            draw_icon(f, src, 1, 1, c)
            x = 8
        tag = it.get("tag") or SOURCES[src].tag
        while tag and measure(tag) > 31 - x:
            tag = tag[:-1]
        f.text(x, 1, tag, c)
        if pages > 1:  # page ticks on the bottom edge
            n = min(pages, 8)
            seg = max(1, min(4, (32 - (n - 1)) // n))
            x0 = (32 - (n * seg + n - 1)) // 2
            cur = min(page, n - 1)
            for k in range(n):
                f.hline(x0 + k * (seg + 1), 31, seg, scale(c, 0.9) if k == cur else scale(c, 0.18))

    def role_color(self, role: str, src: str) -> RGB:
        if role == "author":
            return scale(self.accent(src), 0.85)
        if role == "punch":
            return to_rgb(self.settings.punch_color)
        return to_rgb(self.settings.text_color)

    def draw_page(self, f: Frame, it: dict[str, Any], page: Page, t_in: float) -> None:
        src = it["source"]
        if page.kind == "pause":
            c = to_rgb(self.settings.punch_color)
            for i in range(3):
                k = 0.5 + 0.5 * math.sin(t_in * 7 - i * 1.1)
                f.rect(10 + i * 5, 17, 2, 2, scale(c, 0.2 + 0.8 * k))
            return
        body = [ln for ln in page.lines if ln[1] != "author" or page.font == "tiny"]
        tail = [ln for ln in page.lines if ln[1] == "author" and page.font != "tiny"]
        pitch = LINE_PITCH[page.font]
        fh = FONTS[page.font].height
        top, bottom = 7, 29  # body box (row 31 carries the page ticks)
        if tail:
            bottom = 23
        total = len(body) * pitch - (pitch - fh)
        y = top + max(0, (bottom - top + 1 - total) // 2)
        for text, role in body:
            c = self.role_color(role, src)
            w = measure(text, page.font)
            sp = 1
            if w > 30 and page.font == "tiny" and measure(text, "tiny", spacing=0) <= 32:
                w = measure(text, "tiny", spacing=0)
                sp = 0
            if role == "author":
                f.text_right(30, y, text, c, font=page.font, spacing=sp)
            else:
                f.text((32 - w) // 2, y, text, c, font=page.font, spacing=sp)
            y += pitch
        for text, role in tail:
            f.text_right(30, 25, text, self.role_color(role, src))

    def draw_marquee(self, f: Frame, it: dict[str, Any], t_in: float) -> None:
        src = it["source"]
        segs = self._segments(it)
        tt = t_in
        for i, (text, role, font, secs) in enumerate(segs):
            gap = 0.8 if i == 0 and len(segs) > 1 else 0.0
            if tt < secs + gap or i == len(segs) - 1:
                if tt >= secs:  # the beat between setup and punchline
                    tt = secs - 0.01 if i == len(segs) - 1 else None  # type: ignore[assignment]
                if tt is None:
                    self.draw_page(f, it, Page([], "tiny", 1.0, "pause"), t_in)
                    return
                y = 13 if font == "small" else 14
                c = self.role_color(role, src)
                w = measure(text, font)
                if w <= 30:
                    f.text((32 - w) // 2, y, text, c, font=font)
                else:
                    x = marquee_x(text, tt + 1e-6, 1, 30, font, self.mq_speed(), 12, 1.2)
                    f.text(x, y, text, c, font=font, clip=(1, y, 30, y + FONTS[font].height - 1))
                if role == "punch":
                    f.hline(12, y + FONTS[font].height + 2, 8, scale(c, 0.35))
                break
            tt -= secs + gap
        author = self._author(it) if not it.get("punchline") else ""
        if author:
            draw_marquee(
                f, author, t_in + 1e-6, 1, 25, 30, scale(self.accent(src), 0.85), speed=self.mq_speed()
            )

    # ------------------------------------------------------------ lyrics timeline
    def _lyric_lines(self, it: dict[str, Any]) -> list[tuple[str, str, str]]:
        """Return list of (text_line, role, font) for item `it`."""
        font = self._fonts(it["text"])[-1]
        lines: list[tuple[str, str, str]] = []
        for ln in wrap_text(it["text"], 30, font):
            lines.append((ln, "text", font))
        punch = it.get("punchline")
        if punch:
            pfont = self._fonts(punch)[-1]
            for ln in wrap_text(punch, 30, pfont):
                lines.append((ln, "punch", pfont))
        auth = self._author(it)
        if auth and not punch:
            for ln in wrap_text(auth, 30, "tiny"):
                lines.append((ln, "author", "tiny"))
        return lines

    def lyrics_seconds(self, it: dict[str, Any]) -> float:
        lines = self._lyric_lines(it)
        dwell = max(1.4, 2.0 * self._pace())
        return max(float(self.settings.rotate), len(lines) * dwell + (1.2 if it.get("punchline") else 0.6))

    def draw_lyrics(self, f: Frame, it: dict[str, Any], t_in: float) -> None:
        src = it["source"]
        lines = self._lyric_lines(it)
        if not lines:
            return
        N = len(lines)
        dwell = max(1.4, 2.0 * self._pace())
        total = self.lyrics_seconds(it)
        tt = t_in % total
        k = min(N - 1, int(tt / dwell))
        since = tt - k * dwell

        # Eased transition between lines
        p_ease = min(1.0, since / 0.35)
        ease = 1.0 - (1.0 - p_ease) ** 3

        P = 6
        fh = 5
        top = 8

        if N <= 4:
            scroll = 0.0
        else:
            scroll_target = float(max(0, min(N - 4, k - 1)))
            scroll_prev = float(max(0, min(N - 4, (k - 1) - 1)))
            scroll = scroll_target if k <= 1 else scroll_prev + (scroll_target - scroll_prev) * ease

        f.hline(0, 7, 32, scale(self.accent(src), 0.15))

        for j, (text, role, font) in enumerate(lines):
            yj = round(top + (j - scroll) * P)
            if yj > 31 or yj + fh < 8:
                continue
            is_active = j == k
            if is_active:
                col = self.role_color(role, src)
            else:
                dist = abs(j - k)
                factor = 0.38 if dist == 1 else 0.22
                col = scale(self.role_color(role, src), factor)
            w = measure(text, font)
            sp = 1
            if w > 30 and font == "tiny" and measure(text, "tiny", spacing=0) <= 32:
                w = measure(text, "tiny", spacing=0)
                sp = 0
            if role == "author":
                f.text_right(30, yj, text, col, font=font, spacing=sp)
            else:
                f.text((32 - w) // 2, yj, text, col, font=font, spacing=sp)

    # ------------------------------------------------------------ render
    def _placeholder(self, f: Frame, t: float) -> None:
        if not self.sources:
            f.text_center(10, "NO", PALETTE["mute"])
            f.text_center(17, "SOURCES", PALETTE["dim"])
            return
        p = self._provider()
        if p is not None and p.error and not (p.value and any(p.value.values())):
            offline(f, "DAILY", "OFFLINE")
        else:
            loading(f, t, "DAILY", self.accent(self.sources[0]))

    def paint(self, f: Frame, it: dict[str, Any], pages: list[Page], t_in: float) -> None:
        """Draw item `it` at `t_in` seconds after it appeared."""
        if self.settings.style == "marquee":
            self.draw_header(f, it)
            self.draw_marquee(f, it, t_in)
            return
        if self.settings.style == "lyrics":
            self.draw_header(f, it)
            self.draw_lyrics(f, it, t_in)
            return
        acc = 0.0
        idx = len(pages) - 1
        for i, pg in enumerate(pages):
            if t_in < acc + pg.dur:
                idx = i
                break
            acc += pg.dur
        text_pages = [p for p in pages if p.kind == "text"]
        shown = sum(1 for p in pages[: idx + 1] if p.kind == "text") - 1
        self.draw_header(f, it, max(0, shown), len(text_pages))
        self.draw_page(f, it, pages[idx], t_in - acc)

    def render(self, f: Frame, t: float) -> None:
        if not self.sources:
            self._placeholder(f, t)
            return
        self._advance()
        it = self._item
        if it is None:
            self._placeholder(f, t)
            return
        self.paint(f, it, self._pages, self._clock() - self._t0)

    # ------------------------------------------------------------ clip (marquee/lyrics style)
    def kind(self) -> Kind:
        if self.settings.style in ("lyrics", "marquee") and self._item is not None:
            return "clip"
        return "stream"

    def clip_key(self) -> str:
        self._advance()
        it = self._item
        return super().clip_key() + json.dumps(it.get("id") if it else None)

    def clip_frames(self) -> Clip:
        it = self._item
        if it is None:
            f = Frame()
            self._placeholder(f, 0.0)
            return Clip([f], [1000])
        if self.settings.style == "lyrics":
            total = self.lyrics_seconds(it)
            fps = 8.0
            n = min(self.MAX_CLIP_FRAMES, max(1, math.ceil(total * fps)))
            dt = total / n
        else:
            total = self.marquee_seconds(it)
            # one frame per pixel of travel; the holds (identical frames) are merged below, so long items
            # stay under the frame cap without stretching the step to 2 px
            fps = self.mq_speed()
            n = max(1, round(total * fps))
            dt = 1.0 / fps
        frames: list[Frame] = []
        durs: list[float] = []
        for i in range(n):
            f = Frame()
            self.paint(f, it, [], i * dt)
            if frames and f == frames[-1] and self.settings.style == "marquee":
                durs[-1] += dt
                continue
            frames.append(f)
            durs.append(dt)
        if len(frames) > self.MAX_CLIP_FRAMES:  # very long items: fall back to fewer, larger steps
            n = self.MAX_CLIP_FRAMES
            dt = total / n
            frames = []
            for i in range(n):
                f = Frame()
                self.paint(f, it, [], i * dt)
                frames.append(f)
            durs = [dt] * n
        return Clip(frames, [max(20, round(d * 1000)) for d in durs])

    # ------------------------------------------------------------ actions / status
    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "input":
            key = str(payload.get("key", "")).lower()
            if key not in ("right", "arrowright", "a", " ", "space", "enter"):
                return self.status()
        elif name != "next":
            raise KeyError(name)
        self._skip = True
        self._advance()
        try:
            self.ctx.invalidate()
        except Exception:
            pass
        return self.status()

    def status(self) -> dict[str, Any]:
        it = self._item or {}
        return {
            "sources": len(self.sources),
            "source": it.get("source"),
            "text": it.get("text"),
            "author": it.get("author"),
            "punchline": it.get("punchline"),
        }
