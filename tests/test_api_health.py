"""API health (scripts/api_health.py, docs/API_HEALTH.md) and the provider fixes it led to in 3.6.0.

No live network: the endpoint registry is checked statically, the health checker runs on recorded payloads
(tests/fixtures/health/, captured 2026-10-08), and the fixed providers run against httpx mock transports.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from deskdot.providers import ALL, photos
from deskdot.providers import flights as fl
from deskdot.providers import headlines as hl
from deskdot.providers.base import Endpoint, dig

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "health"
# providers whose hosts are whatever the user types (no fixed endpoint to probe)
USER_HOSTS = {"homeassistant", "uptime", "calendar", "mediaserver", "printer", "anki", "obs"}


def fx(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _health() -> Any:
    spec = importlib.util.spec_from_file_location("api_health", ROOT / "scripts" / "api_health.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["api_health"] = mod  # dataclasses look their module up while the file executes
    spec.loader.exec_module(mod)
    return mod


class Hub:
    def __init__(self, handler: Any) -> None:
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def on_change(self, _n: str) -> None: ...


# ------------------------------------------------------------------------------------------ registry
def test_every_network_provider_declares_its_endpoints() -> None:
    url = re.compile(r"""["']https?://""")
    by_module: dict[str, list[type]] = {}
    for cls in ALL:
        if cls.name not in USER_HOSTS:
            by_module.setdefault(cls.__module__.rsplit(".", 1)[-1], []).append(cls)
    for mod, classes in by_module.items():
        src = (ROOT / "src" / "deskdot" / "providers" / f"{mod}.py").read_text(encoding="utf-8")
        if url.search(src):  # a module with URLs: some provider in it declares them (scripts/api_health.py)
            assert any(c.endpoints for c in classes), f"{mod}.py: list the URLs it calls in `endpoints`"
    for cls in ALL:
        for ep in cls.endpoints:
            assert isinstance(ep, Endpoint) and ep.label
            assert ep.url.startswith(("https://", "http://")) and "{" not in ep.url, (cls.name, ep.url)
            assert ep.role in ("primary", "fallback", "optional") and ep.body in ("json", "text", "bytes")
            assert ep.check or ep.expect, f"{cls.name}/{ep.label}: needs a shape check"


def test_dig() -> None:
    d = {"a": [{"b": 1}, {"b": None}], "c": {"d": "x"}}
    assert dig(d, "a.0.b") == 1 and dig(d, "c.d") == "x"
    assert (
        dig(d, "a.1.b") is None and dig(d, "a.5.b") is None and dig(d, "a.x") is None and dig(d, "z") is None
    )


# ------------------------------------------------------------------------------------- health checker
def test_checker_sees_shape_changes() -> None:
    h = _health()
    ep = Endpoint("HN Algolia", "https://hn.algolia.com/api/v1/search", check=hl.parse_hn_algolia)
    ok = httpx.Response(200, json=fx("hn_algolia.json"))
    assert h.check_body(ep, ok) is None
    assert h.check_body(ep, httpx.Response(200, json={"results": []})) == "parser returned nothing"
    assert "not json" in h.check_body(ep, httpx.Response(200, text="<html>"))
    ep2 = Endpoint("x", "https://x.example/", expect=("data.chart.0.y",))
    assert h.check_body(ep2, httpx.Response(200, json=fx("nasdaq_chart.json"))) is None
    assert h.check_body(ep2, httpx.Response(200, json={"data": None})) == "missing data.chart.0.y"
    boom = Endpoint("x", "https://x.example/", check=lambda d: d["gone"])
    assert h.check_body(boom, httpx.Response(200, json={})).startswith("parser: KeyError")


def test_checker_web_column() -> None:
    h = _health()
    allow = {"api.nasdaq.com"}
    assert h.web_access("https://a.example/x", "*", allow) == "CORS"
    assert h.web_access("https://a.example/x", "https://idotmatrix.com", allow) == "CORS"
    assert h.web_access("https://api.nasdaq.com/x", None, allow) == "proxy"
    assert h.web_access("http://a.example/x", "*", allow) == "NO"  # http can't be fetched from an https page
    assert {"api.nasdaq.com", "opendata.adsb.fi"} <= h.proxy_allowlist()
    assert not {"stooq.com", "api.airplanes.live"} & h.proxy_allowlist()


