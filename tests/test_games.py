"""The games collection: every game plays itself, renders fast, hands over to a human and restarts."""

from __future__ import annotations

import time
from typing import Any

import pytest

from deskdot.apps.games import GAME_IDS
from deskdot.apps.games_core import THEME_LABELS, GameApp
from deskdot.engine import REGISTRY
from deskdot.gfx import Frame

FPS = 12.0


class Clock:
    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t


def _app(
    engine: Any, gid: str, settings: dict[str, Any] | None = None, seed: int = 1
) -> tuple[GameApp, Clock]:
    engine.store.section("apps")[gid] = settings or {}
    app = engine._slot(gid).app
    assert isinstance(app, GameApp)
    clock = Clock()
    app._clock = clock  # type: ignore[method-assign]
    app.rng.seed(seed)
    app.reset()
    return app, clock


def _run(app: GameApp, clock: Clock, seconds: float) -> tuple[float, float | None]:
    """Render `seconds` of wall time; return (worst render seconds, time of first game over)."""
    worst = 0.0
    first_over: float | None = None
    for i in range(int(seconds * FPS)):
        clock.t += 1 / FPS
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, i / FPS)
        worst = max(worst, time.perf_counter() - t0)
        if app.over and first_over is None:
            first_over = i / FPS
    return worst, first_over


def test_ids_registered() -> None:
    assert len(GAME_IDS) >= 11
    assert len(set(GAME_IDS)) == len(GAME_IDS)
    for gid in GAME_IDS:
        cls = REGISTRY[gid]
        assert cls.category == "games"
        assert cls.icon and cls.description and cls.name
        assert 10 <= cls.fps <= 15
        assert {a.id for a in cls.actions} >= {"restart", "demo"}


@pytest.mark.parametrize("gid", GAME_IDS)
async def test_plays_30s(engine, gid: str) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid)
    worst, _ = _run(app, clock, 30)
    assert worst < 0.05, f"{gid} render took {worst * 1000:.1f} ms"
    assert app.kind() == "stream"
    st = app.status()
    assert set(st) >= {"score", "best", "player"} and st["player"] == "ai"


@pytest.mark.parametrize("gid", GAME_IDS)
@pytest.mark.parametrize("theme", list(THEME_LABELS))
async def test_every_theme_renders(engine, gid: str, theme: str) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid, {"theme": theme, "speed": 10, "show_score": theme != "mono"})
    _run(app, clock, 4)


@pytest.mark.parametrize("gid", GAME_IDS)
async def test_ai_survives(engine, gid: str) -> None:  # type: ignore[no-untyped-def]
    """A skilled demo AI lasts a reasonable time (best of three seeds, so the test isn't flaky)."""
    best = 0.0
    for seed in (1, 2, 3):
        app, clock = _app(engine, gid, {"skill": 1.0}, seed=seed)
        _, first = _run(app, clock, 20)
        best = max(best, 20.0 if first is None else first)
        if best >= 8:
            break
    assert best >= 8, f"{gid} AI died after {best:.1f} s"


@pytest.mark.parametrize("gid", GAME_IDS)
async def test_input_switches_to_human_and_back(engine, gid: str) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid)
    _run(app, clock, 1)
    for key in ("left", "up", "a", "right", "down", "b", "space", "ArrowUp"):
        res = await app.action("input", {"key": key})
        assert res["player"] == "you"
        _run(app, clock, 0.3)
    assert app.status()["player"] == "you"
    _run(app, clock, 11)  # idle → the AI takes over again
    assert app.status()["player"] == "ai"
    await app.action("input", {"key": "left"})
    await app.action("demo", {})
    assert app.status()["player"] == "ai"


@pytest.mark.parametrize("gid", GAME_IDS)
async def test_restart_and_best(engine, gid: str) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid)
    _run(app, clock, 5)
    app.score = 99999
    app.game_over()
    assert app.over and app.best >= app.best_candidate()
    if app.best_candidate() == 99999:
        assert app.ctx.data["best"] == 99999
    res = await app.action("restart", {})
    assert not app.over and res["score"] == 0
    with pytest.raises(KeyError):
        await app.action("nope", {})


async def test_game_over_card_then_auto_restart(engine) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "g2048")
    app.game_over()
    _run(app, clock, 1)
    assert app.over
    _run(app, clock, 3)
    assert not app.over and app.score > 0
