"""Trivia questions from the Open Trivia DB (https://opentdb.com, keyless, verified live).

* ``api.php?amount=10&type=multiple&encode=url3986&token=…`` — ten questions per request, URL-encoded (so no
  HTML entities to fight), with a **session token** so questions don't repeat until the pool is exhausted.
* The API allows **one request per 5 seconds per IP** (response_code 5 / HTTP 429 otherwise); the provider
  spaces every request, the token request included, by `GAP` seconds.
* Response codes: 0 ok · 1 not enough questions for the query (retried with a smaller amount, then without
  the difficulty) · 2 invalid parameter · 3 token not found (a new one is requested) · 4 token exhausted (reset)
  · 5 rate limited.
"""

from __future__ import annotations

import asyncio
import random
import time
import zlib
from typing import Any
from urllib.parse import unquote

from .base import Provider
from .daily import clean_text, is_safe

API = "https://opentdb.com/api.php"
TOKEN = "https://opentdb.com/api_token.php"
GAP = 5.5  # seconds between requests (the API allows one per 5 s)
BATCH = 10
LOW = 4  # refill when fewer questions are queued

# id -> (studio label, panel tag <= 28 px in tiny)
CATEGORIES: dict[int, tuple[str, str]] = {
    9: ("General knowledge", "GK"),
    10: ("Books", "BOOKS"),
    11: ("Film", "FILM"),
    12: ("Music", "MUSIC"),
    13: ("Musicals & theatre", "THEATRE"),
    14: ("Television", "TV"),
    15: ("Video games", "GAMES"),
    16: ("Board games", "BOARD"),
    17: ("Science & nature", "SCIENCE"),
    18: ("Computers", "TECH"),
    19: ("Mathematics", "MATHS"),
    20: ("Mythology", "MYTHS"),
    21: ("Sports", "SPORTS"),
    22: ("Geography", "GEO"),
    23: ("History", "HISTORY"),
    24: ("Politics", "CIVICS"),
    25: ("Art", "ART"),
    26: ("Celebrities", "CELEBS"),
    27: ("Animals", "ANIMAL"),
    28: ("Vehicles", "CARS"),
    29: ("Comics", "COMICS"),
    30: ("Gadgets", "GADGETS"),
    31: ("Anime & manga", "ANIME"),
    32: ("Cartoons", "CARTOON"),
}
_BY_NAME = {
    "General Knowledge": 9,
    "Entertainment: Books": 10,
    "Entertainment: Film": 11,
    "Entertainment: Music": 12,
    "Entertainment: Musicals & Theatres": 13,
    "Entertainment: Television": 14,
    "Entertainment: Video Games": 15,
    "Entertainment: Board Games": 16,
    "Science & Nature": 17,
    "Science: Computers": 18,
    "Science: Mathematics": 19,
    "Mythology": 20,
    "Sports": 21,
    "Geography": 22,
    "History": 23,
    "Politics": 24,
    "Art": 25,
    "Celebrities": 26,
    "Animals": 27,
    "Vehicles": 28,
    "Entertainment: Comics": 29,
    "Science: Gadgets": 30,
    "Entertainment: Japanese Anime & Manga": 31,
    "Entertainment: Cartoon & Animations": 32,
}
DIFFICULTIES = ("easy", "medium", "hard")


def category_id(name: str) -> int | None:
    return _BY_NAME.get(name)


def parse_question(raw: dict[str, Any]) -> dict[str, Any] | None:
    """One url3986-encoded result → a clean question with shuffled options (stable per question)."""
    try:
        q = clean_text(unquote(raw["question"]), 300)
        correct = clean_text(unquote(raw["correct_answer"]), 80)
        wrong = [clean_text(unquote(w), 80) for w in raw.get("incorrect_answers") or []]
    except (KeyError, TypeError):
        return None
    kind = raw.get("type") if raw.get("type") in ("multiple", "boolean") else "multiple"
    if not q or not correct or not wrong or any(not w for w in wrong):
        return None
    if not is_safe(" ".join([q, correct, *wrong])):
        return None
    cat_name = unquote(str(raw.get("category") or ""))
    cid = category_id(cat_name)
    diff = unquote(str(raw.get("difficulty") or "medium"))
    qid = f"{zlib.crc32(q.encode()):08x}"
    if kind == "boolean":
        options = ["TRUE", "FALSE"]
        if correct not in options:
            return None
    else:
        options = [correct, *wrong]
        random.Random(qid).shuffle(options)
    return {
        "id": qid,
        "type": kind,
        "difficulty": diff if diff in DIFFICULTIES else "medium",
        "category": cid or 0,
        "tag": CATEGORIES[cid][1]
        if cid in CATEGORIES
        else clean_text(cat_name.split(":")[-1], 12) or "TRIVIA",
        "question": q,
        "options": options,
        "answer": options.index(correct),
    }