async def test_probe_classifies_answers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    h = _health()
    routes = {
        "ok.example": httpx.Response(200, json={"v": 1}),
        "key.example": httpx.Response(401, text="api key required"),
        "gone.example": httpx.Response(410, text="retired"),
        "busy.example": httpx.Response(429),
        "shape.example": httpx.Response(200, json={"w": 1}),
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["origin"] == "https://idotmatrix.com"
        return routes[req.url.host]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        out = {}
        for host in routes:
            ep = Endpoint(host, f"https://{host}/", expect=("v",))
            out[host] = (await h.probe(http, "p", ep, set(), asyncio.Lock())).status
    assert out == {
        "ok.example": "OK",
        "key.example": "KEY",
        "gone.example": "DOWN",
        "busy.example": "LIMIT",
        "shape.example": "SHAPE",
    }


# ------------------------------------------------------------------------------ Hacker News fallback
async def test_headlines_fall_back_to_algolia_when_firebase_is_unreachable() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.host == "hacker-news.firebaseio.com":
            raise httpx.ConnectError("getaddrinfo failed", request=req)
        assert req.url.host == "hn.algolia.com"
        return httpx.Response(200, json=fx("hn_algolia.json"))

    p = hl.HeadlinesProvider(Hub(handler))  # type: ignore[arg-type]
    p.want("hn", "top", 3)
    v = await p.fetch()
    stories = v["hn:top"]
    assert len(stories) == 3 and all(s["title"] and s["id"] for s in stories)
    assert stories[0]["score"] > 0 and stories[0]["site"] and stories[0]["rank"] == 1
    assert "tags=front_page" in seen[-1] and "hitsPerPage=3" in seen[-1]


def test_parse_hn_algolia_tolerates_junk() -> None:
    assert hl.parse_hn_algolia(None) == [] and hl.parse_hn_algolia({"hits": [None, {"title": ""}]}) == []
    s = hl.parse_hn_algolia({"hits": [{"objectID": "1", "title": "Hi", "points": 5, "num_comments": 2}]})[0]
    assert s == {
        "id": "1",
        "title": "HI",
        "score": 5,
        "comments": 2,
        "time": None,
        "by": "",
        "site": "YCOMBINATOR.COM",
    }


# ---------------------------------------------------------------------------------- flights: adsb.fi
def test_adsb_fi_replaces_airplanes_live() -> None:
    assert "airplanes.live" not in fl.READSB_SOURCES and "adsb.fi" in fl.SOURCES
    d = fx("adsbfi.json")
    assert "aircraft" in d and "ac" not in d  # adsb.fi names the list differently
    out = fl.parse_readsb(d, (51.47, -0.45))
    assert len(out) == len(d["aircraft"]) and all("dist_nm" in a and a["callsign"] is not None for a in out)
    assert out == sorted(out, key=lambda a: a["dist_nm"])  # nearest first


# ---------------------------------------------------------------------------------- The Met v1.1 search
async def test_met_uses_the_paginated_v1_1_search() -> None:
    calls: list[httpx.URL] = []
    obj = {
        "primaryImageSmall": "https://images.metmuseum.org/x.jpg",
        "title": "Wheat Field",
        "artistDisplayName": "V",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url)
        if req.url.path.endswith("/v1/search"):
            return httpx.Response(410, json={"message": "retired"})
        if req.url.path.endswith("/v1.1/search"):
            return httpx.Response(200, json={"total": 250, "objectIDs": [11, 12, 13]})
        return httpx.Response(200, json=obj)

    p = photos.PhotosProvider(Hub(handler))  # type: ignore[arg-type]
    url, title, _artist, key = await p._pick("met")
    assert url.endswith("x.jpg") and key.startswith("met:") and title
    first = calls[0]
    assert first.path.endswith("/v1.1/search") and first.params["limit"] == "100"
    assert first.params["offset"] == "0" and first.params["isHighlight"] == "true"
    p._met_ids.clear()  # the cache expired: the next search starts at a random page within the total
    await p._pick("met")
    later = next(u for u in calls[1:] if u.path.endswith("/v1.1/search"))
    assert 0 <= int(later.params["offset"]) <= 150


@pytest.mark.parametrize("name", ["hn_algolia.json", "adsbfi.json", "nasdaq_chart.json"])
def test_fixtures_are_small(name: str) -> None:
    assert (FIX / name).stat().st_size < 8000
