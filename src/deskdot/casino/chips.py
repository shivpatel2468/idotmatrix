"""The chip ladder and a table's rack (docs/CASINO.md §5).

One ladder of chip values, labels and colours shared by the phones, the studio and the TV. A table only offers the
chips the house allows (``min_bet <= value <= max_bet``); a table minimum that is not on the ladder becomes the
smallest chip. The rack holds at most `RACK_MAX` chips spanning the allowed range. ``chips`` in the public casino
status is `chip_rack` of the house limits; the web UIs copy `LADDER` as a fallback for older engines.
"""

from __future__ import annotations

from typing import Any

#: value, label, chip colour, edge-stripe colour
LADDER: tuple[tuple[int, str, str, str], ...] = (
    (1, "1", "#f2efe8", "#2b6cd6"),
    (5, "5", "#d23a3a", "#ffffff"),
    (25, "25", "#2e9a55", "#ffffff"),
    (100, "100", "#1c1c22", "#e8e8e8"),
    (500, "500", "#7b3fc4", "#ffffff"),
    (1_000, "1K", "#f2c230", "#5a3d00"),
    (2_000, "2K", "#e85d9f", "#ffffff"),
    (5_000, "5K", "#c9772b", "#ffffff"),
    (10_000, "10K", "#2f6fd6", "#ffffff"),
    (25_000, "25K", "#18a39a", "#ffffff"),
    (50_000, "50K", "#9a2f4d", "#ffd36b"),
    (100_000, "100K", "#c9a227", "#1c1c22"),
    (250_000, "250K", "#5b2a86", "#ffd36b"),
    (500_000, "500K", "#0f3d2e", "#ffd36b"),
    (1_000_000, "1M", "#111111", "#ffd36b"),
)
RACK_MAX = 7


def short(v: int) -> str:
    """A chip amount with K / M, never rounded up: 1000 → 1K, 2500 → 2.5K, 1250 → 1.25K, 12345 → 12.3K,
    1000000 → 1M, 750 → 750 (at most three significant digits; casino.html's ``short`` is the same)."""
    v = int(v)
    for unit, suffix in ((1_000_000, "M"), (1_000, "K")):
        if v >= unit:
            d = 2 if v < 10 * unit else 1 if v < 100 * unit else 0
            q = v * 10**d // unit
            s = str(q) if not d else f"{q // 10**d}.{q % 10**d:0{d}d}".rstrip("0").rstrip(".")
            return s + suffix
    return str(v)


def _chip(v: int, label: str, color: str, edge: str) -> dict[str, Any]:
    return {"v": v, "label": label, "color": color, "edge": edge}


def chip_rack(min_bet: int, max_bet: int) -> list[dict[str, Any]]:
    """The chips a table offers, smallest first: ``[{v, label, color, edge}]`` (at most `RACK_MAX`)."""
    lo = max(1, int(min_bet))
    hi = max(lo, int(max_bet))
    allowed = [_chip(*c) for c in LADDER if lo <= c[0] <= hi]
    if not allowed or allowed[0]["v"] != lo:
        # the table minimum is not a ladder chip: it becomes the smallest chip, coloured like the next one up
        above = next((c for c in LADDER if c[0] > lo), LADDER[-1])
        allowed.insert(0, _chip(lo, short(lo), above[2], above[3]))
    n = len(allowed)
    if n <= RACK_MAX:
        return allowed
    # evenly by ladder index, halves rounded up (integer maths: casino.html's chipRack picks the very same chips)
    picks = sorted({(2 * i * (n - 1) + RACK_MAX - 1) // (2 * (RACK_MAX - 1)) for i in range(RACK_MAX)})
    return [allowed[i] for i in picks]


def break_into(amount: int, rack: list[dict[str, Any]] | None = None) -> list[int]:
    """A stack's amount as chip values, largest first (greedy over the ladder, or ``rack`` when given)."""
    values = sorted({c["v"] for c in rack} if rack else {c[0] for c in LADDER}, reverse=True)
    out: list[int] = []
    left = int(amount)
    for v in values:
        while left >= v:
            out.append(v)
            left -= v
    if left > 0:
        out.append(left)
    return out
