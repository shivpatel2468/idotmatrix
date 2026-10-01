"""Music: LRC parsing, word timing, title normalisation, lyric search, media clock, palettes, macOS parsing,
and every Now Playing layout rendering with and without data. No network: HTTP and subprocesses are mocked."""

from __future__ import annotations

import asyncio
import io
import time
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image

from deskdot.apps.nowplaying import NowPlaying, NowPlayingSettings, clean, layout_line
from deskdot.gfx import Frame
from deskdot.providers import lyrics as lyr_mod
from deskdot.providers import media_mac
from deskdot.providers.lyrics import (
    Lyrics,
    LyricsProvider,
    clean_lines,
    normalize_track,
    parse_lrc,
    parse_lrc_lines,
    pick_best,
    plain_lines,
)
from deskdot.providers.media import MediaProvider, Snapshot, classify_source, decode_art, extract_palette
from deskdot.providers.media_mac import (
    SEP,
    MacBackend,
    parse_applescript_data,
    parse_nowplaying_cli,
    parse_player,
)

LRC = """[ti:Test]
[00:01.00]Is this the real life?
[00:05.50]Is this just fantasy?
[00:10.00][00:30.00]Caught in a landslide
[00:14.00]♪
[00:20.00]No escape from reality
"""

ENHANCED = """[00:01.00]<00:01.00> Hello <00:01.50> big <00:02.00> world <00:03.00>
[00:04.00]<00:04.00>Two words<00:05.00>
[00:06.00]plain line here
"""


# ------------------------------------------------------------------------------------------ LRC
def test_parse_lrc_compat_and_multistamp() -> None:
    lines = parse_lrc(LRC)
    assert lines[0] == (1.0, "Is this the real life?")
    assert [t for t, _ in lines] == sorted(t for t, _ in lines)
    assert (30.0, "Caught in a landslide") in lines and (10.0, "Caught in a landslide") in lines


def test_parse_lrc_offset_tag() -> None:
    lines = parse_lrc_lines("[offset:+500]\n[00:02.00]a b\n")
    assert lines[0].start == pytest.approx(1.5)
    assert lines[0].words[0].start == pytest.approx(1.5)


def test_enhanced_word_timing() -> None:
    lines = parse_lrc_lines(ENHANCED)
    first = lines[0]
    assert first.timed and first.text == "Hello big world"
    assert [(w.text, w.start, w.end) for w in first.words] == [
        ("Hello", 1.0, 1.5),
        ("big", 1.5, 2.0),
        ("world", 2.0, 3.0),
    ]
    two = lines[1].words  # one stamp, two words: the interval is shared
    assert [w.text for w in two] == ["Two", "words"]
    assert two[0].start == 4.0 and two[1].end == pytest.approx(5.0) and two[0].end == pytest.approx(4.5)
    assert not lines[2].timed and len(lines[2].words) == 3  # estimated
    assert Lyrics(lines).word_synced


def test_estimated_words_split_by_length() -> None:
    lyr = Lyrics(parse_lrc_lines("[00:00.00]aa bbbbbbbb\n[00:10.00]next"))
    w = lyr.entries[0].words
    assert w[0].start == 0 and w[0].end < w[1].end
    assert (w[1].end - w[1].start) > (w[0].end - w[0].start)  # longer word, longer time
    assert lyr.entries[0].end < 10.0  # the sung part ends before the next line


def test_words_at_and_at() -> None:
    lyr = Lyrics(parse_lrc_lines(ENHANCED))
    words, idx, prog = lyr.words_at(1.75)
    assert [w.text for w in words] == ["Hello", "big", "world"] and idx == 1
    assert prog == pytest.approx(0.5)
    assert lyr.words_at(0.2) == ([], -1, 0.0)
    assert lyr.words_at(3.5).index == 2 and lyr.words_at(3.5).progress == 1.0
    i, cur, nxt, p = lyr.at(1.5)
    assert (i, cur, nxt) == (0, "Hello big world", "Two words") and 0 < p < 1
    assert Lyrics([(0.0, "a"), (2.0, "b")]).at(1.0)[1] == "a"  # the classic tuple constructor still works