def parse_batch(payload: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    code = int(payload.get("response_code", 2))
    out = [q for r in payload.get("results") or [] if (q := parse_question(r)) is not None]
    return code, out


class TriviaProvider(Provider[list[dict[str, Any]]]):
    """``value`` = the queued questions. Apps call ``want(category, difficulty, kind)`` and ``take()``."""

    name = "trivia"
    interval = 15.0
    retry = 12.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.query: tuple[int, str, str] = (0, "any", "multiple")
        self.queue: list[dict[str, Any]] = []
        self.token: str | None = None
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self.served = 0

    # ------------------------------------------------------------ interface
    def want(self, category: int = 0, difficulty: str = "any", kind: str = "multiple") -> None:
        q = (int(category), difficulty if difficulty in DIFFICULTIES else "any", kind)
        if q != self.query:
            self.query = q
            self.queue = [x for x in self.queue if self._matches(x)]
            self.refresh()

    def _matches(self, x: dict[str, Any]) -> bool:
        cat, diff, kind = self.query
        return (
            (not cat or x["category"] == cat)
            and (diff == "any" or x["difficulty"] == diff)
            and (kind == "any" or x["type"] == kind)
        )

    def take(self) -> dict[str, Any] | None:
        for i, x in enumerate(self.queue):
            if self._matches(x):
                self.served += 1
                return self.queue.pop(i)
        return None

    def next_interval(self) -> float:
        return GAP if len(self.queue) < LOW else self.interval

    def announce(self, old: list[dict[str, Any]] | None, new: list[dict[str, Any]]) -> bool:
        return (old is None) != (new is None) or bool(old) != bool(new)

    # ------------------------------------------------------------ fetching
    async def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        wait = self._last_request + GAP - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()
        r = await self.hub.http.get(url, params=params)
        if r.status_code == 429:
            return {"response_code": 5}
        r.raise_for_status()
        return r.json()

    async def _token(self, reset: bool = False) -> None:
        if reset and self.token:
            d = await self._request(TOKEN, {"command": "reset", "token": self.token})
            if int(d.get("response_code", 3)) == 0:
                return
        d = await self._request(TOKEN, {"command": "request"})
        self.token = d.get("token") or None

    async def fetch(self) -> list[dict[str, Any]]:
        async with self._lock:
            if len([x for x in self.queue if self._matches(x)]) >= LOW:
                return list(self.queue)
            if self.token is None:
                try:
                    await self._token()
                except Exception:
                    self.token = None  # tokenless requests still work, questions may repeat
            cat, diff, kind = self.query
            amount = BATCH
            for _attempt in range(4):
                params: dict[str, Any] = {"amount": amount, "encode": "url3986"}
                if cat:
                    params["category"] = cat
                if diff != "any":
                    params["difficulty"] = diff
                if kind != "any":
                    params["type"] = kind
                if self.token:
                    params["token"] = self.token
                code, items = parse_batch(await self._request(API, params))
                if code == 0:
                    seen = {x["id"] for x in self.queue}
                    self.queue += [x for x in items if x["id"] not in seen]
                    return list(self.queue)
                if code == 1:  # not enough questions for this query
                    if amount > 3:
                        amount = 3
                    elif diff != "any":
                        diff = "any"
                    else:
                        break
                elif code == 3:
                    await self._token()
                elif code == 4:
                    await self._token(reset=True)
                elif code == 5:
                    continue  # _request already waits GAP
                else:
                    break
            if self.queue:
                return list(self.queue)
            raise RuntimeError(f"opentdb: no questions (code {code})")
