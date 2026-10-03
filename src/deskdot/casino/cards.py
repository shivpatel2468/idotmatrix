"""Playing cards for the casino: cards, decks, shoes, hand rankings and point values.

* `Card` — rank 2..14 (11 J, 12 Q, 13 K, 14 A) and suit ``S H D C``; its code is ``"AS"``, ``"TD"``, ``"9H"``.
* `new_deck()` / `Shoe` — a shoe of n decks shuffled with the round's provably fair `Rng` (Fisher–Yates), with a
  cut card (blackjack/baccarat reshuffle when it comes out).
* `poker_rank5` / `best_of` / `poker_rank7` — the standard 5-card poker ranking (A-2-3-4-5 "wheel" is the lowest
  straight; no wild cards), comparable as plain tuples.
* `teen_patti_rank` — 3-card ranking: trail > pure sequence > sequence > colour > pair > high card, with
  A-K-Q the top sequence and A-2-3 the second.
* `baccarat_value` / `baccarat_total` and `blackjack_total` — point values.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import NamedTuple

from .fair import Rng

SUITS = "SHDC"  # spades, hearts, diamonds, clubs
RED_SUITS = frozenset("HD")
RANK_CHARS = {10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}
CHAR_RANKS = {v: k for k, v in RANK_CHARS.items()} | {str(n): n for n in range(2, 10)}
RANK_NAMES = {
    2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "jack", 12: "queen", 13: "king", 14: "ace",
}  # fmt: skip


class Card(NamedTuple):
    rank: int  # 2..14
    suit: str  # one of SUITS

    @property
    def code(self) -> str:
        return RANK_CHARS.get(self.rank, str(self.rank)) + self.suit

    @property
    def red(self) -> bool:
        return self.suit in RED_SUITS

    @property
    def glyph(self) -> str:
        """The rank as drawn on the panel ("10" for ten, "A" for ace)."""
        return "10" if self.rank == 10 else RANK_CHARS.get(self.rank, str(self.rank))

    def __str__(self) -> str:
        return self.code

    @classmethod
    def parse(cls, code: str) -> Card:
        code = code.strip().upper()
        if len(code) == 3 and code.startswith("10"):
            code = "T" + code[2]
        if len(code) != 2 or code[0] not in CHAR_RANKS or code[1] not in SUITS:
            raise ValueError(f"bad card {code!r}")
        return cls(CHAR_RANKS[code[0]], code[1])


def cards(codes: str | Iterable[str]) -> list[Card]:
    """`cards("AS KD 10H")` → three cards (handy in tests and replays)."""
    items = codes.split() if isinstance(codes, str) else list(codes)
    return [Card.parse(c) for c in items]


def new_deck() -> list[Card]:
    """One ordered 52-card deck (spades, hearts, diamonds, clubs; 2..A within each suit)."""
    return [Card(r, s) for s in SUITS for r in range(2, 15)]


@dataclass
class Shoe:
    """`decks` decks shuffled together. When the cut card (at `penetration` of the shoe) is dealt, `needs_shuffle`
    turns true; the game reshuffles before the next round, as in a real casino."""

    decks: int = 6
    penetration: float = 0.75
    cards: list[Card] | None = None
    pos: int = 0

    def shuffle(self, rng: Rng) -> None:
        self.cards = [c for _ in range(self.decks) for c in new_deck()]
        rng.shuffle(self.cards)
        self.pos = 0

    @property
    def size(self) -> int:
        return 52 * self.decks

    @property
    def remaining(self) -> int:
        return (len(self.cards) if self.cards else 0) - self.pos

    @property
    def cut(self) -> int:
        return max(1, min(self.size - 1, round(self.size * self.penetration)))

    @property
    def needs_shuffle(self) -> bool:
        return self.cards is None or self.pos >= self.cut

    def draw(self) -> Card:
        if self.cards is None or self.pos >= len(self.cards):
            raise RuntimeError("the shoe is empty")
        c = self.cards[self.pos]
        self.pos += 1
        return c


# ------------------------------------------------------------------------ poker
POKER_HANDS = (
    "high card",
    "pair",
    "two pair",
    "three of a kind",
    "straight",
    "flush",
    "full house",
    "four of a kind",
    "straight flush",
)
ROYAL_FLUSH = "royal flush"


class HandRank(NamedTuple):
    """Comparable: (category 0..8, tiebreak ranks high→low). Higher tuple = better hand."""

    category: int
    tiebreak: tuple[int, ...]

    @property
    def name(self) -> str:
        if self.category == 8 and self.tiebreak[0] == 14:
            return ROYAL_FLUSH
        return POKER_HANDS[self.category]


def _straight_high(ranks: set[int]) -> int:
    """The high card of a straight made of exactly these five distinct ranks, else 0 (A-2-3-4-5 → 5)."""
    if len(ranks) != 5:
        return 0
    hi, lo = max(ranks), min(ranks)
    if hi - lo == 4:
        return hi
    if ranks == {14, 2, 3, 4, 5}:
        return 5
    return 0


def poker_rank5(hand: Sequence[Card]) -> HandRank:
    """Rank exactly five cards."""
    if len(hand) != 5:
        raise ValueError("a poker hand has five cards")
    ranks = [c.rank for c in hand]
    counts = Counter(ranks)
    # ranks ordered by (count, rank) — e.g. full house K K K 4 4 → (13, 4)
    order = sorted(counts, key=lambda r: (counts[r], r), reverse=True)
    shape = sorted(counts.values(), reverse=True)
    flush = len({c.suit for c in hand}) == 1
    straight = _straight_high(set(ranks))
    if straight and flush:
        return HandRank(8, (straight,))
    if shape[0] == 4:
        return HandRank(7, tuple(order))
    if shape == [3, 2]:
        return HandRank(6, tuple(order))
    if flush:
        return HandRank(5, tuple(sorted(ranks, reverse=True)))
    if straight:
        return HandRank(4, (straight,))
    if shape[0] == 3:
        return HandRank(3, tuple(order))
    if shape == [2, 2, 1]:
        return HandRank(2, tuple(order))
    if shape[0] == 2:
        return HandRank(1, tuple(order))
    return HandRank(0, tuple(sorted(ranks, reverse=True)))


def best_of(pool: Sequence[Card]) -> tuple[HandRank, tuple[Card, ...]]:
    """The best five-card hand from 5–7 cards: (rank, the five cards)."""
    if not 5 <= len(pool) <= 7:
        raise ValueError("need 5 to 7 cards")
    best: tuple[HandRank, tuple[Card, ...]] | None = None
    for five in combinations(pool, 5):
        r = poker_rank5(five)
        if best is None or r > best[0]:
            best = (r, five)
    assert best is not None
    return best


def poker_rank7(pool: Sequence[Card]) -> HandRank:
    return best_of(pool)[0]


# ------------------------------------------------------------------- teen patti
TEEN_PATTI_HANDS = ("high card", "pair", "colour", "sequence", "pure sequence", "trail")


def _tp_sequence(ranks: list[int]) -> int:
    """Sequence strength (0 = not a sequence): A-K-Q 15, A-2-3 14, K-Q-J 13 … 4-3-2 4."""
    s = sorted(ranks)
    if s == [12, 13, 14]:
        return 15
    if s == [2, 3, 14]:
        return 14
    if s[1] == s[0] + 1 and s[2] == s[1] + 1:
        return s[2]
    return 0


def teen_patti_rank(hand: Sequence[Card]) -> HandRank:
    """Rank a 3-card Teen Patti hand (comparable tuples, categories in TEEN_PATTI_HANDS order)."""
    if len(hand) != 3:
        raise ValueError("a teen patti hand has three cards")
    ranks = [c.rank for c in hand]
    counts = Counter(ranks)
    flush = len({c.suit for c in hand}) == 1
    seq = _tp_sequence(ranks)
    if len(counts) == 1:
        return HandRank(5, (ranks[0],))
    if seq and flush:
        return HandRank(4, (seq,))
    if seq:
        return HandRank(3, (seq,))
    if flush:
        return HandRank(2, tuple(sorted(ranks, reverse=True)))
    if len(counts) == 2:
        pair = next(r for r, n in counts.items() if n == 2)
        kicker = next(r for r, n in counts.items() if n == 1)
        return HandRank(1, (pair, kicker))
    return HandRank(0, tuple(sorted(ranks, reverse=True)))


def teen_patti_name(r: HandRank) -> str:
    return TEEN_PATTI_HANDS[r.category]


# --------------------------------------------------------------- point values
def baccarat_value(c: Card) -> int:
    """A = 1, 2–9 face value, 10/J/Q/K = 0."""
    return 1 if c.rank == 14 else c.rank if c.rank < 10 else 0


def baccarat_total(hand: Iterable[Card]) -> int:
    return sum(baccarat_value(c) for c in hand) % 10


def blackjack_total(hand: Iterable[Card]) -> tuple[int, bool]:
    """(best total, soft): aces count 11 when that doesn't bust (one ace at most can), else 1; J/Q/K = 10."""
    total, aces = 0, 0
    for c in hand:
        if c.rank == 14:
            aces += 1
            total += 1
        else:
            total += min(c.rank, 10)
    if aces and total + 10 <= 21:
        return total + 10, True
    return total, False


