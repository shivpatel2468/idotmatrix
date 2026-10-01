"""Daily Dose — quotes, jokes, facts, advice and "on this day", from ten keyless APIs (all verified live).

Each source keeps a small **queue** of ready items that the provider tops up in the background, so the panel
never waits on the network. Apps call ``want(sources)`` and then ``take(source)`` when they move to the next
item. Batch endpoints are preferred (one request fills a whole queue), which also keeps well inside the
published rate limits:

========== ======================================================= ============================================
source     endpoint                                                notes
========== ======================================================= ============================================
quote      zenquotes.io/api/quotes                                 50 quotes per call; limit ~5 req / 30 s
qotd       zenquotes.io/api/today                                  sticky: one item per day
dad        icanhazdadjoke.com/search?limit=30&page=N               needs ``Accept: application/json``
fact       uselessfacts.jsph.pl/api/v2/facts/random                one per call → a few concurrently
fact_today uselessfacts.jsph.pl/api/v2/facts/today                 sticky
advice     api.adviceslip.com/advice?t=…                           the API caches ~2 s; the query busts it
cat        catfact.ninja/facts?limit=20&page=N                     a random page of short facts
joke       v2.jokeapi.dev/joke/Programming,Pun?safe-mode&amount=10  two-part jokes → setup + punchline
chuck      api.chucknorris.io/jokes/random?category=…              only whitelisted categories (never explicit)
kanye      api.kanye.rest/quotes                                   the whole list at once
history    api.wikimedia.org/feed/v1/…/onthisday/events/MM/DD      ~200 KB: once per day, a dozen short events
========== ======================================================= ============================================

Safe mode is always on: every item passes `is_safe` and every string passes `clean_text`, which keeps only
characters the 1-bit panel fonts can draw.
"""

from __future__ import annotations

import asyncio
import html
import random
import re
import time
import unicodedata
import zlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .base import Provider

Item = dict[str, Any]

# ------------------------------------------------------------------------------------------ text hygiene
_REPLACE = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "`": "'",
    "´": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "«": '"',
    "»": '"',
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "‐": "-",
    "‑": "-",
    " ": " ",
    " ": " ",
    "​": "",
    "×": "X",
    "·": "·",
    "•": "•",
    "…": "...",
    "{": "(",
    "}": ")",
    "~": "-",
    "^": "",
    "\\": "",
    "ß": "SS",
    "æ": "AE",
    "Æ": "AE",
    "œ": "OE",
    "Œ": "OE",
    "ø": "O",
    "Ø": "O",
    "ł": "L",
    "Ł": "L",
    "ð": "D",
    "þ": "TH",
    "€": "EUR",
    "£": "GBP",
    "₹": "RS",
    "¥": "YEN",
}
# everything the `tiny` font can draw (after upper-casing)
TINY_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;!?'\"-+=_/\\%*$#()[]<>|&@°•·…")


