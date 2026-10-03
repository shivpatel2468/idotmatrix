"""Rock Paper Scissors: rules, best-of matches, tournaments, fair AI, phones, the fly and render speed."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot.apps import games_rps as rps
from deskdot.apps.games_rps import PAPER, ROCK, SCISSORS, RockPaperScissors, Tournament, counter, judge
from deskdot.config import Config
from deskdot.gfx import Frame
from deskdot.server import create_app

FPS = 6.0


class Ctx:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def save(self) -> None: ...


class Clock:
    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t


def _make(**settings: Any) -> tuple[RockPaperScissors, Clock]:
    app = RockPaperScissors(Ctx(), RockPaperScissors.Settings(**settings))  # type: ignore[arg-type]
    clock = Clock()
    app._clock = clock  # type: ignore[method-assign]
    app.reset()
    return app, clock


def _render(app: RockPaperScissors, clock: Clock, seconds: float, fps: float = FPS) -> float:
    worst = 0.0
    for _ in range(max(1, int(seconds * fps))):
        clock.t += 1 / fps
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, clock.t)
        worst = max(worst, time.perf_counter() - t0)
    return worst


def _until(app: RockPaperScissors, clock: Clock, cond: Any, limit: float = 30.0) -> None:
    waited = 0.0
    while not cond():
        _render(app, clock, 0.25, 8)
        waited += 0.25
        assert waited < limit, f"stuck in {app.flow}/{app.phase}"


async def _start(app: RockPaperScissors, clock: Clock, **payload: Any) -> None:
    await app.action("start", payload)
    assert app.flow == "intro"
    _render(app, clock, 3)
    assert app.flow == "play"


async def _round(app: RockPaperScissors, clock: Clock, mine: int, theirs: int) -> None:
    """Play one round of You vs AI: the AI's pick is forced (test only) before it locks, the host picks `mine`."""
    _until(app, clock, lambda: app.phase == "pick")
    assert 2 not in app.locked
    app.ai_pick[2] = theirs
    await app.action("input", {"key": {ROCK: "left", PAPER: "up", SCISSORS: "right"}[mine]})
    _until(app, clock, lambda: app.phase in ("reveal", "champ") or app.flow != "play")


# ------------------------------------------------------------------ rules
@pytest.mark.parametrize(
    ("a", "b", "expect"),
    [
        (ROCK, ROCK, 0),
        (ROCK, PAPER, 2),
        (ROCK, SCISSORS, 1),
        (PAPER, ROCK, 1),
        (PAPER, PAPER, 0),
        (PAPER, SCISSORS, 2),
        (SCISSORS, ROCK, 2),
        (SCISSORS, PAPER, 1),
        (SCISSORS, SCISSORS, 0),
    ],
)
def test_every_pairing(a: int, b: int, expect: int) -> None:
    assert judge(a, b) == expect
    assert judge(counter(a), a) == 1, "counter() names the move that beats it"


async def test_reveal_scores_the_round() -> None:
    app, clock = _make()
    await _start(app, clock, mode="cpu")
    await _round(app, clock, PAPER, ROCK)
    assert app.phase == "reveal" and app.last == {"a": PAPER, "b": ROCK, "winner": 1}
    assert app.wins == {1: 1, 2: 0}
    st = app.status()["rps"]
    assert st["picks"] == {"1": "paper", "2": "rock"} and st["winner"] == 1


# ------------------------------------------------------------------ best of N
@pytest.mark.parametrize(("best_of", "need"), [("1", 1), ("3", 2), ("5", 3), ("7", 4)])
async def test_best_of_is_first_to_n_and_draws_dont_count(best_of: str, need: int) -> None:
    app, clock = _make(best_of=best_of)
    await _start(app, clock, mode="cpu")
    assert app.first_to == need
    await _round(app, clock, ROCK, ROCK)  # a draw: replay, nobody scores
    assert app.wins == {1: 0, 2: 0} and app.flow == "play"
    wins = ((ROCK, SCISSORS), (PAPER, ROCK), (SCISSORS, PAPER))
    for i in range(need - 1):
        await _round(app, clock, *wins[i % 3])
        assert app.wins[1] == i + 1
    assert app.flow == "play" and app.champ_seat is None
    await _round(app, clock, SCISSORS, PAPER)  # the deciding round
    assert app.champ_seat == 1 or app.wins[1] >= need
    _until(app, clock, lambda: app.flow == "outro")
    assert app.outcome and app.outcome["seat"] == 1
    assert app.status()["rps"]["champion"] == 1
    _render(app, clock, 1)
    await app.action("input", {"key": "a"})  # rematch
    assert app.flow == "intro"
    _render(app, clock, 3)
    assert app.wins == {1: 0, 2: 0}


