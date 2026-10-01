"""Four Up — four-in-a-row for 1–2 players (AI vs AI until someone takes a seat). Original code and art.

Layout (32 × 32): score row on top (seat 1 left, seat 2 right) with the hovering disc of whoever is to move, then a
7 × 6 board of 4 px cells (29 × 25) whose 3 × 3 holes show the discs. Discs fall into place; the winning four
flashes before the board clears.

Variants (the home screen's MAP row): Classic; Pop Out (on your turn you may pop one of YOUR discs out of the
bottom row instead of dropping — the column slides down; if a pop makes fours for both, the popper wins); Stones
(a few neutral stones hang in the board: discs land on them and the holes beneath are dead).

The AI is a bitboard negamax with alpha-beta, centre-first move order and a window-count evaluation; its depth
follows the skill setting and stays small enough to decide inside one render (pop out has twice the moves, so it
looks two plies ahead).
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, mix, scale
from .games_core import BLACK, WHITE, GameApp, GameSettings, Mode, Theme, tint

SEAT_COLORS: tuple[RGB, ...] = ((0, 200, 255), (255, 60, 90), (80, 255, 120), (255, 200, 0))

COLS, ROWS = 7, 6
H1 = ROWS + 1  # bits per column (one sentinel bit on top)
BX, BY = 1, 7  # board top-left
CELL = 4
ORDER = (3, 2, 4, 1, 5, 0, 6)
TOP_MASK = sum(1 << (c * H1 + ROWS - 1) for c in range(COLS))
FULL = sum(((1 << ROWS) - 1) << (c * H1) for c in range(COLS))
COL_MASK = tuple(((1 << ROWS) - 1) << (c * H1) for c in range(COLS))
POP_CAP = 70  # pop-out rounds can cycle: call it a draw after this many moves


def _bit(c: int, r: int) -> int:
    """r = 0 is the bottom row."""
    return 1 << (c * H1 + r)


def _windows() -> list[int]:
    out = []
    for c in range(COLS):
        for r in range(ROWS):
            for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
                cells = [(c + k * dc, r + k * dr) for k in range(4)]
                if all(0 <= cc < COLS and 0 <= rr < ROWS for cc, rr in cells):
                    m = 0
                    for cc, rr in cells:
                        m |= _bit(cc, rr)
                    out.append(m)
    return out


WINDOWS = _windows()
CENTRE = sum(_bit(3, r) for r in range(ROWS))


def won(b: int) -> bool:
    for s in (1, H1, H1 - 1, H1 + 1):
        m = b & (b >> s)
        if m & (m >> 2 * s):
            return True
    return False


def win_cells(b: int) -> list[tuple[int, int]]:
    for m in WINDOWS:
        if b & m == m:
            return [(i // H1, i % H1) for i in range(COLS * H1) if m >> i & 1]
    return []


def _eval(me: int, opp: int, windows: list[int] = WINDOWS) -> int:
    s = 3 * (bin(me & CENTRE).count("1") - bin(opp & CENTRE).count("1"))
    for w in windows:
        a, b = me & w, opp & w
        if a and not b:
            n = bin(a).count("1")
            s += 1 if n == 1 else 4 if n == 2 else 16
        elif b and not a:
            n = bin(b).count("1")
            s -= 1 if n == 1 else 4 if n == 2 else 18
    return s


class Board:
    __slots__ = ("blk", "heights", "mask", "moves", "pos", "windows")

    def __init__(self) -> None:
        self.pos = [0, 0]  # bitboards of seat 1 and seat 2
        self.mask = 0
        self.blk = 0  # neutral stones and the dead holes beneath them
        self.heights = [0] * COLS
        self.moves = 0
        self.windows = WINDOWS

    def stone(self, c: int, r: int) -> None:
        """Hang a neutral stone at (c, r): it and every hole beneath it are out of play."""
        for rr in range(r + 1):
            self.blk |= _bit(c, rr)
        self.mask |= self.blk
        self.heights[c] = max(self.heights[c], r + 1)
        self.windows = [w for w in WINDOWS if not w & self.blk]

    def full(self) -> bool:
        return self.mask & FULL == FULL

    def can(self, c: int) -> bool:
        return self.heights[c] < ROWS

    def can_pop(self, c: int, who: int) -> bool:
        return bool(self.pos[who] & _bit(c, 0))

    def play(self, c: int, who: int) -> int:
        r = self.heights[c]
        self.pos[who] |= _bit(c, r)
        self.mask |= _bit(c, r)
        self.heights[c] += 1
        self.moves += 1
        return r

    def undo(self, c: int, who: int) -> None:
        self.heights[c] -= 1
        b = _bit(c, self.heights[c])
        self.pos[who] &= ~b
        self.mask &= ~b
        self.moves -= 1

    def pop(self, c: int) -> tuple[int, int, int, int]:
        """Remove the bottom disc of column `c`; everything above slides down. Returns the state for `restore`."""
        saved = (self.pos[0], self.pos[1], self.mask, self.heights[c])
        col, base = COL_MASK[c], c * H1
        for p in (0, 1):
            v = self.pos[p]
            self.pos[p] = (v & ~col) | ((((v & col) >> base) >> 1) << base)
        self.mask = self.pos[0] | self.pos[1] | self.blk
        self.heights[c] -= 1
        self.moves += 1
        return saved

    def restore(self, c: int, saved: tuple[int, int, int, int]) -> None:
        self.pos[0], self.pos[1], self.mask, self.heights[c] = saved
        self.moves -= 1


def negamax(bd: Board, who: int, depth: int, alpha: int, beta: int) -> int:
    opp = 1 - who
    if bd.full():
        return 0
    if depth == 0:
        return _eval(bd.pos[who], bd.pos[opp], bd.windows)
    for c in ORDER:  # win now
        if bd.can(c):
            bd.play(c, who)
            w = won(bd.pos[who])
            bd.undo(c, who)
            if w:
                return 1000 + depth
    best = -(10**6)
    for c in ORDER:
        if not bd.can(c):
            continue
        bd.play(c, who)
        v = -negamax(bd, opp, depth - 1, -beta, -alpha)
        bd.undo(c, who)
        if v > best:
            best = v
        alpha = max(alpha, v)
        if alpha >= beta:
            break
    return best


def best_move(bd: Board, who: int, depth: int) -> int:
    opp = 1 - who
    free = [c for c in ORDER if bd.can(c)]
    for c in free:  # win now
        bd.play(c, who)
        w = won(bd.pos[who])
        bd.undo(c, who)
        if w:
            return c
    for c in free:  # block the opponent's win
        bd.play(c, opp)
        w = won(bd.pos[opp])
        bd.undo(c, opp)
        if w:
            return c
    best, bc = -(10**7), free[0]
    for c in free:
        bd.play(c, who)
        v = -negamax(bd, opp, depth - 1, -(10**6), 10**6)
        bd.undo(c, who)
        if v > best:
            best, bc = v, c
    return bc


# ----------------------------------------------------------------------------------------- pop out
Move = tuple[str, int]  # ("drop" | "pop", column)


def pop_moves(bd: Board, who: int) -> list[Move]:
    return [("drop", c) for c in ORDER if bd.can(c)] + [("pop", c) for c in ORDER if bd.can_pop(c, who)]


def _apply(bd: Board, m: Move, who: int) -> Any:
    if m[0] == "drop":
        bd.play(m[1], who)
        return None
    return bd.pop(m[1])


def _unapply(bd: Board, m: Move, who: int, saved: Any) -> None:
    if m[0] == "drop":
        bd.undo(m[1], who)
    else:
        bd.restore(m[1], saved)


def pop_outcome(bd: Board, who: int) -> int | None:
    """After `who` moved: who has four? (the mover wins ties, as in the pop-out rules)."""
    if won(bd.pos[who]):
        return who
    if won(bd.pos[1 - who]):
        return 1 - who
    return None


def negamax_pop(bd: Board, who: int, depth: int, alpha: int, beta: int) -> int:
    opp = 1 - who
    moves = pop_moves(bd, who)
    if not moves:
        return 0
    best = -(10**6)
    for m in moves:
        saved = _apply(bd, m, who)
        o = pop_outcome(bd, who)
        if o == who:
            v = 1000 + depth
        elif o == opp:
            v = -(1000 + depth)
        elif depth <= 1:
            v = _eval(bd.pos[who], bd.pos[opp])
        else:
            v = -negamax_pop(bd, opp, depth - 1, -beta, -alpha)
        _unapply(bd, m, who, saved)
        if v > best:
            best = v
        alpha = max(alpha, v)
        if alpha >= beta:
            break
    return best


def best_move_pop(bd: Board, who: int, depth: int = 2) -> Move:
    opp = 1 - who
    moves = pop_moves(bd, who)
    best, bm = -(10**7), moves[0]
    for m in moves:
        saved = _apply(bd, m, who)
        o = pop_outcome(bd, who)
        if o == who:
            v = 10**6
        elif o == opp:
            v = -(10**6)
        else:
            v = (
                -negamax_pop(bd, opp, depth - 1, -(10**6), 10**6)
                if depth > 1
                else _eval(bd.pos[who], bd.pos[opp])
            )
        _unapply(bd, m, who, saved)
        if v > best:
            best, bm = v, m
    return bm


# ----------------------------------------------------------------------------------------- the app
class FourUpSettings(GameSettings):
    first_to: int = Field(
        3,
        ge=1,
        le=9,
        title="Match: first to",
        description="Round wins needed to take a match started from the menu",
        json_schema_extra={"group": "Game"},
    )
    stones: int = Field(3, ge=1, le=5, title="Stones (Stones map)", json_schema_extra={"group": "Game"})


FOURUP_THEMES: dict[str, Theme] = {
    "tavern": Theme(
        p=(255, 210, 60),  # brass discs
        e=(255, 130, 150),  # rose discs
        x=(255, 250, 200),
        w=(150, 85, 36),  # oak board
        hud=(255, 230, 170),
        bg=(6, 3, 1),
        r=(
            (255, 210, 60),
            (255, 130, 150),
            (255, 160, 70),
            (200, 255, 120),
            (150, 220, 255),
            (255, 250, 200),
            (230, 170, 255),
        ),
    ),
    "ice": Theme(
        p=(120, 240, 255),
        e=(255, 150, 220),
        x=(255, 255, 160),
        w=(50, 100, 170),  # frosted board
        hud=(210, 240, 255),
        bg=(1, 4, 10),
        r=(
            (120, 240, 255),
            (255, 150, 220),
            (255, 255, 160),
            (150, 255, 190),
            (200, 200, 255),
            (255, 190, 120),
            (255, 255, 255),
        ),
    ),
}


@register
class FourUp(GameApp):
    id = "fourup"
    name = "Four Up"
    description = (
        "Four-in-a-row. Two AIs play until someone takes a seat: left/right aim, A or down drops your disc. "
        "A phone can join as the second player. Variants: Pop Out (up pops your bottom disc) and Stones."
    )
    icon = "grid-3x3"
    Settings = FourUpSettings
    max_players: ClassVar[int] = 2
    controls = ("dpad", "tap", "gamepad")  # best controllers first (phone + Play mode default to the first)
    over_hold = 2.5
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Vs AI", 1, 1, "solo"),
        Mode("duel", "Vs Friend", 2, 2, "ffa"),
    )
    maps: ClassVar[dict[str, str]] = {"classic": "Classic", "popout": "Pop Out", "stones": "Stones"}
    game_themes: ClassVar[dict[str, Theme]] = FOURUP_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"tavern": "Tavern", "ice": "Ice"}

    def new_game(self) -> None:
        self.wins = [0, 0, 0]  # draws, seat 1, seat 2
        self.starter = 0
        self.cursor = [3, 3]
        self.match = bool(self.roster)  # started from the menu: first to N, results screen
        self.you = self.match
        self.variant = self.map_id if self.map_id in self.maps else "classic"
        self._match_done = False
        self._round()

    def _round(self) -> None:
        self.bd = Board()
        self.stones: set[tuple[int, int]] = set()
        if self.variant == "stones":
            cols = self.rng.sample((0, 1, 2, 4, 5, 6), min(6, self.settings.stones))
            for c in cols:
                r = self.rng.randrange(0, 3)
                self.bd.stone(c, r)
                self.stones.add((c, r))
        self.turn = self.starter  # 0 = seat 1, 1 = seat 2
        self.starter = 1 - self.starter
        self.think = 0.7
        self.drop: list[float] | None = None  # [col, row, y px, vy, who]
        self.end_t = 0.0
        self.line: list[tuple[int, int]] = []
        self.plays = 0
        self._plan: Move | None = None  # the AI's chosen move while its hover disc glides over

    # ------------------------------------------------------------------ input
    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        seat = player - 1
        if seat not in (0, 1):
            return
        if seat == 0 and not self.you:  # the host just took over: fresh board, fresh streak
            self.you = True
            self.score = 0
            self._round()
            self.turn = 0
        if k in ("left", "right"):
            d = -1 if k == "left" else 1
            self.cursor[seat] = (self.cursor[seat] + d) % COLS
            return
        if self.turn != seat or self.drop is not None or self.end_t > 0:
            return
        if self.variant == "popout" and k in ("up", "b"):
            self._pop(self.cursor[seat])
        elif k in ("a", "b", "down", "up"):
            self._play(self.cursor[seat])

    # ------------------------------------------------------------------ rules
    def _play(self, c: int) -> None:
        if not self.bd.can(c):
            return
        who = self.turn
        r = self.bd.play(c, who)
        self.cursor[who] = c
        self.plays += 1
        self.drop = [float(c), float(r), float(BY - 4), 0.0, float(who)]

    def _pop(self, c: int) -> None:
        who = self.turn
        if not self.bd.can_pop(c, who):
            return
        self.bd.pop(c)
        self.cursor[who] = c
        self.plays += 1
        x = BX + 2 + c * CELL
        self.fx.burst(self.rng, x, 30, self._cols()[who], 7, 10, 0.5, vy=6)
        o = pop_outcome(self.bd, who)
        if o is not None:
            self._won(o)
            return
        self._next(who)

    def _landed(self) -> None:
        assert self.drop is not None
        who, c, r = int(self.drop[4]), int(self.drop[0]), int(self.drop[1])
        self.drop = None
        self.fx.burst(
            self.rng, BX + 2 + c * CELL, BY + 3 + (ROWS - 1 - r) * CELL, WHITE, 3, 4, 0.2
        )  # a landing puff
        if won(self.bd.pos[who]):
            self._won(who)
            return
        if self.bd.full():
            self.end_t = 1.4
            self.wins[0] += 1
            return
        self._next(who)

    def _next(self, who: int) -> None:
        if self.variant == "popout" and self.plays >= POP_CAP:
            self.end_t = 1.4
            self.wins[0] += 1
            return
        self.turn = 1 - who
        self.think = 0.5

    def _won(self, who: int) -> None:
        self.line = win_cells(self.bd.pos[who])
        self.end_t = 1.8
        self.wins[1 + who] += 1
        for c, r in self.line:
            self.fx.burst(
                self.rng, BX + 2 + c * CELL, BY + 2 + (ROWS - 1 - r) * CELL, self._cols()[who], 3, 8, 0.5
            )
        loser = 2 - who  # the other seat number
        if self.is_human(loser) and (self.match or self.you):
            self.damage(0.7)
        if self.match:
            if max(self.wins[1], self.wins[2]) >= self.settings.first_to:
                self._match_done = True
                self.end_t = 1.4
            return
        self._scored(who + 1)

    def _scored(self, winner: int) -> None:
        if self.you and self.is_human(1):
            if winner == 1:
                self.score += 1
            elif not self.is_human(2):
                self.game_over()  # the AI ended your streak
        else:
            self.score = self.wins[1] + self.wins[2]

    def _finish_match(self) -> None:
        a, b = self.wins[1], self.wins[2]
        self.score = a
        scores = {1: a, 2: b}
        if self.play_mode.id == "duel":
            self.result(winner_seat=1 if a > b else 2, scores=scores)
        else:
            self.result(text="YOU WIN" if a > b else "AI WINS", scores=scores)

    def _ai_move(self) -> Move:
        if self.bd.moves == 0 and not self.stones:
            return ("drop", self.rng.choice((3, 3, 2, 4)))
        if self.variant == "popout":
            if self.rng.random() < (1 - self.skill) * 0.3 + 0.04:
                return self.rng.choice(pop_moves(self.bd, self.turn))
            return best_move_pop(self.bd, self.turn, 2)
        free = [c for c in range(COLS) if self.bd.can(c)]
        slip = (1 - self.skill) * 0.3 + 0.04
        if self.rng.random() < slip:
            return ("drop", self.rng.choice(free))
        depth = 1 + round(3 * self.skill)
        return ("drop", best_move(self.bd, self.turn, depth))

    def _ai_col(self) -> int:
        return self._ai_move()[1]

    # ------------------------------------------------------------------- loop
    def update(self, dt: float) -> None:
        if not self.is_human(1) and not self.match:
            self.you = False
        if self.end_t > 0:
            self.end_t -= dt
            if self.end_t <= 0:
                if self._match_done:
                    self._match_done = False
                    self._finish_match()
                    return
                self._round()
            return
        if self.drop is not None:
            d = self.drop
            d[3] += 160 * dt
            d[2] += d[3] * dt
            target = BY + (ROWS - 1 - d[1]) * CELL + 1
            if d[2] >= target:
                self._landed()
            return
        seat = self.turn + 1
        if self.is_human(seat):
            return  # waiting for that player's drop
        self.think -= dt
        if self.think <= 0:
            if self._plan is None:
                self._plan = self._ai_move()
            kind, c = self._plan
            # glide the hover disc over before dropping, so the move reads
            if self.cursor[self.turn] != c:
                self.cursor[self.turn] += 1 if c > self.cursor[self.turn] else -1
                self.think = 0.09
                return
            self._plan = None
            if kind == "pop":
                self._pop(c)
            else:
                self._play(c)

    # ------------------------------------------------------------------- draw
    def _tid(self) -> str:
        return str(self.sel.get("theme", self.settings.theme))

    def _cols(self) -> tuple[RGB, RGB]:
        th = self.theme
        return (SEAT_COLORS[0], SEAT_COLORS[1]) if self._tid() == "classic" else (th.p, th.e)

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        cols = self._cols()
        board = (8, 20, 90) if self._tid() == "classic" else scale(th.w, 0.6)
        stone = (150, 150, 165) if self._tid() == "classic" else tint(th.w, 0.45)
        f.rect(BX, BY, COLS * CELL + 1, ROWS * CELL + 1, board)
        flash = self.end_t > 0 and self.line and int(now * 6) % 2 == 0
        seat = self.turn
        pop_hint = (
            self.variant == "popout"
            and self.end_t <= 0
            and self.drop is None
            and self.is_human(seat + 1)
            and self.bd.can_pop(self.cursor[seat], seat)
            and int(now * 2) % 2 == 0
        )
        for c in range(COLS):
            for r in range(ROWS):
                x, y = BX + 1 + c * CELL, BY + 1 + (ROWS - 1 - r) * CELL
                b = _bit(c, r)
                if self.bd.blk & b:
                    if (c, r) in self.stones:  # a stone: grey block with a lit top-left
                        f.rect(x, y, 3, 3, scale(stone, 0.7))
                        f.set(x, y, stone)
                    continue  # dead holes beneath a stone stay board-coloured
                col: RGB = BLACK
                for who in (0, 1):
                    if self.bd.pos[who] & b:
                        col = cols[who]
                if self.drop is not None and int(self.drop[0]) == c and int(self.drop[1]) == r:
                    col = BLACK  # still falling
                if col != BLACK and self.end_t > 0 and self.line:
                    col = (
                        mix(col, WHITE, 0.5)
                        if flash and (c, r) in self.line
                        else (col if (c, r) in self.line else scale(col, 0.35))
                    )
                if pop_hint and r == 0 and c == self.cursor[seat]:
                    col = mix(col, WHITE, 0.5)
                f.rect(x, y, 3, 3, col)
        if self.drop is not None:
            c, _r, y, _vy, who = self.drop
            x = BX + 1 + int(c) * CELL
            yy = int(y)
            f.rect(x, max(0, yy), 3, 3 - max(0, -yy), cols[int(who)])
            f.rect(BX, BY, COLS * CELL + 1, 1, board)  # the board's top edge stays in front
        elif self.end_t <= 0:
            x = BX + 1 + self.cursor[seat] * CELL
            if not self.is_human(seat + 1) or int(now * 3) % 3:
                f.rect(x, 5, 3, 2, cols[seat])  # below the score row, above the board
        if self.settings.show_score:
            f.text(1, 0, str(self.wins[1] if not self.you or self.match else self.score), cols[0])
            f.text_right(30, 0, str(self.wins[2]), cols[1])

    def best_candidate(self) -> int:
        return self.score if self.you else 0

    def status(self) -> dict[str, Any]:
        st = super().status()
        st["turn"] = self.turn + 1
        st["wins"] = {"1": self.wins[1], "2": self.wins[2], "draws": self.wins[0]}
        return st
