"""Page themes (docs/STUDIO_UI.md § Page themes, docs/APP_SDK.md § Page theme): the LED palette contract, apps
following the theme, the engine / API, and the studio's mirror of the table."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot.config import Config
from deskdot.engine import REGISTRY
from deskdot.engine.app import themed_settings
from deskdot.gfx import Frame, to_rgb
from deskdot.gfx.themes import DEFAULT_THEME, PAGE_THEMES, ROLES, page_theme
from deskdot.server import create_app

ROOT = Path(__file__).parents[1]
AWARE = sorted(aid for aid, c in REGISTRY.items() if c.theme_aware())
HEX = re.compile(r"^#[0-9a-f]{6}$")


# ------------------------------------------------------------------ the LED palette contract
@pytest.mark.parametrize("tid", list(PAGE_THEMES))
def test_panel_palette_is_led_safe(tid: str) -> None:
    p = PAGE_THEMES[tid].panel
    for role in ("accent", "accent2", "accent3"):
        c = p.role(role)
        assert max(c) >= 170, f"{tid}.{role} {c}: too dim to be an accent on the LEDs"
        assert min(c) <= 235, f"{tid}.{role} {c}: near-white accents blind on the panel (DISPLAY_DESIGN §8)"
    assert min(p.text) >= 200, f"{tid}.text {p.text}: primary text stays near white"
    assert 120 <= max(p.mute) < max(p.text), f"{tid}.mute {p.mute}: reads, but quieter than text"
    # the gamma floor: meaningful dark tones keep their brightest channel above ~45 (DISPLAY_DESIGN §3)
    assert max(p.soft) >= 90, f"{tid}.soft {p.soft}"
    assert 45 <= max(p.track) < max(p.soft), f"{tid}.track {p.track}: lit, and darker than soft"
    assert set(p.public()) == set(ROLES)


def test_the_default_theme_is_the_original_look() -> None:
    th = PAGE_THEMES[DEFAULT_THEME]
    assert th.panel.accent == (255, 72, 24) and th.accent == "#ff4818" and th.accent_light == "#b81f4b"
    assert not th.tint and not th.pattern  # untinted chassis, the dot grid: nothing to override
    assert page_theme("nope") is th and page_theme(None) is th


@pytest.mark.parametrize("tid", list(PAGE_THEMES))
def test_screen_seeds_are_valid(tid: str) -> None:
    th = PAGE_THEMES[tid]
    assert th.name and th.description and len(th.description) < 120
    for k in ("accent", "metal"):
        assert HEX.match(getattr(th, k)), (tid, k)
    for k in ("accent_light", "tint"):
        assert getattr(th, k) == "" or HEX.match(getattr(th, k)), (tid, k)
    if th.pattern:  # a gradient-only texture (no images), one background-size entry per layer, faint
        assert "url(" not in th.pattern
        layers = re.split(r",\s*(?=(?:repeating-)?(?:linear|radial|conic)-gradient)", th.pattern)
        assert all(re.match(r"^(repeating-)?(linear|radial|conic)-gradient\(", x) for x in layers), tid
        assert len(th.pattern_size.split(",")) == len(layers), tid
        assert all(float(a) <= 0.12 for a in re.findall(r"rgba\([^)]*,\s*([0-9.]+)\)", th.pattern)), tid


# ------------------------------------------------------------------ apps follow the theme
def test_theme_aware_apps_have_the_opt_out() -> None:
    assert len(AWARE) >= 20
    for aid in AWARE:
        cls = REGISTRY[aid]
        f = cls.Settings.model_fields.get("follow_theme")
        assert f is not None and f.default is True, aid
        for name, role in cls.theme_colors.items():
            assert role in ROLES, (aid, name)
            default = cls.Settings.model_fields[name].default
            assert isinstance(default, str) and HEX.match(default.lower()), (aid, name)


def test_own_colours_stay_with_photos_flags_games_and_the_casino() -> None:
    from deskdot.apps.games_core import GameApp

    for aid, cls in REGISTRY.items():
        # table themes, genre themes, characters
        own = cls.category in ("casino", "pets") or issubclass(cls, GameApp)
        if own or aid in ("photoframe", "gallery", "worldflags", "agent", "pokedex"):
            assert not cls.theme_aware(), f"{aid}: its colours carry meaning — leave it on its own palette"


def test_themed_settings_only_touch_untouched_colours() -> None:
    cls = REGISTRY["clock"]
    galaxy = PAGE_THEMES["galaxy"]
    s = cls.Settings()
    assert themed_settings(cls, s, PAGE_THEMES[DEFAULT_THEME]) is s  # the default theme: own colours
    t = themed_settings(cls, s, galaxy)
    assert to_rgb(t.accent) == galaxy.panel.accent and t.color == s.color  # only the mapped field
    mine = cls.Settings(accent="#123456")
    assert themed_settings(cls, mine, galaxy).accent == "#123456"  # a colour the person picked is theirs
    off = cls.Settings(follow_theme=False)
    assert themed_settings(cls, off, galaxy) is off


async def test_engine_switches_the_panel_theme(engine: Any) -> None:
    clock = engine._slot("clock").app
    before = clock.clip_key()
    assert engine.snapshot()["settings"]["page_theme"] == DEFAULT_THEME
    with pytest.raises(KeyError):
        engine.set_page_theme("nope")
    info = engine.set_page_theme("volcano")
    assert info["id"] == "volcano" and engine.store.get("page_theme") == "volcano"
    assert engine.snapshot()["settings"]["page_theme"] == "volcano"
    engine.apply_page_theme()  # (the engine applies it after a short settle; the test doesn't wait)
    assert engine.panel_theme.id == "volcano"
    assert to_rgb(clock.settings.accent) == PAGE_THEMES["volcano"].panel.accent
    assert clock.clip_key() != before
    stored = engine.store.section("apps").get("clock", {}).get("accent")
    assert stored in (None, "#ff4818")  # the stored settings are untouched
    assert clock.themed("accent", "#00ff00") == PAGE_THEMES["volcano"].panel.accent
    engine.update_settings("clock", {"follow_theme": False})
    assert clock.settings.accent == "#ff4818" and clock.themed("accent", "#00ff00") == (0, 255, 0)


async def test_theme_recolours_the_frame(engine: Any) -> None:
    def draw() -> Frame:
        f = Frame()
        engine._slot("clock").app.render(f, 1.0)
        return f

    a = draw()
    engine.set_page_theme("galaxy")
    engine.apply_page_theme()
    assert draw() != a


@pytest.mark.parametrize("aid", AWARE)
async def test_aware_apps_render_every_option_in_a_theme(engine: Any, aid: str) -> None:
    engine.set_page_theme("sakura")
    engine.apply_page_theme()
    cls = REGISTRY[aid]
    variants: list[dict[str, Any]] = [{}]
    for name, field in cls.Settings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            variants += [{name: v} for v in extra["enum"]]
    for v in variants:
        engine.store.section("apps")[aid] = v
        engine.slots.pop(aid, None)
        app = engine._slot(aid).app
        for t in (0.0, 1.3):
            app.render(Frame(), t)


# ------------------------------------------------------------------ API
def test_theme_api(tmp_path: Path) -> None:
    with TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "p"))) as c:
        r = c.get("/api/theme").json()
        assert r["id"] == DEFAULT_THEME and len(r["themes"]) == len(PAGE_THEMES)
        assert set(r["themes"][0]) >= {"id", "name", "description", "screen", "panel"}
        assert c.post("/api/theme", json={"id": "arcade"}).json()["id"] == "arcade"
        assert c.get("/api/state").json()["settings"]["page_theme"] == "arcade"
        assert c.post("/api/theme", json={"id": "nope"}).status_code == 422
        assert c.post("/api/theme", json={"id": "Bad Id!"}).status_code == 422


# ------------------------------------------------------------------ the studio mirror
def test_studio_mirror_matches_the_engine() -> None:
    """web/src/lib/pageTheme.ts PAGE_THEMES paints before the engine answers (and offline): keep it in sync."""
    ts = (ROOT / "web/src/lib/pageTheme.ts").read_text(encoding="utf-8")
    m = re.search(r"export const PAGE_THEMES: PageThemeSeed\[\] = (\[.*?\n\]);", ts, re.S)
    assert m, "PAGE_THEMES table not found"
    studio = json.loads(m.group(1))
    engine = [
        {"id": t.id, "name": t.name, "description": t.description, **t.screen()} for t in PAGE_THEMES.values()
    ]
    assert studio == engine