# ============================================================ dealing shoes (blackjack, baccarat — wave 2)
#: the 52 card kinds in `new_deck()` order: a shoe's composition is one count per kind, in this order
CARD_KINDS: tuple[Card, ...] = tuple(new_deck())


def full_composition(decks: int) -> str:
    """A fresh shoe of `decks` decks as a composition string: one digit (0–8) per card kind, `CARD_KINDS` order."""
    if not 1 <= decks <= 8:
        raise ValueError("1 to 8 decks")
    return str(decks) * 52


class DealingShoe:
    """A shoe dealt one card at a time by a **lazy Fisher–Yates shuffle** on the round's `Rng`.

    The cards still in the shoe are listed in `CARD_KINDS` order (each kind repeated by its count). Dealing card k
    is one Fisher–Yates step read from the bottom of that list: ``j = rng.randint(0, n - 1)``, the card at ``j``
    is dealt and the last card moves into its place. A full shuffle followed by dealing from the end gives exactly
    the same cards, so this *is* a Fisher–Yates shuffle that stops once the round has its cards.

    Because the order of the cards left in a shuffled shoe is uniform whatever was dealt before, re-starting the
    lazy shuffle on the remaining cards each round deals exactly the same distribution as one shuffle per shoe —
    so a shoe can last many rounds (cut card) while every round stays verifiable from its own seeds plus the
    composition it started from (`composition`). The phone's JavaScript mirrors `draw()` line for line.

    If a round ever empties the shoe (tiny shoes, many hands), the discards come back: the shoe refills with a
    full composition minus the cards dealt in this round (they are still on the table).
    """

    def __init__(self, decks: int = 6, composition: str | None = None) -> None:
        self.decks = decks
        self.counts = [int(ch) for ch in (composition or full_composition(decks))]
        if len(self.counts) != 52 or any(not 0 <= n <= decks for n in self.counts):
            raise ValueError("bad shoe composition")
        self.rng: Rng | None = None
        self.cards: list[Card] = []
        self.drawn: list[Card] = []  # cards dealt since `begin`

    @property
    def size(self) -> int:
        return 52 * self.decks

    @property
    def remaining(self) -> int:
        return sum(self.counts)

    @property
    def composition(self) -> str:
        return "".join(str(n) for n in self.counts)

    def begin(self, rng: Rng) -> None:
        """Start dealing a round from the current composition with this round's `rng`."""
        self.rng = rng
        self.drawn = []
        self._expand()

    def _expand(self) -> None:
        self.cards = [c for c, n in zip(CARD_KINDS, self.counts, strict=True) for _ in range(n)]

    def draw(self) -> Card:
        if self.rng is None:
            raise RuntimeError("begin() the round first")
        if not self.cards:  # refill: everything except what is on the table this round
            on_table = Counter(self.drawn)
            self.counts = [self.decks - on_table[c] for c in CARD_KINDS]
            self._expand()
            if not self.cards:
                raise RuntimeError("the shoe is empty")
        i = len(self.cards) - 1
        j = self.rng.randint(0, i)
        card = self.cards[j]
        self.cards[j] = self.cards[i]
        self.cards.pop()
        self.counts[CARD_KINDS.index(card)] -= 1
        self.drawn.append(card)
        return card
