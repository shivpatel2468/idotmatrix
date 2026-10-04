"""Entry point for the DeskDot web app: the engine running in a browser tab (docs/WEB_APP.md, ADR 0012).

Pyodide runs this package inside a Web Worker (`site/app/engine/worker.js`). There is no socket server in the
browser, so the page's fetch / WebSocket shims hand each request to `http()` / `ws_*()` here, which call the very
same FastAPI app the desktop serves (`server.create_app`) through the ASGI protocol directly. The panel link is
`device/web.py`, driven by the page's Web Bluetooth bridge.

Browser differences, handled here once so the engine code stays the same everywhere:

* no threads — `asyncio.to_thread` runs the (short) blocking helpers inline;
* no sockets — `httpx.AsyncClient` gets a transport that uses the browser's `fetch` (CORS applies; plain-http
  APIs are upgraded to https because the page is https);
* storage — the data dir lives on an IndexedDB-backed filesystem that the worker syncs after every save.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

log = logging.getLogger("deskdot.web")

_app: Any = None
_lifespan: dict[str, Any] = {}
_sockets: dict[int, _Socket] = {}
_sync: Callable[[], None] = lambda: None  # noqa: E731 — set by the worker: persist the data dir to IndexedDB
#: same-origin fallback for APIs that don't allow browsers (no CORS) — a Netlify Function with a host allowlist
_proxy: str | None = None
#: hosts whose direct fetch failed once: go through the proxy straight away
_proxied: set[str] = set()

# request headers the browser forbids or that force a CORS preflight many public APIs don't answer
_DROP_REQ = {"user-agent", "host", "connection", "content-length", "accept-encoding", "keep-alive"}
# the browser already decoded the body: don't let httpx decode it again
_DROP_RESP = {"content-encoding", "content-length", "transfer-encoding"}
# names that only resolve inside a home / office network
_LAN_SUFFIXES = (".local", ".lan", ".home", ".internal", ".home.arpa", ".localdomain", ".localhost")


def is_local_host(host: str) -> bool:
    """A device on this computer or the LAN (private / loopback / link-local IP, `localhost`, `nas.local`, a bare
    single-label name like `octopi`): the proxy can't reach it and an https page may not call it over plain http."""
    import ipaddress

    h = host.strip("[]").lower().rstrip(".")
    if not h:
        return False
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return h == "localhost" or "." not in h or h.endswith(_LAN_SUFFIXES)
    return ip.is_private or ip.is_loopback or ip.is_link_local


def blocked_message(host: str, url: str, local: bool) -> str:
    """Why a fetch from the tab failed, in words the studio can show (fetch() itself hides the reason)."""
    if local and url.startswith("http://"):
        return (
            f"{host}: the browser app can't reach plain-http devices on your network (an https page may not call "
            "them); use an https address that allows this site (CORS), or the desktop app"
        )
    if local:
        return f"{host}: not reachable from the browser (it must allow https://idotmatrix.com via CORS) or offline"
    return f"{host}: blocked by the browser (the API doesn't allow web pages: no CORS) or offline"


