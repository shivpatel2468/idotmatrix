"""Time-synced lyrics: LRCLIB first (keyless, fast), `syncedlyrics` as the fallback.

One background search per track, cached for the session — misses too (network errors retry after a while).

* Line timing comes from LRC stamps (``[mm:ss.xx]``).
* Word timing comes from enhanced / A2 LRC stamps (``<mm:ss.xx>``) when a source has them; otherwise it is
  estimated by spreading the sung part of the line over its words by character length.
* Plain (unsynced) lyrics are spread over the song's duration, so they still scroll at song pace.

`Lyrics.at(pos)` gives the current/next line; `Lyrics.words_at(pos)` gives the current line's words with their
start/end, the index of the word being sung and the progress through it — everything a karaoke fill needs.
"""

from __future__ import annotations

import asyncio
import bisect
import difflib
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from .base import Provider

log = logging.getLogger("dotdeck.lyrics")

LRCLIB = "https://lrclib.net/api"
_LINE_STAMP = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d+)?)\]")
_WORD_STAMP = re.compile(r"<(\d+):(\d{1,2}(?:[.:]\d+)?)>")
_OFFSET_TAG = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]", re.I)
_META_TAG = re.compile(r"^\[[a-z]+:.*\]$", re.I)

# Sung duration estimate when a line has no word stamps: seconds per character, plus a floor.
_SEC_PER_CHAR = 0.13
_SEC_BASE = 0.4
_RETRY_ERRORS_AFTER = 120.0  # a search that failed on the network is retried after this long
_CACHE_MAX = 256


def _stamp(m: str, s: str) -> float:
    return int(m) * 60 + float(s.replace(":", "."))


# ---------------------------------------------------------------------------- model
@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass
class Line:
    start: float
    text: str
    words: list[Word] = field(default_factory=list)
    end: float = 0.0  # when singing of this line ends (≤ next line's start)
    timed: bool = False  # True when the words carry real (enhanced LRC) timing


class WordsAt(NamedTuple):
    words: list[Word]  # the current line's words (empty before the first line)
    index: int  # word being sung (-1 = the line has not started yet)
    progress: float  # 0..1 through that word


def _estimate_words(text: str, start: float, end: float) -> list[Word]:
    """Distribute [start, end) over the words by character length (+1 for the gap after each)."""
    parts = text.split()
    if not parts:
        return []
    weights = [len(p) + 1 for p in parts]
    total = sum(weights)
    out: list[Word] = []
    t = start
    for p, w in zip(parts, weights, strict=True):
        d = (end - start) * w / total
        out.append(Word(p, t, t + d))
        t += d
    return out


def _parse_words(body: str, line_start: float) -> tuple[str, list[Word]]:
    """Split an enhanced-LRC body (``<00:01.00> hello <00:01.50> world <00:02.10>``) into timed words.

    Each stamp opens a segment that lasts until the next stamp; a segment with several words shares its
    interval evenly. Text before the first stamp starts with the line.
    """
    stamps = list(_WORD_STAMP.finditer(body))
    if not stamps:
        return " ".join(body.split()), []
    segs: list[tuple[float, float | None, list[str]]] = []
    lead = body[: stamps[0].start()].split()
    if lead:
        segs.append((line_start, _stamp(stamps[0].group(1), stamps[0].group(2)), lead))
    for i, m in enumerate(stamps):
        t = _stamp(m.group(1), m.group(2))
        nxt = _stamp(stamps[i + 1].group(1), stamps[i + 1].group(2)) if i + 1 < len(stamps) else None
        pieces = body[m.end() : stamps[i + 1].start() if i + 1 < len(stamps) else len(body)].split()
        if pieces:
            segs.append((t, nxt, pieces))
    out: list[Word] = []
    for t0, t1, pieces in segs:
        end = t1 if t1 is not None and t1 > t0 else t0 + 0.3 * len(pieces) + 0.03 * sum(map(len, pieces))
        step = (end - t0) / len(pieces)
        out += [Word(p, t0 + k * step, t0 + (k + 1) * step) for k, p in enumerate(pieces)]
    return " ".join(w.text for w in out), out


