"""Anki review counts via the AnkiConnect add-on (https://foosoft.net/projects/anki-connect/, API version 6).

Port clash: AnkiConnect listens on 127.0.0.1:**8765** by default — the same port as the DeskDot engine. The
app therefore defaults to **8766**; change AnkiConnect to match in Anki → Tools → Add-ons → AnkiConnect →
Config: ``"webBindPort": 8766`` (restart Anki). If the configured port answers but isn't AnkiConnect (e.g.
it's DeskDot itself on 8765) the value says ``state: "conflict"`` so the panel can explain instead of
failing silently.

Requests (POST JSON ``{"action", "version": 6, "params", "key"?}``): ``deckNames``, ``getDeckStats``,
``getNumCardsReviewedToday`` and, for the word of the day, ``findCards`` + ``cardsInfo`` (cached 10 min).
Anki not running is ordinary: ``state: "off"`` as a value, no error, no log noise.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from .base import Provider
from .radiator import base_url, panel_text, safe_error

VERSION = 6
DESKDOT_PORT = 8765
WORD_TTL = 600.0


class NotAnkiConnect(Exception):
    pass


def card_front(card: dict[str, Any]) -> str:
    """cardsInfo entry -> the first field's text as panel ASCII (HTML, [sound:], cloze markup removed)."""
    fields = card.get("fields") or {}
    ordered = sorted(fields.values(), key=lambda f: f.get("order", 0)) if fields else []
    raw = str(ordered[0].get("value", "")) if ordered else str(card.get("question") or "")
    raw = re.sub(r"\[sound:[^\]]*\]", " ", raw)
    raw = re.sub(r"\{\{c\d+::(.*?)(::[^}]*)?\}\}", r"\1", raw)
    raw = re.sub(r"<(br|div|p)[^>]*>", " ", raw, flags=re.I)
    raw = re.sub(r"<style.*?</style>|<script.*?</script>", " ", raw, flags=re.I | re.S)
    return panel_text(raw, 60)


def sum_stats(stats: dict[str, Any], deck: str) -> dict[str, int]:
    """getDeckStats result -> summed counts. With no deck chosen, only top-level decks are summed
    (sub-deck counts are already included in their parent's)."""
    out = {"new": 0, "learn": 0, "review": 0, "total": 0}
    for s in (stats or {}).values():
        name = str(s.get("name") or "")
        if deck:
            if name != deck:
                continue
        elif "::" in name:
            continue
        out["new"] += int(s.get("new_count") or 0)
        out["learn"] += int(s.get("learn_count") or 0)
        out["review"] += int(s.get("review_count") or 0)
        out["total"] += int(s.get("total_in_deck") or 0)
    return out


class AnkiProvider(Provider[dict[str, Any]]):
    """``value = {"state", "new", "learn", "review", "due", "reviewed", "deck", "word"}``."""

    name = "anki"
    interval = 60.0
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.host, self.port, self.key, self.deck = "127.0.0.1", 8766, "", ""
        self.want_word = False
        self._word: tuple[float, str] | None = None

    def configure(self, host: str, port: int, key: str, deck: str, word: bool) -> None:
        cfg = (host.strip() or "127.0.0.1", int(port), key, deck.strip())
        self.want_word = word
        if cfg != (self.host, self.port, self.key, self.deck):
            self.host, self.port, self.key, self.deck = cfg
            self._word = None
            self.value = None
            self.refresh()

    @property
    def url(self) -> str:
        return base_url(self.host, self.port)

    async def invoke(self, action: str, **params: Any) -> Any:
        body: dict[str, Any] = {"action": action, "version": VERSION}
        if params:
            body["params"] = params
        if self.key:
            body["key"] = self.key
        r = await self.hub.http.post(self.url, json=body, timeout=4.0)
        try:
            data = r.json()
        except ValueError:
            raise NotAnkiConnect(f"HTTP {r.status_code}, not JSON") from None
        if not isinstance(data, dict) or "result" not in data or "error" not in data:
            raise NotAnkiConnect(f"HTTP {r.status_code}, not an AnkiConnect reply")
        if data["error"]:
            raise RuntimeError(str(data["error"]))
        return data["result"]

    async def _word_of_day(self) -> str:
        if self._word and time.time() - self._word[0] < WORD_TTL:
            return self._word[1]
        scope = f'deck:"{self.deck}" ' if self.deck else ""
        word = ""
        for q in (f"{scope}is:due", f"{scope}is:new"):
            ids = await self.invoke("findCards", query=q.strip())
            if ids:
                info = await self.invoke("cardsInfo", cards=[min(ids)])
                word = card_front(info[0]) if info else ""
                if word:
                    break
        self._word = (time.time(), word)
        return word

    async def fetch(self) -> dict[str, Any]:
        base = {"state": "off", "deck": self.deck, "port": self.port}
        try:
            decks = await self.invoke("deckNames")
            if self.deck and self.deck not in decks:
                return dict(base, state="nodeck")
            stats = await self.invoke("getDeckStats", decks=[self.deck] if self.deck else decks)
            reviewed = int(await self.invoke("getNumCardsReviewedToday") or 0)
            word = await self._word_of_day() if self.want_word else ""
        except NotAnkiConnect:
            return dict(base, state="conflict" if self.port == DESKDOT_PORT else "notanki")
        except RuntimeError as e:
            msg = str(e).lower()
            return dict(
                base,
                state="auth" if "key" in msg or "permission" in msg else "error",
                error=safe_error(e, self.key),
            )
        except (httpx.TransportError, OSError):
            return base  # Anki closed: the normal idle case
        c = sum_stats(stats, self.deck)
        due = c["new"] + c["learn"] + c["review"]
        return {
            "state": "ok",
            "deck": self.deck,
            "port": self.port,
            "new": c["new"],
            "learn": c["learn"],
            "review": c["review"],
            "due": due,
            "total": c["total"],
            "reviewed": reviewed,
            "word": word,
            "updated": time.time(),
        }
