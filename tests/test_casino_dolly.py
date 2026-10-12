"""The roulette dolly house setting (docs/CASINO.md §5) and the public win / lose data the TV's and phones' result
moment draws from (docs/TV_VIEW.md §7): winners with their stake, losers with what they lost."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from deskdot.casino import CasinoSession
from deskdot.casino.games.sevens import Sevens
from deskdot.casino.session import DOLLIES, House, _load_house
from deskdot.casino.table import LOCK_SECONDS

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_dolly_defaults_to_classic_gold_and_is_a_choice() -> None:
    assert House().dolly == "classic_gold"
    prop = House.model_json_schema()["properties"]["dolly"]
    assert prop["title"] == "Roulette dolly"
    assert prop["enum"] == list(DOLLIES)
    assert prop["enumLabels"]["classic_gold"] == "Classic Gold"
    assert {
        "classic_gold",
        "crystal",
        "chrome",
        "onyx_gold",
        "rose_gold",
        "diamond",
        "marble_brass",
        "neon",
    } <= set(DOLLIES)
    for v in DOLLIES:
        assert House(dolly=v).dolly == v
    with pytest.raises(ValidationError):
        House(dolly="plastic")


def test_dolly_is_a_host_setting_published_in_the_public_status() -> None:
    s = CasinoSession(clock=Clock())
    assert s.public_state()["house"]["dolly"] == "classic_gold"
    out = s.host_op("settings", {"dolly": "onyx_gold"})
    assert out["house"]["dolly"] == "onyx_gold"
    assert s.public_state()["house"]["dolly"] == "onyx_gold"
    with pytest.raises(ValidationError):
        s.host_op("settings", {"dolly": "nope"})
    assert s.house.dolly == "onyx_gold"  # a bad value changes nothing


def test_stored_house_with_an_unknown_dolly_keeps_the_rest() -> None:
    """Rule 15: stale stored settings never break loading — only the bad key falls back."""
    h = _load_house({"dolly": "gone_style", "min_bet": 5, "max_bet": 50})
    assert h.dolly == "classic_gold" and h.min_bet == 5 and h.max_bet == 50
    assert _load_house({"dolly": "rose_gold"}).dolly == "rose_gold"


def test_every_dolly_style_has_art_on_the_tv_and_the_phone() -> None:
    """The TV draws each style (tv-casino.js DOLLY_STYLES) and the phone page colours its marker for each."""
    tv = (ROOT / "src/deskdot/tv/tv-casino.js").read_text(encoding="utf-8")
    block = tv[tv.index("const DOLLY_STYLES") : tv.index("// end DOLLY_STYLES")]
    phone = (ROOT / "src/deskdot/casino.html").read_text(encoding="utf-8")
    for v in DOLLIES:
        assert re.search(rf"\b{v}\s*:", block), f"tv-casino.js has no {v} dolly"
        assert f'data-dolly="{v}"' in phone or f"[data-dolly={v}]" in phone, f"casino.html has no {v} dolly"


def _round(stakes: dict[str, tuple[str, int]]) -> dict[str, Any]:
    clk = Clock()
    s = CasinoSession(clock=clk)
    for i, pid in enumerate(stakes):
        s.join(pid, i + 2, name=pid.upper())
    g = Sevens(s)
    s.use(g)
    g.open_betting()
    for pid, (spot, amount) in stakes.items():
        assert g.place_bet(pid, spot, amount) is None
    g.lock()
    clk.t += LOCK_SECONDS + g.spin_seconds + 0.01
    g.tick()
    assert g.phase == "result"
    return g.public_state(clk.t)["result"]


def test_result_lists_winners_with_their_stake_and_the_losers() -> None:
    res = _round({"a": ("up", 10), "b": ("down", 20), "c": ("seven", 5)})
    zone = res["outcome"]["zone"]
    winners = {w["seat"]: w for w in res["winners"]}
    losers = {w["seat"]: w for w in res["losers"]}
    expect_win = {"up": 2, "down": 3, "seven": 4}[zone]
    assert set(winners) == {expect_win}
    assert winners[expect_win]["stake"] == {2: 10, 3: 20, 4: 5}[expect_win]
    assert winners[expect_win]["net"] > 0
    assert set(losers) == {2, 3, 4} - {expect_win}
    for seat, w in losers.items():
        stake = {2: 10, 3: 20, 4: 5}[seat]
        assert w["stake"] == stake and w["net"] == -stake
    assert [w["net"] for w in res["losers"]] == sorted(w["net"] for w in res["losers"])  # biggest loss first


def test_chip_set_follows_the_table_theme_unless_the_host_picks_one() -> None:
    from deskdot.apps._casino import TABLE_THEMES
    from deskdot.casino.chips import CHIP_SETS, THEME_CHIP_SET, chip_set_for

    assert set(THEME_CHIP_SET) == set(TABLE_THEMES), "every table theme has its own chip set"
    assert set(THEME_CHIP_SET.values()) <= set(CHIP_SETS)
    assert House().chip_set == "auto"
    assert chip_set_for("auto", "arcade") == "pixel"
    assert chip_set_for("auto", "jade") == "jade"
    assert chip_set_for("auto", "unknown") == "clay"
    assert chip_set_for("neon", "classic") == "neon"
    with pytest.raises(ValidationError):
        House(chip_set="wood")
    s = CasinoSession(clock=Clock())
    assert s.host_op("settings", {"chip_set": "ivory"})["house"]["chip_set"] == "ivory"
    assert _load_house({"chip_set": "gone"}).chip_set == "auto"


def test_every_chip_set_is_drawn_on_the_tv_the_phone_and_the_studio() -> None:
    from deskdot.casino.chips import CHIP_SETS

    tv = (ROOT / "src/deskdot/tv/tv-casino.js").read_text(encoding="utf-8")
    phone = (ROOT / "src/deskdot/casino.html").read_text(encoding="utf-8")
    studio = (ROOT / "web/src/components/casino/casino.css").read_text(encoding="utf-8")
    for v in CHIP_SETS:
        assert f'"{v}"' in tv[tv.index("const CHIP_SETS") : tv.index("const THEME_CHIP_SET")], v
        if v != "clay":  # clay is the base look
            assert f"[data-chips={v}]" in phone, f"casino.html has no {v} chips"
            assert f'[data-chips="{v}"]' in studio, f"casino.css has no {v} chips"


def test_live_status_publishes_the_chip_set_and_the_dolly() -> None:
    import deskdot.apps  # noqa: F401
    from deskdot.engine.app import REGISTRY

    cls = REGISTRY["casino_roulette"]
    app = cls(type("Ctx", (), {})(), cls.Settings(table_theme="arcade"))
    st = app.status()
    assert st["chip_set"] == "pixel"
    assert st["house"]["dolly"] == "classic_gold"
    app.session.host_op("settings", {"chip_set": "gold_rim", "dolly": "rose_gold"})
    st = app.status()
    assert st["chip_set"] == "gold_rim" and st["house"]["dolly"] == "rose_gold"
