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
    assert "classic" in TABLE_THEMES and len(TABLE_THEMES) >= 19
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


# ------------------------------------------------------------------ library previews play a round
async def test_casino_previews_play_a_demo_round(engine) -> None:  # type: ignore[no-untyped-def]
    from io import BytesIO

    from PIL import Image

    from deskdot.engine.app import REGISTRY
    from deskdot.previews import Previews

    casino = [i for i, c in REGISTRY.items() if getattr(c, "category", "") == "casino"]
    assert casino
    for app_id in casino:
        gif = Image.open(BytesIO(Previews(engine)._render(app_id)))
        assert gif.n_frames > 12, f"{app_id}: the preview should show a whole round, not a still"
        frames = set()
        for i in range(0, gif.n_frames, 6):
            gif.seek(i)
            frames.add(gif.convert("RGB").tobytes())
        assert len(frames) > 3, f"{app_id}: the preview doesn't move"


# ------------------------------------------------------------------ waiting for bets: the table, not the QR
async def test_qr_only_while_the_table_is_empty(engine) -> None:  # type: ignore[no-untyped-def]
    app = engine._slot("casino_roulette").app
    app._live()
    app.lobby_url = "https://idotmatrix.com/p/ABCD"
    app.seats = {}
    assert app.lobby_waiting(), "an empty table shows the join QR"
    app.seats = {2: {"name": "LUCKY"}}
    assert not app.lobby_waiting(), "once someone sits down the panel shows the table and who has bet"


def test_seat_row_shows_who_has_bet() -> None:
    from deskdot.apps._casino import WHITE, seat_row
    from deskdot.gfx import Frame

    f = Frame()
    red, blue, green = (230, 18, 36), (30, 110, 255), (0, 190, 80)
    seat_row(f, 22, [(red, 0), (blue, 1), (green, 2)], 0.0)
    x = (32 - 8) // 2
    dim, lit, done = f.px[22][x], f.px[22][x + 3], f.px[22][x + 6]
    assert sum(dim) < sum(red) / 2, "no chips yet: a dim pip"
    assert tuple(lit) == blue, "chips down: the player's colour"
    assert tuple(done) == WHITE and tuple(f.px[23][x + 6]) == green, "done: a capped 2x2 block"


def test_studio_theme_list_mirrors_the_engine() -> None:
    """web/src/components/casino/state.ts TABLE_THEMES shows the swatches before a table is live; keep it in sync."""
    import json
    import re
    from pathlib import Path

    from deskdot.apps._casino import TABLE_THEMES

    ts = (Path(__file__).parents[1] / "web/src/components/casino/state.ts").read_text(encoding="utf-8")
    rows = re.findall(r'\{ id: ("[^"]+"), name: ("[^"]+"), description: ("[^"]*"), css: (\{[^}]*\}) \}', ts)
    studio = {json.loads(i): (json.loads(n), json.loads(d), json.loads(c)) for i, n, d, c in rows}
    assert studio == {k: (t.name, t.description, t.css) for k, t in TABLE_THEMES.items()}


# ------------------------------------------------------------------ the theme on every surface (phone + studio)
DERIVED = ("bg", "surface", "surface2", "surface3", "surface4", "felt_ink", "accent_text")
PHONE = ROOT / "src" / "deskdot" / "casino.html"
STUDIO_CSS = ROOT / "web" / "src" / "components" / "casino" / "casino.css"
STUDIO_TS = ROOT / "web" / "src" / "components" / "casino" / "state.ts"

# Literal colours that may stay: semantic ones (game result tiles / zones, the slot machine's own skin, ticket ink).
# Everything else (accent, felt, surfaces) must come from the theme's variables.
SEMANTIC_ALLOW = {
    "d79a00",
    "c58b00",  # 7 up 7 down: the "seven" tile / zone
    "a87a00",
    "c99400",  # result tiles: "gold"
    "c99a00",
    "d8521a",
    "a08a3a",  # Big Six: the 1, 20 and logo segments
    "5a3a0a",  # the classic slot machine's brass rim (slots keep their own machine theme)
}