async def test_slow_human_gets_a_random_hand() -> None:
    app, clock = _make(round_timer=3)
    await _start(app, clock, mode="cpu")
    _until(app, clock, lambda: app.phase == "pump", limit=6)
    assert app.timed_out == {1} and 1 in app.locked


# ------------------------------------------------------------------ tournaments
def _finish(t: Tournament, prefer: int | None = None) -> list[tuple[int, int]]:
    played = []
    while (m := t.next_match()) is not None:
        a, b = m
        w = prefer if prefer in m else a
        t.record(a, b, w, 2, 1 if w == a else 0)
        played.append(m)
    return played


@pytest.mark.parametrize("n", [3, 4, 5, 6, 7, 8])
def test_knockout_bracket(n: int) -> None:
    t = Tournament("knockout", list(range(1, n + 1)))
    assert sorted(t.entrants) == list(range(1, n + 1))
    assert t.size >= n and t.size & (t.size - 1) == 0
    firsts = t.rounds[0]
    assert all(g[0] is not None for g in firsts), "never a bye against a bye"
    played = _finish(t, prefer=3)
    assert len(played) == n - 1, "a knockout needs n - 1 matches"
    assert t.champion() == 3, "the player who wins every match takes the cup"
    assert len(t.rounds[-1]) == 1
    seen = Counter(s for m in played for s in m)
    assert seen[3] == len(t.rounds) - sum(1 for g in firsts if g[1] is None and g[0] == 3)
    assert not t.alive(next(s for s in t.entrants if s != 3))
    assert t.done_count() == (n - 1, n - 1)


def test_knockout_advances_round_by_round() -> None:
    t = Tournament("knockout", [1, 2, 3, 4])
    a, b = t.next_match()  # type: ignore[misc]
    t.record(a, b, a)
    assert len(t.rounds) == 1, "the final waits until the semi-finals are done"
    c, d = t.next_match()  # type: ignore[misc]
    t.record(c, d, d)
    assert len(t.rounds) == 2 and t.rounds[1][0][:2] == [a, d]
    assert t.next_match() == (a, d)
    t.record(a, d, d)
    assert t.champion() == d and t.next_match() is None


@pytest.mark.parametrize("n", [3, 4, 5, 8])
def test_round_robin(n: int) -> None:
    t = Tournament("robin", list(range(1, n + 1)))
    pairs = {frozenset(g[:2]) for g in t.games}
    assert len(t.games) == n * (n - 1) // 2 == len(pairs), "everyone meets everyone once"
    assert t.champion() is None
    _finish(t, prefer=2)
    table = t.standings()
    assert table[0]["seat"] == 2 and table[0]["wins"] == n - 1
    assert all(r["played"] == n - 1 for r in table)
    assert t.champion() == 2


@pytest.mark.parametrize("fmt", ["knockout", "robin"])
async def test_tournament_plays_to_a_champion(fmt: str) -> None:
    """Host + AI: AI-only matches are simulated, the host's matches are played; a champion is crowned."""
    app, clock = _make(best_of="1", speed=10)
    await _start(app, clock, mode="tour", players=5, map=fmt)
    t = app.tour
    assert t is not None and len(t.entrants) == 5 and app.roster[1]["human"]
    assert sum(r["human"] for r in app.roster.values()) == 1
    assert app.phase == "bracket" and 1 in app.pair, "the next match shown is one with a person in it"
    for _ in range(40):
        if app.flow != "play":
            break
        _until(app, clock, lambda: app.phase == "pick" or app.flow != "play", limit=20)
        if app.flow != "play":
            break
        assert 1 in app.pair
        await app.action("input", {"key": "left"})
        _until(app, clock, lambda: app.phase != "pick" or app.flow != "play", limit=20)
    _until(app, clock, lambda: app.flow == "outro", limit=30)
    assert t.champion() is not None and app.outcome and app.outcome["seat"] == t.champion()
    snap = app.status()["rps"]["tour"]
    assert snap["format"] == fmt
    _render(app, clock, 2)  # the champion screen renders


# ------------------------------------------------------------------ fair AI
def test_random_ai_is_uniform() -> None:
    app, _ = _make(ai_style="random")
    app.hist = {1: [ROCK] * 30}  # even a predictable opponent doesn't bias the random style
    n = 6000
    counts = Counter(app._ai_choose(2, 1) for _ in range(n))
    exp = n / 3
    chi2 = sum((counts[m] - exp) ** 2 / exp for m in (ROCK, PAPER, SCISSORS))
    assert chi2 < 20, f"not uniform: {counts} (chi² {chi2:.1f}, df 2)"


def test_the_ai_uses_a_csprng() -> None:
    import secrets

    assert isinstance(rps._SR, secrets.SystemRandom)


