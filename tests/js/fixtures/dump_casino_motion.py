"""Reference motion from the panel apps, for the TV ports in src/deskdot/tv/tv-casino.js.

Run: ``uv run python tests/js/fixtures/dump_casino_motion.py`` → tests/js/fixtures/casino_motion.json. The JS test
(tests/js/tv_casino.test.mjs) checks that the TV computes the same wheel / ball / dice / reel / card timing as the
panel for the same `since_lock`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import deskdot.apps  # noqa: F401 — registers built-in apps
from deskdot.apps._casino import View
from deskdot.apps.casino_bigsix import SPIN_T, wheel_angle, wheel_params
from deskdot.apps.casino_roulette import wheel_step
from deskdot.apps.casino_slots import reel_pos
from deskdot.casino.games.andarbahar import DEAL_LEAD, deal_pace
from deskdot.casino.games.baccarat import Baccarat
from deskdot.engine.app import REGISTRY

OUT = Path(__file__).with_name("casino_motion.json")
TS = [round(i * 0.173, 3) for i in range(70)]  # 0 … 11.9 s since the lock


def _app(app_id: str, **settings: Any) -> Any:
    cls = REGISTRY[app_id]
    return cls(object(), cls.Settings(**settings))


def roulette() -> dict[str, Any]:
    out: dict[str, Any] = {"ball": [], "step": []}
    for wheel in ("european", "american"):
        app = _app("casino_roulette", wheel=wheel)
        n = len(app.wheel)
        for pocket in (0, 17, n - 1):
            for t in TS:
                b = app.ball(View(phase="spinning", since_lock=t, outcome={"pocket": pocket}), 0.0)
                out["ball"].append({"n": n, "pocket": pocket, "t": t, "a": b[0], "r": b[1]})
    for s in (None, 0.0, 0.05, 0.4, 2.0, 7.9, 30.0):
        for dt in (0.0, 0.016, 0.1, 0.3):
            out["step"].append({"since_lock": s, "dt": dt, "d": wheel_step(s, dt)})
    return out


def bigsix() -> list[dict[str, Any]]:
    out = []
    for seg, nonce in ((0, 1), (27, 2), (41, 77)):
        end, travel = wheel_params(seg, nonce)
        for t in TS:
            out.append({"seg": seg, "end": end, "travel": travel, "stop_s": SPIN_T, "ts": t - 1.0,
                        "phi": wheel_angle(t - 1.0, seg, nonce)})  # fmt: skip
    return out


def sevens() -> list[dict[str, Any]]:
    app = _app("casino_sevens")
    out = []
    for dice, nonce in (([2, 6], 3), ([6, 1], 9)):
        o = {"dice": dice, "sum": sum(dice), "zone": "up"}
        faces = app.tv_reveal_extra(o, nonce)["faces"]
        for t in TS[:30]:
            v = View(phase="spinning", since_lock=t, outcome=o, nonce=nonce)
            out.append({"dice": dice, "faces": faces, "t": t, "at": [list(d) for d in app.dice_at(v)]})
    return out


def slots() -> list[dict[str, Any]]:
    return [
        {"stop": stop, "n": n, "t": t, "i": i, "pos": reel_pos(stop, n, t, i)}
        for stop, n in ((3, 20), (17, 18))
        for i in range(3)
        for t in TS[:24]
    ]


def deals() -> dict[str, Any]:
    o3 = {"player": ["2S", "3S", "4S"], "banker": ["KS", "5H", "9C"]}
    o2 = {"player": ["9S", "KS"], "banker": ["8H", "QC"]}
    return {
        "baccarat": [[list(x) for x in Baccarat.deal_times(o)] for o in (o2, o3)],
        "andar": {"lead": DEAL_LEAD, "pace": {str(n): deal_pace(n) for n in (1, 2, 5, 12, 30, 49)}},
    }


if __name__ == "__main__":
    data = {
        "roulette": roulette(),
        "bigsix": bigsix(),
        "sevens": sevens(),
        "slots": slots(),
        "deals": deals(),
    }
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(OUT, {k: len(v) for k, v in data.items()})