def _css_rules(text: str, *, token_blocks: list[str]) -> str:
    """The stylesheet without the theme token blocks and @property registrations (where literals belong)."""
    for blk in token_blocks:
        text = re.sub(blk, "", text, count=1, flags=re.S)
    return re.sub(r"@property[^\n]*", "", text)


def _warm_literals(css: str) -> list[str]:
    """Hex literals in the gold / orange / amber hue band (what a hard-coded accent looks like)."""
    import colorsys

    out = []
    for m in re.finditer(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", css):
        h = m.group(1).lower()
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
        hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
        if 15 <= hue * 360 <= 65 and sat > 0.45 and val > 0.3:
            out.append(h)
    return out


def test_every_theme_has_the_derived_palette_and_reads() -> None:
    from deskdot.apps._casino import contrast, mix_hex

    for t in TABLE_THEMES.values():
        c = t.css
        for k in DERIVED:
            assert re.fullmatch(r"#[0-9a-f]{6}", c[k]), (t.id, k)
        for s in ("surface", "surface2", "surface3", "surface4"):
            assert contrast(c["accent_text"], c[s]) >= 4.5, (t.id, "accent text", s)
            if s != "surface4":  # the dimmest phone text, on the surfaces text sits on
                assert contrast("#9e9a8c", c[s]) >= 4.5, (t.id, "phone --mute", s)
        assert contrast(c["ink"], c["accent"]) >= 4.5, (t.id, "ink on accent")
        assert contrast(c["ink"], c["accent_hi"]) >= 4.5, (t.id, "ink on accent_hi")
        assert contrast(c["ink"], c["accent_lo"]) >= 3, (t.id, "ink on accent_lo (bold buttons only)")
        assert contrast(c["felt_ink"], c["felt"]) >= 4.5, (t.id, "text on felt")
        # studio: --cz-dim / --cz-mute are felt_ink mixed into the wing (casino.css)
        for share in (0.36, 0.44):
            tone = mix_hex(c["felt_ink"], c["wing"], share)
            for s in ("wing", "wing2", "wing3", "surface2"):
                assert contrast(tone, c[s]) >= 4.5, (t.id, share, s)


def test_classic_stylesheets_are_the_classic_theme() -> None:
    """Classic sets no variables: the phone's registered initial values must be classic's derived tokens."""
    html = PHONE.read_text(encoding="utf-8")
    props = dict(re.findall(r"@property (--[\w-]+)\{[^}]*initial-value:(#[0-9a-f]{6})\}", html))
    m = re.search(r"const THEME_VARS = \{(.*?)\};", html, re.S)
    assert m, "casino.html: THEME_VARS"
    mapping = dict(re.findall(r'"(--[\w-]+)": "(\w+)"', m.group(1)))
    css = CLASSIC.css
    assert set(mapping.values()) >= set(DERIVED) | {
        "felt",
        "felt2",
        "felt3",
        "accent",
        "accent_hi",
        "accent_lo",
        "ink",
    }
    assert set(mapping.values()) <= set(css)
    for var, key in mapping.items():
        if var in props:
            assert props[var] == css[key], (var, key)
        assert (
            re.search(re.escape(var) + r":" + re.escape(css[key]) + r"[;\s]", html)
            or var == "--gold-rgb"
            or var in props
        )


def test_phone_page_follows_the_theme_everywhere() -> None:
    html = PHONE.read_text(encoding="utf-8")
    style = html[html.index("<style>") : html.index("</style>")]
    rules = _css_rules(style, token_blocks=[r":root\{.*?\n\}"])
    stray = [h for h in _warm_literals(rules) if h not in SEMANTIC_ALLOW]
    assert not stray, f"hard-coded accent colours in casino.html (use the theme variables): {stray}"
    for t in TABLE_THEMES.values():  # no theme's accent / felt literal, no accent rgba outside the tokens
        for k in ("accent", "accent_hi", "accent_lo", "felt", "felt2", "felt3"):
            assert t.css[k] not in rules.lower(), (t.id, k)
    assert "rgba(255,204,51" not in rules and "rgba(13,107,69" not in rules and "--rose" not in html
    # applied on every state push (not only on join), browser bar follows the felt, one inline script, no on*= handlers
    assert "applyTheme(S.pub.table_theme)" in html[html.index("function onState") :][:400]
    assert 'meta[name="theme-color"]' in html
    assert html.count("<script") == 1
    assert not re.search(r"<[^>]+\son[a-z]+=", html[: html.index("<script")])
    assert "prefers-reduced-motion" in style


def test_studio_casino_follows_the_theme_everywhere() -> None:
    css = STUDIO_CSS.read_text(encoding="utf-8")
    rules = _css_rules(css, token_blocks=[r"\.cz \{.*?\n\}", r"html\[data-cz\] \{.*?\n\}"])
    rules = re.sub(
        r"var\(--[\w-]+, #[0-9a-fA-F]+\)", "", rules
    )  # var() fallbacks: the gold key outside the view
    stray = [h for h in _warm_literals(rules) if h not in SEMANTIC_ALLOW]
    assert not stray, f"hard-coded accent colours in casino.css: {stray}"
    assert "--rose" not in css and "--tang" not in css
    for tok in ("--color-ember:", "--color-chassis-2:", "--color-ink-3:", "--color-line:"):
        assert css.count(tok) >= 2, tok  # remapped inside .cz and on the page (html[data-cz])
    ts = STUDIO_TS.read_text(encoding="utf-8")
    body = ts[ts.index("export function themeVars") :]
    for k in CLASSIC.css:
        assert f"c.{k}" in body, f"state.ts themeVars/pageVars: {k}"


# ------------------------------------------------------------------ the felt's motif (css.pattern)
def _layers(value: str) -> list[str]:
    """Top-level comma-separated layers of a CSS background value."""
    out, depth, cur = [], 0, ""
    for ch in value:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [*out, cur.strip()]


def test_every_theme_has_a_concept_and_a_gradient_only_pattern() -> None:
    gradient = re.compile(r"(repeating-)?(linear|radial|conic)-gradient\(.*\)", re.S)
    names = set()
    for t in TABLE_THEMES.values():
        assert t.description and len(t.description) <= 120 and '"' not in t.description, t.id
        assert t.name not in names, t.id
        names.add(t.name)
        pat, size = t.css["pattern"], t.css["pattern_size"]
        assert pat != "none", (t.id, "every table has a motif")
        assert "url(" not in pat.lower() and "image-set" not in pat and "element(" not in pat, t.id
        assert "}" not in pat and '"' not in pat and ";" not in pat, (
            t.id
        )  # safe inside a style / the TS mirror
        layers = _layers(pat)
        assert all(gradient.fullmatch(layer) for layer in layers), (t.id, layers)
        assert pat.count("(") == pat.count(")"), t.id
        assert len(_layers(size)) == len(layers), (t.id, "one background-size entry per pattern layer")
        assert all(re.fullmatch(r"auto|[\d.]+px [\d.]+px", s) for s in _layers(size)), (t.id, size)
        for a in re.findall(r"rgba\([^)]*,\s*([\d.]+)\)", pat):  # subtle: the felt stays the felt
            assert float(a) <= 0.36, (t.id, a)


def test_the_pattern_reaches_the_phone_and_the_studio() -> None:
    html = PHONE.read_text(encoding="utf-8")
    assert "--pat:none;--pat-size:auto;" in html
    assert 'st.setProperty("--pat", css.pattern)' in html
    style = html[html.index("<style>") : html.index("</style>")]
    for sel in (".rt .felt{", ".tray{", ".pv-felt{", ".hz-top{", ".hg-felt{", "#s-join::before{"):
        rule = style[style.index(sel) :]
        rule = rule[: rule.index("}")]
        assert "var(--pat)" in rule, sel
    css = STUDIO_CSS.read_text(encoding="utf-8")
    for sel in (".cz-table {", ".cz-board {", ".cz-wing::before {", ".cz-theme > i {"):
        rule = css[css.index(sel) :]
        rule = rule[: rule.index("}")]
        assert "-pat" in rule, sel
    ts = STUDIO_TS.read_text(encoding="utf-8")
    assert '"--cz-pat": c.pattern' in ts and '"--cz-pat-size": c.pattern_size' in ts