# ===================================================================== runtime patches
async def _to_thread(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """No threads in the browser: run the blocking helper inline (they're short: decode an image, parse ICS)."""
    await asyncio.sleep(0)
    return func(*args, **kwargs)


def _proxied_url(url: str) -> str:
    from urllib.parse import quote

    return f"{_proxy}?url={quote(url, safe='')}"


async def _fetch(url: str, kw: dict[str, Any], wait: float) -> tuple[Any, bytes]:
    from pyodide.http import pyfetch  # type: ignore[import-not-found]

    resp = await asyncio.wait_for(pyfetch(url, **kw), wait + 2)
    data = await asyncio.wait_for(resp.bytes(), wait + 2)
    return resp, data


def _refused_by_proxy(resp: Any) -> bool:
    """The proxy's own "host not allowed" (403 without its marker header), as opposed to an upstream 403."""
    return int(resp.status) == 403 and "x-deskdot-proxy" not in {k.lower() for k in resp.headers}


async def probe(url: str, wait: float = 5.0) -> float:
    """Is `url` reachable from this tab? Returns the round trip in ms, raises OSError if not.

    An opaque ("no-cors") request: no CORS needed and no proxy, but the status code stays hidden — a resolved
    fetch means the server answered. Uptime checks use it for sites that don't allow web pages."""
    import time

    from pyodide.ffi import JsException  # type: ignore[import-not-found]
    from pyodide.http import pyfetch  # type: ignore[import-not-found]

    if url.startswith("http://") and not is_local_host(urlsplit(url).hostname or ""):
        url = "https://" + url[len("http://") :]  # an https page may not fetch plain http
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(pyfetch(url, method="GET", mode="no-cors", cache="no-store"), wait)
    except TimeoutError:
        raise OSError("timed out") from None
    except (
        JsException,
        OSError,
    ) as e:  # pyfetch reports network errors as OSError (older Pyodide: JsException)
        raise OSError(f"unreachable: {e}") from None
    return (time.perf_counter() - t0) * 1000


def _fetch_transport() -> Any:
    import httpx

    class FetchTransport(httpx.AsyncBaseTransport):
        """httpx over the browser's fetch(). Mirrors what the engine needs: method, headers, body, status."""

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            from pyodide.ffi import JsException, to_js  # type: ignore[import-not-found]

            url = str(request.url)
            host = request.url.host or ""
            local = is_local_host(host)
            headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ}
            body = await request.aread()
            kw: dict[str, Any] = {"method": request.method, "headers": headers}
            if body and request.method not in ("GET", "HEAD"):
                kw["body"] = to_js(memoryview(body))
            timeout = float((request.extensions.get("timeout") or {}).get("read") or 15.0)
            can_proxy = bool(_proxy) and request.method == "GET" and not local
            # an https page may not fetch plain http: the proxy fetches it as-is, else try the https twin
            via_proxy = can_proxy and (url.startswith("http://") or host in _proxied)
            if url.startswith("http://") and not local and not via_proxy:
                url = "https://" + url[len("http://") :]
            try:
                try:
                    resp, data = await _fetch(_proxied_url(url) if via_proxy else url, kw, timeout)
                except (JsException, OSError):
                    if not can_proxy or via_proxy:
                        raise
                    # fetch() hides the reason; nearly always CORS (the API doesn't allow browsers)
                    resp, data = await _fetch(_proxied_url(str(request.url)), kw, timeout)
                    via_proxy = True
                    if not _refused_by_proxy(resp):
                        _proxied.add(host)
            except TimeoutError:
                raise httpx.ReadTimeout(f"timed out: {host}", request=request) from None
            except (JsException, OSError):
                raise httpx.ConnectError(blocked_message(host, url, local), request=request) from None
            if via_proxy and _refused_by_proxy(resp):
                raise httpx.ConnectError(
                    f"{host}: doesn't allow web pages (no CORS) and isn't on the web app's proxy list",
                    request=request,
                )
            out = [(k, v) for k, v in resp.headers.items() if k.lower() not in _DROP_RESP]
            return httpx.Response(resp.status, headers=out, content=data, request=request)

    return FetchTransport


def patch_runtime() -> None:
    """Make the browser look enough like a host for the engine. Idempotent."""
    asyncio.to_thread = _to_thread  # type: ignore[assignment]

    # stdlib modules Pyodide ships as separate downloads that only unsupported providers use (the OS notification
    # database): an empty stand-in keeps their imports working without the download
    import importlib.util
    import sys
    import types

    for name in ("sqlite3",):
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found and name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    import httpx

    if getattr(httpx.AsyncClient, "_deskdot_web", False):
        return
    transport_cls = _fetch_transport()
    orig_init = httpx.AsyncClient.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("transport", transport_cls())
        orig_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = init  # type: ignore[method-assign]
    httpx.AsyncClient._deskdot_web = True  # type: ignore[attr-defined]

    # persist the data dir (IndexedDB) shortly after every state save
    from .config import Store

    orig_save = Store.save_now

    def save_now(self: Any) -> None:
        orig_save(self)
        _sync()

    Store.save_now = save_now  # type: ignore[method-assign]


