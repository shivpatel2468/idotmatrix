"""Casino table themes (panel + status) and the rulebook (casino/rulebook.py, docs/CASINO_RULES.md)."""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from deskdot.apps._casino import CLASSIC, TABLE_THEMES, CasinoApp, draw_paused
from deskdot.casino import GAMES, CasinoSession
from deskdot.casino.rulebook import CASINO_ORDER, GUIDES, casino_rulebook, guide, markdown, rulebook_for
from deskdot.engine import REGISTRY
from deskdot.gfx import Frame

CASINO_APPS = sorted(a for a, c in REGISTRY.items() if c.category == "casino")
ROOT = Path(__file__).resolve().parents[1]


def test_themes_are_led_safe() -> None:
    assert "classic" in TABLE_THEMES and len(TABLE_THEMES) >= 7
    for t in TABLE_THEMES.values():
        if t is not CLASSIC:  # classic keeps the original look byte for byte
            for k in (
                "accent",
                "accent_dim",
                "alert",
                "chip",
                "chip_dark",
                "rim",
                "wood",
                "felt",
                "felt_dark",
            ):
                assert max(getattr(t, k)) >= 45, (t.id, k)  # dark tones still light the LED
        css = t.public()["css"]
        for k in ("felt", "felt2", "felt3", "accent", "accent_hi", "accent_lo", "wing", "wing2", "wing3"):
            assert re.fullmatch(r"#[0-9a-f]{6}", css[k]), (t.id, k)
        assert re.fullmatch(r"\d+, \d+, \d+", css["accent_rgb"])


def test_every_casino_app_offers_the_themes() -> None:
    for app_id in CASINO_APPS:
        extra = REGISTRY[app_id].Settings.model_fields["table_theme"].json_schema_extra
        assert isinstance(extra, dict) and extra["enum"] == list(TABLE_THEMES)
        assert extra["group"] == "Look"
    # slots keeps its own machine `theme`; the table theme doesn't collide with it
    assert "theme" in REGISTRY["casino_slots"].Settings.model_fields


@pytest.mark.parametrize("app_id", CASINO_APPS)
async def test_every_theme_renders_every_view(engine: Any, app_id: str) -> None:
    views = list(REGISTRY[app_id].Settings.model_fields["view"].json_schema_extra["enum"])  # type: ignore[index]
    for theme in TABLE_THEMES:
        for view in views:
            engine.store.section("apps")[app_id] = {"view": view, "table_theme": theme}
            engine.slots.clear()
            app = engine._slot(app_id).app
            assert isinstance(app, CasinoApp) and app.th.id == theme
            for t in (0.0, 1.3, 4.1, 9.9):
                f = Frame()
                app.render(f, t)
                assert f.px.shape == (32, 32, 3)
            st = app.status()
            assert st["table_theme"]["id"] == theme and st["table_theme"]["css"]["accent"]


async def test_theme_changes_the_panel(engine: Any) -> None:
    def frame(theme: str) -> bytes:
        engine.store.section("apps")["casino_roulette"] = {"view": "betting", "table_theme": theme}
        engine.slots.clear()
        f = Frame()
        engine._slot("casino_roulette").app.render(f, 0.4)
        return f.px.tobytes()

    base = frame("classic")
    assert all(frame(t) != base for t in TABLE_THEMES if t != "classic")
    f = Frame()
    draw_paused(f)  # the default is the classic card
    g = Frame()
    draw_paused(g, CLASSIC)
    assert f.px.tobytes() == g.px.tobytes()


# ------------------------------------------------------------------ rulebook
def test_every_game_has_a_guide() -> None:
    casino_ids = {cls.id for cls in GAMES.values()}
    assert set(CASINO_ORDER) == casino_ids
    assert set(casino_rulebook()) == casino_ids
    for gid in (*CASINO_ORDER, "rps"):
        g = guide(gid)
        assert g is not None and g["title"] and g["tagline"]
        assert 3 <= len(g["how"]) <= 6 and all(len(s) > 20 for s in g["how"])
        assert g["rules"] and all(r["h"] and r["items"] for r in g["rules"])
    assert guide("nope") is None


def _to1(win: Fraction) -> str:
    """A Spot's total return as the "n:1" a player reads (2.5:1, 0.95:1 …)."""
    p = win - 1
    return f"{p.numerator}:1" if p.denominator == 1 else f"{float(p):g}:1"


@pytest.mark.parametrize("gid", ["roulette", "sevens", "bigsix", "andarbahar", "baccarat"])
def test_rulebook_payouts_match_the_spots(gid: str) -> None:
    """Every payout the game's spots pay (default rules) is written in its rulebook."""
    game = GAMES[gid](CasinoSession())
    text = " ".join(" ".join(r["items"]) for r in guide(gid)["rules"])  # type: ignore[index]
    pays = {_to1(s.win) for s in game.spots().values()}
    if gid == "baccarat":
        pays.discard("1:1")  # banker's 0.95:1 is the commission, checked below
        assert "0.95:1" in text
    for p in pays:
        assert f"**{p}**" in text or p in text, (gid, p)


async def test_studio_view_carries_the_guide(engine: Any) -> None:
    engine.store.section("apps")["casino_sevens"] = {}
    engine.slots.clear()
    app = engine._slot("casino_sevens").app
    out = app.host_view(spots=True)
    assert out["guide"]["id"] == "sevens" and out["guide"]["how"]
    assert "guide" not in app.host_view()


def test_hello_rulebook() -> None:
    """What a phone's hello carries: every casino guide in a casino room, the app's own guide for RPS."""
    assert GUIDES["rps"]["title"] == "Rock Paper Scissors"
    assert set(rulebook_for(REGISTRY["casino_roulette"])) == set(CASINO_ORDER)
    assert list(rulebook_for(REGISTRY["rps"])) == ["rps"]
    assert rulebook_for(type("NoGuide", (), {"id": "clock", "category": "info"})) == {}


def test_rules_doc_is_generated_from_the_rulebook() -> None:
    doc = (ROOT / "docs" / "CASINO_RULES.md").read_text(encoding="utf-8")
    assert doc == markdown(), "run: uv run python -m deskdot.casino.rulebook > docs/CASINO_RULES.md"