def test_gap_markers_and_plain() -> None:
    lines = clean_lines(parse_lrc_lines(LRC))
    texts = [ln.text for ln in lines]
    assert "" in texts and "♪" not in texts  # "♪" became an empty gap marker
    plain = plain_lines("First line\n\nSecond line\n[ar:x]\nThird", 200)
    assert [p.text for p in plain] == ["First line", "Second line", "Third"]
    assert plain[0].start == pytest.approx(10.0) and plain[-1].end <= 190.0
    assert not Lyrics(plain, synced=False).synced


@pytest.mark.parametrize(
    ("title", "artist", "want"),
    [
        ("Hey Jude - Remastered 2015", "The Beatles", ("Hey Jude", "The Beatles")),
        ("Come Together (Remastered 2009)", "The Beatles", ("Come Together", "The Beatles")),
        (
            "Queen - Bohemian Rhapsody (Official Video Remastered)",
            "Queen Official",
            ("Bohemian Rhapsody", "Queen"),
        ),
        ("Blinding Lights", "The Weeknd - Topic", ("Blinding Lights", "The Weeknd")),
        ("Levitating (feat. DaBaby)", "Dua Lipa, DaBaby", ("Levitating", "Dua Lipa")),
        ("Anti-Hero", "TaylorSwiftVEVO", ("Anti-Hero", "Taylor Swift")),
        ("Stay With Me", "Sam Smith", ("Stay With Me", "Sam Smith")),
        ("Numb (Official Music Video) [4K UPGRADE] – Linkin Park", "Linkin Park", ("Numb", "Linkin Park")),
        ("Billie Eilish - bad guy", "", ("bad guy", "Billie Eilish")),
        ("Get Lucky ft. Pharrell Williams", "Daft Punk", ("Get Lucky", "Daft Punk")),
        ("Hello (Live)", "Adele", ("Hello (Live)", "Adele")),
    ],
)
def test_normalize_track(title: str, artist: str, want: tuple[str, str]) -> None:
    assert normalize_track(title, artist) == want


def test_pick_best_prefers_synced_and_duration() -> None:
    recs = [
        {"trackName": "Song", "artistName": "Band", "duration": 300, "syncedLyrics": "[00:01.00]x"},
        {"trackName": "Song", "artistName": "Band", "duration": 201, "syncedLyrics": "[00:01.00]y"},
        {"trackName": "Song", "artistName": "Band", "duration": 200, "plainLyrics": "z"},
        {"trackName": "Other thing", "artistName": "Band", "duration": 200, "syncedLyrics": "[00:01.00]q"},
    ]
    assert pick_best(recs, "Song", "Band", 200)["duration"] == 201
    assert pick_best(recs[3:], "Song", "Band", 200) is None


# ------------------------------------------------------------------------------------------ lyric search
class _Hub:
    def __init__(self, handler: Any) -> None:
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.changes: list[str] = []

    def on_change(self, name: str) -> None:
        self.changes.append(name)


async def _wait(lp: LyricsProvider, title: str, artist: str) -> None:
    for _ in range(200):
        if lp.status(title, artist) != "searching":
            return
        await asyncio.sleep(0.01)