def clean_text(raw: Any, limit: int = 400) -> str:
    """Anything → one upper-case line the bitmap fonts can draw (accents folded, HTML decoded, junk dropped)."""
    s = html.unescape(str(raw or ""))
    s = re.sub(r"<[^>]+>", "", s)
    s = "".join(_REPLACE.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.upper()
    s = "".join(ch if ch in TINY_CHARS else (" " if ch.isspace() else "") for ch in s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([.,:;!?])", r"\1", s)
    return s[:limit].rstrip()


# Safe mode (always on). Word-boundary matches on the cleaned, upper-cased text.
_UNSAFE = re.compile(
    r"\b("
    r"SEX\w*|SEXY|NUDE\w*|NAKED|PORN\w*|DICK\w*|COCK\w*|PENIS\w*|VAGINA\w*|BOOB\w*|TIT|TITS|BREASTS?|"
    r"FUCK\w*|SHIT\w*|BITCH\w*|ASS|ASSHOLE\w*|BASTARD\w*|DAMN\w*|CRAP|PISS\w*|SLUT\w*|WHORE\w*|"
    r"RAPE\w*|NAZI\w*|HITLER|RACIS\w*|NIGG\w*|RETARD\w*|GAY|LESBIAN|VIRGIN\w*|ORGASM\w*|CONDOM\w*|"
    r"HORNY|BLACK OUT|DRUNK|COCAINE|HEROIN|SUICID\w*|ABORTION\w*|TERROR\w*|GENOCIDE|HOLOCAUST"
    r")\b"
)
# history events we skip unless nothing else is left (a desk companion should not lead with tragedy)
_GRIM = re.compile(
    r"\b(KILL\w*|DEAD|DEATHS?|DIE[SD]?|MURDER\w*|MASSACRE\w*|BOMB\w*|EXECUT\w*|RIOT\w*|STAMPEDE|"
    r"EARTHQUAKE|CRASH\w*|WOUNDED|SHOOTING|ASSASSIN\w*|HANG\w*|WAR CRIME\w*)\b"
)


def is_safe(text: str) -> bool:
    return not _UNSAFE.search(text.upper())


# ------------------------------------------------------------------------------------------ sources
@dataclass(frozen=True)
class Source:
    id: str
    label: str  # studio label
    tag: str  # panel header (tiny, <= 23 px)
    target: int  # queue size to keep
    low: int  # refill when the queue drops below this
    gap: float  # minimum seconds between fetches (rate limits)
    sticky: bool = False  # one item per day, shown repeatedly
    cycle: bool = False  # items are shown round-robin, never consumed (history)


SOURCES: dict[str, Source] = {
    s.id: s
    for s in (
        Source("quote", "Random quote (ZenQuotes)", "QUOTE", 50, 5, 600),
        Source("qotd", "Quote of the day (ZenQuotes)", "TODAY", 1, 1, 3600, sticky=True),
        Source("dad", "Dad joke (icanhazdadjoke)", "DAD", 30, 5, 120),
        Source("fact", "Useless fact", "FACT", 6, 3, 60),
        Source("fact_today", "Useless fact of the day", "FACT", 1, 1, 3600, sticky=True),
        Source("advice", "Advice (Advice Slip)", "ADVICE", 6, 3, 60),
        Source("cat", "Cat fact (catfact.ninja)", "CAT", 20, 5, 120),
        Source("joke", "Programming & pun jokes (JokeAPI)", "JOKE", 10, 4, 60),
        Source("chuck", "Chuck Norris (safe categories)", "CHUCK", 6, 3, 60),
        Source("kanye", "Kanye (kanye.rest)", "KANYE", 40, 5, 3600),
        Source("history", "On this day (Wikipedia)", "OTD", 12, 1, 3600, cycle=True),
    )
}

ZEN_QUOTES = "https://zenquotes.io/api/quotes"
ZEN_TODAY = "https://zenquotes.io/api/today"
DAD_SEARCH = "https://icanhazdadjoke.com/search"
USELESS_RANDOM = "https://uselessfacts.jsph.pl/api/v2/facts/random"
USELESS_TODAY = "https://uselessfacts.jsph.pl/api/v2/facts/today"
ADVICE = "https://api.adviceslip.com/advice"
CAT_FACTS = "https://catfact.ninja/facts"
JOKEAPI = "https://v2.jokeapi.dev/joke/Programming,Pun"
JOKEAPI_FLAGS = "nsfw,religious,political,racist,sexist,explicit"
CHUCK = "https://api.chucknorris.io/jokes/random"
CHUCK_SAFE = ("dev", "science", "food", "sport", "animal", "travel", "career", "movie", "music", "money")
KANYE_ALL = "https://api.kanye.rest/quotes"
ONTHISDAY = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{mm:02d}/{dd:02d}"
# Wikimedia asks for a descriptive User-Agent (generic ones get 429s under load)
WIKI_HEADERS = {"User-Agent": "DeskDot/3 (desktop LED panel companion; https://github.com/) httpx"}
JSON_HEADERS = {"Accept": "application/json"}

MAX_LEN = 180  # longer items take too many pages on a 32x32 panel


def _item(source: str, text: Any, key: Any = None, **extra: Any) -> Item | None:
    """Build a clean, safe item or None. Two-part items carry ``punchline``; quotes carry ``author``."""
    body = clean_text(text)
    if not body or len(body) > MAX_LEN:
        return None
    out: Item = {"source": source, "text": body}
    for k, v in extra.items():
        if v is None:
            continue
        v = clean_text(v, 60 if k in ("author", "tag") else MAX_LEN) if isinstance(v, str) else v
        if v == "":
            continue
        out[k] = v
    joined = " ".join(str(out.get(k, "")) for k in ("text", "punchline", "author"))
    if not is_safe(joined):
        return None
    out["id"] = f"{source}:{key if key is not None else format(zlib.crc32(joined.encode()), 'x')}"
    return out


# --------------------------------------------------------------------------------------------- parsers
def parse_zen(payload: Any, source: str = "quote") -> list[Item]:
    out: list[Item] = []
    for q in payload if isinstance(payload, list) else []:
        if not isinstance(q, dict):
            continue
        author = str(q.get("a") or "")
        if "zenquotes" in author.lower():  # the rate-limit notice arrives dressed as a quote
            continue
        it = _item(source, q.get("q"), None, author=author or None)
        if it:
            out.append(it)
    return out


def parse_dad(payload: Any) -> tuple[list[Item], int]:
    """icanhazdadjoke /search page → (items, total_pages)."""
    if not isinstance(payload, dict):
        return [], 1
    out = [
        it
        for j in payload.get("results") or []
        if (it := _item("dad", j.get("joke"), j.get("id"))) is not None
    ]
    return out, max(1, int(payload.get("total_pages") or 1))


def split_dad(text: str) -> tuple[str, str | None]:
    """'WHY X? BECAUSE Y.' → ('WHY X?', 'BECAUSE Y.'); single-liners stay whole."""
    m = re.match(r"^(.{8,}?\?)\s+(\S.{2,})$", text)
    if m and len(m.group(2)) >= 3:
        return m.group(1), m.group(2)
    return text, None


def parse_useless(payload: Any, source: str = "fact") -> list[Item]:
    if not isinstance(payload, dict):
        return []
    it = _item(source, payload.get("text"), (payload.get("id") or "")[:12] or None)
    return [it] if it else []


def parse_advice(payload: Any) -> list[Item]:
    slip = (payload or {}).get("slip") if isinstance(payload, dict) else None
    if not isinstance(slip, dict):
        return []
    it = _item("advice", slip.get("advice"), slip.get("id"))
    return [it] if it else []


def parse_cat(payload: Any) -> tuple[list[Item], int]:
    if not isinstance(payload, dict):
        return [], 1
    out = [it for f in payload.get("data") or [] if (it := _item("cat", f.get("fact"))) is not None]
    return out, max(1, int(payload.get("last_page") or 1))


def parse_jokeapi(payload: Any) -> list[Item]:
    if not isinstance(payload, dict) or payload.get("error"):
        return []
    jokes = payload.get("jokes") if "jokes" in payload else [payload]
    out: list[Item] = []
    for j in jokes or []:
        flags = j.get("flags") or {}
        if not j.get("safe", True) or any(flags.values()):
            continue
        tag = "PUN" if j.get("category") == "Pun" else "CODE"
        if j.get("type") == "twopart":
            it = _item("joke", j.get("setup"), j.get("id"), punchline=j.get("delivery"), tag=tag)
            if it and "punchline" not in it:
                it = None
        else:
            it = _item("joke", j.get("joke"), j.get("id"), tag=tag)
        if it:
            out.append(it)
    return out


def parse_chuck(payload: Any) -> list[Item]:
    if not isinstance(payload, dict):
        return []
    cats = payload.get("categories") or []
    if not cats or any(c not in CHUCK_SAFE for c in cats):
        return []
    it = _item("chuck", payload.get("value"), (payload.get("id") or "")[:12] or None)
    return [it] if it else []


def parse_kanye(payload: Any) -> list[Item]:
    quotes = payload if isinstance(payload, list) else [(payload or {}).get("quote")]
    return [it for q in quotes if (it := _item("kanye", q, author="KANYE WEST")) is not None]


def parse_onthisday(payload: Any, keep: int = 12, max_len: int = 110) -> list[Item]:
    """Wikipedia "on this day" → up to `keep` short events spread across the centuries, newest first."""
    events = (payload or {}).get("events") if isinstance(payload, dict) else None
    good: list[tuple[int, Item]] = []
    grim: list[tuple[int, Item]] = []
    for e in events or []:
        try:
            year = int(e.get("year"))
        except (TypeError, ValueError):
            continue
        it = _item("history", e.get("text"), f"{year}", year=year, tag=str(year))
        if not it or len(it["text"]) > max_len:
            continue
        (grim if _GRIM.search(it["text"]) else good).append((year, it))
    pool = good if len(good) >= min(keep, 6) else good + grim
    pool.sort(key=lambda yi: -yi[0])
    if len(pool) > keep:  # evenly spread over the list so every era is represented
        step = (len(pool) - 1) / (keep - 1)
        pool = [pool[round(i * step)] for i in range(keep)]
    return [it for _y, it in pool]


# -------------------------------------------------------------------------------------------- provider
class DailyProvider(Provider[dict[str, list[Item]]]):
    """``value = {source: [queued items]}`` (a snapshot). Apps call ``want(sources)`` and ``take(source)``."""

    name = "daily"
    interval = 20.0
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.sources: list[str] = []
        self._q: dict[str, list[Item]] = {}
        self._last: dict[str, Item] = {}  # last item handed out (repeat when a queue runs dry)
        self._cursor: dict[str, int] = {}
        self._next_ok: dict[str, float] = {}  # rate limiting / sticky refresh per source
        self._fails: dict[str, int] = {}
        self._day: dict[str, str] = {}  # sticky/cycle sources: the date their items belong to
        self._pages: dict[str, int] = {"dad": 25, "cat": 13}
        self._seen: dict[str, set[str]] = {}
        self.errors: dict[str, str] = {}
        self._rng = random.Random()

    # ------------------------------------------------------------ interface
    def want(self, sources: Sequence[str]) -> None:
        clean = [s for s in sources if s in SOURCES]
        new = [s for s in clean if s not in self.sources]
        self.sources = list(dict.fromkeys(clean))
        if new:
            self.refresh()

    def has(self, source: str) -> bool:
        return bool(self._q.get(source)) or source in self._last

    def ready(self) -> list[str]:
        return [s for s in self.sources if self.has(s)]

    def take(self, source: str) -> Item | None:
        """The next item of `source` (consumed unless the source is sticky/cyclic); None if nothing yet."""
        spec = SOURCES.get(source)
        q = self._q.get(source) or []
        if spec is None:
            return None
        if q and (spec.sticky or spec.cycle):
            i = self._cursor.get(source, 0) % len(q)
            self._cursor[source] = i + 1
            return q[i]
        if q:
            it = q.pop(0)
            self._last[source] = it
            return it
        return self._last.get(source)

    def announce(self, old: dict[str, list[Item]] | None, new: dict[str, list[Item]]) -> bool:
        return {k: bool(v) for k, v in (old or {}).items()} != {k: bool(v) for k, v in new.items()}

    # ------------------------------------------------------------ fetching
    def _needs(self, s: str, now: float, today: str) -> bool:
        spec = SOURCES[s]
        if now < self._next_ok.get(s, 0.0):
            return False
        q = self._q.get(s) or []
        if spec.sticky or spec.cycle:
            return not q or self._day.get(s) != today
        return len(q) < spec.low

    async def _get(self, url: str, **kw: Any) -> Any:
        r = await self.hub.http.get(url, **kw)
        r.raise_for_status()
        return r.json()

    async def _fetch_source(self, s: str) -> list[Item]:
        fetchers: dict[str, Callable[[], Awaitable[list[Item]]]] = {
            "quote": self._quote,
            "qotd": self._qotd,
            "dad": self._dad,
            "fact": lambda: self._many(USELESS_RANDOM, parse_useless, 4, params={"language": "en"}),
            "fact_today": self._fact_today,
            "advice": self._advice,
            "cat": self._cat,
            "joke": self._joke,
            "chuck": self._chuck,
            "kanye": self._kanye,
            "history": self._history,
        }
        return await fetchers[s]()

    async def _quote(self) -> list[Item]:
        items = parse_zen(await self._get(ZEN_QUOTES))
        self._rng.shuffle(items)
        return items

    async def _qotd(self) -> list[Item]:
        return parse_zen(await self._get(ZEN_TODAY), "qotd")[:1]

    async def _fact_today(self) -> list[Item]:
        return parse_useless(await self._get(USELESS_TODAY, params={"language": "en"}), "fact_today")

    async def _dad(self) -> list[Item]:
        page = self._rng.randint(1, self._pages["dad"])
        items, pages = parse_dad(
            await self._get(DAD_SEARCH, params={"limit": 30, "page": page}, headers=JSON_HEADERS)
        )
        self._pages["dad"] = pages
        for it in items:
            setup, punch = split_dad(it["text"])
            if punch:
                it["text"], it["punchline"] = setup, punch
        self._rng.shuffle(items)
        return items

    async def _cat(self) -> list[Item]:
        page = self._rng.randint(1, self._pages["cat"])
        items, pages = parse_cat(
            await self._get(CAT_FACTS, params={"max_length": 140, "limit": 20, "page": page})
        )
        self._pages["cat"] = pages
        self._rng.shuffle(items)
        return items

    async def _joke(self) -> list[Item]:
        return parse_jokeapi(
            await self._get(f"{JOKEAPI}?safe-mode", params={"amount": 10, "blacklistFlags": JOKEAPI_FLAGS})
        )

    async def _advice(self) -> list[Item]:
        # the Advice Slip API serves a cached slip for ~2 s; a unique query string busts it
        stamp = int(time.time() * 1000)
        return await self._many(ADVICE, parse_advice, 4, bust=stamp)

    async def _chuck(self) -> list[Item]:
        cats = self._rng.sample(CHUCK_SAFE, 4)

        async def one(c: str) -> list[Item]:
            return parse_chuck(await self._get(CHUCK, params={"category": c}))

        return await self._gather([one(c) for c in cats])

    async def _kanye(self) -> list[Item]:
        items = parse_kanye(await self._get(KANYE_ALL))
        self._rng.shuffle(items)
        return items[: SOURCES["kanye"].target]

    async def _history(self) -> list[Item]:
        d = datetime.now().date()
        r = await self.hub.http.get(ONTHISDAY.format(mm=d.month, dd=d.day), headers=WIKI_HEADERS)
        r.raise_for_status()
        return parse_onthisday(r.json(), SOURCES["history"].target)

    async def _many(
        self, url: str, parse: Callable[[Any], list[Item]], n: int, bust: int | None = None, **kw: Any
    ) -> list[Item]:
        async def one(i: int) -> list[Item]:
            u = f"{url}?t={bust}{i}" if bust is not None else url
            return parse(await self._get(u, **kw))

        return await self._gather([one(i) for i in range(n)])

    @staticmethod
    async def _gather(coros: list[Awaitable[list[Item]]]) -> list[Item]:
        res = await asyncio.gather(*coros, return_exceptions=True)
        ok = [r for r in res if not isinstance(r, BaseException)]
        if not ok:
            err = next(r for r in res if isinstance(r, BaseException))
            raise err
        return [it for r in ok for it in r]

    def _merge(self, s: str, items: list[Item], today: str) -> None:
        spec = SOURCES[s]
        if spec.sticky or spec.cycle:
            if items:
                self._q[s] = items[: spec.target]
                self._day[s] = today
                self._cursor.setdefault(s, 0)
            return
        seen = self._seen.setdefault(s, set())
        q = self._q.setdefault(s, [])
        ids = {it["id"] for it in q}
        fresh = [it for it in items if it["id"] not in ids and it["id"] not in seen]
        if not fresh:  # everything was shown before: allow repeats rather than run dry
            seen.clear()
            fresh = [it for it in items if it["id"] not in ids]
        for it in fresh[: max(0, spec.target - len(q))]:
            q.append(it)
            seen.add(it["id"])
        if len(seen) > 600:
            seen.clear()

    async def fetch(self) -> dict[str, list[Item]]:
        now = time.time()
        today = date.today().isoformat()
        todo = [s for s in self.sources if self._needs(s, now, today)]
        if todo:
            res = await asyncio.gather(*(self._fetch_source(s) for s in todo), return_exceptions=True)
            for s, r in zip(todo, res, strict=True):
                spec = SOURCES[s]
                if isinstance(r, BaseException):
                    n = self._fails[s] = self._fails.get(s, 0) + 1
                    self._next_ok[s] = now + min(1800.0, max(spec.gap / 4, 30.0) * 2 ** (n - 1))
                    self.errors[s] = f"{type(r).__name__}: {r}"[:120]
                    continue
                self._fails.pop(s, None)
                self.errors.pop(s, None)
                self._merge(s, r, today)
                self._next_ok[s] = now + spec.gap
            if self.sources and not any(self.has(s) for s in self.sources) and self.errors:
                raise RuntimeError("; ".join(f"{k}: {v}" for k, v in self.errors.items())[:200])
        return {s: list(self._q.get(s) or []) for s in self.sources}
