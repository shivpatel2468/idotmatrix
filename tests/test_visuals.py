"""Visuals & Gaming apps: Photo Frame, Pokédex, Pixel Avatar, Chess Puzzle, Game Deals.

Parsers run on real captures (tests/fixtures/visuals/, trimmed, 2026-09-24); providers run against a mocked
HTTP transport; every app renders every Choice option with and without data, fast, and bakes clips that fit
the GIF budget.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image

from dotdeck.apps import avatar as avatar_app
from dotdeck.apps import chess as chess_app
from dotdeck.apps import gamedeals as deals_app
from dotdeck.apps import photoframe as photo_app
from dotdeck.apps import pokedex as dex_app
from dotdeck.gfx import Frame
from dotdeck.gfx.image import GIF_BUDGET, encode_gif_budget
from dotdeck.providers import avatars, chess, gamedeals, photos, pokedex

FIX = Path(__file__).parent / "fixtures" / "visuals"
APPS = {
    "photoframe": photo_app.PhotoFrame,
    "pokedex": dex_app.Pokedex,
    "avatar": avatar_app.PixelAvatar,
    "chess": chess_app.ChessPuzzle,
    "gamedeals": deals_app.GameDeals,
}
PROVIDERS = (
    photos.PhotosProvider,
    pokedex.PokedexProvider,
    avatars.AvatarsProvider,
    chess.ChessProvider,
    gamedeals.GameDealsProvider,
)
NOW = 1790200000.0  # 2026-09-24, when the fixtures were captured


def fx(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def raw(name: str) -> bytes:
    return (FIX / name).read_bytes()


def jpeg(w: int = 300, h: int = 200, subject: tuple[int, int] | None = None) -> bytes:
    """A flat grey 'photo' with a bright, textured subject square (for the smart crop)."""
    img = Image.new("RGB", (w, h), (90, 90, 90))
    if subject:
        sx, sy = subject
        sub = Image.effect_noise((60, 60), 80).convert("RGB")
        img.paste(Image.blend(sub, Image.new("RGB", (60, 60), (255, 40, 0)), 0.5), (sx, sy))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


class FakeHub:
    def __init__(self, handler: Any) -> None:
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, e: str, d: dict[str, Any]) -> None:
        self.events.append((e, d))

    def on_change(self, _n: str) -> None:
        pass


class Ctx:
    def __init__(self, **providers: Any) -> None:
        self.providers = providers
        self.data: dict[str, Any] = {}
        self.notices: list[dict[str, Any]] = []
        self.library = None

    def provider(self, name: str) -> Any:
        return self.providers[name]

    def save(self) -> None: ...
    def invalidate(self) -> None: ...

    def notify(self, **kw: Any) -> None:
        self.notices.append(kw)


def img_response(data: bytes, ctype: str = "image/png") -> httpx.Response:
    return httpx.Response(200, content=data, headers={"content-type": ctype})


# =============================================================================== Photo Frame
def test_photo_parsers() -> None:
    url, title, artist = photos.parse_met_object(fx("met_object.json"))  # type: ignore[misc]
    assert url.startswith("https://images.metmuseum.org/") and "web-large" in url
    assert title and artist == photos.artist_name(fx("met_object.json")["artistDisplayName"])
    assert photos.parse_met_object({"primaryImageSmall": ""}) is None
    cle = photos.parse_cleveland(fx("cleveland.json"))
    assert len(cle) == 2 and all(u.endswith("_web.jpg") for u, _t, _a in cle)
    assert "(" not in cle[0][2]  # nationality/dates stripped from the artist
    item = fx("picsum_list.json")[0]
    u = photos.picsum_url(item, 320)
    assert u.startswith("https://picsum.photos/id/") and max(int(x) for x in u.split("/")[-2:]) == 320
    assert (
        photos.dog_breed_from_url("https://images.dog.ceo/breeds/retriever-golden/n1.jpg")
        == "GOLDEN RETRIEVER"
    )
    assert photos.dog_api_url("") == "https://dog.ceo/api/breeds/image/random"
    assert photos.dog_api_url("golden retriever").endswith("/breed/retriever/golden/images/random")
    assert photos.dog_api_url("husky").endswith("/breed/husky/images/random")
    assert photos.artist_name("Vincent van Gogh (Dutch, 1853–1890)") == "Vincent van Gogh"
    assert fx("dog.json")["status"] == "success" and fx("fox.json")["image"] and fx("duck.json")["url"]
    assert fx("cat.json")["id"]


def test_smart_crop_finds_the_subject() -> None:
    img = Image.open(io.BytesIO(jpeg(300, 200, subject=(220, 70)))).convert("RGB")
    x0, _y0, x1, _y1 = photos.smart_square(img)
    assert x1 - x0 == 200 and x0 >= 80  # window slid right, towards the subject
    cx = photos.smart_square(img, "center")
    assert cx == (50, 0, 250, 200)


def test_prepare_photo() -> None:
    still, kb = photos.prepare(jpeg(400, 260, subject=(150, 90)), "smart", "vibrant", True, 0.85)
    assert still.shape == (32, 32, 3) and still.dtype == np.uint8
    assert len(kb) == photos.KB_FRAMES and all(k.shape == (32, 32, 3) for k in kb)
    assert not np.array_equal(kb[0], kb[photos.KB_FRAMES // 2])  # it actually zooms
    assert np.abs(kb[0].astype(int) - kb[-1].astype(int)).mean() < 12  # and loops back seamlessly
    s2, kb2 = photos.prepare(jpeg(400, 260), "fit", "natural")
    assert s2.shape == (32, 32, 3) and kb2 == []  # letterbox has no Ken Burns


async def test_photos_provider_queue() -> None:
    n = {"img": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/list":
            return httpx.Response(200, json=fx("picsum_list.json"))
        if req.url.host == "dog.ceo":
            return httpx.Response(
                200, json={"message": "https://images.dog.ceo/breeds/husky/a.jpg", "status": "success"}
            )
        n["img"] += 1
        return img_response(jpeg(), "image/jpeg")

    p = photos.PhotosProvider(FakeHub(handler))  # type: ignore[arg-type]
    p.want(["picsum", "dogs"], breed="husky")
    for _ in range(4):
        p.value = await p.fetch()
    assert [ph.source for ph in p.value] == ["picsum", "dogs", "picsum", "dogs"]
    assert p.value[1].title == "HUSKY" and p.value[0].artist
    assert p.unseen() == 4 and p.next_interval() == p.interval
    for ph in p.value:
        p.seen(ph.seq)
    assert p.next_interval() == 2.0  # prefetch more
    for _ in range(photos.QUEUE):
        p.value = await p.fetch()
    assert len(p.value) == photos.QUEUE  # ring stays bounded
    p.want(["dogs"])
    assert all(ph.source == "dogs" for ph in p.value)


async def test_photos_provider_errors_back_off() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Just a moment...")

    p = photos.PhotosProvider(FakeHub(handler))  # type: ignore[arg-type]
    p.want(["met", "cats"])
    with pytest.raises(RuntimeError):
        await p.fetch()
    assert set(p._skip_until) == {"met", "cats"}


def _photo(seq: int, kb: bool = True) -> photos.Photo:
    rng = np.random.default_rng(seq)
    still = rng.integers(0, 255, (32, 32, 3), dtype=np.uint8)
    frames = [np.roll(still, i, axis=1) for i in range(photos.KB_FRAMES)] if kb else []
    return photos.Photo(seq, "met", f"TITLE {seq} WITH A LONG NAME", "ARTIST", still, frames, f"k{seq}")


def test_photoframe_rotation_crossfade_and_clip() -> None:
    p = photos.PhotosProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
    p.value = [_photo(1), _photo(2), _photo(3)]
    app = photo_app.PhotoFrame(Ctx(photos=p), photo_app.PhotoFrameSettings(interval=10))
    clock = [100.0]
    app._clock = lambda: clock[0]
    f = Frame()
    app.render(f, 0)
    assert app._cur.seq == 1 and app.kind() == "stream"  # caption intro streams
    clock[0] += 9.0
    assert app.kind() == "clip"  # then the Ken-Burns loop plays natively
    clip = app.clip_frames()
    assert len(clip.frames) == photos.KB_FRAMES
    assert len(encode_gif_budget(clip.frames, clip.durations_ms)) <= GIF_BUDGET
    clock[0] += 1.2
    app.render(f, 0)
    assert app._cur.seq == 2 and app._prev.seq == 1
    assert app.fps == 12.0  # crossfade + caption animate
    app.settings.motion = "still"
    app.settings.caption = "off"
    clock[0] += 30
    app.render(f, 0)
    assert app._cur.seq == 3 and app.kind() == "stream"
    clock[0] += 5
    assert app.fps == 2.0
    f = Frame()
    app.render(f, 0)
    assert np.array_equal(f.px, p.value[2].still)  # still mode, no caption: exactly the prepared photo
    st = app.status()
    assert st["photos"] == 3 and st["source"] == "met"


# =============================================================================== Pokédex
def test_pokemon_parse_and_sprites() -> None:
    e = pokedex.parse_pokemon(fx("pokeapi_pikachu.json"))
    assert e["id"] == 25 and e["name"] == "PIKACHU" and e["types"] == ["electric"]
    assert e["stats"] == [35, 55, 40, 50, 50, 90]
    assert e["sprite_url"].endswith("/25.png") and e["shiny_url"]
    assert pokedex.display_name("mr-mime") == "MR MIME" and pokedex.display_name("ho-oh") == "HO-OH"
    assert pokedex.normalize_key("#025") == "25" and pokedex.normalize_key("Mr. Mime") == "mr-mime"
    assert (
        pokedex.parse_genus({"genera": [{"genus": "Mouse Pokémon", "language": {"name": "en"}}]}) == "MOUSE"
    )
    sp = pokedex.prepare_sprite(raw("pikachu.png"))
    src = np.asarray(pokedex.crop_opaque(Image.open(io.BytesIO(raw("pikachu.png")))))
    palette = {tuple(c) for c in src[src[..., 3] > 128][:, :3]}
    for key, (bw, bh) in pokedex.SIZES.items():
        s = sp[key]
        assert s.w <= bw and s.h <= bh and max(s.w / bw, s.h / bh) > 0.9  # fills its box
        used = {tuple(c) for c in s.px[s.mask]}
        assert used <= palette  # crisp: only the sprite's own colours, no blended in-betweens


async def test_pokedex_provider_cache_and_404() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.host != "pokeapi.co":
            return img_response(raw("pikachu.png"))
        if req.url.path.endswith("/pokemon/missingno"):
            return httpx.Response(404)
        if "/pokemon-species/" in req.url.path:
            return httpx.Response(
                200, json={"genera": [{"genus": "Mouse Pokémon", "language": {"name": "en"}}]}
            )
        return httpx.Response(200, json=fx("pokeapi_pikachu.json"))

    p = pokedex.PokedexProvider(FakeHub(handler))  # type: ignore[arg-type]
    p.want("pikachu")
    p.value = await p.fetch()
    e = p.get("pikachu")
    assert e is not None and e["genus"] == "MOUSE" and p.get(25) is e and p.get("#25") is e
    n = len(calls)
    p.want(25)
    p.value = await p.fetch()
    assert len(calls) == n  # cached
    p.want("missingno")
    p.value = await p.fetch()
    assert p.failed("missingno") and p.next_interval() == p.interval


def _dex_provider() -> pokedex.PokedexProvider:
    p = pokedex.PokedexProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
    e = pokedex.parse_pokemon(fx("pokeapi_pikachu.json"))
    e["genus"] = "MOUSE"
    e["sprites"] = e["shiny"] = pokedex.prepare_sprite(raw("pikachu.png"))
    p._cache[25] = e
    p._names["pikachu"] = 25
    p.value = dict(p._cache)
    return p


def test_pokedex_modes_and_clip() -> None:
    p = _dex_provider()
    app = dex_app.Pokedex(Ctx(pokedex=p), dex_app.PokedexSettings(mode="specific", pokemon="Pikachu"))
    assert app.kind() == "clip" and app.status()["name"] == "PIKACHU"
    clip = app.clip_frames()
    assert abs(sum(clip.durations_ms) - app.loop_seconds() * 1000) < 50
    assert len(encode_gif_budget(clip.frames, clip.durations_ms, 64)) <= GIF_BUDGET
    # daily is stable for a date and inside the generation
    d1 = dex_app.pick_id("2026-09-24", "1")
    assert d1 == dex_app.pick_id("2026-09-24", "1") and 1 <= d1 <= 151
    daily = dex_app.Pokedex(Ctx(pokedex=p), dex_app.PokedexSettings(mode="daily", generation="3"))
    assert 252 <= int(daily.key()) <= 386
    rnd = dex_app.Pokedex(Ctx(pokedex=p), dex_app.PokedexSettings(mode="random", every=60))
    rnd._clock = lambda: 6000.0
    assert rnd.key() == rnd.key() == str(dex_app.pick_id("100:0", "all"))  # period 6000 // 60
    rnd.on_start()
    assert rnd.key(1) in p._wanted  # the next one is prefetched


async def test_pokedex_actions_and_who() -> None:
    p = _dex_provider()
    app = dex_app.Pokedex(Ctx(pokedex=p), dex_app.PokedexSettings(mode="specific", pokemon="25", view="who"))
    f = Frame()
    app.render(f, 1.0)  # silhouette: the sprite area is black on the blue burst
    assert f.get(16, 20) == (0, 0, 0)
    app.render(f, app.settings.guess_seconds + 1.0)  # revealed
    assert f.get(16, 20) != (0, 0, 0)
    await app.action("shiny", {})
    assert app.is_shiny(p.get(25))  # type: ignore[arg-type]
    await app.action("next", {})
    assert app.key() != "25"


# =============================================================================== Pixel Avatar
def test_avatar_parsing_and_decoders() -> None:
    assert avatars.parse_names("Notch, gh:torvalds, db:ada, x:bad, gh:bad name!") == [
        ("minecraft", "Notch"),
        ("github", "torvalds"),
        ("dicebear", "ada"),
    ]
    assert avatars.parse_names("ada", "dicebear") == [("dicebear", "ada")]
    mc = avatars.decode_minecraft(raw("mc_notch.png"))
    assert mc.px.shape == (8, 8, 3) and mc.mask.all()
    ic = avatars.decode_identicon(raw("identicon_torvalds.png"))
    assert ic.px.shape == (5, 5, 3)
    assert [row.tolist() for row in ic.mask] == [
        [True, False, False, False, True],
        [False, True, False, True, False],
        [False, True, True, True, False],
        [False, False, False, False, False],
        [False, True, True, True, False],
    ]
    assert (ic.mask == ic.mask[:, ::-1]).all()  # identicons are mirror-symmetric
    assert max(ic.px[ic.mask][0]) == 255  # colour normalised to full LED value
    db = avatars.decode_dicebear(raw("dicebear_ada.png"))
    assert db.px.shape == (16, 16, 3) and 0 < db.mask.sum() < 256


def test_avatar_blink_closes_eyes() -> None:
    mc = avatars.decode_minecraft(raw("mc_notch.png"))
    mc.name = "Notch"
    b = avatar_app.blinked(mc)
    assert not np.array_equal(b.px, mc.px)
    assert np.array_equal(b.px[6:], mc.px[6:])  # the mouth is untouched
    flat = avatars.Avatar("minecraft", "x", np.full((8, 8, 3), 200, np.uint8), np.ones((8, 8), bool))
    assert avatar_app.blinked(flat) is flat  # no eyes found: unchanged


def test_avatar_exact_grid() -> None:
    p = avatars.AvatarsProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
    mc = avatars.decode_minecraft(raw("mc_notch.png"))
    mc.name = "Notch"
    ic = avatars.decode_identicon(raw("identicon_torvalds.png"))
    ic.name = "torvalds"
    p.value = {("minecraft", "Notch"): mc, ("github", "torvalds"): ic}
    app = avatar_app.PixelAvatar(
        Ctx(avatars=p),
        avatar_app.AvatarSettings(
            names="Notch, gh:torvalds", layout="full", tag="off", animation="none", background="black"
        ),
    )
    f = Frame()
    app.render(f, 0.5)
    for y in range(32):
        for x in range(32):
            assert f.get(x, y) == tuple(int(v) for v in mc.px[y // 4, x // 4])  # ×4, pixel-exact
    f = Frame()
    app.render(f, app.settings.seconds + 0.5)
    assert f.get(0, 0) == (0, 0, 0) and f.get(1, 1) == tuple(
        int(v) for v in ic.px[0, 0]
    )  # 6 px cells + margin
    clip = app.clip_frames()
    assert len(clip.frames) >= 2 and len(encode_gif_budget(clip.frames, clip.durations_ms, 64)) <= GIF_BUDGET


async def test_avatars_provider() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "mc-heads.net":
            return img_response(raw("mc_notch.png"))
        if req.url.host == "github.com":
            return img_response(raw("identicon_torvalds.png"))
        return img_response(raw("dicebear_ada.png"))

    p = avatars.AvatarsProvider(FakeHub(handler))  # type: ignore[arg-type]
    p.want(avatars.parse_names("Notch, gh:torvalds, db:ada"))
    p.value = await p.fetch()
    assert set(p.value) == {("minecraft", "Notch"), ("github", "torvalds"), ("dicebear", "ada")}
    assert p.next_interval() == p.interval


# =============================================================================== Chess
def test_pgn_and_daily_replay() -> None:
    d = fx("chess_daily.json")
    assert chess.pgn_moves(d["pgn"]) == ["Qe1+", "Rxe1", "Rxe1+", "Nf1", "h2+", "Kg2", "h1=Q#"]
    pz = chess.parse_puzzle(d)
    assert pz.side == "b" and len(pz.moves) == 7 and len(pz.boards) == 8
    last = pz.moves[-1]
    assert last.promo == "Q" and last.mate and chess.sq_name(last.to) == "h1"
    assert pz.boards[-1][0][7] == "q"  # promoted black queen on h1
    assert chess.sq_name(pz.moves[1].frm) == "d1" and pz.moves[1].capture
    r = chess.parse_puzzle(fx("chess_random.json"), "random")
    assert r.moves and r.kind == "random"


def test_san_resolver_edge_cases() -> None:
    b, side, _c, ep = chess.parse_fen("r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1")
    m = chess.resolve_san(b, side, "exd6", ep)  # en passant
    assert m.ep == chess.sq("d5") and m.capture
    nb = chess.apply(b, m)
    assert nb[4][3] == "." and nb[5][3] == "P"
    ooo = chess.resolve_san(b, "w", "O-O-O")
    nb = chess.apply(b, ooo)
    assert nb[0][2] == "K" and nb[0][3] == "R" and nb[0][0] == "."
    oo = chess.resolve_san(b, "b", "O-O")
    nb = chess.apply(b, oo)
    assert nb[7][6] == "k" and nb[7][5] == "r"
    # disambiguation by file / rank
    b, *_ = chess.parse_fen("4k3/8/8/8/8/8/8/R6R w - - 0 1")
    assert chess.sq_name(chess.resolve_san(b, "w", "Rhd1").frm) == "h1"
    assert chess.sq_name(chess.resolve_san(b, "w", "Rad1").frm) == "a1"
    with pytest.raises(ValueError):
        chess.resolve_san(b, "w", "Rd1")  # ambiguous
    b, *_ = chess.parse_fen("4k3/8/8/8/8/8/8/R3K2R w - - 0 1")
    assert chess.sq_name(chess.resolve_san(b, "w", "Rf1").frm) == "h1"  # the a-rook is blocked by the king
    # a pinned knight can't be the one that moves
    b, *_ = chess.parse_fen("4k3/4r3/8/8/8/2N3N1/8/4K3 w - - 0 1")
    b[2][4] = "N"  # knight on e3, pinned by the rook on e7
    b[2][2] = b[2][6] = "."
    b[2][6] = "N"  # knight on g3
    assert chess.sq_name(chess.resolve_san(b, "w", "Nf5").frm) == "g3"
    # double pawn push and promotion capture
    b, *_ = chess.parse_fen("1r2k3/P7/8/8/8/8/4P3/4K3 w - - 0 1")
    assert chess.sq_name(chess.resolve_san(b, "w", "e4").frm) == "e2"
    pm = chess.resolve_san(b, "w", "axb8=N+")
    assert pm.promo == "N" and pm.check and chess.apply(b, pm)[7][1] == "N"
    with pytest.raises(ValueError):
        chess.parse_fen("8/8/8 w - - 0 1")


async def test_chess_provider() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=fx("chess_random.json" if req.url.path.endswith("random") else "chess_daily.json")
        )

    p = chess.ChessProvider(FakeHub(handler))  # type: ignore[arg-type]
    p.want("daily")
    p.want("random")
    p.value = await p.fetch()
    assert p.value["daily"].kind == "daily" and p.value["random"].kind == "random"


def _chess_app(**kw: Any) -> chess_app.ChessPuzzle:
    p = chess.ChessProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
    p.value = {"daily": chess.parse_puzzle(fx("chess_daily.json"))}
    return chess_app.ChessPuzzle(Ctx(chess=p), chess_app.ChessSettings(**kw))


async def test_chess_timeline_clip_and_input() -> None:
    app = _chess_app()
    pz = app.puzzle()
    assert pz is not None and app.flipped(pz)  # black to move → black at the bottom
    assert app.xy(pz, 0, 0) == (28, 0)
    clip = app.clip_frames()
    assert abs(sum(clip.durations_ms) - app.loop_seconds(pz) * 1000) < 50
    assert len(clip.frames) <= 180
    assert len(encode_gif_budget(clip.frames, clip.durations_ms, app.clip_colors)) <= GIF_BUDGET
    f = Frame()
    app.render(f, app.loop_seconds(pz) - 0.1)  # final position: the promoted queen on h1
    x, y = app.xy(pz, 7, 0)
    assert f.get(x + 1, y + 1) != chess_app.THEMES["night"][0]
    await app.action("input", {"key": "ArrowRight"})
    assert app.kind() == "stream" and app.status()["manual_ply"] == 1
    await app.action("input", {"key": "b"})
    assert app.status()["manual_ply"] == 7
    await app.action("restart", {})
    assert app.kind() == "clip"
    await app.action("solve", {})
    assert app.loop_seconds(pz) < _chess_app().loop_seconds(pz)
    assert "h1=Q#" in app.status()["solution"]


# =============================================================================== Game Deals
def test_deal_parsers() -> None:
    gv = gamedeals.parse_giveaways(fx("gamerpower.json"))
    assert gv and all(g["kind"] == "free" and g["now"] == 0 for g in gv)
    assert gv[0]["title"] == "Dire Echo" and gv[0]["tag"] == "ITCH" and gv[0]["was"] == 5.99
    assert gv[0]["ends"] == gamedeals.parse_end("2026-09-30 23:59:00")
    assert gamedeals.parse_giveaways({"status": 0, "status_message": "none"}) == []
    assert gamedeals.clean_giveaway_title("Dwarven Realms (Steam) Key Giveaway") == (
        "Dwarven Realms",
        "Steam",
    )
    stores = {s["storeID"]: s["storeName"] for s in fx("cheapshark_stores.json")}
    ds = gamedeals.parse_deals(fx("cheapshark_deals.json"), stores)
    assert ds[0]["tag"] == "STEAM" and ds[0]["savings"] == 45 and ds[0]["now"] == 24.73
    assert len({d["title"] for d in ds}) == len(ds)  # one row per game
    assert gamedeals.store_style("Epic Games Store")[0] == "EPIC"
    assert gamedeals.store_style("Nowhere Shop")[1] == (140, 140, 160)
    assert deals_app.fmt_left(3 * 86400 + 7200 + 5) == "3D 2H"
    assert deals_app.fmt_left(3700) == "1H 1M" and deals_app.fmt_left(-1) == "ENDED"
    assert deals_app.fmt_price(24.73) == "25" and deals_app.fmt_price(4.99) == "4.99"


async def test_gamedeals_provider_params() -> None:
    seen: list[httpx.URL] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url)
        if "gamerpower" in req.url.host:
            return httpx.Response(200, json=fx("gamerpower.json"))
        if req.url.path.endswith("/stores"):
            return httpx.Response(200, json=fx("cheapshark_stores.json"))
        return httpx.Response(200, json=fx("cheapshark_deals.json"))

    p = gamedeals.GameDealsProvider(FakeHub(handler))  # type: ignore[arg-type]
    p.want("both", "steam", "7", 15.0, "value")
    v = await p.fetch()
    assert v["giveaways"] and v["deals"]
    gp = next(u for u in seen if "gamerpower" in u.host)
    cs = next(u for u in seen if u.path.endswith("/deals"))
    assert gp.params["platform"] == "steam" and gp.params["sort-by"] == "value"
    assert cs.params["storeID"] == "7" and cs.params["upperPrice"] == "15"


def _deals_app(**kw: Any) -> tuple[deals_app.GameDeals, gamedeals.GameDealsProvider, Ctx]:
    p = gamedeals.GameDealsProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
    stores = {s["storeID"]: s["storeName"] for s in fx("cheapshark_stores.json")}
    p.value = {
        "giveaways": gamedeals.parse_giveaways(fx("gamerpower.json")),
        "deals": gamedeals.parse_deals(fx("cheapshark_deals.json"), stores),
        "updated": NOW,
    }
    ctx = Ctx(gamedeals=p)
    app = deals_app.GameDeals(ctx, deals_app.GameDealsSettings(**kw))
    app._clock = lambda: NOW
    return app, p, ctx


def test_gamedeals_rotation_filters_and_clip() -> None:
    app, _p, _ctx = _deals_app(min_savings=40)
    items = app.items()
    assert [i["kind"] for i in items[:2]] == ["free", "deal"]  # interleaved
    assert all(i["kind"] == "free" or i["savings"] >= 40 for i in items)
    only, _p2, _c = _deals_app(source="deals", min_savings=0, max_price=24.0)
    assert all(i["now"] <= 24.0 for i in only.items())
    later, _p3, _c3 = _deals_app(source="giveaways")
    later._clock = lambda: NOW + 30 * 86400  # everything has ended by then (except open-ended ones)
    assert all(not i["ends"] for i in later.items())
    assert app.kind() == "clip"
    clip = app.clip_frames()
    assert len(encode_gif_budget(clip.frames, clip.durations_ms, app.clip_colors)) <= GIF_BUDGET
    k1 = app.clip_key()
    app._clock = lambda: NOW + app.settings.rotate
    assert app.clip_key() != k1  # the next game re-bakes


def test_gamedeals_notifies_new_free_game_once() -> None:
    app, p, ctx = _deals_app()
    app.items()
    assert ctx.notices == [] and ctx.data["armed"]  # first fetch only arms
    app.items()
    assert ctx.notices == []
    fresh = dict(p.value["giveaways"][0], id="gp:999", title="Brand New")
    p.value = dict(p.value, giveaways=[fresh, *p.value["giveaways"]], updated=NOW + 60)
    app.items()
    assert len(ctx.notices) == 1 and "BRAND NEW" in ctx.notices[0]["message"].upper()
    p.value = dict(p.value, updated=NOW + 120)
    app.items()
    assert len(ctx.notices) == 1  # not twice


# =============================================================================== every app, every option
def _variants(cls: type) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{}]
    for name, field in cls.Settings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            out += [{name: v} for v in extra["enum"]]
    return out


def _loaded(app_id: str) -> dict[str, Any]:
    if app_id == "photoframe":
        p = photos.PhotosProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
        p.value = [_photo(1), _photo(2, kb=False)]
        return {"photos": p}
    if app_id == "pokedex":
        return {"pokedex": _dex_provider()}
    if app_id == "avatar":
        p = avatars.AvatarsProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
        mc = avatars.decode_minecraft(raw("mc_notch.png"))
        ic = avatars.decode_identicon(raw("identicon_torvalds.png"))
        db = avatars.decode_dicebear(raw("dicebear_ada.png"))
        p.value = {("minecraft", "Notch"): mc, ("github", "torvalds"): ic, ("dicebear", "dotdeck"): db}
        return {"avatars": p}
    if app_id == "chess":
        p = chess.ChessProvider(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
        pz = chess.parse_puzzle(fx("chess_daily.json"))
        p.value = {"daily": pz, "random": pz}
        return {"chess": p}
    _app, p, _ctx = _deals_app()
    return {"gamedeals": p}


CASES = [(aid, v, loaded) for aid, cls in APPS.items() for v in _variants(cls) for loaded in (False, True)]


@pytest.mark.parametrize(
    ("app_id", "settings", "loaded"),
    CASES,
    ids=[f"{a}-{list(s.values())}-{'data' if d else 'empty'}" for a, s, d in CASES],
)
def test_every_variant_renders_fast(app_id: str, settings: dict[str, Any], loaded: bool) -> None:
    cls = APPS[app_id]
    if app_id == "pokedex" and loaded:
        settings = {"mode": "specific", "pokemon": "pikachu", **settings}
    if app_id == "avatar" and loaded:
        settings = {"names": "Notch, gh:torvalds, db:dotdeck", **settings}
    if loaded:
        providers = _loaded(app_id)
    else:
        name = cls.uses[0]
        prov = next(pc for pc in PROVIDERS if pc.name == name)
        providers = {name: prov(FakeHub(lambda r: httpx.Response(500)))}  # type: ignore[arg-type]
    app = cls(Ctx(**providers), cls.Settings(**settings))
    worst = 0.0
    for t in (0.0, 0.37, 1.9, 7.3, 13.1, 31.0):
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, t)
        worst = max(worst, time.perf_counter() - t0)
        assert f.px.shape == (32, 32, 3)
        if loaded:
            assert f.px.any()
    assert worst < 0.05, f"{app_id} render took {worst * 1000:.1f} ms"
    assert app.kind() in ("stream", "clip")
    json.dumps(app.status())


def test_offline_states() -> None:
    for app_id, cls in APPS.items():
        name = cls.uses[0]
        prov = next(pc for pc in PROVIDERS if pc.name == name)(FakeHub(lambda r: httpx.Response(500)))  # type: ignore[arg-type]
        prov.error = "ConnectError: offline"
        f = Frame()
        cls(Ctx(**{name: prov}), cls.Settings()).render(f, 0.5)
        assert f.get(16, 9) != (0, 0, 0) or f.px[9:15].any(), app_id  # amber label drawn
        assert tuple(f.px[9:15].max(axis=(0, 1))) == (255, 170, 0), app_id


def test_apps_survive_missing_provider() -> None:
    """In a bare engine (providers not registered yet) apps show their loading screen instead of crashing."""

    class Bare(Ctx):
        def provider(self, name: str) -> Any:
            raise KeyError(name)

    for cls in APPS.values():
        app = cls(Bare(), cls.Settings())
        app.on_start()
        f = Frame()
        app.render(f, 0.3)
        assert f.px.any() and app.kind() == "stream"


async def test_engine_integration(engine) -> None:  # type: ignore[no-untyped-def]
    """Registered in a real (sim) engine with the providers added to the hub, every app builds and renders."""
    for pc in PROVIDERS:
        engine.hub.providers[pc.name] = pc(engine.hub)
    for app_id in APPS:
        slot = engine._slot(app_id)
        f = Frame()
        slot.app.render(f, 0.5)
        assert slot.app.kind() in ("stream", "clip")