def test_pattern_ai_punishes_repeats_but_not_randomness() -> None:
    app, _ = _make(ai_style="pattern")
    app.hist = {1: [ROCK] * 20}
    picks = Counter(app._ai_choose(2, 1) for _ in range(600))
    assert picks[PAPER] > 0.7 * 600, f"rock every time is punished with paper: {picks}"
    app.hist = {1: []}
    picks = Counter(app._ai_choose(2, 1) for _ in range(600))
    assert min(picks.values()) > 120, "with no history it plays uniformly"


def test_cheeky_ai_gives_mostly_honest_tells() -> None:
    app, _ = _make(ai_style="cheeky")
    honest = 0
    for _ in range(600):
        app._start_pick()
        honest += app.tell[2] == app.ai_pick[2]
    assert 0.55 < honest / 600 < 0.8


async def test_the_ai_cannot_peek() -> None:
    """Every AI pick is fixed when the round starts — the opponent's input is never read to make it."""
    app, clock = _make(ai_style="pattern", best_of="7")
    await _start(app, clock, mode="cpu")
    calls: list[tuple[int, int]] = []
    orig = app._ai_choose

    def spy(seat: int, opp: int) -> int:
        calls.append((seat, opp))
        return orig(seat, opp)

    app._ai_choose = spy  # type: ignore[method-assign]
    for mine in (ROCK, PAPER, SCISSORS, ROCK, ROCK):
        _until(app, clock, lambda: app.phase == "pick" or app.flow != "play")
        if app.flow != "play":
            break  # the match is over
        _render(app, clock, 0.1)
        fixed = app.ai_pick[2]
        n_calls = len(calls)
        hist_before = list(app.hist.get(1, []))
        status = app.status()["rps"]
        assert "picks" not in status and "rock" not in json.dumps(
            {k: v for k, v in status.items() if k not in ("art", "keys")}
        )
        await app.action("input", {"key": {ROCK: "left", PAPER: "up", SCISSORS: "right"}[mine]})
        assert app.status()["rps"]["locked"] == [1] or 2 in app.locked
        _until(app, clock, lambda: app.phase in ("reveal", "champ") or app.flow != "play")
        assert len(calls) == n_calls, "no AI pick is made after the round started"
        assert app.last["b"] == fixed, "the AI threw what it chose before the human picked"
        assert app.hist[1][: len(hist_before)] == hist_before
        if app.flow != "play":
            break


# ------------------------------------------------------------------ input paths
async def test_keyboard_aliases_and_random_pick() -> None:
    app, clock = _make()
    for key, move in (("1", ROCK), ("2", PAPER), ("3", SCISSORS), ("r", ROCK), ("p", PAPER), ("s", SCISSORS)):
        await _start(app, clock, mode="cpu")
        _until(app, clock, lambda: app.phase == "pick")
        await app.action("input", {"key": key})
        assert app.locked[1] == move
        await app.action("input", {"key": "up"})
        assert app.locked[1] == move, "a locked hand is final"
    await _start(app, clock, mode="cpu")
    _until(app, clock, lambda: app.phase == "pick")
    await app.action("input", {"key": "down"})
    assert app.locked[1] in (ROCK, PAPER, SCISSORS)


async def test_phone_picks_in_one_v_one() -> None:
    app, clock = _make()
    await app.action(
        "seat", {"player": 2, "joined": True, "name": "MAX", "color": "#50ff78", "avatar": "cat"}
    )
    await _start(app, clock, mode="pvp")
    assert app.pair == (1, 2) and app._human(2)
    _until(app, clock, lambda: app.phase == "pick")
    _render(app, clock, 5)  # people take their time: nobody is auto-picked before the timer
    assert app.locked == {}
    await app.action("input", {"key": "up", "player": 2})
    assert app.locked == {2: PAPER}
    st = app.status()["rps"]
    assert st["locked"] == [2] and "picks" not in st, "the other phone only learns that P2 locked in"
    assert st["players"]["2"]["name"] == "MAX" and st["players"]["2"]["color"] == "#50ff78"
    await app.action("input", {"key": "left", "player": 1})
    _until(app, clock, lambda: app.phase == "reveal")
    assert app.last["winner"] == 2


async def test_two_phones_play_while_the_host_watches() -> None:
    app, clock = _make()
    for seat, name in ((2, "ANA"), (3, "BO")):
        await app.action("seat", {"player": seat, "joined": True, "name": name})
    await _start(app, clock, mode="pvp")
    assert app.pair == (2, 3)
    _until(app, clock, lambda: app.phase == "pick")
    await app.action("input", {"key": "left", "player": 1})  # the host isn't playing
    assert 1 not in app.locked
    await app.action("input", {"key": "right", "player": 2})
    await app.action("input", {"key": "up", "player": 3})
    _until(app, clock, lambda: app.phase == "reveal")
    assert app.last == {"a": SCISSORS, "b": PAPER, "winner": 2}


