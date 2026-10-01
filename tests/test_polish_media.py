"""Smoothness and clarity rules for the media apps (Now Playing, Visualizer, Camera, Mirror, Photo Frame,
Gallery, Pokédex, Chess, Trivia): seamless loops, even frame rates, GIFs that fit without dropped frames,
bars that fall smoothly, marquees that step evenly, text inside the margins and tones the LEDs can show."""

from __future__ import annotations

import io
import itertools
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image

from dotdeck.apps import chess as chess_app
from dotdeck.apps import live
from dotdeck.apps import nowplaying as np_app
from dotdeck.apps import photoframe as photo_app
from dotdeck.apps import pokedex as dex_app
from dotdeck.apps import trivia as trivia_app
from dotdeck.apps.gallery import Gallery, GallerySettings
from dotdeck.gfx import Frame
from dotdeck.gfx.image import GIF_BUDGET, encode_gif, encode_gif_budget
from dotdeck.providers import photos
from test_music import LYR, _Ctx, _FakeAudio, _FakeMedia, _png, _value
from test_visuals import Ctx, FakeHub, _chess_app, _dex_provider, _photo


def gif_frames(data: bytes) -> int:
    return getattr(Image.open(io.BytesIO(data)), "n_frames", 1)


def fits_without_drops(frames: list[Frame], durations: list[int], colors: int) -> None:
    gif = encode_gif_budget(frames, durations, colors)
    assert len(gif) <= GIF_BUDGET
    # the budget encoder drops every other frame when a GIF is too big; the frame count must survive it
    assert gif_frames(gif) == gif_frames(encode_gif(frames, durations, max_colors=colors))


# ================================================================================ Pokédex
@pytest.mark.parametrize("view", ["cycle", "who", "stats", "portrait", "info"])
def test_pokedex_loop_is_seamless_even_and_fits(view: str) -> None:
    app = dex_app.Pokedex(Ctx(pokedex=_dex_provider()), dex_app.PokedexSettings(mode="specific", view=view))
    first, wrapped = Frame(), Frame()
    app.render(first, 0.0)
    app.render(wrapped, app.loop_seconds())
    assert first == wrapped
    clip = app.clip_frames()
    assert app.clip_fps <= 10
    assert all(d % 100 == 0 for d in clip.durations_ms), "whole 10 fps frames only"
    fits_without_drops(clip.frames, clip.durations_ms, app.clip_colors)


def test_pokedex_pages_fade_through_black_and_reveal_is_not_white() -> None:
    p = _dex_provider()
    app = dex_app.Pokedex(Ctx(pokedex=p), dex_app.PokedexSettings(mode="specific"))
    s = app.settings.page_seconds

    def lit(t: float) -> float:
        f = Frame()
        app.render(f, t)
        return float(f.px.astype(np.float32).sum())

    assert lit(s) < lit(s + 0.2) < lit(s + 1.0)  # a new page fades in instead of popping
    assert lit(s - 0.05) < lit(s - 1.0)  # and the old one fades out
    who = dex_app.Pokedex(Ctx(pokedex=p), dex_app.PokedexSettings(mode="specific", view="who"))
    f = Frame()
    who.render(f, who.settings.guess_seconds)  # the reveal flash
    assert f.px.min(axis=2).mean() < 150, "no full-panel white on LEDs"


# ================================================================================ Chess
@pytest.mark.parametrize("theme", ["night", "wood", "green", "blue"])
def test_chess_loop_even_seamless_and_fits(theme: str) -> None:
    app = _chess_app(theme=theme)
    pz = app.puzzle()
    assert pz is not None
    first, wrapped = Frame(), Frame()
    app.render(first, 0.0)
    app.render(wrapped, app.loop_seconds(pz))
    assert first == wrapped
    clip = app.clip_frames()
    assert len(clip.frames) <= 180
    step = round(1000 / app.clip_fps)
    assert all(d % step == 0 for d in clip.durations_ms) or all(
        d % (2 * step) == 0 for d in clip.durations_ms
    )
    fits_without_drops(clip.frames, clip.durations_ms, app.clip_colors)


