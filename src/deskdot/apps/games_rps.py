"""Rock Paper Scissors: a 1v1 party game for the panel and phones. Original code and pixel art.

Two pixel hands (a fist, a flat hand, two fingers) face each other across the panel in their players' colours.
Every round: both sides pick in secret (phones, keyboard, AI or the fruit fly), the fists pump three times to
"ROCK… PAPER… SCISSORS…", and both picks are revealed at once on "SHOOT!". First to N round wins takes the match.

Modes: You vs AI, 1 v 1 (keyboard + phone, or two phones while the host watches), Tournament (3–8 players,
knockout bracket or round robin; AI-only matches are simulated so the party keeps moving) and AI vs AI (also the
attract screen). Keys: ← rock, ↑ paper, → scissors, ↓ a random pick (API / keyboard also take 1 2 3 and R P S).

Fairness: every AI pick is made from a CSPRNG (`secrets.SystemRandom`) at the start of the round, from the history
of *finished* rounds only — no AI ever sees anyone's pick for the current round. Picks stay secret in `status()`
(phones only learn who has locked in) until the reveal.
"""

from __future__ import annotations

import math
import secrets
from functools import lru_cache
from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from ..engine.app import Choice, register
from ..gfx import RGB, Frame, measure, mix, scale
from ..gfx.avatars import draw_avatar
from ..gfx.font import fit
from .games_core import SEAT_RGB, WHITE, GameApp, GameSettings, Mode, Theme, _hex

ROCK, PAPER, SCISSORS = 0, 1, 2
MOVES = ("rock", "paper", "scissors")
#: phone / keyboard keys → picks ("down" = let fate pick). Phones send these through the normal {"k": key} input.
KEY_MOVE = {"left": ROCK, "up": PAPER, "right": SCISSORS}
#: extra keys accepted from the API / a raw keyboard (translated before the shared key handling)
KEY_ALIAS = {"1": "left", "2": "up", "3": "right", "r": "left", "p": "up", "s": "right", "x": "right"}
_SR = secrets.SystemRandom()  # every pick the game makes for someone comes from here


def judge(a: int, b: int) -> int:
    """0 = draw, 1 = `a` wins, 2 = `b` wins."""
    d = (a - b) % 3
    return 0 if d == 0 else 1 if d == 1 else 2


def counter(m: int) -> int:
    """The move that beats `m` (paper beats rock, scissors beat paper, rock beats scissors)."""
    return (m + 1) % 3


# ------------------------------------------------------------------ pixel art (original), pointing right
# c = sleeve (player colour) · h = glove (player colour, lightened) · l = highlight · s = shade (finger lines)
ART: dict[str, tuple[str, ...]] = {
    "rock": (
        "....hhhhhh....",
        "cc.hlllhhhhh..",
        "cchhhhhhhhhhh.",
        "cchhhhhhllllhh",
        "cchhhhhhhhhhsh",
        "cchhhhhhhsssss",
        "cchhhhhhhhhhhh",
        "cchhhhhhhsssss",
        "cchhhhhhhhhhhh",
        "cc.hhhhhhssss.",
        "....hhhhhhhh..",
    ),
    "paper": (
        "......hh.......",
        ".....hhh.......",
        "....hhh........",
        "cc.hhhhhhhhhhh.",
        "cchlllhhhhhhhhh",
        "cchhhhhh.......",
        "cchhhhhhhhhhhhh",
        "cchhhhhhhhhhhhh",
        "cchhhhhh.......",
        "cchhhhhhhhhhhh.",
        "cchhhhhhhhhhhh.",
        "cc.hhhhh.......",
        "....hhhhhhhhh..",
        ".....hhhhhhh...",
    ),
    "scissors": (
        ".............hh",
        "...........hhhh",
        ".........hhhhh.",
        "...hhhhhhhhh...",
        "cc.hlllhhhh....",
        "cchhhhhhhh.....",
        "cchhhhhhhhh....",
        "cchhhhhhhhhhhhh",
        "cchhhhhhhhhhhhh",
        "cchhhhhhhsssss.",
        "cc.hhhhhhhhhh..",
        "....hhhhhhh....",
    ),
}
#: 5 × 5 icons for tells and small spaces
MINI: dict[int, tuple[str, ...]] = {
    ROCK: (".###.", "#####", "#####", "#####", ".###."),
    PAPER: ("#.#.#", "#.#.#", "#####", "#####", ".###."),
    SCISSORS: ("#...#", ".#.#.", "..#..", "##.##", "##.##"),
}
TROPHY = (
    "#.#######.#",
    "#.#######.#",
    ".#.#####.#.",
    "...#####...",
    "....###....",
    ".....#.....",
    ".....#.....",
    "...#####...",
    "...#####...",
)
TICK = ("....#", "...#.", "#.#..", ".#...")
BOT_NAMES = ("REX", "ZAP", "BIT", "JET", "ACE", "KIT", "ORB", "GIG")
#: colours for AI seats beyond the four seat defaults (skipping any a phone player already shows)
EXTRA_RGB: tuple[RGB, ...] = (
    (255, 45, 120),
    (255, 120, 20),
    (150, 80, 255),
    (50, 100, 255),
    (31, 224, 255),
    (240, 240, 240),
)
HY = 17  # vertical centre of the hands
PUMP_BEAT = 0.42  # seconds per "ROCK… PAPER… SCISSORS…" bob
WORDS = ("ROCK", "PAPER", "SCISSORS")