async def test_phones_watch_the_demo() -> None:
    app, clock = _make()
    await app.action("seat", {"player": 2, "joined": True})
    _until(app, clock, lambda: app.phase == "pick")
    await app.action("input", {"key": "up", "player": 2})
    assert app.locked.get(2) != PAPER or 2 in app.by_ai, "a phone can't play the demo's AI hand"


def test_phone_controller_over_the_websocket(tmp_path: Path) -> None:
    c = TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))
    with c:
        code = c.post("/api/play/lobby", json={"app": "rps"}).json()["code"]
        page = c.get(f"/p/{code}").text
        assert 'data-m="rps"' in page and "function renderRps" in page
        with c.websocket_connect(f"/ws/p/{code}?cid=phone-rps-0001") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello" and hello["seat"] == 2 and hello["controls"][0] == "rps"
            assert c.post("/api/play/lobby/start").status_code == 200
            r = c.post("/api/apps/rps/actions/start", json={"mode": "pvp"})
            assert r.status_code == 200
            game = c.app.state.engine._slot("rps").app  # type: ignore[attr-defined]
            assert game.pair == (1, 2)
            game.flow = "play"  # skip the 3-2-1 intro
            game._start_pick()
            ws.send_text(json.dumps({"k": "right"}))
            ws.send_text(json.dumps({"type": "ping", "t": 1}))
            state, pong = None, False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not (pong and state):
                m = ws.receive_json()
                if m["type"] == "state" and m["status"].get("rps"):
                    state = m["status"]["rps"]
                pong = pong or m["type"] == "pong"
            assert game.locked.get(2) == SCISSORS, "the phone's tap locked scissors"
            assert state is not None and set(state["art"]) == {"rock", "paper", "scissors"}


# ------------------------------------------------------------------ the fruit fly
def test_the_fly_plays_rps() -> None:
    app, clock = _make(pilot="fly")
    by_fly = 0
    rounds = 0
    seen_round = -1
    for _ in range(900):
        clock.t += 1 / 12
        app.render(Frame(), clock.t)
        if app.phase == "pump" and app.round_no != seen_round:
            seen_round = app.round_no
            rounds += 1
            by_fly += 1 not in app.timed_out and 1 not in app.by_ai
    assert rounds >= 5
    assert by_fly >= 1, "the fly's neurons picked a hand themselves"
    assert app.status()["player"] == "fly"
    assert app.name_of(1) == "FLY"


# ------------------------------------------------------------------ rendering
MODES = [("attract", {}), ("cpu", {}), ("pvp", {}), ("demo", {}), ("tour", {"players": 6})]


@pytest.mark.parametrize("reveal", ["shoot", "count", "instant"])
@pytest.mark.parametrize(("mode", "extra"), MODES)
async def test_every_phase_renders_fast(mode: str, extra: dict[str, Any], reveal: str) -> None:
    app, clock = _make(reveal=reveal, ai_style="cheeky", best_of="3", speed=10)
    if mode != "attract":
        await app.action("start", {"mode": mode, **extra})
        if mode == "tour":
            app.roster[1]["human"] = False  # let the AI play the host's matches too
    phases: set[str] = set()
    worst = _render(app, clock, 0.5)
    for _ in range(int(60 * FPS)):
        worst = max(worst, _render(app, clock, 1 / FPS))
        phases.add(app.phase if app.flow in ("play", "attract") else app.flow)
        if app.flow == "outro":
            worst = max(worst, _render(app, clock, 1))
            break
    assert worst < 0.05, f"{mode} render took {worst * 1000:.1f} ms"
    assert {"pick", "pump", "reveal"} <= phases, phases
    if mode == "attract":
        assert "champ" in phases and "vs" in phases
    elif mode == "tour":
        assert "bracket" in phases


@pytest.mark.parametrize("theme", ["arena", "party", "classic", "neon", "retro", "mono"])
@pytest.mark.parametrize("effects", ["full", "calm", "minimal"])
def test_themes_and_effects_render(theme: str, effects: str) -> None:
    app, clock = _make(theme=theme, effects=effects)
    _render(app, clock, 12)
    f = Frame()
    app.render(f, clock.t)
    assert f.px.any()


def test_sprites_stay_on_the_panel() -> None:
    for move in (ROCK, PAPER, SCISSORS):
        _px, mask = rps.hand_sprite(move, (0, 200, 255), False)
        h, w = mask.shape
        assert w <= 15 and h <= 14, "two hands fit side by side with a gap"
        assert mask[:, -1].any(), "the hand reaches towards the opponent"
    assert rps.word_width("SCISSORS") <= 30
