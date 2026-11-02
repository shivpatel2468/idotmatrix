"""The watch's themes (docs/DESIGN_TASTE.md §1, §5): the casino's table themes, generated for the Wear OS apps by
scripts/gen_watch_themes.py."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from deskdot.gfx.themes import DEFAULT_THEME, PAGE_THEMES

ROOT = Path(__file__).parents[1]


def _gen() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gen_watch_themes", ROOT / "scripts" / "gen_watch_themes.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_watch_themes_are_current() -> None:
    """WatchThemes.gen.kt comes from TABLE_THEMES: regenerate it (uv run python scripts/gen_watch_themes.py) after
    changing a table or the token derivation."""
    for path, text in _gen().outputs().items():
        assert path.read_text(encoding="utf-8") == text, (
            f"{path.name} is stale: run scripts/gen_watch_themes.py"
        )


def test_every_table_is_on_the_watch_in_the_studio_order() -> None:
    kt = _gen().KT.read_text(encoding="utf-8")
    ids = re.findall(r'^ {12}id = "([^"]+)",$', kt, flags=re.M)
    assert ids == list(PAGE_THEMES), "the watch lists the same tables as the studio, in the same order"
    assert f'const val DEFAULT: String = "{DEFAULT_THEME}"' in kt
    for t in PAGE_THEMES.values():
        assert f'name = "{t.name}",' in kt


@pytest.mark.parametrize("tid", list(PAGE_THEMES))
def test_watch_palette_is_usable_on_oled(tid: str) -> None:
    """The colours the watch draws with are solid (no surprise transparency) and the accent stands out from black."""
    gen = _gen()
    tok = PAGE_THEMES[tid].tokens()
    for mode in ("dark", "light"):
        for key in ("color-chassis-0", "color-ink-1", "color-ember", "color-gold", "color-on-ember"):
            assert gen.argb(tok[mode][key]) >> 24 == 0xFF, f"{tid}.{mode}.{key} must be opaque"
        stops = gen.gradient_stops(tok[mode]["m-gold-leaf"])
        assert stops[0][0] == 0.0 and stops[-1][0] == 1.0, f"{tid}.{mode} gold leaf spans 0..1"
    acc = gen.argb(tok["dark"]["color-ember"])
    assert max((acc >> 16) & 0xFF, (acc >> 8) & 0xFF, acc & 0xFF) >= 150, (
        f"{tid}: the accent rim reads on OLED black"
    )


@pytest.mark.parametrize(
    ("css", "want"),
    [
        ("#2ff3e0", 0xFF2FF3E0),
        ("#abc", 0xFFAABBCC),
        ("#11223380", 0x80112233),
        ("rgb(1, 2, 3)", 0xFF010203),
        ("rgba(47, 243, 224, 0.1)", 0x1A2FF3E0),
        ("rgba(47, 243, 224, 50%)", 0x802FF3E0),
    ],
)
def test_argb_reads_css_colours(css: str, want: int) -> None:
    assert _gen().argb(css) == want


def test_argb_refuses_gradients() -> None:
    with pytest.raises(ValueError):
        _gen().argb("linear-gradient(90deg, #000, #fff)")


def test_another_apps_copy_uses_its_own_package(tmp_path: Path) -> None:
    gen = _gen()
    out = tmp_path / "WatchThemes.gen.kt"
    assert gen.main(["--out", str(out), "--package", "com.gen6.theme"]) == 0
    text = out.read_text(encoding="utf-8")
    assert "\npackage com.gen6.theme\n" in text
    assert gen.main(["--out", str(out), "--package", "com.gen6.theme", "--check"]) == 0
