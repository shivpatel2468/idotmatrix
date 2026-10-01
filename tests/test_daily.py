"""Daily & Money apps: Daily Dose, Trivia, Headlines, Currency.

Provider parsing runs on trimmed real captures in tests/fixtures/daily/ (recorded 2026-09-24); fetch logic runs
against a fake HTTP client; the apps render every layout with and without data on an injected clock.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from deskdot.apps.currency import Currency, CurrencySettings, compact, group_digits, short_num, unit_for
from deskdot.apps.daily import Daily, DailySettings, flow_pages, wrap_text
from deskdot.apps.headlines import Headlines, HeadlinesSettings, age_text
from deskdot.apps.trivia import Trivia, TriviaSettings
from deskdot.gfx import Frame, measure
from deskdot.providers import currency as fx
from deskdot.providers import daily as dd
from deskdot.providers import headlines as hl
from deskdot.providers import trivia as tv

FIX = Path(__file__).parent / "fixtures" / "daily"


def fx_json(name: str) -> Any:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- fakes
class Resp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._p, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._p

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Http:
    """Routes a URL (+ params) to a payload via `route(url, params) -> Resp | payload`."""

    def __init__(self, route: Callable[[str, dict[str, Any]], Any]) -> None:
        self.route = route
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, params: Any = None, headers: Any = None, **_: Any) -> Resp:
        p = dict(params or {})
        self.calls.append((url, p))
        r = self.route(url, p)
        return r if isinstance(r, Resp) else Resp(r)


class Hub:
    def __init__(self, route: Callable[[str, dict[str, Any]], Any]) -> None:
        self.http = Http(route)
        self.providers: dict[str, Any] = {}

    def on_change(self, _n: str) -> None: ...


class Ctx:
    def __init__(self, providers: dict[str, Any]) -> None:
        self._p = providers
        self.data: dict[str, Any] = {}
        self.saved = 0

    def provider(self, name: str) -> Any:
        return self._p[name]

    def save(self) -> None:
        self.saved += 1

    def invalidate(self) -> None: ...
    def notify(self, **_: Any) -> None: ...


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def lit(f: Frame) -> int:
    return int((f.px.sum(axis=2) > 0).sum())


# ============================================================================= Daily Dose: provider
def test_clean_text_keeps_only_drawable_glyphs() -> None:
    s = dd.clean_text("Café “naïve” — 50% {x} &amp; <b>bold</b>\\ ok…")
    assert s == 'CAFE "NAIVE" - 50% (X) & BOLD OK...'
    assert set(s) <= dd.TINY_CHARS
    assert dd.clean_text("  a \n\n b  ,  c ") == "A B, C"
    assert dd.is_safe("CATS HAVE 32 EAR MUSCLES") and not dd.is_safe("the best sex is fun")


def test_daily_parsers_on_real_captures() -> None:
    q = dd.parse_zen(fx_json("zenquotes_quotes"))
    assert len(q) == 5 and all(i["author"] and i["id"].startswith("quote:") for i in q)
    assert dd.parse_zen([{"q": "Too many requests. Obtain an auth key", "a": "zenquotes.io"}]) == []
    assert dd.parse_zen(fx_json("zenquotes_today"), "qotd")[0]["author"] == "BHAGAVAD GITA"
    dad, pages = dd.parse_dad(fx_json("icanhazdadjoke_search"))
    assert len(dad) >= 5 and pages == 25
    assert dd.split_dad("WHY DO BEES HUM? BECAUSE THEY DON'T KNOW THE WORDS.") == (
        "WHY DO BEES HUM?",
        "BECAUSE THEY DON'T KNOW THE WORDS.",
    )
    assert dd.split_dad("I USED TO HATE FACIAL HAIR, BUT THEN IT GREW ON ME.")[1] is None
    assert dd.parse_useless(fx_json("uselessfacts_random"))[0]["text"].startswith("TABLE TENNIS")
    assert dd.parse_advice(fx_json("adviceslip"))[0]["id"] == "advice:130"
    cats, last = dd.parse_cat(fx_json("catfact_facts"))
    assert len(cats) == 5 and last == 11
    jokes = dd.parse_jokeapi(fx_json("jokeapi"))
    two = [j for j in jokes if "punchline" in j]
    assert two and all(j["tag"] in ("CODE", "PUN") for j in jokes)
    flagged = {"jokes": [{"type": "single", "joke": "x y z", "flags": {"nsfw": True}, "safe": False}]}
    assert dd.parse_jokeapi(flagged) == []
    assert dd.parse_chuck(fx_json("chucknorris"))[0]["source"] == "chuck"
    assert dd.parse_chuck(fx_json("chucknorris") | {"categories": []}) == []  # uncategorised: never
    assert dd.parse_chuck(fx_json("chucknorris") | {"categories": ["explicit"]}) == []
    k = dd.parse_kanye(fx_json("kanye_quotes"))
    assert len(k) == 10 and k[0]["author"] == "KANYE WEST"
    hist = dd.parse_onthisday(fx_json("wikipedia_onthisday"), keep=8)
    years = [h["year"] for h in hist]
    assert len(hist) == 8 and years == sorted(years, reverse=True)
    assert all(len(h["text"]) <= 110 and h["tag"] == str(h["year"]) for h in hist)
    assert not any(dd._GRIM.search(h["text"]) for h in hist)  # enough cheerful events that day
    for it in q + dad + jokes + k + hist:
        json.dumps(it)
        assert set(it["text"]) <= dd.TINY_CHARS


def _daily_route(url: str, params: dict[str, Any]) -> Any:
    table = {
        "zenquotes.io/api/quotes": "zenquotes_quotes",
        "zenquotes.io/api/today": "zenquotes_today",
        "icanhazdadjoke": "icanhazdadjoke_search",
        "facts/random": "uselessfacts_random",
        "facts/today": "uselessfacts_random",
        "adviceslip": "adviceslip",
        "catfact": "catfact_facts",
        "jokeapi": "jokeapi",
        "chucknorris": "chucknorris",
        "kanye": "kanye_quotes",
        "onthisday": "wikipedia_onthisday",
    }
    for k, name in table.items():
        if k in url:
            return fx_json(name)
    return Resp({}, 404)


async def test_daily_provider_queues_rate_limits_and_takes() -> None:
    hub = Hub(_daily_route)
    p = dd.DailyProvider(hub)
    p.want(list(dd.SOURCES))
    v = await p.fetch()
    assert set(v) == set(dd.SOURCES) and all(v[s] for s in ("quote", "dad", "joke", "history", "kanye"))
    n_calls = len(hub.http.calls)
    zen = [c for c in hub.http.calls if "zenquotes.io/api/quotes" in c[0]]
    assert len(zen) == 1  # one batch fills the whole queue
    await p.fetch()  # nothing is due yet (queues full / gaps not elapsed)
    assert len(hub.http.calls) == n_calls
    # consumable sources pop; sticky and cyclic ones repeat / rotate
    a, b = p.take("quote"), p.take("quote")
    assert a and b and a["id"] != b["id"]
    assert p.take("qotd") == p.take("qotd")
    h1, h2 = p.take("history"), p.take("history")
    assert h1 and h2 and h1["id"] != h2["id"]
    # advice requests carry a cache-buster
    assert all("?t=" in u for u, _ in hub.http.calls if "adviceslip" in u)
    # chuck: only whitelisted categories are requested
    assert all(c[1]["category"] in dd.CHUCK_SAFE for c in hub.http.calls if "chucknorris" in c[0])


async def test_daily_provider_failures_back_off() -> None:
    hub = Hub(lambda u, p: Resp({}, 503))
    p = dd.DailyProvider(hub)
    p.want(["quote", "dad"])
    with pytest.raises(RuntimeError):
        await p.fetch()
    assert set(p.errors) == {"quote", "dad"} and p._next_ok["quote"] > time.time()
    assert p.take("quote") is None


# ============================================================================= Daily Dose: layout + app
def test_wrap_preserves_whole_words_and_pages_balance() -> None:
    lines = wrap_text("I NEEDED A PASSWORD EIGHT CHARACTERS LONG", 30, "tiny")

    def line_w(ln: str) -> int:
        return measure(ln, "tiny", spacing=0) if measure(ln, "tiny") > 30 else measure(ln, "tiny")

    assert all(line_w(ln) <= 30 for ln in lines)
    assert "PASSWORD" in lines and "CHARACTERS" in lines  # whole words preserved, no synthetic hyphens
    assert wrap_text("OSIRIS-REX", 30)[0] == "OSIRIS-"  # existing hyphens are the break
    text = "NASA'S OSIRIS-REX CAPSULE CONTAINING SAMPLES FROM THE ASTEROID 101955 BENNU LANDS BACK ON EARTH."
    pages = flow_pages([(text, "text")], 30, 4)
    sizes = [len(p.lines) for p in pages]
    assert max(sizes) - min(sizes) <= 1  # no orphaned last page
    auth = flow_pages([("YOU ARE NOT STUCK", "text"), ("- WAYNE DYER", "author")], 30, 4)
    assert auth[-1].lines[-1][1] == "author"


def test_daily_lyrics_mode() -> None:
    p = _daily_provider(
        quote=[{"id": "q:1", "source": "quote", "text": "A NOBLE IS A WILLING HEART", "author": "ANON"}]
    )
    app, _clk = _daily(p, quote=True, style="lyrics")
    app.render(Frame(), 0)
    assert app.kind() == "clip"
    clip = app.clip_frames()
    assert len(clip.frames) > 5


def _daily_provider(**queues: list[dict[str, Any]]) -> dd.DailyProvider:
    p = dd.DailyProvider(Hub(_daily_route))
    p._q = {k: list(v) for k, v in queues.items()}
    p.value = dict(p._q)
    return p


JOKE = {
    "id": "joke:1",
    "source": "joke",
    "text": "WHY DO JAVA DEVS WEAR GLASSES?",
    "punchline": "POKER FACE.",
}
QUOTE = {
    "id": "quote:1",
    "source": "quote",
    "text": "IT IS IN CHANGING THAT WE FIND PURPOSE.",
    "author": "HERACLITUS",
}
LONG = {"id": "fact:1", "source": "fact", "text": " ".join(["ELEPHANTS CANNOT JUMP"] * 5)}


def _daily(p: Any, **kw: Any) -> tuple[Daily, Clock]:
    base = {s: False for s in dd.SOURCES}
    base.update(kw)
    app = Daily(Ctx({"daily": p}), DailySettings(**base))
    clk = Clock()
    app._clock = clk  # type: ignore[method-assign]
    return app, clk


def test_daily_joke_setup_pause_punchline() -> None:
    p = _daily_provider(joke=[JOKE, dict(JOKE, id="joke:2")])
    app, clk = _daily(p, joke=True)
    f = Frame()
    app.render(f, 0)
    kinds = [pg.kind for pg in app._pages]
    assert "pause" in kinds and app._pages[-1].lines[0][1] == "punch"
    assert app._pages[-1].font == "small"  # a short punchline gets the big(ger) type
    assert sum(pg.dur for pg in app._pages) >= app.settings.rotate
    frames = []
    for pg in app._pages:
        clk.t += pg.dur
        frames.append(Frame())
    assert lit(f) > 20
    clk.t += 1
    app.render(Frame(), 0)
    assert app._item and app._item["id"] == "joke:2"  # advanced to the next item


def test_daily_quote_author_and_rotation_across_sources() -> None:
    p = _daily_provider(quote=[QUOTE] * 3, fact=[LONG] * 3)
    app, clk = _daily(p, quote=True, fact=True)
    seen = []
    for _ in range(4):
        app.render(Frame(), 0)
        seen.append(app._item["source"])  # type: ignore[index]
        clk.t += app._dur + 0.01
    assert seen == ["quote", "fact", "quote", "fact"]
    app2, _ = _daily(_daily_provider(quote=[QUOTE]), quote=True)
    app2.render(Frame(), 0)
    roles = [r for pg in app2._pages for _t, r in pg.lines]
    assert roles[-1] == "author"


async def test_daily_marquee_is_a_bounded_clip_and_next_skips() -> None:
    p = _daily_provider(fact=[LONG, dict(LONG, id="fact:2")])
    app, _clk = _daily(p, fact=True, style="marquee")
    app.render(Frame(), 0)
    assert app.kind() == "clip"
    key = app.clip_key()
    clip = app.clip_frames()
    assert 1 < len(clip.frames) <= Daily.MAX_CLIP_FRAMES and len(clip.durations_ms) == len(clip.frames)
    await app.action("next", {})
    assert app.clip_key() != key and app._item["id"] == "fact:2"  # type: ignore[index]


def test_daily_states() -> None:
    p = dd.DailyProvider(Hub(_daily_route))
    app, _ = _daily(p, quote=True)
    f = Frame()
    app.render(f, 0.3)
    assert lit(f) > 0 and app.kind() == "stream"  # loading
    p.error = "boom"
    f2 = Frame()
    app.render(f2, 0.3)
    assert lit(f2) > 0
    none, _ = _daily(p)
    f3 = Frame()
    none.render(f3, 0)
    assert lit(f3) > 0  # NO SOURCES


# ============================================================================= Trivia
def test_trivia_parse_real_capture() -> None:
    code, qs = tv.parse_batch(fx_json("opentdb"))
    assert code == 0 and len(qs) == 4
    q = qs[0]
    assert q["question"].startswith('"NEPHELOCOCCYGIA" IS THE PRACTICE')
    assert q["options"][q["answer"]] == "FINDING SHAPES IN CLOUDS" and len(q["options"]) == 4
    assert tv.parse_question(fx_json("opentdb")["results"][0])["options"] == q["options"]  # stable shuffle
    assert q["tag"] == "GK" and q["difficulty"] == "hard"
    b = tv.parse_question(
        {
            "type": "boolean",
            "difficulty": "easy",
            "category": "History",
            "question": "The%20sky%20is%20blue.",
            "correct_answer": "True",
            "incorrect_answers": ["False"],
        }
    )
    assert b and b["options"] == ["TRUE", "FALSE"] and b["answer"] == 0 and b["tag"] == "HISTORY"
    for tag in (v[1] for v in tv.CATEGORIES.values()):
        assert measure(tag) <= 28


async def test_trivia_provider_token_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tv, "GAP", 0.0)
    script = [
        {"response_code": 0, "token": "T1"},  # token
        {"response_code": 4, "results": []},  # token exhausted
        {"response_code": 0},  # reset ok
        fx_json("opentdb"),
    ]

    def route(url: str, params: dict[str, Any]) -> Any:
        return script.pop(0)

    hub = Hub(route)
    p = tv.TriviaProvider(hub)
    v = await p.fetch()
    assert len(v) == 4 and p.token == "T1"
    assert hub.http.calls[2][1] == {"command": "reset", "token": "T1"}
    assert hub.http.calls[3][1]["token"] == "T1" and hub.http.calls[3][1]["encode"] == "url3986"
    q = p.take()
    assert q and len(p.queue) == 3
    p.want(17, "hard", "boolean")  # nothing queued matches the new query
    assert p.take() is None


def _trivia(qs: list[dict[str, Any]], **kw: Any) -> tuple[Trivia, Clock, Ctx]:
    p = tv.TriviaProvider(Hub(lambda u, pr: Resp({}, 500)))
    p.queue = list(qs)
    p.query = (0, "any", "any")
    ctx = Ctx({"trivia": p})
    app = Trivia(ctx, TriviaSettings(qtype="any", **kw))
    clk = Clock()
    app._clock = clk  # type: ignore[method-assign]
    app.human_at = -1e9
    return app, clk, ctx


async def test_trivia_auto_play_runs_the_whole_flow() -> None:
    _code, qs = tv.parse_batch(fx_json("opentdb"))
    app, clk, ctx = _trivia(qs, seconds=10, reveal_seconds=3)
    phases = []
    for _ in range(400):
        f = Frame()
        app.render(f, 0)
        assert f.px.shape == (32, 32, 3)
        if not phases or phases[-1] != app.phase:
            phases.append(app.phase)
        clk.t += 0.25
        if len(phases) > 6:
            break
    assert phases[:6] == ["intro", "question", "options", "board", "reveal", "intro"]
    assert ctx.data.get("answered", 0) == 0  # nobody played: nothing scored


async def test_trivia_human_answers_score_and_streak() -> None:
    _code, qs = tv.parse_batch(fx_json("opentdb"))
    app, clk, ctx = _trivia(qs * 2, auto_play=False)
    app.render(Frame(), 0)
    q = app.q
    assert q is not None
    await app.action("input", {"key": "enter"})  # skip to the board
    assert app.phase == "board"
    for _ in range(q["answer"]):
        await app.action("input", {"key": "ArrowDown"})
    await app.action("input", {"key": "a"})
    assert app.phase == "reveal" and app.picked == q["answer"]
    assert ctx.data["score"] == 1 and ctx.data["streak"] == 1 and ctx.saved
    clk.t += 60
    app.render(Frame(), 0)
    assert app.phase == "wait"  # auto-play off: stays on the reveal
    await app.action("input", {"key": "a"})
    assert app.phase == "intro" and app.q is not None and app.q["id"] != q["id"]
    await app.action("reveal", {})
    assert app.phase == "reveal"
    st = await app.action("reset_score", {})
    assert st["score"] == 0


def test_trivia_states() -> None:
    app, _clk, _ctx = _trivia([])
    f = Frame()
    app.render(f, 0.2)
    assert lit(f) > 0
    app._provider().error = "x"
    f2 = Frame()
    app.render(f2, 0.2)
    assert lit(f2) > 0


# ============================================================================= Headlines
def test_headline_parsers() -> None:
    s = hl.parse_hn_item(fx_json("hn_item"))
    assert s and s["score"] == 346 and s["comments"] == 147 and s["site"] == "QUALCOMM.COM"
    assert hl.parse_hn_item({"type": "story", "dead": True, "title": "x"}) is None
    sp = hl.parse_space(fx_json("spaceflight_articles"))
    assert len(sp) == 3 and sp[0]["score"] is None and sp[0]["time"]
    dv = hl.parse_devto(fx_json("devto_top"))
    assert len(dv) == 3 and dv[0]["site"] == "DEV.TO" and dv[0]["score"] is not None
    lb = hl.parse_lobsters(fx_json("lobsters_hottest"))
    assert lb[0]["score"] == 99 and lb[0]["comments"] == 33
    assert age_text(1000.0, 1000.0 + 90) == "1M" and age_text(0, 5) == ""
    assert age_text(1000.0, 1000.0 + 7300) == "2H" and age_text(1.0, 1.0 + 3 * 86400) == "3D"


def _hl_route(url: str, params: dict[str, Any]) -> Any:
    if "topstories" in url:
        return fx_json("hn_topstories")
    if "/item/" in url:
        item = fx_json("hn_item")
        iid = int(url.rsplit("/", 1)[1].split(".")[0])
        return item | {"id": iid, "score": iid % 500, "title": f"Story {iid}"}
    if "spaceflight" in url:
        return fx_json("spaceflight_articles")
    if "dev.to" in url:
        return fx_json("devto_top")
    if "lobste.rs" in url:
        return fx_json("lobsters_hottest")
    return Resp({}, 404)


async def test_headlines_provider_fetches_hn_items_concurrently_and_caches() -> None:
    hub = Hub(_hl_route)
    p = hl.HeadlinesProvider(hub)
    p.want("hn", "top", 5)
    v = await p.fetch()
    stories = v["hn:top"]
    assert [s["rank"] for s in stories] == [1, 2, 3, 4, 5]
    n = len(hub.http.calls)
    await p.fetch()
    assert len(hub.http.calls) == n + 1  # only the id list: items are cached for ITEM_TTL
    p.want("space", "new", 3)
    v = await p.fetch()
    assert "space:top" in v and len(v["space:top"]) == 3


def _headlines(value: dict[str, Any], **kw: Any) -> tuple[Headlines, Clock]:
    p = hl.HeadlinesProvider(Hub(_hl_route))
    p.value = value
    app = Headlines(Ctx({"headlines": p}), HeadlinesSettings(**kw))
    clk = Clock()
    app._clock = clk  # type: ignore[method-assign]
    return app, clk


def _hn_value() -> dict[str, Any]:
    items = [
        dict(hl.parse_hn_item(fx_json("hn_item")) or {}, id=str(i), rank=i, score=500 - i * 40)
        for i in range(1, 7)
    ]
    return {"hn:top": items, "lobsters:top": hl.parse_lobsters(fx_json("lobsters_hottest"))}


@pytest.mark.parametrize("layout", ["card", "big", "ticker"])
@pytest.mark.parametrize("title_style", ["marquee", "wrap"])
def test_headlines_layouts(layout: str, title_style: str) -> None:
    app, clk = _headlines(_hn_value(), layout=layout, title_style=title_style, min_points=100)
    assert all((s["score"] or 0) >= 100 for s in app.stories())
    for dt in (0.0, 3.0, 30.0):
        clk.t += dt
        f = Frame()
        app.render(f, clk.t - 1000)
        assert lit(f) > 30
    if app.kind() == "clip":
        clip = app.clip_frames()
        assert 1 <= len(clip.frames) <= 200 and len(clip.durations_ms) == len(clip.frames)
        app.clip_key()


def test_headlines_ticker_holds_on_each_story() -> None:
    app, _ = _headlines(_hn_value(), layout="ticker")
    clip = app.clip_frames()
    holds = [d for d in clip.durations_ms if d >= 2000]
    assert len(holds) >= len(app.stories())
    assert sum(clip.durations_ms) > 1000 * 2 * len(holds) * 0.9


def test_headlines_states() -> None:
    app, _ = _headlines({})
    f = Frame()
    app.render(f, 0.3)
    assert lit(f) > 0 and app.kind() == "stream"
    app2, _ = _headlines({"hn:top": []})
    f2 = Frame()
    app2.render(f2, 0.3)
    assert lit(f2) > 0  # NO NEWS


# ============================================================================= Currency
def test_currency_formatting() -> None:
    assert group_digits("8298817", indian=True) == "82,98,817"
    assert group_digits("250000", indian=True) == "2,50,000"
    assert group_digits("1234567", indian=False) == "1,234,567"
    assert compact(8298817, indian=True) == "83.0L" and compact(3.2e8, indian=True) == "32.0CR"
    assert compact(1_000_000) == "1.00M"
    assert unit_for(0.0104) == 100 and unit_for(95.7) == 1 and unit_for(0.00915) == 1000
    assert short_num(0.0104, 20) == ".0104" and short_num(1.2e-7, 12) == "<.1"
    assert fx.parse_codes("usd, eur;gbp  usd BTC") == ["USD", "EUR", "GBP", "BTC"]


def test_currency_from_home_board_scales_each_page() -> None:
    from deskdot.apps.currency import page_unit, sig_text, unit_token
    from deskdot.gfx.font import FONTS

    per_inr = [1 / 95.74, 1 / 109.25, 1 / 127.1, 1 / 0.6063]  # USD EUR GBP JPY
    unit = page_unit(per_inr, 17)
    assert unit_token(unit, indian=True) == "1K"
    assert [sig_text(r * unit, 17)[0] for r in per_inr] == ["10.44", "9.153", "7.868", "1649"]
    crypto = [1 / 26.04, 1 / 74.9, 1 / 8.3e6, 1 / 116.3]  # AED SGD BTC CHF
    unit = page_unit(crypto, 17)
    assert unit_token(unit, indian=True) == "1L" and all(sig_text(r * unit, 17)[1] >= 3 for r in crypto)
    assert unit_token(10**7, indian=False) == "10M"
    glyphs = FONTS["tiny"].glyphs
    for v in (1.2e-7, 0.0001, 0.5, 3.0, 12345678.0):
        assert all(ch in glyphs for ch in short_num(v, 12)), v  # never the "?" fallback glyph


def test_frankfurter_cross_rates_keep_precision() -> None:
    d = fx_json("frankfurter_eur_series")
    out = fx.parse_frankfurter(d, "INR", ["USD", "GBP", "EUR"])
    last = sorted(d["rates"])[-1]
    row = d["rates"][last]
    assert out["USD"]["rate"] == pytest.approx(row["INR"] / row["USD"])
    assert out["EUR"]["rate"] == pytest.approx(row["INR"])
    assert out["USD"]["date"] == last and len(out["USD"]["history"]) == len(d["rates"])
    prev = d["rates"][sorted(d["rates"])[-2]]
    assert out["USD"]["change_pct"] == pytest.approx(
        (row["INR"] / row["USD"] / (prev["INR"] / prev["USD"]) - 1) * 100
    )
    snap = fx_json("fawaz_usd")
    assert fx.fawaz_rate(snap, "USD", "INR") == pytest.approx(1 / snap["usd"]["inr"])


async def test_currency_provider_routes_and_falls_back() -> None:
    fz = fx_json("fawaz_usd")

    def inr_snapshot(date_: str) -> dict[str, Any]:  # an INR-based fawaz snapshot built from the USD one
        usd = fz["usd"]
        return {"date": date_, "inr": {k: v / usd["inr"] for k, v in usd.items()} | {"usd": 1 / usd["inr"]}}

    def route(url: str, params: dict[str, Any]) -> Any:
        if "frankfurter" in url and url.endswith("/currencies"):
            return {c: c for c in fx.ECB}
        if "frankfurter" in url:
            return fx_json("frankfurter_eur_series")
        if "currency-api" in url:
            tag = url.split("currency-api@")[1].split("/")[0] if "@" in url else "latest"
            return inr_snapshot(tag if tag != "latest" else "2026-09-24")
        return Resp({}, 404)

    hub = Hub(route)
    p = fx.CurrencyProvider(hub)
    p.want("INR", ["USD", "GBP", "AED", "BTC"], "30d")
    v = await p.fetch()
    assert v["base"] == "INR" and v["pairs"]["USD"]["source"] == "ecb"
    assert v["pairs"]["AED"]["source"] == "fawaz" and v["pairs"]["BTC"]["rate"] > 1e5
    assert v["pairs"]["USD"]["rate"] == pytest.approx(95.8, rel=0.01)
    dated = [u for u, _ in hub.http.calls if "currency-api@20" in u]
    assert 1 <= len(dated) <= fx.SNAPSHOTS
    n = len(hub.http.calls)
    await p.fetch()  # dated snapshots are cached forever
    assert len([u for u, _ in hub.http.calls[n:] if "currency-api@20" in u]) == 0

    def down(url: str, params: dict[str, Any]) -> Any:
        return Resp({}, 503) if "frankfurter" in url else route(url, params)

    p2 = fx.CurrencyProvider(Hub(down))
    p2.want("INR", ["USD"], "7d")
    v2 = await p2.fetch()
    assert v2["pairs"]["USD"]["source"] == "fawaz"  # ECB down -> fallback


def _fx_value() -> dict[str, Any]:
    out = fx.parse_frankfurter(fx_json("frankfurter_eur_series"), "INR", ["USD", "GBP", "EUR"])
    btc = fx.pair_entry("BTC", [("2026-09-22", 7.7e6), ("2026-09-23", 8.3e6)], "fawaz")
    assert btc
    return {"base": "INR", "range": "30d", "date": "2026-09-23", "pairs": {**out, "BTC": btc}}


@pytest.mark.parametrize("layout", ["pair", "board", "converter", "heat"])
@pytest.mark.parametrize("direction", ["to_home", "from_home"])
def test_currency_layouts(layout: str, direction: str) -> None:
    p = fx.CurrencyProvider(Hub(lambda u, pr: Resp({}, 500)))
    p.value = _fx_value()
    app = Currency(
        Ctx({"currency": p}),
        CurrencySettings(layout=layout, direction=direction, quotes="USD,GBP,EUR,BTC,XYZ", amount=250000),
    )
    for t in (0.0, 8.0, 16.0, 24.0, 32.0):
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, t)
        assert time.perf_counter() - t0 < 0.05
        assert lit(f) > 15
    assert app.status()["rates"]["USD"] > 50


def test_currency_stale_base_and_states() -> None:
    p = fx.CurrencyProvider(Hub(lambda u, pr: Resp({}, 500)))
    p.value = _fx_value()
    app = Currency(Ctx({"currency": p}), CurrencySettings(base="USD", quotes="INR"))
    assert app.data() is None  # value belongs to another base: show loading, not wrong numbers
    f = Frame()
    app.render(f, 0.3)
    assert lit(f) > 0
    with pytest.raises(ValueError):
        CurrencySettings(quotes=" ,, ")
