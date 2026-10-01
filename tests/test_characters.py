"""Character sprite library and the Pet app."""

from __future__ import annotations

import itertools
import time
from typing import Any

import numpy as np
import pytest

from deskdot.gfx import Frame
from deskdot.gfx.characters import (
    ACCESSORIES,
    ANIMS,
    CHARACTERS,
    GROUPS,
    Character,
    draw_character,
    list_characters,
)

REQUIRED = (
    "idle",
    "walk",
    "run",
    "jump",
    "dance",
    "sleep",
    "sit",
    "eat",
    "happy",
    "sad",
    "wave",
    "kick",
    "work",
)
GROUP_EXTRAS = {
    "troops": ("attack",),
    "fps": ("shoot", "reload", "crouch"),
    "monsters": ("attack",),
    "claude": ("think",),
}
TIMES = (0.0, 0.13, 0.41, 0.9, 1.7, 3.3, 7.9)


def test_library_shape() -> None:
    assert len(CHARACTERS) >= 40
    assert set(GROUPS) == {"claude", "dogs", "cats", "critters", "monsters", "troops", "fps", "tv", "sports"}
    assert "none" in ACCESSORIES
    for c in CHARACTERS.values():
        assert isinstance(c, Character)
        assert c.group in GROUPS and c.name and c.description
        assert 1 <= c.w <= 20 and 1 <= c.h <= 20
        assert len(c.slots) >= 2  # body + eyes at least (Clawd is deliberately one flat colour)
        for rgb in c.slots.values():
            assert len(rgb) == 3 and all(0 <= v <= 255 for v in rgb)
        assert set(c.anims) <= set(ANIMS)
    for g in GROUPS:
        assert list_characters(g), f"group {g} is empty"
    assert len(list_characters()) == len(CHARACTERS)
    assert {"clawd", "claude_mini"} <= set(CHARACTERS)


@pytest.mark.parametrize("cid", list(CHARACTERS))
def test_required_anims(cid: str) -> None:
    c = CHARACTERS[cid]
    for a in REQUIRED + GROUP_EXTRAS.get(c.group, ()):
        assert a in c.anims, f"{cid} lacks {a}"


@pytest.mark.parametrize("cid", list(CHARACTERS))
def test_every_anim_renders(cid: str) -> None:
    c = CHARACTERS[cid]
    for a in c.anims:
        for t in TIMES:
            f = Frame()
            bbox = draw_character(f, cid, a, t, 8, 8)
            assert bbox == (8, 8, c.w, c.h)
            assert f.px.any(), f"{cid}/{a} at t={t} drew nothing"
            # the character's own box holds most of what was drawn
            inside = f.px[8 : 8 + c.h, 8 : 8 + c.w].any(axis=2).sum()
            assert inside > 12, f"{cid}/{a} at t={t} barely drew inside its box"


def test_unknown_anim_falls_back_to_idle() -> None:
    a, b = Frame(), Frame()
    draw_character(a, "clawd", "no-such-anim", 0.0, 8, 8)
    draw_character(b, "clawd", "idle", 0.0, 8, 8)
    assert a == b


def test_clipping_is_safe() -> None:
    for x, y in ((-40, -40), (-10, 20), (28, 28), (100, 5)):
        f = Frame()
        draw_character(f, "knight", "attack", 0.5, x, y, scale=2)
        draw_character(f, "shiba", "kick", 1.0, x, y)


def test_recolour() -> None:
    base, red = Frame(), Frame()
    draw_character(base, "clawd", "idle", 0.0, 8, 8)
    draw_character(red, "clawd", "idle", 0.0, 8, 8, colors={"body": "#00ff00"})
    assert base != red
    assert (red.px == np.array([0, 255, 0], np.uint8)).all(axis=2).sum() > 40
    # unknown slots and bad colours are ignored
    junk = Frame()
    draw_character(junk, "clawd", "idle", 0.0, 8, 8, colors={"nope": "#ffffff", "body": "zzz"})
    assert junk == base


def test_scale_two_and_flip() -> None:
    f1, f2 = Frame(), Frame()
    draw_character(f1, "pug", "idle", 0.0, 8, 8)
    bbox = draw_character(f2, "pug", "idle", 0.0, 0, 0, scale=2)
    assert bbox == (0, 0, 32, 32)
    assert f2.px.any(axis=2).sum() > 3 * f1.px.any(axis=2).sum()
    a, b = Frame(), Frame()
    draw_character(a, "pug", "idle", 0.0, 8, 8)
    draw_character(b, "pug", "idle", 0.0, 8, 8, flip=True)
    assert np.array_equal(a.px[8:24, 8:24], b.px[8:24, 8:24][:, ::-1])


def test_accessories_render() -> None:
    for acc in ACCESSORIES:
        for cid in ("clawd", "knight", "shiba", "bunny", "grin_ghost"):
            f = Frame()
            draw_character(f, cid, "walk", 0.3, 0, 0, scale=2, accessory=acc)
            assert f.px.any()
    plain, hat = Frame(), Frame()
    draw_character(plain, "knight", "idle", 0.0, 8, 8)
    draw_character(hat, "knight", "idle", 0.0, 8, 8, accessory="crown")
    assert plain != hat