def parse_lrc_lines(text: str) -> list[Line]:
    """Parse LRC (simple, multi-stamp and enhanced/A2 word stamps) into timed `Line`s, sorted."""
    offset = 0.0
    raw: list[tuple[float, str]] = []
    for row in text.splitlines():
        row = row.strip()
        om = _OFFSET_TAG.match(row)
        if om:
            offset = int(om.group(1)) / 1000.0  # positive offset = lyrics appear earlier
            continue
        stamps = _LINE_STAMP.findall(row)
        if not stamps:
            continue
        body = _LINE_STAMP.sub("", row)
        for m, s in stamps:
            raw.append((_stamp(m, s), body))
    raw.sort(key=lambda e: e[0])
    lines: list[Line] = []
    for t_raw, body in raw:
        t = max(0.0, t_raw - offset)
        txt, words = _parse_words(body, t_raw)
        if offset and words:
            words = [Word(w.text, max(0.0, w.start - offset), max(0.0, w.end - offset)) for w in words]
        lines.append(Line(t, txt, words, timed=bool(words)))
    _finish(lines)
    return lines


def _finish(lines: list[Line], song_end: float | None = None) -> None:
    """Fill in sung end times and estimated word timing."""
    for i, ln in enumerate(lines):
        nxt = lines[i + 1].start if i + 1 < len(lines) else (song_end or ln.start + 6.0)
        avail = max(0.3, nxt - ln.start)
        if ln.timed and ln.words:
            ln.end = min(max(ln.words[-1].end, ln.start + 0.2), max(nxt, ln.words[-1].end))
            continue
        chars = len(ln.text)
        sung = min(avail * 0.95, max(0.8, chars * _SEC_PER_CHAR + _SEC_BASE)) if chars else 0.0
        ln.end = ln.start + sung
        ln.words = _estimate_words(ln.text, ln.start, ln.end)


_GAP_TEXT = re.compile(r"^[\s♪♫♬♩~*.…-]*$")


def clean_lines(lines: list[Line]) -> list[Line]:
    """Turn "♪" / "..." lines into empty gap markers (instrumental breaks), drop repeated and leading gaps."""
    out: list[Line] = []
    for ln in lines:
        if _GAP_TEXT.match(ln.text):
            if out and out[-1].text:
                out.append(Line(ln.start, "", [], ln.start))
            continue
        out.append(ln)
    while out and not out[-1].text:
        out.pop()
    _finish(out)
    return out


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """Parse LRC, including lines with several timestamps. Returns [(seconds, line)] sorted."""
    return [(ln.start, ln.text) for ln in parse_lrc_lines(text)]


def plain_lines(text: str, duration: float) -> list[Line]:
    """Unsynced lyrics spread over the song (5 % intro, 5 % outro) by line length, so they scroll at pace."""
    rows = [r.strip() for r in text.splitlines()]
    rows = [r for r in rows if r and not _META_TAG.match(r)]
    if not rows:
        return []
    dur = duration if duration and duration > 20 else max(60.0, 3.2 * len(rows))
    t0, t1 = dur * 0.05, dur * 0.95
    weights = [len(r) + 12 for r in rows]  # +12 ≈ breath between lines
    total = sum(weights)
    lines: list[Line] = []
    t = t0
    for r, w in zip(rows, weights, strict=True):
        lines.append(Line(t, r))
        t += (t1 - t0) * w / total
    _finish(lines, song_end=t1)
    return lines