# ===================================================================== boot
async def boot(
    root: str = "/deskdot",
    sync: Callable[[], None] | None = None,
    proxy: str | None = None,
    public_url: str | None = None,
) -> dict[str, Any]:
    """Create the engine (device="web") and run the ASGI lifespan startup."""
    global _app, _sync, _proxy
    if sync is not None:
        _sync = sync
    _proxy = proxy or None
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    patch_runtime()
    base = Path(root)
    (base / "data").mkdir(parents=True, exist_ok=True)
    (base / "plugins").mkdir(parents=True, exist_ok=True)
    os.environ["DESKDOT_WEB_DIST"] = str(base / "no-studio")  # the page serves the studio, not the engine

    import time

    t0 = time.perf_counter()
    from .config import load_config
    from .server import create_app

    t1 = time.perf_counter()
    cfg = load_config(
        base / "deskdot.toml",
        device="web",
        data_dir=base / "data",
        plugins_dir=base / "plugins",
        host="127.0.0.1",
        public_url=public_url
        or None,  # the site's origin: phones join at <origin>/p/<code> (WebRTC, host-rtc.js)
    )
    _app = create_app(cfg)
    t2 = time.perf_counter()
    await _start_lifespan()
    log.info("engine up: import %.1fs, create %.1fs, start %.1fs", t1 - t0, t2 - t1, time.perf_counter() - t2)
    return {"ok": True, "platform": "web"}


async def _start_lifespan() -> None:
    inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    started: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    async def receive() -> dict[str, Any]:
        return await inbox.get()

    async def send(msg: dict[str, Any]) -> None:
        if msg["type"] == "lifespan.startup.complete" and not started.done():
            started.set_result(None)
        elif msg["type"] == "lifespan.startup.failed" and not started.done():
            started.set_exception(RuntimeError(msg.get("message") or "engine failed to start"))

    scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}, "state": {}}
    _lifespan["inbox"] = inbox
    _lifespan["task"] = asyncio.create_task(_app(scope, receive, send), name="lifespan")
    await inbox.put({"type": "lifespan.startup"})
    await started


async def shutdown() -> None:
    """Stop the engine cleanly (the page is closing)."""
    inbox = _lifespan.get("inbox")
    if inbox is not None:
        await inbox.put({"type": "lifespan.shutdown"})
        with contextlib.suppress(Exception):
            await asyncio.wait_for(_lifespan["task"], 3.0)
    _sync()


def device() -> Any:
    """The engine's panel backend (the worker forwards the user's "Connect panel" pick to it)."""
    return _app.state.engine.device if _app is not None else None


def user_picked() -> None:
    dev = device()
    if dev is not None and hasattr(dev, "_user_picked_cb"):
        dev._user_picked_cb()


# ===================================================================== camera / screen / sound
# The page captures (host-media.js: getUserMedia / getDisplayMedia, downscaled there); the worker forwards here and
# providers/webmedia.py turns it into the values the apps read. The engine asks for streams through the worker's
# `deskdotMedia` bridge (want / stop).
def _raw(data: Any) -> bytes:
    if data is None:
        return b""
    to_bytes = getattr(data, "to_bytes", None)  # a JS Uint8Array (JsProxy)
    return bytes(to_bytes()) if to_bytes is not None else bytes(data)


def media_frame(kind: str, w: int, h: int, data: Any) -> None:
    """An RGB frame (w*h*3 bytes) from the camera or the shared screen."""
    from .providers import webmedia

    webmedia.frame(str(kind), int(w), int(h), _raw(data))


def media_audio(sample_rate: float, data: Any, source: str = "") -> None:
    """The newest float32 samples (as bytes) from the mic or a shared tab / screen."""
    from .providers import webmedia

    webmedia.audio(float(sample_rate), _raw(data), str(source or ""))


def media_state(kind: str, state: str, detail: str = "") -> None:
    """The page's stream state: waiting (needs a click) | live | denied | error | stopped | unsupported."""
    from .providers import webmedia

    webmedia.state(str(kind), str(state), str(detail or ""))


def media_hello() -> None:
    """The page's capture add-on loaded: repeat the requests still wanted."""
    from .providers import webmedia

    webmedia.hello()


# ===================================================================== HTTP
def _scope(
    kind: str, path: str, headers: list[tuple[str, str]], method: str = "GET", client: str | None = None
) -> dict[str, Any]:
    path, _, query = path.partition("?")
    scope: dict[str, Any] = {
        "type": kind,
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "https" if kind == "http" else "wss",
        "path": unquote(path),
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query.encode(),
        "headers": [(k.lower().encode("latin-1"), str(v).encode("latin-1")) for k, v in headers],
        # the studio is local by definition (it's the same tab); a phone tunnelled in over WebRTC (host-rtc.js) is not
        "client": (client or "127.0.0.1", 0),
        "server": ("127.0.0.1", 8765),
        "state": {},
    }
    if kind == "http":
        scope["method"] = method.upper()
    else:
        scope["subprotocols"] = []
    return scope