def test_beat_bounces_dance() -> None:
    a, b = Frame(), Frame()
    draw_character(a, "clawd", "dance", 0.0, 0, 0, scale=2, beat=0.0)
    draw_character(b, "clawd", "dance", 0.0, 0, 0, scale=2, beat=1.0)
    assert a != b


def test_draw_is_fast() -> None:
    ids = list(CHARACTERS)
    for cid in ids:  # warm the caches, as a running app would
        for a in CHARACTERS[cid].anims:
            draw_character(Frame(), cid, a, 0.2, 8, 8)
    f = Frame()
    n = 0
    t0 = time.perf_counter()
    for i in range(3):
        for cid in ids:
            for a in CHARACTERS[cid].anims:
                draw_character(f, cid, a, i * 0.37, 8, 8, scale=1 + i % 2)
                n += 1
    avg = (time.perf_counter() - t0) / n
    assert avg < 0.001, f"average draw {avg * 1000:.3f} ms"


# ----------------------------------------------------------------------------------------------- Pet app
class _Provider:
    def __init__(self, value: Any) -> None:
        self.value = value
        self.error = None


class _Ctx:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    def provider(self, _name: str) -> _Provider:
        return _Provider(self.value)


def _app(value: Any = None, **settings: Any):  # type: ignore[no-untyped-def]
    from deskdot.apps.pets import Pet, PetSettings

    return Pet(_Ctx(value), PetSettings(**settings))  # type: ignore[arg-type]


def test_pet_app_registers() -> None:
    from deskdot.apps.pets import Pet
    from deskdot.engine import REGISTRY

    assert REGISTRY["pet"] is Pet
    assert Pet.uses == ("audio",)
    Pet.meta()


@pytest.mark.parametrize("scene", ["none", "grass", "room", "night", "beach", "space", "stage", "snow"])
def test_pet_scenes_and_alive(scene: str) -> None:
    for sc in ("1", "2"):
        app = _app(None, scene=scene, scale=sc, name="REX", character="shiba", accessory="cap")
        worst = 0.0
        for t in (0.0, 0.7, 3.1, 11.4, 62.0, 400.0, 5000.0):
            f = Frame()
            t0 = time.perf_counter()
            app.render(f, t)
            worst = max(worst, time.perf_counter() - t0)
            assert f.px.any()
        assert worst < 0.05


def test_pet_every_choice_renders() -> None:
    from deskdot.apps.pets import PetSettings

    for name, field in PetSettings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            for opt in extra["enum"]:
                f = Frame()
                _app(None, **{name: opt}).render(f, 1.3)
                assert f.px.any(), f"{name}={opt} drew nothing"


def test_pet_alive_is_deterministic_and_varied() -> None:
    a, b = _app(), _app()
    seen = set()
    for i in range(0, 600, 3):
        fa, fb = Frame(), Frame()
        a.render(fa, i * 0.5)
        b.render(fb, i * 0.5)
        assert fa == fb
        seen.add(a.status()["animation"])
    assert len(seen) >= 5, seen


def test_pet_music_sync() -> None:
    quiet = {"bands": [0.0] * 32, "level": 0.0}
    loud = {"bands": [0.9] * 32, "level": 0.3}
    beat = {"bands": [0.2] * 32, "level": 0.2, "beat": 1.0, "bpm": 120.0}
    for val in (None, quiet, loud, beat, {"weird": True}):
        app = _app(val, music_sync=True)
        app.render(Frame(), 2.0)
    app = _app(loud, music_sync=True)
    app.render(Frame(), 2.0)
    assert app.status()["animation"] == "dance"
    app = _app(quiet, music_sync=True, animation="sleep")
    app.render(Frame(), 2.0)
    assert app.status()["animation"] == "sleep"


def test_pet_custom_colours() -> None:
    plain = Frame()
    _app(animation="idle").render(plain, 0.0)
    custom = Frame()
    _app(animation="idle", use_custom_colors=True, primary="#00ff00").render(custom, 0.0)
    assert plain != custom


def test_step_anim_time_never_skips_a_pose() -> None:
    from deskdot.gfx.characters import step_anim_time
    from deskdot.gfx.characters.build import RIGS

    an = RIGS["clawd"].anims["walk"]
    starts = [fr[0] for fr in an._norm]
    for t0 in (0.0, 100.0, 12345.678):  # large clocks expose float drift at pose boundaries
        t, seen = t0, []
        for _ in range(40):  # 6 fps, slower than the 0.14 s walk poses
            t = step_anim_time("clawd", "walk", t, 1 / 6)
            tt = t % an.total
            seen.append(max(i for i, s in enumerate(starts) if s <= tt))
        steps = [(b - a) % len(starts) for a, b in itertools.pairwise(seen)]
        assert set(steps) <= {0, 1}, f"poses skipped from t0={t0}: {steps}"
        assert steps.count(1) >= 30, f"clock stalled from t0={t0}: {seen}"  # legs must keep moving
    assert step_anim_time("clawd", "sleep", 0.0, 0.1) == 0.1  # long poses hold real time