async def test_lyrics_provider_lrclib_get(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.path == "/api/get":
            assert req.url.params["track_name"] == "Bohemian Rhapsody"
            return httpx.Response(200, json={"syncedLyrics": LRC, "instrumental": False, "duration": 354})
        return httpx.Response(404, json={})

    async def no_enhanced(self: Any, term: str, base: Any) -> None:
        return None

    monkeypatch.setattr(LyricsProvider, "_enhanced", no_enhanced)
    hub = _Hub(handler)
    lp = LyricsProvider(hub)
    t, a = "Queen - Bohemian Rhapsody (Official Video)", "Queen Official"
    assert lp.get(t, a, "", 354) is None and lp.status(t, a) == "searching"
    await _wait(lp, t, a)
    got = lp.get(t, a)
    assert got is not None and got.synced and got.source == "lrclib" and lp.status(t, a) == "found"
    n = len(calls)
    assert lp.get(t, a) is got and len(calls) == n  # cached, no new request
    assert "lyrics" in hub.changes
    await hub.http.aclose()


async def test_lyrics_provider_instrumental_plain_and_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        name = req.url.params.get("track_name", "") or req.url.params.get("q", "")
        if "Canon" in name:
            return httpx.Response(200, json={"instrumental": True})
        if "Plainy" in name and req.url.path == "/api/search":
            return httpx.Response(
                200, json=[{"trackName": "Plainy", "artistName": "X", "plainLyrics": "a\nb"}]
            )
        if req.url.path == "/api/search":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})

    async def fake_synced(self: Any, term: str, duration: float) -> Any:
        return None

    monkeypatch.setattr(LyricsProvider, "_syncedlyrics", fake_synced)
    hub = _Hub(handler)
    lp = LyricsProvider(hub)
    for t in ("Canon in D", "Plainy", "Nothing"):
        lp.get(t, "X", "", 120)
    for t in ("Canon in D", "Plainy", "Nothing"):
        await _wait(lp, t, "X")
    assert lp.status("Canon in D", "X") == "instrumental" and lp.get("Canon in D", "X") is None
    plain = lp.get("Plainy", "X")
    assert plain is not None and not plain.synced and lp.status("Plainy", "X") == "plain"
    assert lp.status("Nothing", "X") == "none"
    await hub.http.aclose()