@lru_cache(maxsize=256)
def hand_sprite(move: int, colour: RGB, flip: bool) -> tuple[np.ndarray, np.ndarray]:
    """(pixels, mask) for a hand in a player's colour; `flip` points it left (the right-hand player)."""
    rows = ART[MOVES[move]]
    w = max(len(r) for r in rows)
    glove = mix(colour, WHITE, 0.35)
    pal = {"c": colour, "h": glove, "l": mix(colour, WHITE, 0.72), "s": scale(glove, 0.5)}
    px = np.zeros((len(rows), w, 3), np.float32)
    mask = np.zeros((len(rows), w), bool)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in pal:
                xx = w - 1 - x if flip else x
                px[y, xx] = pal[ch]
                mask[y, xx] = True
    return px, mask


def draw_mini(f: Frame, x: int, y: int, rows: tuple[str, ...], col: RGB, zoom: int = 1) -> None:
    for yy, row in enumerate(rows):
        for xx, ch in enumerate(row):
            if ch == "#":
                if zoom == 1:
                    f.set(x + xx, y + yy, col)
                else:
                    f.rect(x + xx * zoom, y + yy * zoom, zoom, zoom, col)


def cut(text: str, width: int) -> str:
    """Hard-cut a name to `width` px (an ellipsis would eat half of a short name)."""
    while text and measure(text) > width:
        text = text[:-1].rstrip()
    return text


def word_width(text: str) -> int:
    """Tiny-font width with a 1 px wide I (so SCISSORS fits inside the 1 px margins)."""
    return sum(1 if ch == "I" else measure(ch) for ch in text) + len(text) - 1


def draw_word(f: Frame, y: int, text: str, col: RGB, cx: int = 16) -> None:
    x = cx - word_width(text) // 2
    for ch in text:
        if ch == "I":
            f.vline(x, y, 5, col)
            x += 2
        else:
            f.text(x, y, ch, col)
            x += measure(ch) + 1