def test_chess_pieces_glide_in_small_steps() -> None:
    app = _chess_app()
    pz = app.puzzle()
    assert pz is not None
    start = app._intro_len(pz) + app.settings.think
    for i, mv in enumerate(pz.moves[:3]):
        slide = app._slide(pz, mv)
        (x0, y0), (x1, y1) = app.xy(pz, *mv.frm), app.xy(pz, *mv.to)
        dist = max(abs(x1 - x0), abs(y1 - y0))
        frames = round(slide * chess_app.FPS)
        # eased, so the middle frames move fastest; still only a few pixels per frame
        assert dist / frames <= 2.5, f"move {i}: {dist} px in {frames} frames"
        start += slide + app.settings.move_seconds


def test_chess_night_board_survives_gamma() -> None:
    light, dark, *_ = chess_app.THEMES["night"]
    assert max(light) >= 60 and max(light) - max(dark) >= 40  # the checkerboard reads on the panel


# ================================================================================ Trivia
@pytest.mark.parametrize("word", ["BREAKING", "PRACTICE", "FREEZING", "'NEPHELOC", "IN CLOUDS"])
def test_trivia_text_stays_inside_the_margins(word: str) -> None:
    f = Frame()
    trivia_app.text_fit(f, 10, word, (255, 255, 255))
    assert f.px[:, 0].max() == 0 and f.px[:, 31].max() == 0
    assert f.px.any()


def test_trivia_marquee_steps_one_pixel_per_frame() -> None:
    assert trivia_app.Trivia.fps == trivia_app.MARQUEE  # px/s == frames/s


# ================================================================================ Visualizer
class _Audio:
    error = None

    def __init__(self) -> None:
        self.value: dict[str, Any] | None = None


class _ACtx:
    def __init__(self, a: _Audio) -> None:
        self.a = a

    def provider(self, _n: str) -> Any:
        return self.a


def _audio(level: float) -> dict[str, Any]:
    b = [level] * 32
    return {"bands": b, "peaks": b, "level": 0.1, "wave": [0.0] * 32}


@pytest.mark.parametrize("style", ["bars", "mirror", "fire", "radial", "rings"])
def test_visualizer_bars_fall_smoothly(style: str) -> None:
    a = _Audio()
    app = live.Visualizer(_ACtx(a), live.VisualizerSettings(style=style, peaks=False))
    a.value = _audio(1.0)
    app.render(Frame(), 0.0)
    a.value = _audio(0.0)  # silence: the capture's own value drops at once
    levels, heights = [1.0], []
    for i in range(1, 16):
        f = Frame()
        app.render(f, i / app.fps)
        assert app._lv is not None
        levels.append(float(app._lv[5]))
        heights.append(int((f.px[:, 5].max(axis=1) > 0).sum()))
    falls = -np.diff(levels)
    steady = falls[levels[1:] > np.float32(0.0)]
    assert np.allclose(steady, live.FALL / app.fps, atol=1e-4), "an even fall, not a drop"
    if style == "bars":
        assert max(-np.diff(heights)) <= round(live.FALL / app.fps * 31) + 1


def test_visualizer_top_pixel_is_sub_pixel() -> None:
    a = _Audio()
    app = live.Visualizer(_ACtx(a), live.VisualizerSettings(style="bars", palette="mono", peaks=False))
    a.value = _audio(10.5 / 31)
    f = Frame()
    app.render(f, 0.0)
    col = f.px[:, 5].max(axis=1)
    assert col[31 - 10] > 0 and 0 < col[31 - 10] < col[31 - 5]  # a half-lit top row


def test_camera_and_mirror_show_the_captured_frame() -> None:
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (32, 32, 3), dtype=np.uint8)

    class P:
        value = img
        error = None

        def configure(self, *a: Any) -> None: ...

    class C:
        def provider(self, _n: str) -> Any:
            return P()

    for cls, st in ((live.Camera, live.CameraSettings()), (live.Mirror, live.MirrorSettings())):
        f = Frame()
        cls(C(), st).render(f, 0.0)  # type: ignore[arg-type]
        assert np.array_equal(f.px, img)


# ================================================================================ Now Playing
def _np(layout: str, art: bytes | None = None, **kw: Any) -> tuple[np_app.NowPlaying, _FakeMedia]:
    media = _FakeMedia(_value(), art=art)
    media.value["title"] = "A Very Long Song Title That Scrolls"  # type: ignore[index]
    app = np_app.NowPlaying(_Ctx(media, LYR, _FakeAudio()), np_app.NowPlayingSettings(layout=layout, **kw))
    return app, media


