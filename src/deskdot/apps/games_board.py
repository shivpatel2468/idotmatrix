"""Board games: X and 0 (tic-tac-toe). Original code and art.

Layout (32 × 32): score row on top (X wins left, O wins right, whose turn in the middle), then a 3 × 3 board of
8 px cells with 1 px grid lines (26 × 26) centred below it. Marks are drawn with 2 px strokes so they read at a
glance from across the room; the winning line flashes before the board clears.

Variants (the home screen's MAP row): Classic; Vanishing (only your last three marks stay, the next one to fade
blinks); Misère (make three in a row and you LOSE). Classic and misère are solved exactly (cached at import);
vanishing never fills up, so its AI is a cached depth-limited search over (X marks, O marks) in age order.
"""

from __future__ import annotations

from functools import cache, lru_cache
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, mix, scale
from .games_core import WHITE, GameApp, GameSettings, Mode, Theme

LINES3 = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
CELL = 8
BX, BY = 3, 6  # top-left of the 26 × 26 board
KEEP = 3  # vanishing: marks each side keeps
VANISH_DEPTH = 4  # plies the vanishing AI looks ahead
VANISH_CAP = 40  # vanishing rounds end in a draw after this many moves


def winner(b: tuple[int, ...]) -> tuple[int, tuple[int, int, int] | None]:
    """(1 = X, 2 = O, 3 = draw, 0 = playing), and the winning line."""
    for ln in LINES3:
        a = b[ln[0]]
        if a and a == b[ln[1]] == b[ln[2]]:
            return a, ln
    return (3, None) if all(b) else (0, None)


@cache
def _minimax(b: tuple[int, ...], me: int) -> tuple[int, int]:
    """(score from `me`'s point of view, best cell). +10 win, -10 loss, quicker wins score higher."""
    w, _ = winner(b)
    if w == 3:
        return 0, -1
    if w:
        return (10 if w == me else -10), -1
    other = 3 - me
    best, cell = -99, -1
    for i in range(9):
        if b[i]:
            continue
        nb = (*b[:i], me, *b[i + 1 :])
        s, _ = _minimax(nb, other)
        s = -s
        s -= 1 if s > 0 else -1 if s < 0 else 0  # prefer fast wins, slow losses
        if s > best:
            best, cell = s, i
    return best, cell


@cache
def _misere(b: tuple[int, ...], me: int) -> tuple[int, int]:
    """Misère: whoever completes a line loses. Same shape as `_minimax`, terminal scores flipped."""
    w, _ = winner(b)
    if w == 3:
        return 0, -1
    if w:
        return (-10 if w == me else 10), -1
    other = 3 - me
    best, cell = -99, -1
    for i in range(9):
        if b[i]:
            continue
        s, _ = _misere((*b[:i], me, *b[i + 1 :]), other)
        s = -s
        s -= 1 if s > 0 else -1 if s < 0 else 0
        if s > best:
            best, cell = s, i
    return best, cell


def _line_of(cells: tuple[int, ...]) -> bool:
    s = set(cells)
    return any(a in s and b in s and c in s for a, b, c in LINES3)


@lru_cache(maxsize=200_000)
def _vanish(xs: tuple[int, ...], os: tuple[int, ...], me: int, depth: int) -> tuple[int, int]:
    """Vanishing variant: `xs` / `os` are each side's marks, oldest first. (score for `me`, best cell)."""
    mine, theirs = (xs, os) if me == 1 else (os, xs)
    taken = set(xs) | set(os)
    best, cell = -99, -1
    for i in (4, 0, 2, 6, 8, 1, 3, 5, 7):  # centre and corners first: better cut-offs, nicer ties
        if i in taken:
            continue
        nm = (*(mine[1:] if len(mine) >= KEEP else mine), i)
        if _line_of(nm):
            s = 10 + depth
        elif depth <= 1:
            s = 0
        else:
            nx, no = (nm, theirs) if me == 1 else (theirs, nm)
            s = -_vanish(nx, no, 3 - me, depth - 1)[0]
        if s > best:
            best, cell = s, i
            if s >= 10 + depth:
                break
    return best, cell