# ------------------------------------------------------------------ tournaments
class Tournament:
    """A knockout bracket (byes for odd fields) or a round robin over `entrants` (seats)."""

    def __init__(self, fmt: str, entrants: list[int]) -> None:
        self.fmt = fmt if fmt in ("knockout", "robin") else "knockout"
        order = list(entrants)
        _SR.shuffle(order)  # fair seeding
        self.entrants = order
        self.rounds: list[list[list[int | None]]] = []  # knockout: rounds of [a, b, winner]
        self.games: list[list[int | None]] = []  # robin: [a, b, winner, rounds a, rounds b]
        if self.fmt == "knockout":
            n = len(order)
            size = 2
            while size < n:
                size *= 2
            self.size = size
            half = size // 2
            byes = size - n
            spots = {round((j + 0.5) * half / byes - 0.5) for j in range(byes)} if byes else set()
            it = iter(order)
            first: list[list[int | None]] = []
            for i in range(half):
                a = next(it)
                if i in spots:
                    first.append([a, None, a])  # a bye: straight through
                else:
                    first.append([a, next(it), None])
            self.rounds.append(first)
            self._advance()
        else:
            ring: list[int | None] = list(order) + ([None] if len(order) % 2 else [])
            m = len(ring)
            for _ in range(m - 1):  # circle method: everyone plays once per round
                for i in range(m // 2):
                    a, b = ring[i], ring[m - 1 - i]
                    if a is not None and b is not None:
                        self.games.append([a, b, None, 0, 0])
                ring = [ring[0], ring[-1], *ring[1:-1]]

    def _advance(self) -> None:
        while True:
            last = self.rounds[-1]
            if len(last) == 1 or any(g[2] is None for g in last):
                return
            winners = [g[2] for g in last]
            self.rounds.append([[winners[i], winners[i + 1], None] for i in range(0, len(winners), 2)])

    def next_match(self) -> tuple[int, int] | None:
        if self.fmt == "knockout":
            for g in self.rounds[-1]:
                if g[2] is None and g[0] is not None and g[1] is not None:
                    return int(g[0]), int(g[1])
            return None
        for g in self.games:
            if g[2] is None:
                return int(g[0]), int(g[1])  # type: ignore[arg-type]
        return None

    def record(self, a: int, b: int, winner: int, ra: int = 0, rb: int = 0) -> None:
        if self.fmt == "knockout":
            for g in self.rounds[-1]:
                if g[2] is None and {g[0], g[1]} == {a, b}:
                    g[2] = winner
                    break
            self._advance()
            return
        for g in self.games:
            if g[2] is None and {g[0], g[1]} == {a, b}:
                g[2] = winner
                g[3], g[4] = (ra, rb) if g[0] == a else (rb, ra)
                return

    def standings(self) -> list[dict[str, int]]:
        """Robin table, best first: match wins, then round difference, then rounds won."""
        t = {s: {"seat": s, "wins": 0, "played": 0, "diff": 0, "rounds": 0} for s in self.entrants}
        for a, b, w, ra, rb in self.games:
            if w is None:
                continue
            for s, mine, theirs in ((a, ra, rb), (b, rb, ra)):
                row = t[int(s)]  # type: ignore[arg-type]
                row["played"] += 1
                row["wins"] += int(w == s)
                row["diff"] += int(mine or 0) - int(theirs or 0)
                row["rounds"] += int(mine or 0)
        return sorted(t.values(), key=lambda r: (-r["wins"], -r["diff"], -r["rounds"]))

    def champion(self) -> int | None:
        if self.fmt == "knockout":
            last = self.rounds[-1]
            return int(last[0][2]) if len(last) == 1 and last[0][2] is not None else None
        if any(g[2] is None for g in self.games):
            return None
        return self.standings()[0]["seat"]

    def alive(self, seat: int) -> bool:
        if self.fmt != "knockout":
            return True
        for rnd in self.rounds:
            for a, b, w in rnd:
                if w is not None and seat in (a, b) and w != seat:
                    return False
        return True

    def done_count(self) -> tuple[int, int]:
        if self.fmt == "knockout":
            real = [g for rnd in self.rounds for g in rnd if g[1] is not None]
            total = len(self.entrants) - 1
            return sum(1 for g in real if g[2] is not None), total
        return sum(1 for g in self.games if g[2] is not None), len(self.games)

    def snapshot(self) -> dict[str, Any]:
        if self.fmt == "knockout":
            return {
                "format": "knockout",
                "size": self.size,
                "rounds": [[list(g) for g in r] for r in self.rounds],
            }
        return {
            "format": "robin",
            "games": [list(g[:3]) for g in self.games],
            "table": self.standings(),
        }


# ------------------------------------------------------------------ settings, themes
class RPSSettings(GameSettings):
    best_of: str = Choice(
        "3",
        {"1": "Best of 1", "3": "Best of 3", "5": "Best of 5", "7": "Best of 7"},
        title="Match length",
        group="Game",
    )
    round_timer: int = Field(
        8,
        ge=3,
        le=30,
        title="Seconds to pick",
        description="Anyone who hasn't picked when time runs out gets a random hand",
        json_schema_extra={"group": "Game"},
    )
    ai_style: str = Choice(
        "random",
        {
            "random": "Random (truly uniform — unbeatable in the long run)",
            "pattern": "Pattern hunter (punishes your habits)",
            "cheeky": "Cheeky (gives away tells… mostly honest)",
        },
        title="AI style",
        group="Game",
    )
    reveal: str = Choice(
        "shoot",
        {"shoot": "Rock, paper, scissors, shoot!", "count": "3-2-1 countdown", "instant": "Instant"},
        title="Reveal",
        group="Game",
    )


THEMES_RPS: dict[str, Theme] = {
    "arena": Theme(
        p=(0, 200, 255),
        e=(255, 60, 90),
        x=(255, 214, 0),
        w=(70, 60, 110),
        hud=(235, 235, 245),
        bg=(3, 2, 8),
        r=(
            (255, 214, 0),
            (255, 60, 90),
            (0, 200, 255),
            (80, 255, 120),
            (255, 120, 20),
            (150, 80, 255),
            WHITE,
        ),
    ),
    "party": Theme(
        p=(255, 45, 160),
        e=(0, 230, 200),
        x=(255, 240, 90),
        w=(120, 40, 140),
        hud=(255, 225, 245),
        bg=(8, 0, 10),
        r=(
            (255, 45, 160),
            (255, 240, 90),
            (0, 230, 200),
            (150, 80, 255),
            (255, 120, 20),
            (80, 255, 120),
            WHITE,
        ),
    ),
}


@register
class RockPaperScissors(GameApp):
    id = "rps"
    name = "Rock Paper Scissors"
    description = (
        "The party classic, 1 v 1: two pixel hands pump ROCK… PAPER… SCISSORS… SHOOT! Play the AI, a friend "
        "(keyboard + phone, or two phones) or run a 3–8 player tournament — friends join by scanning the panel's QR "
        "code and pick their hand on big buttons. Plays AI vs AI when idle."
    )
    icon = "hand"
    Settings = RPSSettings
    max_players = 8
    controls = ("rps", "dpad", "gamepad")  # "rps" = the phone's three big hand buttons
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("cpu", "You vs AI", 1, 1, "solo", "Arrows: left rock, up paper, right scissors"),
        Mode("pvp", "1 v 1", 2, 2, "ffa", "Keyboard + phone, or two phones"),
        Mode("tour", "Tournament", 3, 8, "ffa", "Knockout or round robin"),
        Mode("demo", "AI vs AI", 1, 1, "solo"),
    )
    maps: ClassVar[dict[str, str]] = {"knockout": "Knockout", "robin": "Round robin"}
    game_themes: ClassVar[dict[str, Theme]] = THEMES_RPS
    game_theme_labels: ClassVar[dict[str, str]] = {"arena": "Arena", "party": "Party"}
    fly_keys: ClassVar[dict[str, str]] = {"a": "", "b": ""}  # the fly picks with its steering neurons only

    # ------------------------------------------------------------------ setup
    def new_game(self) -> None:
        self.hist: dict[int, list[int]] = {}  # seat -> picks in finished rounds (what "pattern" learns from)
        self.tour: Tournament | None = None
        self.match_kind = self._kind()
        self.match_no = 0
        self.champ_seat: int | None = None
        self.pair = (1, 2)
        self.wins = {1: 0, 2: 0}
        self.round_no = 0
        self.phase = "vs"
        self.phase_t = 0.0
        self.locked: dict[int, int] = {}
        self.by_ai: set[int] = set()
        self.timed_out: set[int] = set()
        self.ai_pick: dict[int, int] = {}
        self.think: dict[int, float] = {}
        self.tell: dict[int, int] = {}
        self.fly_target = ROCK
        self.last: dict[str, Any] = {}
        self.lock_flash: dict[int, float] = {}
        self.anim = 0.0
        self.go_at: float | None = None
        if self.match_kind == "tour":
            self.tour = Tournament(self.map_id, sorted(self.roster))
            self._next_tour_match()
        elif self.match_kind == "attract":
            self._start_match(1, 2)
        else:  # the intro screen shows who plays, so the first round starts straight away
            seats = sorted(self.roster)
            pair = (seats[0], seats[1]) if len(seats) >= 2 else (seats[0] if seats else 1, 2)
            self._start_match(*pair, vs=False)

    def _kind(self) -> str:
        if not self.roster or self.flow == "attract":
            return "attract"
        return self.play_mode.id

    @property
    def first_to(self) -> int:
        try:
            n = int(self.settings.best_of)
        except (TypeError, ValueError):
            n = 3
        return n // 2 + 1

    def _start_match(self, a: int, b: int, vs: bool = True) -> None:
        self.pair = (a, b)
        self.wins = {a: 0, b: 0}
        self.round_no = 0
        self.match_no += 1
        self.champ_seat = None
        self.last = {}
        if vs:
            self._phase("vs")
        else:
            self._start_pick()

    def _phase(self, name: str) -> None:
        self.phase, self.phase_t = name, 0.0

    def _start_pick(self) -> None:
        """A new round. Every AI pick is fixed *now*, from finished rounds only, before anyone's input arrives."""
        self.round_no += 1
        self._phase("pick")
        self.locked, self.by_ai, self.timed_out, self.lock_flash = {}, set(), set(), {}
        self.go_at = None
        a, b = self.pair
        self.ai_pick = {a: self._ai_choose(a, b), b: self._ai_choose(b, a)}
        self.think = {s: _SR.uniform(0.6, 1.9) for s in self.pair}
        self.tell = {}
        if self.settings.ai_style == "cheeky":
            for s in self.pair:  # a tell: the truth two times in three, otherwise a bluff
                m = self.ai_pick[s]
                self.tell[s] = m if _SR.random() < 2 / 3 else (m + _SR.choice((1, 2))) % 3
        # the fruit fly smells the hand that beats the opponent's tell, else a fair random hand
        self.fly_target = counter(self.tell[b]) if b in self.tell else _SR.randrange(3)

    def _ai_choose(self, seat: int, opp: int) -> int:
        """An AI pick for `seat`. Only the opponent's *finished* rounds are visible here (never this round)."""
        if self.settings.ai_style == "pattern":
            h = self.hist.get(opp, [])[-40:]
            if len(h) >= 3:
                last = h[-1]
                trans = [0.0, 0.0, 0.0]
                for i in range(len(h) - 1):
                    if h[i] == last:
                        trans[h[i + 1]] += 1.0
                freq = [0.0, 0.0, 0.0]
                for m in h[-12:]:
                    freq[m] += 1.0
                score = [2 * trans[m] + 0.5 * freq[m] for m in range(3)]
                tot = sum(score)
                best = max(range(3), key=lambda m: score[m])
                if tot > 0 and score[best] / tot > 0.45 and _SR.random() < 0.85:
                    return counter(best)
        return _SR.randrange(3)

    # ------------------------------------------------------------------ people
    def seat_colour(self, seat: int) -> RGB:
        s = self.seats.get(seat)
        if s and s.get("color"):
            return s["color"]  # type: ignore[no-any-return]
        if seat in SEAT_RGB:
            return SEAT_RGB[seat]
        used = {tuple(v["color"]) for v in self.seats.values() if v.get("color")}
        free = [c for c in EXTRA_RGB if c not in used] or list(EXTRA_RGB)
        return free[(seat - 5) % len(free)]

    def _human(self, seat: int) -> bool:
        if self.flow == "attract" or not self.roster:
            return seat == 1 and self.human
        return self.is_human(seat)

    def name_of(self, seat: int) -> str:
        if seat in self.seats and not self.seats[seat].get("local") and self._human(seat):
            return self.seat_name(seat).upper()
        if seat == 1 and self._human(1):
            if self._player_label() == "fly":
                return "FLY"
            people = sum(1 for s in self.pair if self._human(s))
            return "YOU" if people <= 1 and self.match_kind != "tour" else "P1"
        if seat in self.seats and self._human(seat):
            return f"P{seat}"
        return BOT_NAMES[(seat - 1) % len(BOT_NAMES)]

    def avatar_of(self, seat: int) -> str:
        s = self.seats.get(seat)
        if s and s.get("avatar") and self._human(seat):
            return str(s["avatar"])
        if seat == 1 and self._human(1):
            return "knight"
        return "bot"

    # ------------------------------------------------------------------ input
    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "input":
            k = str(payload.get("key", "")).lower()
            if k in KEY_ALIAS:
                payload = {**payload, "key": KEY_ALIAS[k]}
        return await super().action(name, payload)

    def key_p(self, k: str, player: int) -> None:
        if self.phase == "pick" and player in self.pair:
            if self.match_kind == "attract" and player != 1:
                return  # the demo: only the host can grab the left hand; phones watch until a game starts
            mine = self.locked.get(player)
            if mine is not None and player not in self.by_ai:
                return  # locked in: final
            if mine is not None and not (self.match_kind == "attract" and player == 1):
                return
            mv = _SR.randrange(3) if k == "down" else KEY_MOVE.get(k)
            if mv is not None:
                self.by_ai.discard(player)
                self._lock(player, mv)
        elif k == "a" and self.phase in ("vs", "bracket", "champ") and self.phase_t > 0.8:
            self.phase_t = 99.0  # skip ahead

    def _lock(self, seat: int, mv: int) -> None:
        self.locked[seat] = mv
        self.lock_flash[seat] = 0.0

    # ------------------------------------------------------------------ simulation
    def update(self, dt: float) -> None:
        self.anim += dt
        self.phase_t += dt
        for s in list(self.lock_flash):
            self.lock_flash[s] += dt
        ph = self.phase
        if ph == "vs" and self.phase_t > 2.2:
            self._start_pick()
        elif ph == "bracket" and self.phase_t > 4.0:
            self._phase("vs")
        elif ph == "pick":
            for s in self.pair:
                if s not in self.locked and not self._human(s) and self.phase_t >= self.think[s]:
                    self._lock(s, self.ai_pick[s])
                    self.by_ai.add(s)
            if len(self.locked) == 2:
                if self.go_at is None:
                    self.go_at = self.phase_t + 0.4  # a beat to see both locks
                elif self.phase_t >= self.go_at:
                    self._phase("pump")
            elif self.phase_t >= self.settings.round_timer:
                for s in self.pair:  # too slow: fate picks for you
                    if s not in self.locked:
                        self._lock(s, _SR.randrange(3))
                        self.timed_out.add(s)
                self._phase("pump")
        elif ph == "pump" and self.phase_t >= self._pump_len():
            self._reveal()
        elif ph == "reveal" and self.phase_t >= 2.1:
            if self.champ_seat is not None:
                self._phase("champ")
            else:
                self._start_pick()
        elif ph == "champ":
            if self.settings.effects != "minimal" and self.rng.random() < 0.6:
                col = self.seat_colour(self.champ_seat or 1) if self.rng.random() < 0.6 else self.theme.x
                self.fx.emit(
                    self.rng.uniform(1, 30), 0, self.rng.uniform(-3, 3), self.rng.uniform(8, 16), col, 2.4
                )
            if self.phase_t > 3.2:
                self._after_match()

    def _pump_len(self) -> float:
        return {"shoot": 3 * PUMP_BEAT, "count": 1.5, "instant": 0.15}.get(
            self.settings.reveal, 3 * PUMP_BEAT
        )

    def _reveal(self) -> None:
        a, b = self.pair
        ma, mb = self.locked[a], self.locked[b]
        r = judge(ma, mb)
        self.hist.setdefault(a, []).append(ma)
        self.hist.setdefault(b, []).append(mb)
        winner = a if r == 1 else b if r == 2 else None
        self.last = {"a": ma, "b": mb, "winner": winner}
        self._phase("reveal")
        if winner is None:
            return
        self.wins[winner] += 1
        loser = b if winner == a else a
        if winner == 1 and self._human(1) and self.match_kind in ("cpu", "attract"):
            self.score += 1
        if self._human(loser) and not self._human(winner):
            self.damage(0.5)
        if self.settings.effects != "minimal":
            x = 7 if winner == a else 24
            self.fx.burst(self.rng, x, HY, mix(self.seat_colour(winner), WHITE, 0.3), 14, 16, 0.7)
        if self.wins[winner] >= self.first_to:
            self.champ_seat = winner

    def _after_match(self) -> None:
        a, b = self.pair
        w = self.champ_seat or a
        if self.match_kind == "attract":
            self._start_match(1, 2)
        elif self.match_kind == "tour" and self.tour is not None:
            self.tour.record(a, b, w, self.wins[a], self.wins[b])
            self._next_tour_match()
        else:
            self.result(winner_seat=w, scores=dict(self.wins))

    def _next_tour_match(self) -> None:
        """Simulate AI-only matches straight away (fairly, the same AI); stop at the next match with a person."""
        t = self.tour
        assert t is not None
        while True:
            nxt = t.next_match()
            if nxt is None:
                champ = t.champion()
                self.champ_seat = champ
                table = t.standings() if t.fmt == "robin" else []
                scores = {r["seat"]: r["wins"] for r in table} if table else {}
                self.result(winner_seat=champ, scores=scores)
                return
            a, b = nxt
            if self._human(a) or self._human(b):
                self.pair = nxt
                self.wins = {a: 0, b: 0}
                self.match_no += 1
                self.round_no = 0
                self.champ_seat = None
                self.last = {}
                self._phase("bracket")
                return
            ra, rb = self._sim_match(a, b)
            t.record(a, b, a if ra > rb else b, ra, rb)

    def _sim_match(self, a: int, b: int) -> tuple[int, int]:
        wa = wb = 0
        for _ in range(300):
            ma, mb = self._ai_choose(a, b), self._ai_choose(b, a)  # both fixed before either is played
            self.hist.setdefault(a, []).append(ma)
            self.hist.setdefault(b, []).append(mb)
            r = judge(ma, mb)
            wa += r == 1
            wb += r == 2
            if max(wa, wb) >= self.first_to:
                return wa, wb
        return (wa + 1, wb) if _SR.random() < 0.5 else (wa, wb + 1)

    def begin(self) -> None:
        """Seat the match: 1 v 1 pairs two phones when two have joined (the host watches); a tournament seats
        every person and fills up with AI; AI vs AI hands every seat to the AI."""
        mid = self.play_mode.id
        self.flow = "home"  # leaving the demo (the studio's "start" can come straight from attract)
        if mid == "tour":
            people = [1, *sorted(s for s in self.seats if s <= self.max_players)]
            n = max(3, min(8, max(int(self.sel.get("players", 3)), len(people))))
            self.sel["players"] = n
            seats = people[:n]
            free = [s for s in range(1, 9) if s not in seats]
            while len(seats) < n:
                seats.append(free.pop(0))
            self.roster = {s: {"team": None, "human": s in people, "ready": False} for s in sorted(seats)}
            self.human_at = self._clock()
            self._start_intro()
            return
        super().begin()
        if mid == "demo":
            for r in self.roster.values():
                r["human"] = False
        elif mid == "pvp":
            phones = [s for s in sorted(self.seats) if not self.seats[s].get("local")]
            locals_ = [s for s in sorted(self.seats) if self.seats[s].get("local")]
            if len(phones) >= 2:  # two phones: they play, the host watches
                a, b = phones[0], phones[1]
            else:
                a, b = 1, (phones or locals_ or [2])[0]
            self.roster = {
                s: {"team": None, "human": s in self.seats or s == 1, "ready": False} for s in (a, b)
            }
        self._start_intro()

    # ------------------------------------------------------------------ the fruit-fly pilot
    def pilot_anchor(self) -> tuple[float, float] | None:
        return (7.0, float(HY))

    def fly_lure(self) -> list[tuple[float, float, float]]:
        """Sugar on the side of the hand to throw: left = rock, above = paper, right = scissors."""
        if self.phase != "pick" or 1 not in self.pair or (1 in self.locked and 1 not in self.by_ai):
            return []
        ax, ay = 7.0, float(HY)
        dx, dy = {ROCK: (-9.0, 0.0), PAPER: (0.0, -9.0), SCISSORS: (9.0, 0.0)}[self.fly_target]
        return [(ax + dx, ay + dy, 1.0)]

    # ------------------------------------------------------------------ drawing
    def _hand(
        self, f: Frame, seat: int, move: int, right: bool, dx: int, dy: int, k: float, glow: float
    ) -> None:
        px, mask = hand_sprite(move, self.seat_colour(seat), right)
        arr = px
        if glow > 0:
            arr = arr + (255.0 - arr) * glow
        if k != 1.0:
            arr = arr * k
        h, w = mask.shape
        x = (32 - w - dx) if right else dx
        y = HY - h // 2 + dy
        f.blit(np.clip(arr, 0, 255).astype(np.uint8), x, y, mask)

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        ph = self.phase
        if ph == "bracket":
            self._draw_bracket(f, now)
        elif ph == "vs":
            self._draw_vs(f, self.pair, self.phase_t)
        elif ph == "champ":
            self._draw_champ(f, now)
        else:
            self._draw_table(f, now)

    def _pips(self, f: Frame) -> None:
        a, b = self.pair
        n = self.first_to
        for i in range(n):
            for seat, x in ((a, 1 + 3 * i), (b, 29 - 3 * i)):
                col = self.seat_colour(seat)
                filled = i < self.wins.get(seat, 0)
                fresh = filled and i == self.wins[seat] - 1 and self.phase == "reveal" and self.phase_t < 0.9
                if fresh and int(self.phase_t * 8) % 2 == 0:
                    col = mix(col, WHITE, 0.5)
                f.rect(x, 1, 2, 2, col if filled else scale(col, 0.22))
        label = f"R{self.round_no}"
        if measure(label) <= 28 - 6 * n:
            f.text_center(1, label, scale(self.theme.hud, 0.45))

    def _draw_table(self, f: Frame, now: float) -> None:
        th = self.theme
        a, b = self.pair
        ph = self.phase
        self._pips(f)
        fx_on = self.settings.effects
        if ph == "pick":
            for seat, right in ((a, False), (b, True)):
                locked = seat in self.locked
                breathe = (
                    0 if locked else -int((math.sin(self.anim * 3 + (2 if right else 0)) + 1) * 0.5 + 0.5)
                )
                fl = self.lock_flash.get(seat, 9.0)
                glow = 0.35 * max(0.0, 1 - fl / 0.3) if fx_on != "minimal" else 0.0
                self._hand(f, seat, ROCK, right, 0, breathe, 1.0 if locked else 0.5, glow)
                cx = 24 if right else 7
                col = self.seat_colour(seat)
                if seat in self.tell and not self._human(
                    seat
                ):  # a cheeky AI's tell (its hand shows the lock)
                    if int(self.anim * 3) % 4:
                        draw_mini(f, cx - 2, 4, MINI[self.tell[seat]], mix(col, WHITE, 0.5))
                elif locked:
                    draw_mini(f, cx - 2, 5, TICK, mix(col, WHITE, 0.4))
                else:
                    for i in range(3):
                        on = int(self.anim * 4) % 4 > i
                        f.set(cx - 2 + 2 * i, 7, mix(col, WHITE, 0.3) if on else scale(col, 0.25))
            # names under the hands, timer bar along the bottom edge
            na, nb = cut(self.name_of(a), 14), cut(self.name_of(b), 14)
            f.text(1, 25, na, self.seat_colour(a))
            f.text_right(30, 25, nb, self.seat_colour(b))
            left = max(0.0, 1 - self.phase_t / max(1, self.settings.round_timer))
            if any(self._human(s) for s in self.pair):
                w = round(30 * left)
                col = (80, 255, 120) if left > 0.5 else (255, 200, 0) if left > 0.25 else (255, 60, 60)
                if w:
                    f.hline(16 - (w + 1) // 2, 31, w, col)
        elif ph == "pump":
            t = self.phase_t
            style = self.settings.reveal
            if style == "shoot":
                beat = min(2, int(t / PUMP_BEAT))
                frac = min(1.0, t / PUMP_BEAT - beat)
                dy = -round(3 * math.sin(math.pi * frac))
                for seat, right in ((a, False), (b, True)):
                    self._hand(f, seat, ROCK, right, 0, dy, 1.0, 0.0)
                draw_word(f, 25, WORDS[beat], th.hud if beat < 2 else mix(th.hud, th.x, 0.5))
            elif style == "count":
                n = 3 - min(2, int(t / 0.5))
                jig = 1 if int(t * 16) % 2 else 0
                for seat, right in ((a, False), (b, True)):
                    self._hand(f, seat, ROCK, right, jig if fx_on == "full" else 0, 0, 1.0, 0.0)
                f.text_center(24, str(n), th.x, font="small")
            else:
                for seat, right in ((a, False), (b, True)):
                    self._hand(f, seat, ROCK, right, 0, 0, 1.0, 0.0)
                draw_word(f, 25, "SHOOT!", th.x)
        elif ph == "reveal":
            t = self.phase_t
            w = self.last.get("winner")
            thrust = 1 if t < 0.15 else 0
            for seat, right, mv in ((a, False, self.last["a"]), (b, True, self.last["b"])):
                k, glow, dx = 1.0, 0.0, thrust
                if t > 0.45:
                    if w is None:
                        k = 0.75
                    elif seat == w:
                        if fx_on == "full" and t < 1.5:
                            glow = 0.25 + 0.2 * math.sin(t * 18)
                        elif fx_on == "calm":
                            glow = 0.15
                    else:
                        k = 0.35
                        if fx_on == "full" and t < 0.8:
                            dx += 1 if int(t * 30) % 2 else -1
                self._hand(f, seat, mv, right, max(0, dx), 0, k, glow)
            if t < 0.45 and self.settings.reveal != "count":
                draw_word(f, 25, "SHOOT!", th.x)
            elif w is None:
                draw_word(f, 25, "DRAW", th.x)
            else:
                cx = 7 if w == a else 24  # one word under the winning hand; the losing hand is dimmed
                x = max(1, min(31 - measure("WIN"), cx - measure("WIN") // 2))
                f.text(x, 25, "WIN", mix(self.seat_colour(w), WHITE, 0.25))
                if fx_on == "full" and 0.45 < t < 1.2:  # the winner's colour runs round the edge, fading
                    al = 0.55 * (1 - (t - 0.45) / 0.75)
                    col = self.seat_colour(w)
                    for x in range(32):
                        f.blend(x, 0, col, al)
                    for y in range(1, 32):
                        f.blend(0, y, col, al)
                        f.blend(31, y, col, al)

    def _draw_vs(self, f: Frame, pair: tuple[int, int], t: float, countdown: str = "") -> None:
        th = self.theme
        a, b = pair
        ca, cb = self.seat_colour(a), self.seat_colour(b)
        f.rect(0, 0, 32, 12, scale(ca, 0.1))
        f.rect(0, 20, 32, 12, scale(cb, 0.1))
        draw_avatar(f, 2, 2, self.avatar_of(a), ca)
        f.text(12, 4, fit(self.name_of(a), 19), ca)
        draw_avatar(f, 22, 22, self.avatar_of(b), cb)
        nb = fit(self.name_of(b), 19)
        f.text(20 - measure(nb), 24, nb, cb)
        if countdown:
            f.text_center(13, countdown, th.x, font="small")
        else:  # VS lands with a short flash, then settles
            f.text_center(13, "VS", mix(th.x, WHITE, 0.5) if t < 0.25 else th.x, font="small")
            if self.match_kind == "tour" and self.tour is not None:
                stage = self._stage_label()
                if stage:
                    f.text(1, 14, stage[:3], scale(th.hud, 0.5))

    def _stage_label(self) -> str:
        t = self.tour
        if t is None:
            return ""
        if t.fmt == "knockout":
            left = len(t.rounds[-1])
            return "FIN" if left == 1 else "SF" if left == 2 else "QF" if left == 4 else ""
        done, total = t.done_count()
        return f"{done + 1}/{total}" if measure(f"{done + 1}/{total}") <= 9 else ""

    def _draw_champ(self, f: Frame, now: float) -> None:
        w = self.champ_seat or self.pair[0]
        col = self.seat_colour(w)
        bounce = -abs(round(2 * math.sin(self.phase_t * 5)))
        draw_avatar(f, 8, 1 + bounce + 1, self.avatar_of(w), col, zoom=2)
        name = self.name_of(w)
        if measure(name, "small") <= 30:
            f.text_center(19, name, col, font="small")
        else:
            f.text_center(20, fit(name, 30), col)
        a, b = self.pair
        sa, sb = str(self.wins[a]), str(self.wins[b])
        x = 16 - (measure(sa) + measure("-") + measure(sb) + 2) // 2
        x = f.text(x, 27, sa, self.seat_colour(a)) + 1
        x = f.text(x, 27, "-", scale(self.theme.hud, 0.5)) + 1
        f.text(x, 27, sb, self.seat_colour(b))

    def _draw_bracket(self, f: Frame, now: float) -> None:
        t = self.tour
        if t is None:
            return
        blink = int(self.phase_t * 4) % 2 == 0
        if t.fmt == "knockout":
            self._draw_knockout(f, t, blink)
        else:
            self._draw_robin(f, t, blink)

    def _draw_knockout(self, f: Frame, t: Tournament, blink: bool) -> None:
        size = t.size
        levels = int(math.log2(size)) + 1
        xs = [round(1 + i * (27 / (levels - 1))) for i in range(levels)]
        line = (64, 64, 84)

        def occupant(level: int, i: int) -> int | None:
            if level == 0:
                g = t.rounds[0][i // 2]
                return g[i % 2]
            if level - 1 < len(t.rounds):
                g = t.rounds[level - 1][i]
                return g[2]
            return None

        def yc(level: int, i: int) -> int:
            sp = 32 / (size >> level)
            return int(sp * (i + 0.5))

        cur = set(self.pair)
        for lv in range(levels):
            for i in range(size >> lv):
                y = yc(lv, i)
                occ = occupant(lv, i)
                if lv < levels - 1:  # connector to the parent slot
                    py = yc(lv + 1, i // 2)
                    mx = (xs[lv] + 3 + xs[lv + 1]) // 2
                    par = occupant(lv + 1, i // 2)
                    c = scale(self.seat_colour(par), 0.6) if par is not None and par == occ else line
                    if occ is not None or lv > 0:
                        f.hline(xs[lv] + 3, y, mx - xs[lv] - 3, c)
                        f.vline(mx, min(y, py), abs(py - y) + 1, c)
                        f.hline(mx, py, xs[lv + 1] - mx, c)
                if occ is None:
                    if lv == 0:
                        continue  # a bye's empty slot
                    f.rect(xs[lv], y - 1, 3, 3, line, fill=False)
                    continue
                col = self.seat_colour(occ)
                if not t.alive(occ) and lv < levels - 1:
                    col = scale(col, 0.3)
                if occ in cur and lv == len(t.rounds) - 1 and not blink:
                    col = mix(col, WHITE, 0.6)
                if lv == levels - 1:
                    col = mix(col, (255, 214, 0), 0.3)
                f.rect(xs[lv], y - 1, 3, 3, col)

    def _draw_robin(self, f: Frame, t: Tournament, blink: bool) -> None:
        table = t.standings()
        n = len(table)
        cur = set(self.pair)
        if n <= 4:
            for i, row in enumerate(table):
                s = row["seat"]
                y = 1 + i * 8
                col = self.seat_colour(s)
                if s in cur and not blink:
                    col = mix(col, WHITE, 0.5)
                f.text(1, y, fit(self.name_of(s), 22), col)
                f.text_right(30, y, str(row["wins"]), WHITE if i == 0 else scale(WHITE, 0.6))
                f.hline(1, y + 6, 29, scale(col, 0.25))
            return
        h = 32 // n
        for i, row in enumerate(table):
            s = row["seat"]
            y = i * h + (h - 3) // 2
            col = self.seat_colour(s)
            if s in cur and not blink:
                col = mix(col, WHITE, 0.6)
            f.rect(1, y, 3, 3, col)
            for k in range(row["wins"]):
                f.rect(6 + k * 3, y, 2, 3, scale(col, 0.75))
            for k in range(row["wins"], row["played"]):
                f.rect(6 + k * 3, y + 1, 2, 1, scale(col, 0.3))

    # ------------------------------------------------------------------ flow screens
    def draw_intro(self, f: Frame, now: float) -> None:
        th = self.theme
        el = now - self.flow_t
        n = 3 - int(el / 0.6)
        cd = str(n) if n > 0 else "GO"
        if self.match_kind == "tour" and self.tour is not None:
            f.clear(th.bg)
            label = "BRACKET" if self.tour.fmt == "knockout" else "LEAGUE"
            f.text_center(2, label, th.hud)
            f.hline(2, 9, 28, scale(th.p, 0.5))
            seats = self.tour.entrants
            x0 = 16 - (len(seats) * 4 - 1) // 2
            for i, s in enumerate(seats):
                col = self.seat_colour(s)
                f.rect(x0 + i * 4, 13, 3, 3, col if self._human(s) else scale(col, 0.45))
            f.text_center(22, cd, th.x if n > 0 else (80, 255, 120), font="small")
            return
        f.clear(th.bg)
        self._draw_vs(f, self.pair, el, countdown=cd)

    def draw_outro(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        o = self.outcome or {}
        w = o.get("seat") or self.pair[0]
        col = self.seat_colour(w)
        el = now - self.flow_t
        if self.match_kind == "tour":
            gold = (255, 200, 0)
            draw_mini(f, 5, 1, TROPHY, gold, zoom=2)
            f.rect(9, 10, 1, 1, mix(gold, WHITE, 0.6))
            name = self.name_of(w)
            if measure(name, "small") <= 30:
                f.text_center(19, name, col, font="small")
            else:
                f.text_center(20, fit(name, 30), col)
            f.text_center(26, "CHAMP" if int(el * 1.5) % 2 == 0 else "A AGAIN", th.x)
            return
        draw_avatar(f, 8, 1, self.avatar_of(w), col, zoom=2)
        you = self.match_kind == "cpu"
        if you:
            txt, c = ("YOU WIN", th.x) if w == 1 else ("YOU LOSE", scale(th.hud, 0.7))
            f.text_center(19, txt, c)
        else:
            name = self.name_of(w)
            f.text_center(19, fit(name, 30), col)
        a, b = self.pair
        if int(el * 1.5) % 2 == 0:
            sa, sb = str(self.wins.get(a, 0)), str(self.wins.get(b, 0))
            x = 16 - (measure(sa) + measure("-") + measure(sb) + 2) // 2
            x = f.text(x, 26, sa, self.seat_colour(a)) + 1
            x = f.text(x, 26, "-", scale(th.hud, 0.5)) + 1
            f.text(x, 26, sb, self.seat_colour(b))
        else:
            f.text_center(26, "A AGAIN", scale(th.hud, 0.55))

    def _menu_rows(self) -> list[str]:
        rows = super()._menu_rows()
        if self.play_mode.id != "tour" and "map" in rows:
            rows.remove("map")  # the bracket format only matters for tournaments
        if self.play_mode.min_players == self.play_mode.max_players and "players" in rows:
            rows.remove("players")
        return rows

    # ------------------------------------------------------------------ status (phones, studio, agents)
    def best_candidate(self) -> int:
        return self.score if self._human(1) else 0

    def status(self) -> dict[str, Any]:
        st = super().status()
        a, b = self.pair
        reveal = self.phase in ("reveal", "champ") and bool(self.last)
        rps: dict[str, Any] = {
            "phase": self.phase,
            "kind": self.match_kind,
            "match": self.match_no,
            "round": self.round_no,
            "pair": [a, b],
            "wins": {str(a): self.wins.get(a, 0), str(b): self.wins.get(b, 0)},
            "first_to": self.first_to,
            "locked": sorted(self.locked) if self.phase in ("pick", "pump") else [a, b] if reveal else [],
            "players": {
                str(s): {"name": self.name_of(s), "color": _hex(self.seat_colour(s)), "human": self._human(s)}
                for s in self._everyone()
            },
            "keys": {"rock": "left", "paper": "up", "scissors": "right", "random": "down"},
            "art": ART,
        }
        if self.phase == "pick":
            rps["left"] = max(0, math.ceil(self.settings.round_timer - self.phase_t))
            rps["timer"] = int(self.settings.round_timer)
        if self.tell:
            rps["tell"] = {str(s): MOVES[m] for s, m in self.tell.items() if not self._human(s)}
        if reveal:  # picks are secret until both hands are shown
            rps["picks"] = {str(a): MOVES[self.last["a"]], str(b): MOVES[self.last["b"]]}
            rps["winner"] = self.last.get("winner") or 0
        if (self.champ_seat is not None and self.phase == "champ") or self.flow == "outro":
            rps["champion"] = self.champ_seat or (self.outcome or {}).get("seat")
        if self.tour is not None:
            rps["tour"] = self.tour.snapshot()
        st["rps"] = rps
        return st

    def _everyone(self) -> list[int]:
        if self.tour is not None:
            return list(self.tour.entrants)
        return list(self.pair)
