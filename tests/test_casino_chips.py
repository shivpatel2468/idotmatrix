"""The chip ladder and a table's rack (casino/chips.py) and its place in the public status."""

from __future__ import annotations

from deskdot.casino import CasinoSession
from deskdot.casino.chips import LADDER, RACK_MAX, break_into, chip_rack, short


def values(rack: list[dict]) -> list[int]:
    return [c["v"] for c in rack]


def test_default_table_offers_the_low_chips():
    assert values(chip_rack(1, 500)) == [1, 5, 25, 100, 500]


def test_high_roller_table_shows_k_chips_and_hides_small_ones():
    rack = chip_rack(1_000, 10_000)
    assert values(rack) == [1_000, 2_000, 5_000, 10_000]
    assert [c["label"] for c in rack] == ["1K", "2K", "5K", "10K"]
    assert rack[0]["color"] == "#f2c230" and rack[0]["edge"] == "#5a3d00"


def test_chips_outside_the_limits_are_not_offered():
    rack = chip_rack(25, 2_000)
    assert values(rack) == [25, 100, 500, 1_000, 2_000]
    assert all(25 <= c["v"] <= 2_000 for c in rack)


def test_off_ladder_minimum_becomes_the_smallest_chip():
    rack = chip_rack(10, 100)
    assert values(rack) == [10, 25, 100]
    first = rack[0]
    assert first["label"] == "10" and first["color"] == "#2e9a55"  # coloured like the next chip up (25)
    assert values(chip_rack(1_500, 5_000)) == [1_500, 2_000, 5_000]
    assert chip_rack(1_500, 5_000)[0]["label"] == "1.5K"
    assert values(chip_rack(3, 4)) == [3]
    assert values(chip_rack(7, 7)) == [7]


def test_rack_is_capped_and_spans_the_range():
    rack = chip_rack(1, 1_000_000)
    assert len(rack) == RACK_MAX
    assert rack[0]["v"] == 1 and rack[-1]["v"] == 1_000_000
    assert values(rack) == sorted(set(values(rack)))
    for lo, hi in ((1, 5_000), (5, 100_000), (100, 1_000_000)):
        r = chip_rack(lo, hi)
        assert len(r) <= RACK_MAX and r[0]["v"] == lo and r[-1]["v"] == hi


def test_max_below_min_never_breaks():
    assert values(chip_rack(500, 100)) == [500]


def test_short_labels():
    assert [short(v) for v in (1, 750, 1_000, 2_500, 1_250, 1_999, 10_000, 12_345, 250_000, 1_000_000, 1_500_000)] == [
        "1", "750", "1K", "2.5K", "1.25K", "1.99K", "10K", "12.3K", "250K", "1M", "1.5M",
    ]  # fmt: skip
    for v, label, *_ in LADDER:
        assert short(v) == label


def test_break_into_ladder_chips_largest_first():
    assert break_into(3_630) == [2_000, 1_000, 500, 100, 25, 5]
    assert break_into(0) == []


def test_public_status_carries_the_rack_and_follows_the_limits():
    s = CasinoSession()
    assert values(s.public_state()["chips"]) == values(chip_rack(s.house.min_bet, s.house.max_bet))
    s.house = s.house.model_copy(update={"min_bet": 1_000, "max_bet": 5_000})
    assert values(s.public_state()["chips"]) == [1_000, 2_000, 5_000]