def test_nowplaying_colours_from_dark_art_stay_readable() -> None:
    dark = _png([(10, 20, 60), (5, 5, 30)])
    app, _media = _np("karaoke", art=dark)
    app.render(Frame(), 0.0)
    assert max(app._sung()) >= np_app.READABLE and max(app._accent()) >= np_app.READABLE


@pytest.mark.parametrize("layout", ["minimal", "spectrum_art", "cover_text", "palette"])
def test_nowplaying_marquee_moves_evenly(layout: str) -> None:
    app, media = _np(layout, art=None)
    fps = app.fps
    xs = []
    for i in range(int(fps * 4)):
        t = 2.0 + i / fps
        media.position = t
        f = Frame()
        app.render(f, t)
        # the leftmost lit column of the title row tracks the scroll
        y = {"minimal": 8, "spectrum_art": 1, "cover_text": 24, "palette": 9}[layout]
        row = (f.px[y : y + 5] >= 250).all(axis=2).any(axis=0)
        xs.append(row)
    shifts = []
    for a, b in itertools.pairwise(xs):
        best = min(range(0, 4), key=lambda d: int((a[d:] != b[: 32 - d]).sum()))
        shifts.append(best)
    moving = [d for d in shifts if d]
    assert moving and len(set(moving)) == 1, f"uneven marquee steps {shifts}"


def test_nowplaying_spectrum_falls_smoothly() -> None:
    app, _media = _np("spectrum_art")
    vals = [app._smooth_bars([1.0] * 10, 0.0)]
    for i in range(1, 12):
        vals.append(app._smooth_bars([0.0] * 10, i / 10))
    drops = np.diff([-v[0] for v in vals])
    assert np.allclose(drops[:7], np_app.FALL / 10, atol=1e-5)  # then it rests on the floor


# ================================================================================ Photo Frame
def _photos_provider(value: list[Any]) -> Any:
    p = photos.PhotosProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
    p.value = value
    return p


def test_photoframe_crossfade_starts_from_the_frame_on_screen() -> None:
    p = _photos_provider([_photo(1), _photo(2)])
    app = photo_app.PhotoFrame(Ctx(photos=p), photo_app.PhotoFrameSettings(interval=17, caption="off"))
    clock = [100.0]
    app._clock = lambda: clock[0]
    app.render(Frame(), 0)
    clock[0] += 16.95
    before = Frame()
    app.render(before, 0)  # mid-zoom: not the loop's first frame
    assert not np.array_equal(before.px, p.value[0].kb[0])
    clock[0] += 0.1
    after = Frame()
    app.render(after, 0)
    assert app._cur.seq == 2  # type: ignore[union-attr]
    # 1/8 into the crossfade: still almost exactly what was on screen, no jump back to the zoom's start
    diff = np.abs(after.px.astype(int) - before.px.astype(int)).mean()
    jump = np.abs(after.px.astype(int) - p.value[0].kb[0].astype(int)).mean()
    assert diff < jump


@pytest.mark.parametrize("caption", ["intro", "always"])
def test_photoframe_caption_hands_over_without_popping(caption: str) -> None:
    black = np.zeros((32, 32, 3), np.uint8)
    kb = [black] * photos.KB_FRAMES
    p = _photos_provider([photos.Photo(1, "met", "A TITLE THAT IS FAR TOO LONG", "ARTIST", black, kb, "k")])
    app = photo_app.PhotoFrame(Ctx(photos=p), photo_app.PhotoFrameSettings(interval=30, caption=caption))
    clock = [100.0]
    app._clock = lambda: clock[0]
    app.render(Frame(), 0)
    intro = app._intro_len()
    peak = []
    for i in range(12):
        clock[0] = 100.0 + intro - 0.1 + i * photo_app.CAPTION_OUT / 8
        f = Frame()
        app.render(f, 0)
        peak.append(int(f.px[26:31].max()))
    # the scrolling line dims in steps instead of vanishing / swapping in one frame
    assert any(0 < v < 200 for v in peak), peak
    assert app.kind() == "clip"


# ================================================================================ Gallery
def test_gallery_empty_state_keeps_margins() -> None:
    class C:
        library = None
        data: dict[str, Any] = {}  # noqa: RUF012

    f = Frame()
    Gallery(C(), GallerySettings()).render(f, 0.0)  # type: ignore[arg-type]
    assert f.px.any() and f.px[:, 0].max() == 0 and f.px[:, 31].max() == 0
