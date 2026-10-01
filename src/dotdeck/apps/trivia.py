"""Trivia — Open Trivia DB questions you can play from the studio keyboard (or watch it play itself).

Flow per question: **intro** (category + difficulty) → **question** (auto-fitted pages) → **options** (each
answer on its own card, A–D) → **board** (all options as rows, countdown on the edge ring; arrows pick, `a`
confirms) → **reveal** (correct row green, a wrong pick red, the ring turns the result colour) → **score**
(only after a human answer) → next. Without input the board times out and reveals by itself.

Score, streak and best streak persist in ``ctx.data``.
"""

from __future__ import annotations

import math
import time
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Color, register
from ..gfx import PALETTE, Frame, measure, mix, scale, to_rgb
from ..gfx.color import RGB
from ..gfx.font import FONTS, marquee_x
from ..providers.trivia import CATEGORIES
from ._kit import PERIMETER, loading, offline, ring
from .daily import LINE_PITCH, Page, flow_pages, font_can_draw, reading_time, wrap_text

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)
LETTERS = "ABCD"
DIFF_COLORS: dict[str, RGB] = {"easy": PALETTE["lime"], "medium": PALETTE["amber"], "hard": PALETTE["red"]}
DIFF_PIPS = {"easy": 1, "medium": 2, "hard": 3}
KEYS = {
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "w": "up",
    "s": "down",
    " ": "a",
    "space": "a",
    "enter": "a",
    "escape": "b",
    "backspace": "b",
}
# one hue per category family so the tag colour hints at the topic
CAT_COLORS: dict[int, RGB] = {
    **dict.fromkeys((10, 11, 12, 13, 14, 15, 16, 26, 29, 31, 32), PALETTE["magenta"]),
    **dict.fromkeys((17, 18, 19, 30), PALETTE["cyan"]),
    **dict.fromkeys((20, 23, 24, 25), PALETTE["amber"]),
    **dict.fromkeys((21, 27, 28), PALETTE["lime"]),
    22: PALETTE["sky"],
    9: PALETTE["violet"],
}
PACE = {"slow": 1.4, "normal": 1.0, "fast": 0.72}
FPS = 10.0
MARQUEE = FPS  # px/s: exactly one pixel per frame (12 px/s at 8 fps stepped 1-2-1-2 and read as stutter)
TRACK: RGB = (46, 46, 64)  # unlit meter pips: still visible through the panel's gamma 1.5


class TriviaSettings(AppSettings):
    category: str = Choice(
        "any",
        {"any": "Any category", **{str(k): v[0] for k, v in CATEGORIES.items()}},
        title="Category",
        group="Questions",
    )
    difficulty: str = Choice(
        "any",
        {"any": "Any", "easy": "Easy", "medium": "Medium", "hard": "Hard"},
        title="Difficulty",
        group="Questions",
    )
    qtype: str = Choice(
        "multiple",
        {"multiple": "Multiple choice", "boolean": "True / false", "any": "Mixed"},
        title="Type",
        group="Questions",
    )
    seconds: int = Field(15, ge=5, le=60, title="Seconds to answer", json_schema_extra={"group": "Play"})
    reveal_seconds: int = Field(4, ge=2, le=15, title="Reveal seconds", json_schema_extra={"group": "Play"})
    preview: bool = Field(
        True,
        title="Read out options",
        description="Show each option on its own card before the answer board",
        json_schema_extra={"group": "Play"},
    )
    auto_play: bool = Field(
        True,
        title="Auto-play",
        description="Move on after the reveal by itself; off = wait for A / Next",
        json_schema_extra={"group": "Play"},
    )
    pace: str = Choice(
        "normal", {"slow": "Slow", "normal": "Normal", "fast": "Fast"}, title="Reading pace", group="Play"
    )
    show_score: bool = Field(True, title="Score card after answers", json_schema_extra={"group": "Play"})
    accent: Color = Field("#00dcff", title="Accent", json_schema_extra={"group": "Colours"})
    correct: Color = Field("#00ff78", title="Correct", json_schema_extra={"group": "Colours"})
    wrong: Color = Field("#ff143c", title="Wrong", json_schema_extra={"group": "Colours"})


