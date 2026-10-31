"""HTTP routes for the panel hand-over (ADR 0015, docs/API.md "Panel hand-over").

Two groups:

* `/api/handover/*` — the studio's own API (this computer only, like the rest of `/api`). `tab` and `free` may also be
  called by the web app (idotmatrix.com/app) in a browser tab on this computer: they answer with CORS and
  Private-Network-Access headers for those origins only, and refuse any other cross-site Origin (no CSRF: a page on
  another site can't make this engine release the panel).
* `/lan/handover/*` — the one narrow surface other devices on the LAN may reach (`LanGate` lets it through): pairing
  (rate-limited, private addresses only, needs the user's Allow) and the signed release / announce requests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .handover import AuthError, Handover

#: origins of the web app that may use /api/handover/tab and /api/handover/free cross-origin (same as /api/health)
WEB_APP_ORIGINS = frozenset(
    {"https://idotmatrix.com", "https://www.idotmatrix.com", "http://localhost:8799", "http://127.0.0.1:8799"}
)
CROSS_ORIGIN_PATHS = ("/api/handover/tab", "/api/handover/free", "/api/handover")


def _same_site(origin: str, request: Request) -> bool:
    """The studio itself (served by this engine, or the dev server on another loopback port)."""
    host = request.headers.get("host", "")
    if origin in (f"http://{host}", f"https://{host}"):
        return True
    return urlsplit(origin).hostname in ("127.0.0.1", "localhost", "::1")


def _cors(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin", "")
    if origin not in WEB_APP_ORIGINS:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Private-Network": "true",
        "Vary": "Origin",
    }


def _check_origin(request: Request) -> None:
    """A POST that changes who holds the panel: the studio itself, the web app, or a non-browser client only."""
    origin = request.headers.get("origin")
    if origin and origin not in WEB_APP_ORIGINS and not _same_site(origin, request):
        raise HTTPException(403, "not allowed from this site")


def _addr(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _json(request: Request) -> tuple[bytes, dict[str, Any]]:
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413, "too large")
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "invalid JSON") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "expected an object")
    return raw, data


def register(app: FastAPI, ho: Handover, on_enabled: Callable[[bool], None] | None = None) -> None:
    # ------------------------------------------------------------------ the studio (this computer)
    @app.get("/api/handover")
    async def handover_state(request: Request) -> JSONResponse:
        return JSONResponse(ho.brief(), headers=_cors(request))

    @app.post("/api/handover/take")
    async def handover_take(request: Request, force: bool = Body(False, embed=True)) -> dict[str, Any]:
        """ "Use the panel here": ask whoever holds it to let go, wait for the panel, connect (progress in state)."""
        _check_origin(request)
        return ho.take(force=force)

    @app.post("/api/handover/pair")
    async def handover_pair(request: Request, peer: str = Body(..., embed=True)) -> dict[str, Any]:
        _check_origin(request)
        try:
            return await ho.pair(peer)
        except KeyError:
            raise HTTPException(404, "no such DeskDot nearby") from None
        except Exception as e:
            raise HTTPException(502, f"couldn't reach it: {e}") from None

    @app.post("/api/handover/pair/answer")
    async def handover_pair_answer(
        request: Request, peer: str = Body(..., embed=True), allow: bool = Body(..., embed=True)
    ) -> dict[str, Any]:
        _check_origin(request)
        try:
            return ho.answer_pair(peer, allow)
        except KeyError:
            raise HTTPException(404, "no pending request from it") from None

    @app.post("/api/handover/forget")
    async def handover_forget(request: Request, peer: str = Body(..., embed=True)) -> dict[str, Any]:
        _check_origin(request)
        ho.forget(peer)
        return {"ok": True}

    @app.put("/api/handover/settings")
    async def handover_settings(request: Request, enabled: bool = Body(..., embed=True)) -> dict[str, Any]:
        _check_origin(request)
        await ho.set_enabled(enabled)
        if on_enabled is not None:
            on_enabled(enabled)
        return {"ok": True, "enabled": ho.enabled}

    # ------------------------------------------------------------------ the web app in a tab on this computer
    @app.post("/api/handover/tab")
    async def handover_tab(request: Request) -> JSONResponse:
        """The browser tab reports whether it holds the panel; the answer says whether someone wants it."""
        _check_origin(request)
        _, body = await _json(request)
        res = ho.on_tab_report(bool(body.get("holding")), body.get("panel"))
        return JSONResponse(res, headers=_cors(request))

    @app.post("/api/handover/free")
    async def handover_free(request: Request) -> JSONResponse:
        """The browser tab wants the panel: release it here, or ask the DeskDot on the LAN that has it."""
        _check_origin(request)
        res = await ho.free_for_tab()
        return JSONResponse(res, headers=_cors(request))

    for path in CROSS_ORIGIN_PATHS:

        @app.options(path, include_in_schema=False)
        async def handover_preflight(request: Request) -> Response:
            headers = _cors(request)
            if headers:
                headers["Access-Control-Allow-Methods"] = "GET, POST"
                headers["Access-Control-Allow-Headers"] = "content-type"
                headers["Access-Control-Max-Age"] = "600"
            return Response(status_code=204, headers=headers)

    # ------------------------------------------------------------------ the LAN (LanGate lets only these through)
    @app.post("/lan/handover/pair")
    async def lan_pair(request: Request) -> JSONResponse:
        _, body = await _json(request)
        try:
            return JSONResponse(ho.on_pair_request(body, _addr(request)))
        except AuthError as e:
            return JSONResponse({"detail": str(e)}, status_code=e.status)

    @app.post("/lan/handover/pair/poll")
    async def lan_pair_poll(request: Request) -> JSONResponse:
        _, body = await _json(request)
        try:
            return JSONResponse(ho.on_pair_poll(body, _addr(request)))
        except AuthError as e:
            return JSONResponse({"detail": str(e)}, status_code=e.status)

    @app.post("/lan/handover/release")
    async def lan_release(request: Request) -> JSONResponse:
        raw, body = await _json(request)
        try:
            peer = ho.verify("POST", request.url.path, dict(request.headers), raw, _addr(request))
        except AuthError as e:
            return JSONResponse({"detail": str(e)}, status_code=e.status)
        res = await ho.on_release_request(peer, body)
        return JSONResponse(res, status_code=200 if res.get("ok") or res.get("busy") else 409)

    @app.post("/lan/handover/announce")
    async def lan_announce(request: Request) -> JSONResponse:
        raw, body = await _json(request)
        try:
            peer = ho.verify("POST", request.url.path, dict(request.headers), raw, _addr(request))
        except AuthError as e:
            return JSONResponse({"detail": str(e)}, status_code=e.status)
        return JSONResponse(ho.on_announce(peer, body))
