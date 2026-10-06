"""`CasinoSession`: the party. Players, the bank, the house settings, the table in play, history and leaderboard.

One session per engine (`AppContext.shared("casino", CasinoSession)`), shared by every casino app, so credits
follow players from roulette to dice to blackjack. Persisted in the store section ``casino``:

* ``wallets`` / ``ledger`` — the bank (`bank.py`);
* ``house`` — base credits, table limits and timers (`House`);
* ``nonce`` — the round counter (never reused);
* ``history`` — the last rounds with their fairness proofs (revealed seeds), newest last.

Players are identified by a **pid**: ``"host"`` for the studio, otherwise a stable id the server derives from the
phone's client id (so a phone that drops and comes back — even on another seat — finds its credits again).
Lobby seats map to pids while the phone is connected.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

from . import fair
from .bank import Bank
from .chips import chip_rack

if TYPE_CHECKING:
    from .table import CasinoGame, RoundResult

HOST = "host"
HISTORY_MAX = 60
HOST_OPS = (
    "start_round",
    "lock",
    "settings",
    "credits",
    "kick",
    "pause",
    "reset_session",
    "verify",
)


class House(BaseModel):
    """The host's table settings, shared by every casino game."""

    base_credits: int = Field(1000, ge=0, le=1_000_000, title="Starting credits")
    min_bet: int = Field(1, ge=1, le=100_000, title="Table minimum (per bet)")
    max_bet: int = Field(500, ge=1, le=1_000_000, title="Table maximum (per bet)")
    bet_seconds: int = Field(20, ge=5, le=180, title="Betting time (from the first chip)")
    result_seconds: int = Field(7, ge=3, le=60, title="Result shown for")
    turn_seconds: int = Field(20, ge=5, le=120, title="Turn time (card games)")
    auto_next: bool = Field(True, title="Open the next round automatically")


@dataclass
class Player:
    pid: str
    seat: int | str  # lobby seat (2…) or "host"
    name: str = ""
    color: str = "#f0f0f0"
    avatar: str = ""
    client_seed: str = ""
    online: bool = True
    kicked: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "name": self.name,
            "color": self.color,
            "avatar": self.avatar,
            "online": self.online,
        }