class Lyrics:
    """Lyrics for one track. `lines` keeps the classic [(seconds, text)] shape; `entries` has word timing."""

    def __init__(
        self,
        lines: list[tuple[float, str]] | list[Line],
        *,
        synced: bool = True,
        source: str = "",
    ) -> None:
        if lines and isinstance(lines[0], Line):
            entries = list(lines)  # type: ignore[arg-type]
        else:
            entries = [Line(t, txt) for t, txt in lines]  # type: ignore[misc]
            _finish(entries)
        self.entries: list[Line] = entries  # type: ignore[assignment]
        self.lines: list[tuple[float, str]] = [(e.start, e.text) for e in self.entries]
        self._times = [e.start for e in self.entries]
        self.synced = synced
        self.source = source
        self.word_synced = any(e.timed for e in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def index(self, pos: float) -> int:
        """Index of the line active at `pos` (-1 before the first line)."""
        return bisect.bisect_right(self._times, pos) - 1

    def at(self, pos: float) -> tuple[int, str, str, float]:
        """(index, current, next, progress-through-current 0..1) at `pos` seconds."""
        i = self.index(pos)
        if i < 0:
            nxt = self.lines[0][1] if self.lines else ""
            return -1, "", nxt, 0.0
        cur = self.lines[i][1]
        nxt = self.lines[i + 1][1] if i + 1 < len(self.lines) else ""
        end = self._times[i + 1] if i + 1 < len(self._times) else self._times[i] + 4
        prog = (pos - self._times[i]) / max(0.1, end - self._times[i])
        return i, cur, nxt, max(0.0, min(1.0, prog))

    def words_at(self, pos: float) -> WordsAt:
        """The current line's words, the word being sung and the progress (0..1) through it."""
        i = self.index(pos)
        if i < 0:
            return WordsAt([], -1, 0.0)
        words = self.entries[i].words
        if not words or pos < words[0].start:
            return WordsAt(words, -1, 0.0)
        starts = [w.start for w in words]
        j = bisect.bisect_right(starts, pos) - 1
        w = words[j]
        prog = 1.0 if pos >= w.end else (pos - w.start) / max(0.01, w.end - w.start)
        return WordsAt(words, j, max(0.0, min(1.0, prog)))


# ---------------------------------------------------------------------------- titles
_NOISE_WORDS = re.compile(
    r"official|video|audio|lyrics?|visuali[sz]er|remaster|\b(?:hd|hq|4k|8k|mv|m/v)\b|explicit|clean version|"
    r"upgrade|color coded|full album|audio only|radio edit|single version|album version|\bmono\b|\bstereo\b",
    re.I,
)
_BRACKETS = re.compile(r"\s*[\(\[【]([^\)\]】]*)[\)\]】]")
_FEAT_BRACKET = re.compile(r"^\s*(?:feat\.?|ft\.|featuring|with)\s", re.I)
_FEAT_BARE = re.compile(r"\s+(?:feat\.|feat|ft\.|featuring)\s+.*$", re.I)
_DASH_SUFFIX = re.compile(
    r"\s+[-–—]\s+((?:\d{4}\s+)?(?:(?:\d{4}\s+)?remaster(?:ed)?|live|mono|stereo|radio edit|single|version|edit|"
    r"demo|official)\b.*)$",
    re.I,
)
_CHANNEL = re.compile(
    r"(?:\s*-\s*topic|\s*vevo|\s+official(?:\s+channel)?|\s+music|\s+records|\s+tv)\s*$", re.I
)
_ARTIST_SPLIT = re.compile(r"\s*(?:,|;|/|\s(?:feat\.?|ft\.|featuring|x|vs\.?)\s)\s*", re.I)


def _strip_title(t: str) -> str:
    def drop(m: re.Match[str]) -> str:
        inner = m.group(1)
        return "" if _NOISE_WORDS.search(inner) or _FEAT_BRACKET.match(inner) else m.group(0)

    t = _BRACKETS.sub(drop, t)
    t = _FEAT_BARE.sub("", t)
    t = _DASH_SUFFIX.sub("", t)
    t = re.sub(r"\s*\|.*$", "", t)  # "Song | Artist | Channel"
    t = re.sub(r"\s*#\w+", "", t)  # hashtags
    t = t.strip().strip("\"'“”‘’").strip()
    return re.sub(r"\s{2,}", " ", t)


def _primary_artist(a: str) -> str:
    a = a.strip()
    stripped = _CHANNEL.sub("", a)
    if stripped != a and " " not in stripped:  # "TaylorSwiftVEVO" -> "Taylor Swift"
        stripped = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stripped)
    return _ARTIST_SPLIT.split(stripped, maxsplit=1)[0].strip()


def _same(a: str, b: str) -> bool:
    a, b = re.sub(r"\W+", "", a.lower()), re.sub(r"\W+", "", b.lower())
    return bool(a and b) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() > 0.8)