# the whole game tree is ~6k positions: solve it once at import so no render() ever pays for a cold search
_minimax((0,) * 9, 1)
_minimax((0,) * 9, 2)
_misere((0,) * 9, 1)
_misere((0,) * 9, 2)


class TicTacToeSettings(GameSettings):
    first_to: int = Field(
        3,
        ge=1,
        le=9,
        title="Match: first to",
        description="Round wins needed to take a match started from the menu",
        json_schema_extra={"group": "Game"},
    )


THEMES_TTT: dict[str, Theme] = {
    "chalk": Theme(
        p=(240, 240, 225),  # chalk X
        e=(255, 200, 70),  # yellow chalk O
        x=(120, 230, 255),
        w=(70, 120, 90),
        hud=(210, 240, 215),
        bg=(2, 10, 5),
        r=(
            (240, 240, 225),
            (255, 200, 70),
            (120, 230, 255),
            (255, 150, 190),
            (150, 255, 150),
            (255, 170, 90),
            (200, 200, 255),
        ),
    ),
    "arcade": Theme(
        p=(80, 240, 255),
        e=(255, 120, 210),
        x=(255, 240, 90),
        w=(90, 70, 170),
        hud=(230, 230, 255),
        bg=(4, 2, 12),
        r=(
            (80, 240, 255),
            (255, 120, 210),
            (255, 240, 90),
            (130, 255, 130),
            (255, 160, 60),
            (200, 150, 255),
            (255, 255, 255),
        ),
    ),
}


