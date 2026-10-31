"""Page themes (docs/STUDIO_UI.md § Page themes, docs/APP_SDK.md § Page theme): the casino's table themes as the
studio's themes, the LED palette contract, apps following the theme, the engine / API, old ids, and the studio's
generated copy."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot.config import Config
from deskdot.engine import REGISTRY
from deskdot.engine.app import themed_settings
from deskdot.gfx import Frame, to_rgb
from deskdot.gfx.tables import TABLE_THEMES, contrast
from deskdot.gfx.themes import DEFAULT_THEME, LEGACY, PAGE_THEMES, ROLES, SURFACES, TEXT_TOKENS, page_theme
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


def test_page_themes_are_the_casino_tables() -> None:
    assert [(t.id, t.name, t.description) for t in PAGE_THEMES.values()] == [
        (t.id, t.name, t.description) for t in TABLE_THEMES.values()
    ]
    assert DEFAULT_THEME == "cyber" and PAGE_THEMES[DEFAULT_THEME].name == "Cyber grid"
    assert page_theme("nope") is PAGE_THEMES["cyber"] and page_theme(None) is PAGE_THEMES["cyber"]


def test_old_ids_map_to_the_nearest_table() -> None:
    assert LEGACY["ember"] == "cyber" and page_theme("ember").id == "cyber"
    assert page_theme("glacier").id == "arctic"
    for old, new in LEGACY.items():
        assert new in PAGE_THEMES and old not in PAGE_THEMES, old
    # every pre-3.9 id is either a table id already or mapped
    before = [
        "ember",
        "graphite",
        "sunset",
        "citrus",
        "royal",
        "crimson",
        "midnight",
        "strip",
        "emerald",
        "noir",
    ]
    before += [
        "jade",
        "deco",
        "marigold",
        "cyber",
        "arcade",
        "sakura",
        "glacier",
        "oasis",
        "abyss",
        "volcano",
        "galaxy",
    ]
    assert all(old in PAGE_THEMES or old in LEGACY for old in before)


@pytest.mark.parametrize("tid", list(PAGE_THEMES))
def test_screen_tokens_read_like_the_casino(tid: str) -> None:
    th = PAGE_THEMES[tid]
    tok = th.tokens()
    c = th.table.css
    assert tok["dark"].keys() == tok["light"].keys()  # the light block overrides every dark token
    # dark: exactly the casino's room around the table (casino.css html[data-cz], state.ts pageVars)
    d = tok["dark"]
    assert [d[f"color-chassis-{i}"] for i in range(5)] == [
        c["bg"],
        c["surface"],
        c["surface2"],
        c["surface3"],
        c["surface4"],
    ]
    assert d["color-ember-2"] == c["accent_hi"] and d["color-ember-deep"] == c["accent_deep"]
    for mode, t in tok.items():
        for k in (*TEXT_TOKENS,):
            low = min(contrast(t[k], t[s]) for s in SURFACES)
            assert low >= 4.5, f"{tid}.{mode} {k} {t[k]}: {low:.2f}:1 on the page"
        assert contrast(t["color-on-ember"], t["color-ember"]) >= 4.5, (
            tid,
            mode,
            "lettering on an accent key",
        )
        for k in ("m-texture",):  # gradients only (no images), one background-size entry per layer
            assert "url(" not in t[k]
            layers = re.split(r",\s*(?=(?:repeating-)?(?:linear|radial|conic)-gradient)", t[k])
            assert all(re.match(r"^(repeating-)?(linear|radial|conic)-gradient\(", x) for x in layers), (
                tid,
                mode,
            )
            assert len(t["m-texture-size"].split(",")) == len(layers), (tid, mode)
    assert min(contrast(tok["dark"]["color-ink-1"], tok["dark"][s]) for s in SURFACES) >= 7


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
    assert themed_settings(cls, s, None) is s  # no theme (bare previews): own colours
    cyber = themed_settings(cls, s, PAGE_THEMES[DEFAULT_THEME])  # the default theme recolours too
    assert to_rgb(cyber.accent) == PAGE_THEMES[DEFAULT_THEME].panel.accent
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
        assert c.post("/api/theme", json={"id": "ember"}).json()["id"] == "cyber"  # an old studio's id
        assert c.post("/api/theme", json={"id": "nope"}).status_code == 422
        assert c.post("/api/theme", json={"id": "Bad Id!"}).status_code == 422


# ------------------------------------------------------------------ the studio's generated copy
def test_generated_studio_themes_are_current() -> None:
    """web/src/lib/pageThemes.gen.ts and web/src/pageTheme.default.gen.css come from TABLE_THEMES: regenerate them
    (uv run python scripts/gen_page_themes.py) after changing a table or the token derivation."""
    spec = importlib.util.spec_from_file_location("gen_page_themes", ROOT / "scripts" / "gen_page_themes.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for path, text in mod.outputs().items():
        assert path.read_text(encoding="utf-8") == text, (
            f"{path.name} is stale: run scripts/gen_page_themes.py"
        )
    ts = (ROOT / "web/src/lib/pageThemes.gen.ts").read_text(encoding="utf-8")
    assert all(f'"id": "{t}"' in ts for t in PAGE_THEMES)