def normalize_track(title: str, artist: str = "") -> tuple[str, str]:
    """Clean a player's (title, artist) for lookups.

    Strips "(Remastered 2011)", "- Official Video", "feat. X", "[Lyrics]", channel suffixes (" - Topic",
    "VEVO") and splits YouTube-style "Artist - Song" (or "Song - Artist") titles.
    """
    title = (title or "").strip()
    artist = (artist or "").strip()
    a = _primary_artist(artist)
    t = _strip_title(title) or title
    m = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", t)
    if m:
        left, right = m.group(1).strip(), m.group(2).strip()
        if a and _same(right, a) and not _same(left, a):
            t = left  # "Song - Artist"
        elif not a or _same(left, a) or _same(left, artist) or _CHANNEL.search(artist):
            a = a if a and _same(left, a) else _primary_artist(left)
            t = right  # "Artist - Song"
    return (_strip_title(t) or t), a


# ---------------------------------------------------------------------------- provider
class LyricsProvider(Provider[None]):
    """Not a poller: `get()` returns cached lyrics or starts one background search."""

    name = "lyrics"

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._tasks: set[asyncio.Task[None]] = set()
        self._cache: OrderedDict[str, Lyrics | None] = OrderedDict()
        self._meta: dict[str, str] = {}  # key -> "instrumental" | "error"
        self._failed_at: dict[str, float] = {}
        self._pending: set[str] = set()

    def acquire(self) -> None:  # no polling loop
        self._refs += 1

    @staticmethod
    def _key(title: str, artist: str) -> str:
        return f"{title}\x1f{artist}".lower()

    def get(self, title: str, artist: str, album: str = "", duration: float = 0.0) -> Lyrics | None:
        key = self._key(title, artist)
        if key in self._cache:
            failed = self._failed_at.get(key)
            if not (failed and time.monotonic() - failed > _RETRY_ERRORS_AFTER):
                self._cache.move_to_end(key)
                return self._cache[key]
            del self._cache[key]
            self._failed_at.pop(key, None)
        if key not in self._pending:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return None
            self._pending.add(key)
            task = loop.create_task(self._search(key, title, artist, album, duration))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return None

    def status(self, title: str, artist: str) -> str:
        """idle | searching | found (synced) | plain | instrumental | none."""
        key = self._key(title, artist)
        if key in self._pending:
            return "searching"
        if key in self._cache:
            lyr = self._cache[key]
            if lyr is None:
                return "instrumental" if self._meta.get(key) == "instrumental" else "none"
            return "found" if lyr.synced else "plain"
        return "idle"

    def _store(self, key: str, lyr: Lyrics | None) -> None:
        self._cache[key] = lyr
        self._cache.move_to_end(key)
        while len(self._cache) > _CACHE_MAX:
            old, _ = self._cache.popitem(last=False)
            self._meta.pop(old, None)
            self._failed_at.pop(old, None)

    # ------------------------------------------------------------------ search
    async def _search(self, key: str, title: str, artist: str, album: str, duration: float) -> None:
        errors = 0
        try:
            t, a = normalize_track(title, artist)
            best: Lyrics | None = None
            try:
                best = await self._lrclib(key, t, a, album, duration)
            except Exception as e:
                errors += 1
                log.info("lrclib failed for %s: %s", title, e)
            if (best is None or not best.synced) and self._meta.get(key) != "instrumental":
                try:
                    alt = await self._syncedlyrics(f"{t} {a}".strip(), duration)
                    if alt is not None:
                        best = alt
                except Exception as e:
                    errors += 1
                    log.info("syncedlyrics failed for %s: %s", title, e)
            self._store(key, best)
            if best is None and errors:
                self._failed_at[key] = time.monotonic()
        finally:
            self._pending.discard(key)
            self.hub.on_change(self.name)
        # try to upgrade line-synced lyrics to word-synced ones (Musixmatch, when it answers)
        lyr = self._cache.get(key)
        if lyr is not None and lyr.synced and not lyr.word_synced:
            try:
                up = await self._enhanced(f"{t} {a}".strip(), lyr)
                if up is not None and self._cache.get(key) is lyr:
                    self._store(key, up)
                    self.hub.on_change(self.name)
            except Exception as e:
                log.debug("enhanced lyrics failed for %s: %s", title, e)

    async def _lrclib(self, key: str, title: str, artist: str, album: str, duration: float) -> Lyrics | None:
        http = self.hub.http
        attempts: list[dict[str, Any]] = []
        full: dict[str, Any] = {"track_name": title, "artist_name": artist}
        if album:
            full["album_name"] = album
        if duration and duration > 0:
            full["duration"] = round(duration)
        attempts.append(full)
        if len(full) > 2:
            attempts.append({"track_name": title, "artist_name": artist})
        if artist:
            for params in attempts:
                r = await http.get(f"{LRCLIB}/get", params=params)
                if r.status_code == 200:
                    lyr = self._from_record(key, r.json(), duration)
                    if lyr is not None and lyr.synced:
                        return lyr
                elif r.status_code != 404:
                    r.raise_for_status()
        results: list[dict[str, Any]] = []
        for params in (
            {"track_name": title, "artist_name": artist} if artist else {"track_name": title},
            {"q": f"{artist} {title}".strip()},
        ):
            r = await http.get(f"{LRCLIB}/search", params=params)
            r.raise_for_status()
            results = [x for x in (r.json() or []) if isinstance(x, dict)]
            if results:
                break
        rec = pick_best(results, title, artist, duration)
        return self._from_record(key, rec, duration) if rec else None

    def _from_record(self, key: str, rec: dict[str, Any], duration: float) -> Lyrics | None:
        if rec.get("instrumental"):
            self._meta[key] = "instrumental"
            return None
        synced = rec.get("syncedLyrics") or ""
        if synced.strip():
            lines = clean_lines(parse_lrc_lines(synced))
            if lines:
                return Lyrics(lines, synced=True, source="lrclib")
        plain = rec.get("plainLyrics") or ""
        if plain.strip():
            dur = duration or float(rec.get("duration") or 0)
            lines = plain_lines(plain, dur)
            if lines:
                return Lyrics(lines, synced=False, source="lrclib")
        return None

    async def _syncedlyrics(self, term: str, duration: float) -> Lyrics | None:
        import syncedlyrics

        lrc = await asyncio.wait_for(
            asyncio.to_thread(
                syncedlyrics.search, term, synced_only=True, providers=["Musixmatch", "NetEase", "Megalobiz"]
            ),
            timeout=20,
        )
        if not lrc:
            return None
        lines = clean_lines(parse_lrc_lines(lrc))
        return Lyrics(lines, synced=True, source="syncedlyrics") if lines else None

    async def _enhanced(self, term: str, base: Lyrics) -> Lyrics | None:
        import syncedlyrics

        lrc = await asyncio.wait_for(
            asyncio.to_thread(syncedlyrics.search, term, enhanced=True, providers=["Musixmatch"]), timeout=15
        )
        if not lrc or not _WORD_STAMP.search(lrc):
            return None
        lines = clean_lines(parse_lrc_lines(lrc))
        # sanity: must describe the same song (similar line count and first-line time)
        if not lines or abs(len(lines) - len(base)) > max(4, len(base) // 4):
            return None
        if base.entries and abs(lines[0].start - base.entries[0].start) > 4:
            return None
        return Lyrics(lines, synced=True, source="musixmatch")


def pick_best(
    results: list[dict[str, Any]], title: str, artist: str, duration: float
) -> dict[str, Any] | None:
    """Best LRCLIB search record for (title, artist, duration); None if nothing plausibly matches."""

    def sim(a: str, b: str) -> float:
        a, b = re.sub(r"\W+", " ", a.lower()).strip(), re.sub(r"\W+", " ", b.lower()).strip()
        if not a or not b:
            return 0.0
        return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()

    best, best_score = None, -1e9
    for rec in results:
        rt, ra = normalize_track(
            str(rec.get("trackName") or rec.get("name") or ""), str(rec.get("artistName") or "")
        )
        ts = sim(rt, title)
        if ts < 0.6:
            continue
        score = ts * 2.0 + (sim(ra, artist) * 1.5 if artist else 0.0)
        score += 2.0 if rec.get("syncedLyrics") else (0.5 if rec.get("plainLyrics") else -3.0)
        rd = float(rec.get("duration") or 0)
        if duration and rd:
            d = abs(rd - duration)
            score += 1.5 if d <= 2 else 0.8 if d <= 5 else -0.5 if d <= 15 else -2.5
        if score > best_score:
            best, best_score = rec, score
    return best