@register
class TicTacToe(GameApp):
    id = "tictactoe"
    name = "X and 0"
    description = (
        "Tic-tac-toe for 1 or 2 players. Play X against the AI (arrows move, A places), or let a friend join from "
        "their phone on your Wi-Fi as O by scanning the panel's QR code. Variants: vanishing marks and misère."
    )
    icon = "hash"
    Settings = TicTacToeSettings
    over_hold = 2.5
    max_players = 2  # X = seat 1 (you), O = seat 2 (a friend's phone, or the AI)
    controls = ("dpad", "gamepad")  # best controllers first (phone + Play mode default to the first)
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Vs AI", 1, 1, "solo"),
        Mode("duel", "Vs Friend", 2, 2, "ffa"),
    )
    maps: ClassVar[dict[str, str]] = {"classic": "Classic", "vanish": "Vanishing", "misere": "Misere"}
    game_themes: ClassVar[dict[str, Theme]] = THEMES_TTT
    game_theme_labels: ClassVar[dict[str, str]] = {"chalk": "Chalkboard", "arcade": "Arcade"}

    def new_game(self) -> None:
        self.wins = [0, 0, 0]  # draws, X, O
        self.match = bool(self.roster)  # a match started from the menu (first to N), not the self-play demo
        self.you = self.match  # a human is playing X
        self.variant = self.map_id if self.map_id in self.maps else "classic"
        self.starter = 1
        self._match_done = False
        self._round()

    def _round(self) -> None:
        self.board: tuple[int, ...] = (0,) * 9
        self.order: dict[int, list[int]] = {1: [], 2: []}  # each side's marks, oldest first (vanishing)
        self.moves = 0
        self.turn = self.starter
        self.starter = 3 - self.starter
        self.think = 0.6
        self.curs = {1: 4, 2: 4}  # each player's own cursor
        self.placed: dict[int, float] = {}  # cell -> seconds since placed (draw-in animation)
        self.fading: dict[int, list[float]] = {}  # vanishing: cell -> [seconds left, side]
        self.end_t = 0.0  # > 0 while the finished board is shown
        self.line: tuple[int, int, int] | None = None

    # ------------------------------------------------------------------ rules
    def _place(self, i: int) -> None:
        if self.board[i] or self.end_t > 0:
            return
        b = list(self.board)
        mine = self.order[self.turn]
        if self.variant == "vanish" and len(mine) >= KEEP:
            old = mine.pop(0)
            b[old] = 0
            self.placed.pop(old, None)
            self.fading[old] = [0.35, float(self.turn)]
        b[i] = self.turn
        mine.append(i)
        self.board = tuple(b)
        self.placed[i] = 0.0
        self.moves += 1
        w, ln = winner(self.board)
        if self.variant == "vanish" and w == 3:
            w = 0  # the vanishing board never fills up
        if not w and self.variant == "vanish" and self.moves >= VANISH_CAP:
            w, ln = 3, None
        if w:
            if self.variant == "misere" and w in (1, 2):
                w = 3 - w  # three in a row loses
            self._round_over(w, ln)
            return
        self.turn = 3 - self.turn
        self.think = 0.55

    def _round_over(self, w: int, ln: tuple[int, int, int] | None) -> None:
        self.line = ln
        self.end_t = 1.6
        self.wins[0 if w == 3 else w] += 1
        if w in (1, 2):
            loser = 3 - w
            if self.is_human(loser) and (self.match or self.human):
                self.damage(0.7)
            if ln:
                for c in ln:
                    r, cc = divmod(c, 3)
                    x, y = BX + cc * (CELL + 1) + 4, BY + r * (CELL + 1) + 4
                    self.fx.burst(self.rng, x, y, self._col(w), 4, 9, 0.5)
        if self.match:
            n = self.settings.first_to
            if max(self.wins[1], self.wins[2]) >= n:
                self.end_t = 1.2
                self._match_done = True
            return
        if self.versus:
            pass  # two players: the side scores (self.wins) are the scoreboard
        elif self.human:
            if w == 1:
                self.score += 1
            elif w == 2:
                self.game_over()  # your streak ends
        else:
            self.score = self.wins[1] + self.wins[2]

    def _finish_match(self) -> None:
        x, o = self.wins[1], self.wins[2]
        self.score = x
        scores = {1: x, 2: o}
        if self.play_mode.id == "duel":
            self.result(winner_seat=1 if x > o else 2, scores=scores)
        else:
            self.result(text="YOU WIN" if x > o else "AI WINS", scores=scores)

    def _ai_cell(self) -> int:
        free = [i for i in range(9) if not self.board[i]]
        # the O side slips now and then (lower skill slips more) so demo games aren't all draws
        slip = (1 - self.skill) * 0.6 + (0.12 if self.turn == 2 and not self.match else 0.0)
        if len(free) < 9 and self.rng.random() < slip:
            return self.rng.choice(free)
        if len(free) == 9:  # vary the opening
            return self.rng.choice((0, 2, 4, 6, 8, 4))
        if self.variant == "vanish":
            c = _vanish(tuple(self.order[1]), tuple(self.order[2]), self.turn, VANISH_DEPTH)[1]
        elif self.variant == "misere":
            c = _misere(self.board, self.turn)[1]
        else:
            c = _minimax(self.board, self.turn)[1]
        return c if c >= 0 and not self.board[c] else self.rng.choice(free)

    # ------------------------------------------------------------------ loop
    def key_p(self, k: str, player: int) -> None:
        if player not in (1, 2):
            return
        if player == 1 and not self.you:  # the host just took over: fresh board, fresh streak
            self.you = True
            self.score = 0
            self._round()
            self.turn = 1
        d = {"up": -3, "down": 3, "left": -1, "right": 1}.get(k)
        if d is not None:
            r, c = divmod(self.curs[player], 3)
            if k in ("left", "right"):
                c = (c + d) % 3
            else:
                r = (r + d // 3) % 3
            self.curs[player] = r * 3 + c
        elif k in ("a", "b") and self.turn == player:  # only the player whose turn it is can place
            self._place(self.curs[player])

    @property
    def versus(self) -> bool:
        """Two people are playing each other (host + a phone)."""
        if self.match:
            return self.is_human(2)
        return self.human and self.is_human(2)

    def update(self, dt: float) -> None:
        for i in self.placed:
            self.placed[i] += dt
        for c in list(self.fading):
            self.fading[c][0] -= dt
            if self.fading[c][0] <= 0:
                del self.fading[c]
        if self.end_t > 0:
            self.end_t -= dt
            if self.end_t <= 0:
                if self._match_done:
                    self._match_done = False
                    self._finish_match()
                    return
                self._round()
            return
        if not self.human and not self.match:
            self.you = False
        if self.is_human(self.turn):
            return  # a person's move: wait for them
        self.think -= dt
        if self.think <= 0:
            self._place(self._ai_cell())

    # ------------------------------------------------------------------ draw
    def _col(self, who: int) -> RGB:
        return self.theme.p if who == 1 else self.theme.e

    def _mark(self, f: Frame, i: int, who: int, color: RGB, k: float) -> None:
        r, c = divmod(i, 3)
        x0, y0 = BX + c * (CELL + 1) + 1, BY + r * (CELL + 1) + 1  # 6 × 6 inside the cell
        if who == 1:  # X: two 2 px-wide diagonals; the second stroke draws in after the first
            n1 = round(6 * min(1.0, k * 2))
            n2 = round(6 * max(0.0, min(1.0, k * 2 - 1)))
            for d in range(n1):
                f.rect(x0 + min(d, 4), y0 + d, 2, 1, color)
            for d in range(n2):
                f.rect(x0 + max(0, 4 - d), y0 + d, 2, 1, color)
        else:  # O: a 6 × 6 ring with 1 px corners cut, 2 px thick
            if k < 1:
                color = scale(color, 0.4 + 0.6 * k)
            f.rect(x0 + 1, y0, 4, 2, color)
            f.rect(x0 + 1, y0 + 4, 4, 2, color)
            f.rect(x0, y0 + 1, 2, 4, color)
            f.rect(x0 + 4, y0 + 1, 2, 4, color)

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        cx, co = th.p, th.e
        grid = scale(th.w, 0.8)
        for k in (1, 2):
            f.vline(BX + k * (CELL + 1) - 1, BY, 26, grid)
            f.hline(BX, BY + k * (CELL + 1) - 1, 26, grid)
        flash = self.end_t > 0 and self.line is not None and int(now * 6) % 2 == 0
        # vanishing: the mark that disappears on its owner's next move blinks dim
        doomed = -1
        if self.variant == "vanish" and self.end_t <= 0 and len(self.order[self.turn]) >= KEEP:
            doomed = self.order[self.turn][0]
        for i, v in enumerate(self.board):
            if not v:
                continue
            col = cx if v == 1 else co
            if self.line and i not in self.line and self.end_t > 0:
                col = scale(col, 0.35)  # the winning line stays bright; everything else steps back
            elif flash and self.line and i in self.line:
                col = mix(col, WHITE, 0.55)
            elif i == doomed and int(now * 4) % 2:
                col = scale(col, 0.4)
            self._mark(f, i, v, col, min(1.0, self.placed.get(i, 1.0) / 0.25))
        for i, (left, side) in self.fading.items():  # a vanished mark fades out
            self._mark(f, i, int(side), scale(cx if side == 1 else co, 0.15 + left), 1.0)
        if self.is_human(self.turn) and self.end_t <= 0 and int(now * 3) % 3:
            r, c = divmod(self.curs[self.turn], 3)
            ring_col = th.x if self.turn == 1 and not self.versus else (cx if self.turn == 1 else co)
            f.rect(BX + c * (CELL + 1), BY + r * (CELL + 1), CELL, CELL, ring_col, fill=False)
        if self.settings.show_score:
            if self.human and not self.versus and not self.match:
                f.text(1, 0, "YOU", cx)
                f.text_right(30, 0, str(self.score), WHITE)
            else:
                # counts only, in their side's colour ("0O" would read as a double zero)
                f.text(1, 0, str(self.wins[1]), cx)
                f.text_right(30, 0, str(self.wins[2]), co)
            if self.end_t <= 0:  # whose turn: a 2 px dot in their colour, top centre
                f.rect(15, 2, 2, 2, cx if self.turn == 1 else co)

    def best_candidate(self) -> int:
        return self.score if self.human else 0

    def status(self) -> dict[str, Any]:
        st = super().status()
        st["turn"] = self.turn  # phones show "Your turn" / "Their turn"
        st["wins"] = {"x": self.wins[1], "o": self.wins[2], "draws": self.wins[0]}
        return st