async def http(
    method: str, path: str, headers: list[tuple[str, str]], body: bytes = b"", client: str | None = None
) -> tuple[int, list[tuple[str, str]], bytes]:
    """One HTTP request through the ASGI app. `path` includes the query string."""
    if _app is None:
        return 503, [("content-type", "application/json")], b'{"detail":"engine is starting"}'
    scope = _scope("http", path, headers, method, client)
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": bytes(body or b""), "more_body": False}
        await asyncio.Event().wait()  # a disconnect never comes: the caller waits for the response
        return {"type": "http.disconnect"}

    status = 500
    out_headers: list[tuple[str, str]] = []
    chunks: list[bytes] = []

    async def send(msg: dict[str, Any]) -> None:
        nonlocal status, out_headers
        if msg["type"] == "http.response.start":
            status = int(msg["status"])
            out_headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in msg.get("headers", [])]
        elif msg["type"] == "http.response.body":
            chunks.append(bytes(msg.get("body", b"")))

    try:
        await _app(scope, receive, send)
    except Exception as e:  # pragma: no cover — FastAPI turns handler errors into 500s itself
        log.exception("request failed: %s %s", method, path)
        return 500, [("content-type", "text/plain")], f"engine error: {e}".encode()
    return status, out_headers, b"".join(chunks)


async def http_js(method: str, path: str, headers: Any, body: Any = None, client: Any = None) -> Any:
    """`http()` for the worker: JS arrays / Uint8Array in, a plain JS object out."""
    from pyodide.ffi import to_js  # type: ignore[import-not-found]

    import js  # type: ignore[import-not-found]

    hdrs = headers.to_py() if hasattr(headers, "to_py") else headers
    raw = body.to_bytes() if hasattr(body, "to_bytes") else bytes(body or b"")
    status, out, data = await http(
        method, path, [(str(k), str(v)) for k, v in hdrs], raw, str(client) if client else None
    )
    return to_js(
        {"status": status, "headers": [[k, v] for k, v in out], "body": memoryview(data)},
        dict_converter=js.Object.fromEntries,
    )


# ===================================================================== WebSocket
class _Socket:
    def __init__(
        self, sid: int, path: str, emit: Callable[[str, Any], None], client: str | None = None
    ) -> None:
        self.sid = sid
        self.client = client
        self.emit = emit
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.closed = False
        self.task = asyncio.create_task(self._run(path), name=f"ws-{sid}")

    async def _run(self, path: str) -> None:
        await self.inbox.put({"type": "websocket.connect"})

        async def receive() -> dict[str, Any]:
            return await self.inbox.get()

        async def send(msg: dict[str, Any]) -> None:
            t = msg["type"]
            if t == "websocket.accept":
                self.emit("open", None)
            elif t == "websocket.send":
                if msg.get("bytes") is not None:
                    self.emit("bytes", bytes(msg["bytes"]))
                else:
                    self.emit("text", msg.get("text") or "")
            elif t == "websocket.close":
                self._closed(int(msg.get("code", 1000)))

        try:
            await _app(_scope("websocket", path, [], client=self.client), receive, send)
        except Exception as e:
            log.warning("socket %s ended: %s", path, e)
        self._closed(1000)

    def _closed(self, code: int) -> None:
        if not self.closed:
            self.closed = True
            self.emit("close", code)
            _sockets.pop(self.sid, None)


def ws_open(sid: int, path: str, emit: Callable[[str, Any], None], client: Any = None) -> None:
    """Open a socket; `emit(event, data)` gets "open", "text", "bytes" (a JS Uint8Array) and "close"."""
    try:
        from pyodide.ffi import to_js  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover — not in a browser (tests): pass bytes through
        to_js = None

    def out(ev: str, data: Any) -> None:
        if isinstance(data, bytes) and to_js is not None:
            data = to_js(memoryview(data))
        emit(ev, data)

    _sockets[sid] = _Socket(sid, path, out, str(client) if client else None)


def ws_send(sid: int, data: Any) -> None:
    s = _sockets.get(sid)
    if s is None:
        return
    if isinstance(data, str):
        s.inbox.put_nowait({"type": "websocket.receive", "text": data})
    else:
        raw = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)  # a JS Uint8Array or bytes
        s.inbox.put_nowait({"type": "websocket.receive", "bytes": raw})


def ws_close(sid: int, code: int = 1000) -> None:
    s = _sockets.get(sid)
    if s is not None:
        s.inbox.put_nowait({"type": "websocket.disconnect", "code": code})
