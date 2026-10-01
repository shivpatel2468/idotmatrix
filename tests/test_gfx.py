import numpy as np
import pytest

from deskdot.gfx import FONTS, Frame, Sprite, measure, to_rgb, wrap
from deskdot.gfx.color import calibrate
from deskdot.gfx.font import fit, marquee_x
from deskdot.gfx.image import encode_gif, fit_image, import_media


def test_primitives_clip_to_panel() -> None:
    f = Frame()
    f.rect(-10, -10, 100, 100, (255, 0, 0))
    assert (f.px == (255, 0, 0)).all()
    f.clear().line(-5, -5, 40, 40, "#00ff00")
    assert f.get(0, 0) == (0, 255, 0) and f.get(31, 31) == (0, 255, 0)
    f.text(28, 30, "WWWW", (1, 2, 3))  # runs off the right and bottom edges — must not raise
    f.circle(0, 0, 50, (9, 9, 9))


def test_text_never_draws_outside_clip() -> None:
    f = Frame()
    f.text(-7, 10, "HELLO WORLD", (255, 255, 255), clip=(5, 0, 20, 31))
    lit = np.argwhere(f.px.any(axis=2))
    assert lit[:, 1].min() >= 5 and lit[:, 1].max() <= 20


@pytest.mark.parametrize("name", list(FONTS))
def test_fonts_are_well_formed(name: str) -> None:
    font = FONTS[name]
    digits = {font.glyph(d).shape[1] for d in "0123456789"}
    assert len(digits) == 1, "digits must be tabular so numbers don't jitter"
    for g in font.glyphs.values():
        assert g.shape[0] == font.height


def test_tiny_letters_distinct() -> None:
    # regressions from the old build: duplicate 'V' key and 0 == O
    t = FONTS["tiny"]
    assert not np.array_equal(t.glyph("V"), t.glyph("U"))
    assert not np.array_equal(t.glyph("0"), t.glyph("O"))


def test_measure_wrap_fit() -> None:
    assert measure("") == 0
    assert measure("AB") == 3 + 1 + 3
    lines = wrap("THE QUICK BROWN FOX JUMPS", 30)
    assert all(measure(ln) <= 30 for ln in lines)
    assert measure(fit("SUPERCALIFRAGILISTIC", 20)) <= 20
    assert marquee_x("HI", 5.0, 0, 32) == (32 - measure("HI")) // 2  # fits: centred, static


def test_color_parsing() -> None:
    assert to_rgb("#f00") == (255, 0, 0)
    assert to_rgb("00ff00") == (0, 255, 0)
    assert to_rgb("ember") == (255, 72, 24)
    assert to_rgb((300, -5, 10)) == (255, 0, 10)


def test_calibration_crushes_black_and_keeps_white() -> None:
    from PIL import Image

    img = Image.new("RGB", (4, 1))
    img.putdata([(5, 5, 5), (128, 128, 128), (255, 255, 255), (0, 0, 0)])
    cal = calibrate(img, "vibrant")
    out = [cal.getpixel((x, 0)) for x in range(4)]
    assert out[0] == (0, 0, 0)
    assert out[1][0] < 128  # gamma darkens midtones
    assert out[2][0] == 255 and out[2][2] < 255  # white balance trims blue


def test_sprite_parse_and_blit() -> None:
    s = Sprite.parse([".#.", "###"], {"#": "#ff0000"})
    f = Frame()
    f.sprite(s, 30, 30)  # partially off-panel
    assert f.get(31, 30) == (255, 0, 0) and f.get(30, 30) == (0, 0, 0)


def test_fit_image_and_gif_roundtrip() -> None:
    from PIL import Image

    img = Image.new("RGBA", (200, 100), (255, 0, 0, 255))
    out = fit_image(img, "contain")
    assert out.size == (32, 32)
    frames = [Frame(fill=(i * 20, 0, 0)) for i in range(5)]
    gif = encode_gif(frames, [100] * 5)
    assert gif[:6] == b"GIF89a"
    back, durations = import_media(gif, profile="raw")
    assert len(back) == 5 and durations == [100] * 5


def test_worldmap_masks_and_projection() -> None:
    from deskdot.gfx.worldmap import SIZES, draw_world, land, project

    for w, h in SIZES:
        m = land(w, h)
        assert m.shape == (h, w)
        assert 0.2 < m.mean() < 0.45  # roughly the Earth's land fraction on this projection
    x, y = project(19.07, 72.88)  # Mumbai
    assert land(32, 16)[int(y), int(x)] or land(32, 16)[int(y), int(x) + 1]
    f = Frame()
    draw_world(f, (0, 200, 0), (0, 0, 40), size=(128, 64), view=(32, 32), offset=(80, 16), x=0, y=0)
    assert f.px.any()
    draw_world(f, "#00ff00", None, x=-40, y=40)  # fully off-panel: no error


def test_gif_budget_is_a_hard_limit() -> None:
    from deskdot.gfx.image import GIF_BUDGET, encode_gif_budget

    rng = np.random.default_rng(7)
    frames = []
    for _ in range(120):  # noisy frames compress terribly
        f = Frame()
        f.px[:] = rng.integers(0, 255, (32, 32, 3), dtype=np.uint8)
        frames.append(f)
    gif = encode_gif_budget(frames, [100] * len(frames))
    assert len(gif) <= GIF_BUDGET
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(gif))
    total = 0
    for i in range(im.n_frames):
        im.seek(i)
        total += im.info.get("duration", 0)
    assert abs(total - 12000) <= 200, "playback time is preserved when frames are dropped"