class CasinoSession:
    def __init__(
        self,
        section: dict[str, Any] | None = None,
        save: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.section: dict[str, Any] = section if section is not None else {}
        self._save = save or (lambda: None)
        self.clock = clock
        self.bank = Bank(self.section, self._save)
        self.house = _load_house(self.section.get("house"))
        n = self.section.get("nonce")
        self.nonce = n if type(n) is int and n >= 0 else 0
        h = self.section.get("history")
        self.history: list[dict[str, Any]] = (
            [e for e in h if isinstance(e, dict)][-HISTORY_MAX:] if isinstance(h, list) else []
        )
        self.players: dict[str, Player] = {}
        self.game: CasinoGame | None = None
        self.paused = False
        self._paused_at = 0.0
        self.version = 0  # bumps on every change (apps use it to know when to re-render / re-push)
        self._notes: dict[str, tuple[int, str, str]] = {}  # pid -> (id, text, kind)
        self._note_id = 0

    # ------------------------------------------------------------ persistence
    def save(self) -> None:
        self.section["house"] = self.house.model_dump()
        self.section["nonce"] = self.nonce
        self.section["history"] = self.history[-HISTORY_MAX:]
        self._save()

    def changed(self) -> None:
        self.version += 1

    def next_nonce(self) -> int:
        self.nonce += 1
        self.save()
        return self.nonce

    # ----------------------------------------------------------------- tables
    def use(self, game: CasinoGame) -> None:
        """`game` is the table in play now. The previous table closes (open bets refunded)."""
        if self.game is not None and self.game is not game:
            self.game.abort()
        self.game = game
        self.changed()

    def release(self, game: CasinoGame) -> None:
        """The app showing `game` stopped: close the table so no bets stay in escrow."""
        if self.game is game:
            game.abort()
            self.game = None
            self.changed()

    # ---------------------------------------------------------------- players
    def join(
        self,
        pid: str,
        seat: int | str,
        name: str = "",
        color: str = "",
        avatar: str = "",
    ) -> Player:
        """A phone sat down (or updated its profile). First visit: a wallet with the base credits."""
        # a seat belongs to one pid: whoever had it before is gone
        for other in list(self.players.values()):
            if other.seat == seat and other.pid != pid:
                other.online = False
                other.seat = 0
        p = self.players.get(pid)
        if p is None:
            p = self.players[pid] = Player(pid=pid, seat=seat)
        p.seat, p.online = seat, True
        if name:
            p.name = name
        if color:
            p.color = color
        if avatar:
            p.avatar = avatar
        self.bank.open(pid, self.house.base_credits, name=p.name, color=p.color, avatar=p.avatar)
        self.changed()
        return p

    def leave(self, seat: int | str) -> None:
        """The phone in `seat` disconnected. Its bets stay on the table (it may come back); its wallet stays."""
        p = self.player_at(seat)
        if p is not None:
            p.online = False
            self.changed()

    def ensure_host(self) -> Player:
        p = self.players.get(HOST)
        if p is None or p.seat != "host":
            p = self.join(HOST, "host", name="HOST", color="#00c8ff")
        return p

    def player_at(self, seat: int | str) -> Player | None:
        return next((p for p in self.players.values() if p.seat == seat), None)

    def pid_at(self, seat: int | str) -> str | None:
        p = self.player_at(seat)
        return p.pid if p else None

    def seat_of(self, pid: str) -> int | str | None:
        p = self.players.get(pid)
        return p.seat if p else None

    def name_of(self, pid: str) -> str:
        p = self.players.get(pid)
        if p and p.name:
            return p.name
        w = self.bank.get(pid)
        return w.name if w and w.name else pid

    def seated(self) -> list[Player]:
        """Players at the table now, in seat order (host first)."""
        ps = [p for p in self.players.values() if p.online and p.seat]
        return sorted(ps, key=lambda p: (0, 0) if p.seat == "host" else (1, int(p.seat)))

    def client_seeds(self) -> list[str]:
        """Every seated player's seed in seat order (fair.client_seed joins them)."""
        return [p.client_seed for p in self.seated() if p.client_seed]

    def set_seed(self, pid: str, seed: Any) -> str | None:
        s = fair.clean_client_seed(seed)
        p = self.players.get(pid)
        if s is None or p is None:
            return "Not a valid seed"
        p.client_seed = s
        self.changed()
        return None

    # ----------------------------------------------------------------- notices
    def notify(self, pid: str, text: str, kind: str = "info") -> None:
        """A message for one player's phone (shown as a toast once; `id` tells new from old)."""
        self._note_id += 1
        self._notes[pid] = (self._note_id, text, kind)
        self.changed()

    def note_for(self, pid: str) -> dict[str, Any] | None:
        n = self._notes.get(pid)
        return {"id": n[0], "text": n[1], "kind": n[2]} if n else None

    # ----------------------------------------------------------------- history
    def record(self, game: CasinoGame, res: RoundResult) -> None:
        rnd = game.round
        assert rnd is not None
        entry = {
            "round": res.nonce,
            "game": game.id,
            "t": round(time.time()),
            **res.summary,
            "outcome": res.outcome,
            "rules": game.rules.model_dump(mode="json"),
            "proof": rnd.proof(),
            "wagered": sum(p["stake"] for p in res.payouts.values()),
            "paid": sum(p["payout"] for p in res.payouts.values()),
            "nets": {pid: p["net"] for pid, p in res.payouts.items()},
        }
        self.history.append(entry)
        del self.history[:-HISTORY_MAX]
        self.save()
        self.changed()

    def find_round(self, nonce: int) -> dict[str, Any] | None:
        return next((e for e in reversed(self.history) if e.get("round") == nonce), None)

    def verify(self, nonce: int) -> dict[str, Any]:
        """Recompute a past round from its revealed seeds and check it matches what was paid."""
        from .table import GAMES

        e = self.find_round(nonce)
        if e is None:
            return {"ok": False, "error": "no such round"}
        pr = e.get("proof") or {}
        cls = GAMES.get(str(e.get("game")))
        if cls is None or not pr.get("server_seed"):
            return {"ok": False, "error": "round not verifiable"}
        rules = e.get("rules") or {}
        res = fair.verify(
            pr["server_seed"],
            pr["hash"],
            pr.get("client_seed") or fair.HOUSE_CLIENT_SEED,
            int(pr["nonce"]),
            lambda rng: cls.replay_with(rules, rng, e.get("outcome")),
        )
        res["matches"] = res["outcome"] == e.get("outcome")
        res["ok"] = bool(res["hash_ok"] and res["matches"])
        res["round"] = nonce
        res["proof"] = pr
        return res

    # -------------------------------------------------------------------- host
    def host_op(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        """The studio's ops (docs/API.md → casino). Returns a small JSON result."""
        g = self.game
        now = self.clock()
        if op == "start_round":
            if g is None:
                raise ValueError("no casino table is showing")
            if g.phase in ("idle", "result"):
                g.open_betting(now)
            return {"phase": g.phase}
        if op == "lock":  # "spin now" — close betting early
            if g is None or not g.lock(now):
                raise ValueError("betting isn't open")
            return {"phase": g.phase}
        if op == "settings":
            patch = {k: v for k, v in payload.items() if k in House.model_fields}
            self.house = House.model_validate({**self.house.model_dump(), **patch})
            if self.house.min_bet > self.house.max_bet:
                self.house = self.house.model_copy(update={"max_bet": self.house.min_bet})
            self.save()
            self.changed()
            return {"house": self.house.model_dump()}
        if op == "credits":
            return self._credits(payload)
        if op == "kick":
            pid = self._target(payload)
            if pid is None:
                raise KeyError("player")
            p = self.players[pid]
            p.kicked = payload.get("on", True) is not False
            if p.kicked and g is not None and g.phase == "betting":
                g.clear(pid)
            self.changed()
            return {"pid": pid, "kicked": p.kicked}
        if op == "pause":
            on = payload.get("on")
            on = (not self.paused) if not isinstance(on, bool) else on
            if on and not self.paused:
                self.paused, self._paused_at = True, now
            elif not on and self.paused:
                self.paused = False
                if g is not None:
                    g.pause_shift(now - self._paused_at)
            self.changed()
            return {"paused": self.paused}
        if op == "reset_session":
            if g is not None:
                g.abort(now)
            base = payload.get("base_credits")
            if type(base) is int and 0 <= base <= 1_000_000:
                self.house = self.house.model_copy(update={"base_credits": base})
            self.bank.reset(self.house.base_credits)
            self.history.clear()
            self.save()
            if g is not None:
                g.last_bets.clear()
                g.result = None
                g.open_betting(now)
            self.changed()
            return {"ok": True}
        if op == "verify":
            n = payload.get("round")
            if type(n) is not int:
                raise ValueError("round must be a number")
            return self.verify(n)
        raise KeyError(op)

    def _target(self, payload: dict[str, Any]) -> str | None:
        pid = payload.get("pid")
        if isinstance(pid, str) and pid in self.players:
            return pid
        seat = payload.get("seat")
        if seat == "host":
            return self.ensure_host().pid
        if type(seat) is int:
            return self.pid_at(seat)
        return None

    def _credits(self, payload: dict[str, Any]) -> dict[str, Any]:
        set_, add = payload.get("set"), payload.get("add")
        if (set_ is None) == (add is None) or not all(type(v) is int for v in (set_, add) if v is not None):
            raise ValueError("send exactly one of set / add (whole numbers)")
        if payload.get("all") is True:
            pids = [p.pid for p in self.players.values()]
        else:
            one = self._target(payload)
            if one is None:
                raise KeyError("player")
            pids = [one]
        out = {}
        for pid in pids:
            out[pid] = (
                self.bank.set_credits(pid, set_) if set_ is not None else self.bank.add_credits(pid, add)
            )
            self.notify(pid, f"The host set your credits to {out[pid]:,}", "info")
        self.changed()
        return {"credits": out}

    # ------------------------------------------------------------------ state
    def leaderboard(self) -> list[dict[str, Any]]:
        known = list(self.players)
        out = []
        for w in self.bank.leaderboard(known):
            p = self.players.get(w["pid"])
            out.append(
                {
                    "seat": p.seat if p else None,
                    "name": (p.name if p and p.name else w["name"]) or w["pid"],
                    "color": (p.color if p else w["color"]) or "#f0f0f0",
                    "avatar": (p.avatar if p else w["avatar"]) or "",
                    "online": bool(p and p.online),
                    "credits": w["credits"],
                    "staked": w["escrow"],
                    "net": w["net"],
                    "biggest": w["biggest"],
                }
            )
        return out

    def public_state(self) -> dict[str, Any]:
        return {
            "casino": True,
            "paused": self.paused,
            "house": self.house.model_dump(),
            # the chip rack every UI shows: only the chips the table limits allow (casino/chips.py)
            "chips": chip_rack(self.house.min_bet, self.house.max_bet),
            "players": self.leaderboard(),
            # recent rounds with their revealed seeds: phones verify them on the spot (casino.html)
            "history": [
                {k: e.get(k) for k in ("round", "game", "label", "tone", "outcome", "rules", "proof")}
                for e in self.history[-24:]
            ],
        }

    def private_state(self, pid: str) -> dict[str, Any]:
        p = self.players.get(pid)
        w = self.bank.get(pid)
        return {
            "pid": pid,
            "seat": p.seat if p else None,
            "name": p.name if p else "",
            "credits": w.credits if w else 0,
            "escrow": w.escrow if w else 0,
            "net": w.net if w else 0,
            "biggest": w.biggest if w else 0,
            "client_seed": p.client_seed if p else "",
            "kicked": bool(p and p.kicked),
            "notice": self.note_for(pid),
        }


def _load_house(raw: Any) -> House:
    """Stored house settings, dropping any key that no longer validates (rule 15)."""
    if not isinstance(raw, dict):
        return House()
    data = {k: v for k, v in raw.items() if k in House.model_fields}
    for _ in range(len(data) + 1):
        try:
            return House.model_validate(data)
        except ValidationError as e:
            bad = {str(err["loc"][0]) for err in e.errors() if err["loc"]}
            if not bad:
                break
            for k in bad:
                data.pop(k, None)
    return House()