async def test_lyrics_provider_falls_back_to_syncedlyrics(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_synced(self: Any, term: str, duration: float) -> Any:
        return Lyrics(parse_lrc_lines(ENHANCED), source="syncedlyrics")

    monkeypatch.setattr(LyricsProvider, "_syncedlyrics", fake_synced)
    hub = _Hub(lambda req: httpx.Response(404 if req.url.path == "/api/get" else 200, json=[]))
    lp = LyricsProvider(hub)
    lp.get("Song", "Band")
    await _wait(lp, "Song", "Band")
    got = lp.get("Song", "Band")
    assert got is not None and got.source == "syncedlyrics" and got.word_synced
    await hub.http.aclose()


def test_lyrics_module_keeps_public_names() -> None:
    assert lyr_mod.LyricsProvider.name == "lyrics"
    assert callable(lyr_mod.Lyrics.at) and callable(lyr_mod.Lyrics.words_at)


# ------------------------------------------------------------------------------------------ media
def _png(colors: list[tuple[int, int, int]], size: int = 64) -> bytes:
    img = Image.new("RGB", (size, size))
    band = size // len(colors)
    for i, c in enumerate(colors):
        img.paste(c, (0, i * band, size, (i + 1) * band if i < len(colors) - 1 else size))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_extract_palette() -> None:
    img = decode_art(_png([(220, 20, 30), (220, 20, 30), (30, 40, 200)]))
    pal = extract_palette(img)
    assert 3 <= len(pal) <= 5
    assert pal[0][0] > 200 and pal[0][2] < 120  # dominant red first, normalised to full value
    assert any(c[2] > 200 and c[0] < 150 for c in pal)  # the blue is in there
    assert pal == extract_palette(img)  # deterministic
    grey = extract_palette(decode_art(_png([(90, 90, 90), (200, 200, 200)])))
    assert len(grey) >= 3


def test_decode_art_crops_letterbox() -> None:
    img = Image.new("RGB", (160, 90), (0, 0, 0))
    img.paste((255, 0, 0), (0, 20, 160, 70))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    out = decode_art(buf.getvalue())
    assert out.size == (128, 128)
    assert np.asarray(out)[64, 64, 0] > 200
    assert decode_art(b"not an image") is None


@pytest.mark.parametrize(
    ("app", "artist", "want"),
    [
        ("Spotify.exe", "", "spotify"),
        ("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "", "spotify"),
        ("Chrome", "Queen", "chrome"),
        ("Chrome", "Queen - Topic", "youtube_music"),
        ("Chrome._crx_cinhimbnkkaeohfgghhklpknlkffjgod", "", "youtube_music"),
        ("MSEdge", "", "edge"),
        ("AppleInc.AppleMusicWin_nzyj5cx40ttqa!App", "", "apple_music"),
        ("308046B0AF4A39CB", "", "firefox"),
        ("", "", "other"),
    ],
)
def test_classify_source(app: str, artist: str, want: str) -> None:
    key, label = classify_source(app, "t", artist)
    assert key == want and label


class FakeBackend:
    def __init__(self) -> None:
        self.snap: Snapshot | None = None
        self.art_bytes: bytes | None = None
        self.controls: list[str] = []

    async def snapshot(self) -> Snapshot | None:
        return self.snap

    async def art(self) -> bytes | None:
        return self.art_bytes

    async def control(self, action: str) -> bool:
        self.controls.append(action)
        return True


async def test_media_clock_seek_jitter_pause() -> None:
    hub = _Hub(lambda req: httpx.Response(404))
    be = FakeBackend()
    mp = MediaProvider(hub, backend=be)
    now = time.monotonic()
    be.snap = Snapshot("Song", "Band", playing=True, position=10.0, duration=200, app="Spotify.exe", sampled=now,
                       stamp=1)  # fmt: skip
    v = await mp.fetch()
    assert v["active"] and v["source"] == "spotify" and v["is_spotify"] and v["source_label"] == "SPOTIFY"
    for key in (
        "title",
        "artist",
        "album",
        "playing",
        "position",
        "duration",
        "app",
        "art_id",
        "track",
        "palette",
    ):
        assert key in v
    assert mp.position == pytest.approx(10.0, abs=0.05)
    # a routine refresh that disagrees by < jitter keeps our smooth clock
    ours = mp.position
    be.snap = Snapshot("Song", "Band", playing=True, position=ours + 0.1, duration=200, sampled=time.monotonic(),
                       stamp=2)  # fmt: skip
    await mp.fetch()
    assert mp.position == pytest.approx(ours, abs=0.05)
    # a seek re-anchors
    be.snap = Snapshot(
        "Song", "Band", playing=True, position=120.0, duration=200, sampled=time.monotonic(), stamp=3
    )
    await mp.fetch()
    assert mp.position == pytest.approx(120.0, abs=0.05)
    # pause freezes
    be.snap = Snapshot(
        "Song", "Band", playing=False, position=121.0, duration=200, sampled=time.monotonic(), stamp=4
    )
    await mp.fetch()
    frozen = mp.position
    await asyncio.sleep(0.05)
    assert mp.position == frozen == pytest.approx(121.0)
    # nothing playing
    be.snap = None
    assert (await mp.fetch()) == {"active": False}
    await mp.control("next")
    assert be.controls == ["next"]
    await hub.http.aclose()


async def test_media_unknown_position_counts_from_track_start() -> None:
    hub = _Hub(lambda req: httpx.Response(404))
    be = FakeBackend()
    mp = MediaProvider(hub, backend=be)
    be.snap = Snapshot("A", "B", playing=True, position=0.0, sampled=time.monotonic(), position_known=False)
    await mp.fetch()
    await asyncio.sleep(0.06)
    await mp.fetch()  # a stale 0.0 must not pull the clock back
    assert mp.position >= 0.05
    await hub.http.aclose()


async def test_media_art_player_then_itunes(monkeypatch: pytest.MonkeyPatch) -> None:
    art = _png([(255, 0, 0), (0, 0, 255)])
    requests: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests.append(str(req.url))
        if req.url.host == "itunes.apple.com":
            return httpx.Response(
                200, json={"results": [{"artworkUrl100": "https://img.example/a/100x100bb.jpg"}]}
            )
        if req.url.host == "img.example":
            assert "600x600bb" in str(req.url)
            return httpx.Response(200, content=art)
        return httpx.Response(404)

    real_sleep = asyncio.sleep

    async def fast_sleep(d: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    hub = _Hub(handler)
    be = FakeBackend()
    mp = MediaProvider(hub, backend=be)
    mp.refresh = lambda: None  # type: ignore[method-assign]
    # 1) player art
    be.art_bytes = art
    be.snap = Snapshot("One", "Band", playing=True, sampled=time.monotonic())
    await mp.fetch()
    await mp._art_task  # type: ignore[misc]
    assert mp.art == art and mp.art_source == "player" and mp.art_id and mp.art_image is not None
    assert mp.palette[0][0] > 200
    # 2) no player art -> iTunes (and it is cached per search term)
    be.art_bytes = None
    be.snap = Snapshot("Two", "Band", playing=True, sampled=time.monotonic())
    await mp.fetch()
    assert mp.art is None  # reset on track change
    await mp._art_task  # type: ignore[misc]
    assert mp.art_source == "itunes" and mp.art == art
    n = len(requests)
    assert await mp._itunes_art("Two", "Band") == art and len(requests) == n
    await hub.http.aclose()


# ------------------------------------------------------------------------------------------ macOS
def test_parse_spotify_output() -> None:
    out = SEP.join(["playing", "Bohemian Rhapsody", "Queen", "A Night at the Opera", "354947", "12,5",
                    "https://i.scdn.co/image/abc", "spotify:track:1"]) + "\n"  # fmt: skip
    s = parse_player(out, "spotify", sampled=1.0)
    assert (
        s is not None and s.playing and s.title == "Bohemian Rhapsody" and s.album == "A Night at the Opera"
    )
    assert s.duration == pytest.approx(354.947) and s.position == pytest.approx(12.5)
    assert s.art_url == "https://i.scdn.co/image/abc" and s.app == "spotify"
    paused = parse_player(out.replace("playing", "kPSp", 1), "spotify")
    assert paused is not None and not paused.playing
    assert parse_player("stopped\n", "spotify") is None
    assert parse_player("none", "spotify") is None
    assert parse_player("", "spotify") is None


def test_parse_music_output() -> None:
    out = SEP.join(["paused", "Song", "Artist", "missing value", "215.3", "1.234,5", "", "ABC"])
    s = parse_player(out, "music")
    assert s is not None and not s.playing and s.duration == pytest.approx(215.3) and s.album == ""
    assert s.art_url is None


def test_parse_nowplaying_cli() -> None:
    out = "Song\nArtist\nnull\n200.5\n42\n1\nnull\n"
    s = parse_nowplaying_cli(out)
    assert (
        s is not None
        and s.playing
        and s.title == "Song"
        and s.album == ""
        and s.position == pytest.approx(42)
    )
    assert parse_nowplaying_cli("null\nnull\nnull\nnull\nnull\n0\nnull\n") is None


def test_parse_applescript_data() -> None:
    assert parse_applescript_data("«data JPEG FFD8FFE000»") == bytes.fromhex("FFD8FFE000")
    assert parse_applescript_data("«data tdta89504E47»") == bytes.fromhex("89504E47")
    assert parse_applescript_data("nothing") is None


class _Proc:
    def __init__(self, out: str, code: int = 0, err: str = "") -> None:
        self._out, self.returncode, self._err = out.encode(), code, err.encode()

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._out, self._err

    def kill(self) -> None:
        pass


async def test_mac_backend_prefers_playing_source(monkeypatch: pytest.MonkeyPatch) -> None:
    spotify = SEP.join(["paused", "S", "A", "Al", "100000", "3", "https://x/y.jpg", "id"])
    music = SEP.join(["playing", "M", "B", "Bl", "180", "7", "", "pid"])
    calls: list[tuple[str, ...]] = []

    async def fake_exec(*args: str, **kw: Any) -> _Proc:
        calls.append(args)
        if args[0] == "ps":
            return _Proc("/usr/sbin/cfprefsd\n/Applications/Spotify.app/Contents/MacOS/Spotify\n"
                         "/System/Applications/Music.app/Contents/MacOS/Music\n")  # fmt: skip
        if args[0] == "osascript":
            script = args[2]
            if "Spotify" in script and "playpause" not in script:
                return _Proc(spotify)
            if 'application "Music"' in script and "player state" in script:
                return _Proc(music)
            return _Proc("")
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(media_mac.shutil, "which", lambda name: None)
    monkeypatch.setattr(media_mac.asyncio, "create_subprocess_exec", fake_exec)
    be = MacBackend()
    snap = await be.snapshot()
    assert snap is not None and snap.title == "M" and snap.playing and snap.app == "music"
    assert await be.control("toggle")
    assert calls[-1][:2] == ("osascript", "-e") and 'tell application "Music" to playpause' in calls[-1][2]
    with pytest.raises(KeyError):
        await be.control("explode")


async def test_mac_backend_permission_denied_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_exec(*args: str, **kw: Any) -> _Proc:
        if args[0] == "ps":
            return _Proc("/Applications/Spotify.app/Contents/MacOS/Spotify\n")
        return _Proc("", 1, "execution error: Not authorized to send Apple events to Spotify. (-1743)")

    monkeypatch.setattr(media_mac.shutil, "which", lambda name: None)
    monkeypatch.setattr(media_mac.asyncio, "create_subprocess_exec", fake_exec)
    assert await MacBackend().snapshot() is None


# ------------------------------------------------------------------------------------------ app
def test_clean_and_layout_line() -> None:
    assert clean("Beyoncé’s “Déjà vu” — ok", "tiny") == 'BEYONCE\'S "DEJA VU" - OK'
    assert '"' not in clean('say "hi"', "small")
    line = Lyrics(parse_lrc_lines(ENHANCED)).entries[0]
    rows = layout_line(line, 0, "small")
    assert rows and all(r.w <= 30 or len(r.words) == 1 for r in rows)
    assert [len(r.words) for r in rows] and sum(len(r.words) for r in rows) == 3
    assert rows[0].words[0][:2] == (1.0, 1.5)
    assert rows[0].fill_x(0.5) == 0 and rows[-1].fill_x(10) == rows[-1].words[-1][3]
    wide = layout_line(Lyrics([(0.0, "escape")]).entries[0], 0, "auto")
    assert wide[0].dy == 1 and wide[0].w <= 30  # too wide for 7 px: a compact row, centred in the slot


class _FakeMedia:
    def __init__(
        self,
        value: dict[str, Any] | None,
        pos: float = 0.0,
        art: bytes | None = None,
        error: str | None = None,
    ):
        self.value, self.position, self.error = value, pos, error
        self.art = art
        self.art_image = decode_art(art) if art else None
        self.art_id = "id1" if art else None
        self.palette = (
            extract_palette(self.art_image) if art else [(255, 72, 24), (255, 170, 0), (255, 0, 190)]
        )


class _FakeLyrics:
    def __init__(self, lyr: Lyrics | None) -> None:
        self.lyr = lyr

    def get(self, *a: Any, **kw: Any) -> Lyrics | None:
        return self.lyr

    def status(self, *a: Any) -> str:
        return "found" if self.lyr else "none"


class _FakeAudio:
    def __init__(self, value: dict[str, Any] | None = None) -> None:
        self.value = value
        self.refs = 0

    def acquire(self) -> None:
        self.refs += 1

    def release(self) -> None:
        self.refs -= 1


class _Ctx:
    def __init__(self, media: _FakeMedia, lyr: Lyrics | None, audio: _FakeAudio | None = None) -> None:
        self.p = {"media": media, "lyrics": _FakeLyrics(lyr), "audio": audio or _FakeAudio()}

    def provider(self, name: str) -> Any:
        return self.p[name]


def _value(playing: bool = True, duration: float = 200.0) -> dict[str, Any]:
    return {"active": True, "title": "Déjà Vu (Remastered)", "artist": "Band", "album": "LP", "playing": playing,
            "position": 0.0, "duration": duration, "app": "Spotify.exe", "is_spotify": True, "source": "spotify",
            "source_label": "SPOTIFY", "art_id": None, "track": "x"}  # fmt: skip


LAYOUTS = list(NowPlayingSettings.model_fields["layout"].json_schema_extra["enum"])  # type: ignore[index]
ART = _png([(250, 60, 20), (20, 120, 250), (240, 220, 30)])
LYR = Lyrics(clean_lines(parse_lrc_lines(LRC + ENHANCED.replace("[00:0", "[00:4"))))


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize(
    "data", ["full", "no_art", "no_lyrics", "paused", "no_duration", "idle", "loading", "error"]
)
def test_every_layout_renders(layout: str, data: str) -> None:
    value: dict[str, Any] | None = _value(
        playing=data != "paused", duration=0 if data == "no_duration" else 200
    )
    if data == "idle":
        value = {"active": False}
    if data in ("loading", "error"):
        value = None
    media = _FakeMedia(
        value, art=None if data in ("no_art", "idle") else ART, error="boom" if data == "error" else None
    )
    app = NowPlaying(_Ctx(media, None if data == "no_lyrics" else LYR), NowPlayingSettings(layout=layout))
    worst = 0.0
    for pos in (0.0, 0.5, 1.2, 3.3, 7.9, 12.0, 15.0, 25.0, 41.0, 44.5, 60.0, 250.0):
        media.position = pos
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, pos)
        worst = max(worst, time.perf_counter() - t0) if pos else 0.0  # first frame builds the art cache
        assert f.px.shape == (32, 32, 3)
    assert worst < 0.02, f"{layout}/{data}: {worst * 1000:.1f} ms"
    st = app.status()
    assert isinstance(st, dict)
    if value and value.get("active"):
        assert st["source"] == "spotify" and "lyrics" in st


def test_karaoke_fill_moves_and_lights_panel() -> None:
    media = _FakeMedia(_value(), art=None)
    app = NowPlaying(_Ctx(media, LYR), NowPlayingSettings(layout="karaoke", theme_from_art=False))
    sung = np.array([255, 214, 0])

    def sung_pixels(pos: float) -> int:
        media.position = pos - app.settings.offset
        f = Frame()
        app.render(f, pos)
        return int((f.px == sung).all(axis=2).sum())

    a, b = sung_pixels(1.3), sung_pixels(2.6)
    assert 0 < a < b  # the fill advances through the line
    f = Frame()
    media.position = 3.0
    app.render(f, 3.0)
    assert f.px[:29].any(axis=2).sum() > 60  # big type fills the panel


@pytest.mark.parametrize("idle", ["no_music", "clock", "last_art", "nothing"])
def test_idle_screens(idle: str) -> None:
    media = _FakeMedia(_value(), art=ART)
    app = NowPlaying(_Ctx(media, LYR), NowPlayingSettings(layout="cover", idle_screen=idle))
    app.render(Frame(), 0.0)  # remember the art
    media.value = {"active": False}
    f = Frame()
    app.render(f, 1.0)
    assert f.px.any() == (idle != "nothing")


def test_audio_acquired_only_for_audio_layouts() -> None:
    audio = _FakeAudio({"bands": [0.5] * 32, "peaks": [0.7] * 32, "level": 0.2})
    media = _FakeMedia(_value(), art=ART)
    app = NowPlaying(_Ctx(media, LYR, audio), NowPlayingSettings(layout="karaoke"))
    app.on_start()
    assert audio.refs == 0
    app.settings = NowPlayingSettings(layout="spectrum_art")
    app.on_settings()
    assert audio.refs == 1
    f = Frame()
    app.render(f, 1.0)
    assert f.px.any()
    app.on_stop()
    assert audio.refs == 0
    assert NowPlaying.uses == ("media", "lyrics")