def text_fit(f: Frame, y: int, text: str, color: RGB, font: str = "tiny") -> None:
    """Centre a line inside the 1 px margins. A word too long for the row (wrap_text allows one that fits
    with no letter spacing) loses only as many letter gaps as it must, spread evenly — fully condensed
    type turns into a blob on the LEDs."""
    w = measure(text, font)
    if w <= 30:
        f.text(1 + (30 - w) // 2, y, text, color, font)
        return
    gaps = len(text) - 1
    drop = min(gaps, w - 30)
    glyphs = [FONTS[font].glyph(ch) for ch in text]

    def contact(i: int) -> float:  # how much two neighbours would touch with no gap between them
        a, b = glyphs[i][:, -1], glyphs[i + 1][:, 0]
        return float((a & b).sum()) + 0.5 * float((a[1:] & b[:-1]).sum() + (a[:-1] & b[1:]).sum())

    # close the gaps where the letters touch least (an I or T next to anything), spread along the word
    order = sorted(range(gaps), key=lambda i: (contact(i), abs(i - gaps / 2)))
    closed = set(order[:drop])
    ww = w - drop
    x = 1 + (30 - ww) // 2 if ww <= 30 else (32 - ww) // 2
    for i, ch in enumerate(text):
        x = f.text(x, y, ch, color, font)
        if i < gaps and i not in closed:
            x += 1


@register
class Trivia(App):
    id = "trivia"
    name = "Trivia"
    description = (
        "Open Trivia DB quiz: question, options A–D, countdown ring, reveal. Play with the arrow keys."
    )
    icon = "circle-question-mark"
    category = "games"
    Settings = TriviaSettings
    fps = FPS
    uses = ("trivia",)
    actions = (
        Action("next", "Next question", "skip-forward"),
        Action("reveal", "Reveal", "eye"),
        Action("reset_score", "Reset score", "rotate-ccw"),
    )
    _clock: ClassVar[Any] = staticmethod(time.monotonic)
    INTRO: ClassVar[float] = 1.8
    SCORE: ClassVar[float] = 2.6
    HUMAN_IDLE: ClassVar[float] = 90.0

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.human_at = -1e9
        self.on_settings()

    # ------------------------------------------------------------ lifecycle
    def _provider(self) -> Any:
        try:
            return self.ctx.provider("trivia")
        except KeyError:
            return None

    def _query(self) -> tuple[int, str, str]:
        s = self.settings
        return (0 if s.category == "any" else int(s.category), s.difficulty, s.qtype)

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(*self._query())

    def on_settings(self) -> None:
        self.q: dict[str, Any] | None = None
        self.phase = "idle"
        self.t0 = 0.0
        self.sel = 0
        self.picked: int | None = None
        self.qpages: list[Page] = []
        self.opages: list[tuple[int, Page]] = []
        self.on_start()

    # ------------------------------------------------------------ score
    @property
    def stats(self) -> dict[str, int]:
        try:
            d = self.ctx.data
        except Exception:
            return {"score": 0, "answered": 0, "streak": 0, "best": 0}
        for k in ("score", "answered", "streak", "best"):
            d.setdefault(k, 0)
        return d  # type: ignore[no-any-return]

    def _record(self, right: bool) -> None:
        st = self.stats
        st["answered"] += 1
        if right:
            st["score"] += 1
            st["streak"] += 1
            st["best"] = max(st["best"], st["streak"])
        else:
            st["streak"] = 0
        try:
            self.ctx.save()
        except Exception:
            pass

    @property
    def human(self) -> bool:
        return self._clock() - self.human_at < self.HUMAN_IDLE

    # ------------------------------------------------------------ timeline
    def _pace(self) -> float:
        return PACE.get(self.settings.pace, 1.0)

    def _text_pages(self, text: str, role: str, top_rows: int = 4) -> list[Page]:
        pace = self._pace()
        if font_can_draw(text, "small"):
            lines = wrap_text(text, 30, "small")
            if len(lines) <= 2:
                pg = Page([(ln, role) for ln in lines], "small")
                pg.dur = reading_time(pg.lines, pace)
                return [pg]
        return flow_pages([(text, role)], 30, top_rows, "tiny", pace)

    def _load(self, q: dict[str, Any]) -> None:
        self.q = q
        self.sel = 0
        self.picked = None
        self.qpages = self._text_pages(q["question"], "text")
        self.opages = []
        if self.settings.preview and q["type"] == "multiple":
            for i, opt in enumerate(q["options"]):
                for pg in self._text_pages(opt, "option", 3):
                    pg.dur = max(1.6, pg.dur * 0.8)
                    self.opages.append((i, pg))

    def _dur(self, phase: str) -> float:
        if phase == "intro":
            return self.INTRO * self._pace()
        if phase == "question":
            return sum(p.dur for p in self.qpages)
        if phase == "options":
            return sum(p.dur for _i, p in self.opages)
        if phase == "board":
            return float(self.settings.seconds)
        if phase == "reveal":
            return float(self.settings.reveal_seconds)
        if phase == "score":
            return self.SCORE
        return math.inf  # idle / wait

    def _go(self, phase: str, now: float) -> None:
        if phase == "reveal" and self.phase != "reveal" and self.q is not None and self.picked is not None:
            self._record(self.picked == self.q["answer"])
        self.phase, self.t0 = phase, now

    def _after(self, phase: str) -> str:
        order = ["intro", "question", "options", "board", "reveal", "score"]
        nxt = order[order.index(phase) + 1] if phase in order[:-1] else "next"
        if nxt == "options" and not self.opages:
            nxt = "board"
        if nxt == "score" and not (self.picked is not None and self.settings.show_score):
            nxt = "next"
        if nxt == "next" and not self.settings.auto_play:
            nxt = "wait"
        return nxt

    def _next_question(self, now: float) -> None:
        p = self._provider()
        q = p.take() if p is not None else None
        if q is None:
            self.q, self.phase = None, "idle"
            return
        self._load(q)
        self._go("intro", now)

    def _step(self) -> float:
        now = self._clock()
        if self.phase == "idle":
            self._next_question(now)
        for _ in range(8):
            if self.phase in ("idle", "wait") or now - self.t0 < self._dur(self.phase):
                break
            nxt = self._after(self.phase)
            if nxt == "next":
                self._next_question(self.t0 + self._dur(self.phase))
            else:
                self._go(nxt, self.t0 + self._dur(self.phase))
        if now - self.t0 > 600:  # catch up after a long pause (app was hidden)
            self.t0 = now
        return now - self.t0

    # ------------------------------------------------------------ colours
    def cat_color(self) -> RGB:
        return CAT_COLORS.get(int(self.q["category"]) if self.q else 0, to_rgb(self.settings.accent))

    # ------------------------------------------------------------ drawing
    def header(self, f: Frame, label: str | None = None, color: RGB | None = None) -> None:
        q = self.q
        assert q is not None
        c = color or self.cat_color()
        tag = label or q["tag"]
        while tag and measure(tag) > 28:
            tag = tag[:-1]
        f.text(1, 1, tag, c)
        diff = q["difficulty"]
        dc = DIFF_COLORS.get(diff, PALETTE["amber"])
        for k in range(3):  # a 1 px difficulty meter, filled bottom-up
            f.set(30, 5 - 2 * k, dc if k < DIFF_PIPS.get(diff, 2) else TRACK)

    def ticks(self, f: Frame, n: int, i: int, c: RGB) -> None:
        if n < 2:
            return
        n = min(n, 8)
        seg = max(1, min(4, (32 - (n - 1)) // n))
        x0 = (32 - (n * seg + n - 1)) // 2
        for k in range(n):
            f.hline(x0 + k * (seg + 1), 31, seg, scale(c, 0.9) if k == min(i, n - 1) else scale(c, 0.35))

    def body(self, f: Frame, page: Page, color: RGB, top: int = 7, bottom: int = 29) -> None:
        pitch = LINE_PITCH[page.font]
        fh = FONTS[page.font].height
        total = len(page.lines) * pitch - (pitch - fh)
        y = top + max(0, (bottom - top + 1 - total) // 2)
        for text, _role in page.lines:
            text_fit(f, y, text, color, page.font)
            y += pitch

    @staticmethod
    def _page_at(pages: list[Any], el: float, dur: Any = lambda p: p.dur) -> int:
        acc = 0.0
        for i, p in enumerate(pages):
            acc += dur(p)
            if el < acc:
                return i
        return len(pages) - 1

    def draw_intro(self, f: Frame, el: float) -> None:
        q = self.q
        assert q is not None
        c = self.cat_color()
        f.text_center(3, q["tag"], c)
        n = self.stats["answered"] + 1 if self.human else (self._provider().served if self._provider() else 1)
        label = f"Q{n}"
        f.text_center(11, label if measure(label, "small") <= 30 else "Q", WHITE, font="small")
        diff = q["difficulty"]
        dc = DIFF_COLORS.get(diff, PALETTE["amber"])
        f.text_center(22, diff.upper(), scale(dc, 0.9))
        # a sweep under the tag draws the eye in
        w = min(24, int(24 * min(1.0, el / 0.6)))
        f.hline(16 - w // 2, 9, w, scale(c, 0.5))

    def draw_question(self, f: Frame, el: float) -> None:
        i = self._page_at(self.qpages, el)
        self.header(f)
        self.body(f, self.qpages[i], WHITE)
        self.ticks(f, len(self.qpages), i, self.cat_color())

    def draw_option_card(self, f: Frame, el: float) -> None:
        i = self._page_at(self.opages, el, lambda ip: ip[1].dur)
        idx, page = self.opages[i]
        acc = to_rgb(self.settings.accent)
        f.rect(1, 1, 7, 7, scale(acc, 0.85))
        f.text(3, 2, LETTERS[idx], BLACK)
        n = len(self.q["options"]) if self.q else 4
        f.text_right(30, 2, f"{idx + 1}/{n}", scale(acc, 0.6))
        self.body(f, page, WHITE, top=10, bottom=29)
        for k in range(n):  # which of the four we're on
            f.hline(8 + k * 4, 31, 3, acc if k == idx else scale(acc, 0.35))

    def _rows(self) -> list[tuple[int, int]]:
        """(y of text, band height) per option."""
        assert self.q is not None
        if self.q["type"] == "boolean":
            return [(8, 9), (19, 9)]
        return [(3, 7), (10, 7), (17, 7), (24, 7)]

    def draw_board(self, f: Frame, el: float, reveal: bool) -> None:
        q = self.q
        assert q is not None
        s = self.settings
        acc, ok, bad = to_rgb(s.accent), to_rgb(s.correct), to_rgb(s.wrong)
        boolean = q["type"] == "boolean"
        focus = self.sel
        if not self.human and not reveal:  # nobody playing: walk the focus so every option gets read
            focus = int(el / max(1.5, s.seconds / len(q["options"]))) % len(q["options"])
        for i, (opt, (y, h)) in enumerate(zip(q["options"], self._rows(), strict=True)):
            font = "small" if boolean else "tiny"
            fh = FONTS[font].height
            band_y = y - (h - fh) // 2
            text_c, letter_c = mix(WHITE, BLACK, 0.12), acc
            if reveal:
                if i == q["answer"]:
                    f.rect(1, band_y, 30, h, scale(ok, 0.32))
                    text_c, letter_c = WHITE, ok
                elif i == self.picked:
                    f.rect(1, band_y, 30, h, scale(bad, 0.3))
                    text_c, letter_c = mix(WHITE, bad, 0.3), bad
                else:
                    text_c, letter_c = PALETTE["dim"], scale(PALETTE["dim"], 0.7)
            elif i == focus:
                f.rect(1, band_y, 30, h, scale(acc, 0.4 if self.human else 0.3))
                text_c = WHITE
            else:
                text_c = PALETTE["mute"]
            if boolean:
                f.text_center(y, opt, text_c, font="small")
                continue
            f.text(2, y, LETTERS[i], letter_c)
            x0, w = 7, 23  # a 2 px gutter after the letter, so scrolling text never reads as part of it
            active = (reveal and i == q["answer"]) or (not reveal and i == focus)
            tw = measure(opt)
            if tw <= w:
                f.text(x0, y, opt, text_c)
            elif active:
                tq = (int(el * FPS + 1e-6) + 0.01) / FPS  # whole frames: one pixel per frame
                x = marquee_x(opt, tq, x0, w, "tiny", MARQUEE, 12, 0.8)
                clip = (x0, y, x0 + w - 1, y + 4)
                f.text(x, y, opt, text_c, clip=clip)
                f.text(x + tw + 12, y, opt, text_c, clip=clip)
            else:
                f.text(x0, y, opt, text_c, clip=(x0, y, x0 + w - 1, y + 4))
        if reveal:
            c = PALETTE["dim"] if self.picked is None else (ok if self.picked == q["answer"] else bad)
            k = 0.55 + 0.45 * math.sin(el * 5) if self.picked is not None else 0.6
            for x, yy in PERIMETER:
                f.set(x, yy, scale(c, k))
        else:
            left = max(0.0, 1.0 - el / max(1.0, float(s.seconds)))
            rc = mix(bad, ok, min(1.0, left * 1.6)) if left < 0.6 else ok
            ring(f, left, scale(rc, 0.9), track=(14, 14, 20), head=True)

    def draw_score(self, f: Frame, el: float) -> None:
        q = self.q
        assert q is not None
        st = self.stats
        right = self.picked == q["answer"]
        c = to_rgb(self.settings.correct if right else self.settings.wrong)
        f.text_center(3, "RIGHT!" if right else "WRONG", c, font="small")
        score = f"{st['score']}/{st['answered']}"
        f.text_center(13, score if measure(score, "small") <= 30 else str(st["score"]), WHITE, font="small")
        line = f"STREAK {st['streak']}" if st["streak"] else f"BEST {st['best']}"
        f.text_center(24, line if measure(line) <= 30 else str(st["streak"]), scale(c, 0.8))
        if right and st["streak"] >= 3:  # sparkle round the edge for a hot streak
            for j in range(0, len(PERIMETER), 8):
                x, y = PERIMETER[(j + int(el * 20)) % len(PERIMETER)]
                f.set(x, y, scale(to_rgb(self.settings.accent), 0.8))

    def render(self, f: Frame, t: float) -> None:
        el = self._step()
        q = self.q
        if q is None:
            p = self._provider()
            if p is not None and p.error:
                offline(f, "TRIVIA", "OFFLINE")
            else:
                loading(f, t, "TRIVIA", to_rgb(self.settings.accent))
            return
        ph = self.phase
        if ph == "intro":
            self.draw_intro(f, el)
        elif ph == "question":
            self.draw_question(f, el)
        elif ph == "options":
            self.draw_option_card(f, el)
        elif ph == "board":
            self.draw_board(f, el, reveal=False)
        elif ph in ("reveal", "wait"):
            self.draw_board(f, el, reveal=True)
            if ph == "wait" and int(el * 2) % 2 == 0:  # "press A" hint
                f.set(31, 31, WHITE)
        elif ph == "score":
            self.draw_score(f, el)

    # ------------------------------------------------------------ input / actions
    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        now = self._clock()
        if name == "next":
            self._next_question(now)
        elif name == "reveal":
            if self.q is not None and self.phase not in ("reveal", "score", "wait"):
                self._go("reveal", now)
        elif name == "reset_score":
            st = self.stats
            for k in ("score", "answered", "streak", "best"):
                st[k] = 0
            try:
                self.ctx.save()
            except Exception:
                pass
        elif name == "input":
            k = str(payload.get("key", "")).lower()
            self._key(KEYS.get(k, k), now)
        else:
            raise KeyError(name)
        return self.status()

    def _key(self, k: str, now: float) -> None:
        if k not in ("up", "down", "left", "right", "a", "b") or self.q is None:
            return
        self.human_at = now
        n = len(self.q["options"])
        ph = self.phase
        if ph in ("intro", "question", "options"):
            if k in ("a", "right", "down"):
                self._go("board", now)
        elif ph == "board":
            if k in ("up", "left"):
                self.sel = (self.sel - 1) % n
            elif k in ("down", "right"):
                self.sel = (self.sel + 1) % n
            elif k == "a":
                self.picked = self.sel
                self._go("reveal", now)
            elif k == "b":
                self._go("question", now)
        elif ph in ("reveal", "score", "wait") and k == "a":
            self._next_question(now)

    def status(self) -> dict[str, Any]:
        q = self.q or {}
        st = self.stats
        return {
            "phase": self.phase,
            "question": q.get("question"),
            "options": q.get("options"),
            "selected": self.sel,
            "category": q.get("tag"),
            "difficulty": q.get("difficulty"),
            "score": st["score"],
            "answered": st["answered"],
            "streak": st["streak"],
            "player": "you" if self.human else "auto",
        }
