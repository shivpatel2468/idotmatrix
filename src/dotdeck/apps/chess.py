"""Chess Puzzle — chess.com's daily (or a random) puzzle on an 8×8 board of 4×4 squares, then its solution.

Timeline of one loop: an intro card (title marquee, who is to move) → the position, with the side to move's
king pulsing while you think → every solution move slides into place with the last move highlighted → a hold
on the final position (a mated king flashes red). The loop is deterministic, so it is baked as a clip.

Input keys step through the solution by hand (left/right, a = restart); the app streams while you do and
returns to the baked loop after a few idle seconds.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Clip, Kind, register
from ..gfx import PALETTE, Frame, draw_marquee, ease_in_out, measure, mix, scale
from ..gfx.color import RGB
from ..providers.chess import Board, Move, Puzzle, king_sq
from ._kit import loading, offline
from .games_core import KEY_ALIASES
from .pokedex import bake

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)
SLIDE = 0.45  # shortest slide (s); longer moves take longer, so every piece glides at about the same speed
SLIDE_MAX = 1.2
SLIDE_SPEED = 16.0  # px/s: ~1.6 px per baked frame, small steps that read as motion
FPS = 10.0  # the fastest GIF rate verified on the panel; every blink below is a whole number of frames
MARQUEE = FPS  # px/s: exactly one pixel per frame, no uneven 1-2 px stepping
PULSE_STEP = 0.3  # the thinking king's glow changes every 3 frames
FLASH_STEP = 0.4  # the mated king blinks every 4 frames
FADE = 0.3  # intro card <-> board: a short fade instead of a pop
INTRO_DIM = 0.16
HUMAN_IDLE = 20.0

# 3×4 piece glyphs ('#' body, '+' accent); pawns are one row shorter so they read as the small piece
GLYPHS: dict[str, tuple[str, ...]] = {
    "K": (".+.", "###", ".#.", "###"),
    "Q": ("#+#", ".#.", "###", "###"),
    "R": ("#.#", "###", ".#.", "###"),
    "B": (".+.", "##.", ".#.", "###"),
    "N": ("##.", ".##", ".#.", "###"),
    "P": ("...", ".#.", ".#.", "###"),
}

# theme → (light square, dark square, white piece, black piece, white accent, black accent, highlight)
THEMES: dict[str, tuple[RGB, RGB, RGB, RGB, RGB, RGB, RGB]] = {
    # Night is the LED-native default: a quiet board with two bright armies. The classic boards keep the
    # dark squares mid-bright so black pieces (LEDs off) still read as silhouettes on every square.
    "night": (
        (64, 64, 92),  # light squares stay visible through the panel's gamma 1.5
        (18, 18, 30),
        (255, 240, 210),
        (255, 70, 30),
        (255, 190, 60),
        (255, 214, 0),
        (0, 160, 255),
    ),
    "wood": (
        (200, 146, 84),
        (128, 80, 36),
        (255, 248, 225),
        (0, 0, 0),
        (255, 190, 60),
        (150, 30, 0),
        (255, 214, 0),
    ),
    "green": (
        (170, 185, 120),
        (70, 120, 50),
        (255, 255, 240),
        (0, 0, 0),
        (255, 210, 60),
        (170, 20, 10),
        (255, 230, 60),
    ),
    "blue": (
        (120, 140, 185),
        (55, 75, 135),
        (255, 255, 255),
        (0, 0, 0),
        (255, 214, 0),
        (200, 30, 30),
        (255, 214, 0),
    ),
}


class ChessSettings(AppSettings):
    source: str = Choice("daily", {"daily": "Daily puzzle", "random": "Random puzzle"}, title="Puzzle")
    new_every: int = Field(
        0, ge=0, le=1440, title="New random puzzle every (min)", description="0 = only with the Next button"
    )
    think: int = Field(8, ge=1, le=120, title="Think time (s)", description="Before the solution plays")
    move_seconds: float = Field(1.5, ge=0.5, le=10, title="Seconds per move")
    theme: str = Choice(
        "night", {"night": "Night (LED)", "wood": "Wood", "green": "Green", "blue": "Blue"}, title="Board"
    )
    orientation: str = Choice(
        "auto", {"auto": "Side to move at the bottom", "white": "White at the bottom"}, title="Orientation"
    )
    intro: bool = Field(True, title="Intro card (title, side to move)")
    highlight: bool = Field(True, title="Highlight last move")


def piece_masks() -> dict[str, list[tuple[int, int, bool]]]:
    out: dict[str, list[tuple[int, int, bool]]] = {}
    for k, rows in GLYPHS.items():
        out[k] = [(x, y, ch == "+") for y, row in enumerate(rows) for x, ch in enumerate(row) if ch != "."]
    return out


PIECES = piece_masks()


@register
class ChessPuzzle(App):
    id = "chess"
    name = "Chess Puzzle"
    description = "Chess.com's daily puzzle on a 32×32 board, then the solution plays out move by move."
    icon = "crown"
    category = "games"
    Settings = ChessSettings
    uses = ("chess",)
    fps = 8.0
    clip_fps = FPS
    clip_colors = 48
    actions = (
        Action("next", "Next puzzle", "shuffle"),
        Action("solve", "Show solution", "eye"),
        Action("restart", "Restart", "rotate-ccw"),
        Action("input", "Step", "gamepad-2"),
    )

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._clock = time.monotonic
        self._manual: int | None = None  # ply shown by hand (0 = start position)
        self._manual_at = -1e9
        self._solved = False
        self._board_cache: tuple[str, np.ndarray] | None = None
        self._sprites: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}

    # ------------------------------------------------------------ data
    def _provider(self) -> Any:
        try:
            return self.ctx.provider("chess")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(self.settings.source, self.settings.new_every * 60.0)

    def on_settings(self) -> None:
        self._manual = None
        self._solved = False
        self.on_start()

    def puzzle(self) -> Puzzle | None:
        p = self._provider()
        v = (p.value if p is not None else None) or {}
        pz = v.get(self.settings.source)
        if pz is None and p is not None:
            self.on_start()
        return pz

    @property
    def manual(self) -> bool:
        return self._manual is not None and self._clock() - self._manual_at < HUMAN_IDLE

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        pz = self.puzzle()
        n = len(pz.moves) if pz else 0
        if name == "next":
            p = self._provider()
            if p is not None:
                if self.settings.source == "daily":
                    self.settings.source = "random"
                p.next_random()
            self._manual, self._solved = None, False
        elif name == "solve":
            self._solved = True
            self._manual = None
        elif name == "restart":
            self._manual, self._solved = None, False
        elif name == "input":
            k = str(payload.get("key", "")).lower()
            k = KEY_ALIASES.get(k, k)
            cur = self._manual if self.manual and self._manual is not None else 0
            if k in ("right", "down"):
                cur = min(n, cur + 1)
            elif k in ("left", "up"):
                cur = max(0, cur - 1)
            elif k == "a":
                cur = 0
            elif k == "b":
                cur = n
            else:
                return self.status()
            self._manual, self._manual_at = cur, self._clock()
        else:
            raise KeyError(name)
        self.ctx.invalidate()
        return self.status()

    # ------------------------------------------------------------ timeline
    def _intro_len(self, pz: Puzzle) -> float:
        if not self.settings.intro:
            return 0.0
        w = measure(pz.title.upper())
        return max(3.5, 1.2 + (w + 12) / MARQUEE + 0.8) if w > 30 else 3.5

    def _slide(self, pz: Puzzle, mv: Move) -> float:
        """Seconds this move slides for: proportional to the distance, so pieces glide at an even speed."""
        (x0, y0), (x1, y1) = self.xy(pz, *mv.frm), self.xy(pz, *mv.to)
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        return round(min(SLIDE_MAX, max(SLIDE, d / SLIDE_SPEED)) * FPS) / FPS  # whole frames

    def loop_seconds(self, pz: Puzzle) -> float:
        s = self.settings
        think = 0.0 if self._solved else float(s.think)
        moves = sum(self._slide(pz, m) + s.move_seconds for m in pz.moves)
        return self._intro_len(pz) + think + moves + 3.0

    def kind(self) -> Kind:
        return "clip" if self.puzzle() is not None and not self.manual else "stream"

    def clip_key(self) -> str:
        pz = self.puzzle()
        tag = f"{pz.kind}:{pz.fen}:{len(pz.moves)}" if pz else "none"
        return super().clip_key() + f"|{tag}|{self._solved}"

    def clip_frames(self) -> Clip:
        pz = self.puzzle()
        if pz is None:
            f = Frame()
            self.render(f, 0.0)
            return Clip([f], [1000])
        secs = self.loop_seconds(pz)
        clip = bake(self, secs, fps=self.clip_fps, limit=10_000)
        if len(clip.frames) > 180:  # too long for one GIF: half the rate keeps every step even
            clip = bake(self, secs, fps=self.clip_fps / 2, limit=180)
        return clip

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        pz = self.puzzle()
        if pz is None:
            p = self._provider()
            if p is not None and p.error:
                offline(f, "CHESS", "OFFLINE")
            else:
                loading(f, t, "CHESS", PALETTE["gold"])
            return
        if self.manual and self._manual is not None:
            ply = self._manual
            last = pz.moves[ply - 1] if ply else None
            self.board(f, pz, pz.boards[ply], last)
            if ply == 0:
                self._pulse_king(f, pz, pz.boards[0], t)
            return
        s = self.settings
        tt = t % self.loop_seconds(pz)
        intro = self._intro_len(pz)
        if tt < intro:
            self._intro(f, pz, tt)
            return
        tt -= intro
        think = 0.0 if self._solved else float(s.think)
        if tt < think:
            self.board(f, pz, pz.boards[0], None)
            self._pulse_king(f, pz, pz.boards[0], tt)
            if intro and tt < FADE:  # the intro card's dimmed board brightens into the puzzle
                f.dim(INTRO_DIM + (1 - INTRO_DIM) * round((tt + 0.1) / FADE * 3) / 3)
            return
        tt -= think
        for i, mv in enumerate(pz.moves):
            slide = self._slide(pz, mv)
            if tt < slide + s.move_seconds:
                if tt >= slide:
                    self.board(f, pz, pz.boards[i + 1], mv)
                else:
                    last = pz.moves[i - 1] if i else None
                    self.board(f, pz, pz.boards[i], last, sliding=(mv, ease_in_out(tt / slide)))
                break
            tt -= slide + s.move_seconds
        else:  # final hold
            mv = pz.moves[-1]
            self.board(f, pz, pz.boards[-1], mv)
            if mv.mate:
                self._flash_mated(f, pz, tt)
            if intro:  # dim down into the intro card, which starts the loop again
                left = 3.0 - tt
                if left < FADE:
                    k = left / FADE
                    f.dim(INTRO_DIM + (1 - INTRO_DIM) * round(k * 3) / 3)

    # ------------------------------------------------------------ drawing
    def flipped(self, pz: Puzzle) -> bool:
        return self.settings.orientation == "auto" and pz.side == "b"

    def xy(self, pz: Puzzle, f: int, r: int) -> tuple[int, int]:
        if self.flipped(pz):
            return (7 - f) * 4, r * 4
        return f * 4, (7 - r) * 4

    def board(
        self,
        fr: Frame,
        pz: Puzzle,
        b: Board,
        last: Move | None,
        sliding: tuple[Move, float] | None = None,
    ) -> None:
        light, dark, _wp, _bp, _wa, _ba, hi = THEMES[self.settings.theme]
        marks = {last.frm, last.to} if last is not None and self.settings.highlight else set()
        if sliding is not None and self.settings.highlight:
            marks = {sliding[0].frm}
        fr.px[:] = self._empty_board()  # cached checkerboard; only highlighted squares are repainted
        for f, r in marks:
            x, y = self.xy(pz, f, r)
            fr.rect(x, y, 4, 4, mix(light if (f + r) % 2 else dark, hi, 0.55))
        hidden: set[tuple[int, int]] = set()
        if sliding is not None:
            mv = sliding[0]
            hidden.add(mv.frm)
            if mv.rook:
                hidden.add(mv.rook[0])
        for r in range(8):
            for f in range(8):
                p = b[r][f]
                if p != "." and (f, r) not in hidden:
                    x, y = self.xy(pz, f, r)
                    self.piece(fr, x, y, p)
        if sliding is not None:
            mv, k = sliding
            movers = [((mv.frm, mv.to), mv.piece)]
            if mv.rook:  # castling: the rook slides too (b is the position before the move)
                movers.append((mv.rook, b[mv.rook[0][1]][mv.rook[0][0]]))
            for (a, z), p in movers:
                x0, y0 = self.xy(pz, *a)
                x1, y1 = self.xy(pz, *z)
                self.piece(fr, round(x0 + (x1 - x0) * k), round(y0 + (y1 - y0) * k), p)

    def _empty_board(self) -> np.ndarray:
        """The bare checkerboard for the current theme (the pattern is symmetric under the 180° flip)."""
        theme = self.settings.theme
        if self._board_cache is None or self._board_cache[0] != theme:
            light, dark, *_rest = THEMES[theme]
            yy, xx = np.mgrid[:32, :32]
            # a1 (file 0, rank 0) is dark; square parity is invariant under the orientation flip
            is_light = ((xx // 4) + (7 - yy // 4)) % 2 == 1
            px = np.where(is_light[..., None], np.array(light, np.uint8), np.array(dark, np.uint8))
            self._board_cache = (theme, px.astype(np.uint8))
        return self._board_cache[1]

    def _sprite(self, p: str) -> tuple[np.ndarray, np.ndarray]:
        theme = self.settings.theme
        key = (theme, p)
        spr = self._sprites.get(key)
        if spr is None:
            _l, _d, wp, bp, wa, ba, _h = THEMES[theme]
            body, acc = (wp, wa) if p.isupper() else (bp, ba)
            px = np.zeros((4, 3, 3), np.uint8)
            mask = np.zeros((4, 3), bool)
            for dx, dy, is_acc in PIECES[p.upper()]:
                px[dy, dx] = acc if is_acc else body
                mask[dy, dx] = True
            spr = self._sprites[key] = (px, mask)
        return spr

    def piece(self, fr: Frame, x: int, y: int, p: str) -> None:
        px, mask = self._sprite(p)
        fr.blit(px, x, y, mask)

    def _pulse_king(self, fr: Frame, pz: Puzzle, b: Board, t: float) -> None:
        """Side to move: its king's square breathes."""
        k = king_sq(b, pz.side)
        if k is None:
            return
        x, y = self.xy(pz, *k)
        light, dark, *_rest = THEMES[self.settings.theme]
        base = light if (k[0] + k[1]) % 2 else dark
        glow = (0.0, 0.5, 1.0, 0.5)[int(t / PULSE_STEP + 1e-6) % 4]  # few distinct frames, even steps
        col = mix(base, PALETTE["cyan"] if pz.side == "w" else PALETTE["magenta"], 0.25 + 0.45 * glow)
        fr.rect(x, y, 4, 4, col)
        self.piece(fr, x, y, b[k[1]][k[0]])

    def _flash_mated(self, fr: Frame, pz: Puzzle, t: float) -> None:
        loser = "b" if len(pz.moves) % 2 == (1 if pz.side == "w" else 0) else "w"
        k = king_sq(pz.boards[-1], loser)
        if k is None or int(t / FLASH_STEP + 1e-6) % 2:
            return
        x, y = self.xy(pz, *k)
        fr.rect(x, y, 4, 4, PALETTE["red"])
        self.piece(fr, x, y, pz.boards[-1][k[1]][k[0]])

    def _intro(self, f: Frame, pz: Puzzle, t: float) -> None:
        # the position, dimmed, behind a card
        self.board(f, pz, pz.boards[0], None)
        f.dim(INTRO_DIM)
        white = pz.side == "w"
        label = "DAILY" if pz.kind == "daily" else "PUZZLE"
        f.text_center(2, label, PALETTE["amber"])
        who = "WHITE" if white else "BLACK"
        side_c = WHITE if white else PALETTE["mute"]
        f.text_center(10, who, side_c, font="small")
        f.text_center(19, "TO MOVE", scale(WHITE, 0.7))
        f.rect(0, 25, 32, 7, BLACK)
        t = (int(t * FPS + 1e-6) + 0.01) / FPS  # whole frames: the marquee steps exactly one pixel per frame
        draw_marquee(f, pz.title.upper(), t, 1, 26, 30, PALETTE["gold"], speed=MARQUEE)

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        pz = self.puzzle()
        if not pz:
            return {"loaded": False}
        return {
            "title": pz.title,
            "to_move": "white" if pz.side == "w" else "black",
            "solution": " ".join(m.san for m in pz.moves),
            "url": pz.url,
            "manual_ply": self._manual if self.manual else None,
        }
