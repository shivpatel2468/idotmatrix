"""OBS Studio status over obs-websocket v5 (built into OBS 28+; Tools → WebSocket Server Settings).

A minimal client written against the v5 protocol spec
(https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md):

1. server → ``Hello`` (op 0) with ``rpcVersion`` and, when a password is set, ``authentication``
   ``{challenge, salt}``;
2. client → ``Identify`` (op 1) with ``rpcVersion: 1``, ``eventSubscriptions`` and
   ``authentication = b64(sha256(b64(sha256(password + salt)) + challenge))``;
3. server → ``Identified`` (op 2), or closes with 4009 (authentication failed);
4. requests (op 6) ``GetStreamStatus`` / ``GetRecordStatus`` / ``GetCurrentProgramScene`` → responses (op 7);
   events (op 5) ``CurrentProgramSceneChanged``, ``StreamStateChanged``, ``RecordStateChanged``, ``ExitStarted``.

OBS not running is the normal case: the provider reports ``state: "off"`` as a *value* (no error, no log
spam) and retries with capped exponential backoff. The password is never logged or put in a value.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import itertools
import json
import time
from typing import Any

from .base import Provider
from .radiator import Backoff, safe_error

RPC_VERSION = 1
# EventSubscription bits (protocol.md): General 1<<0, Scenes 1<<2, Outputs 1<<6
EVENTS = (1 << 0) | (1 << 2) | (1 << 6)
AUTH_FAILED = 4009


def auth_string(password: str, salt: str, challenge: str) -> str:
    """The v5 authentication string: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class AuthError(Exception):
    pass


def _idle(state: str, **kw: Any) -> dict[str, Any]:
    return {
        "state": state,  # unset | off | auth | on
        "streaming": False,
        "recording": False,
        "paused": False,
        "reconnecting": False,
        "stream_since": None,
        "rec_since": None,
        "scene": "",
        "skipped": 0,
        "total": 0,
        "congestion": 0.0,
        "rec_bytes": 0,
        "version": "",
        **kw,
    }


class OBSProvider(Provider[dict[str, Any]]):
    """``value``: see `_idle` for the fields. Apps call ``configure(host, port, password)``."""

    name = "obs"
    feature = "lan"  # plain http / ws on the LAN: not from an https page (platforms.FEATURES)
    interval = 2.0  # status poll while connected (elapsed time is extrapolated locally between polls)
    retry = 5.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.host, self.port, self.password = "", 4455, ""
        self._ws: Any = None
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._ids = itertools.count(1)
        self._backoff = Backoff(2.0, 30.0)
        self._retry_at = 0.0
        self._st: dict[str, Any] = _idle("unset")
        self._closing: asyncio.Future[None] | None = None

    # ------------------------------------------------------------ interface
    def configure(self, host: str, port: int, password: str) -> None:
        cfg = (host.strip(), int(port), password)
        if cfg != (self.host, self.port, self.password):
            self.host, self.port, self.password = cfg
            self._backoff.reset()
            self._retry_at = 0.0
            self._drop_soon()
            self.refresh()

    def next_interval(self) -> float:
        if self._ws is not None:
            return self.interval
        return max(1.0, self._retry_at - time.time()) if self._retry_at else self.retry

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        keys = ("state", "streaming", "recording", "paused", "scene", "reconnecting")
        return (
            old is None
            or any(old.get(k) != new.get(k) for k in keys)
            or old.get("skipped") != new.get("skipped")
        )

    # ------------------------------------------------------------ connection
    def _drop_soon(self) -> None:
        if self._ws is not None:
            ws, self._ws = self._ws, None
            self._closing = asyncio.ensure_future(self._close(ws))

    async def _close(self, ws: Any) -> None:
        if self._reader and not self._reader.done():
            self._reader.cancel()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("closed"))
        self._pending.clear()
        with contextlib.suppress(Exception):
            await ws.close()

    async def _connect(self) -> None:
        from websockets.asyncio.client import connect

        uri = f"ws://{self.host}:{self.port}"
        ws = await connect(
            uri, open_timeout=3, close_timeout=1, subprotocols=["obswebsocket.json"], max_size=2**22
        )  # type: ignore[list-item]
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if hello.get("op") != 0:
                raise ConnectionError("not an obs-websocket v5 server")
            d = hello.get("d") or {}
            ident: dict[str, Any] = {"rpcVersion": RPC_VERSION, "eventSubscriptions": EVENTS}
            auth = d.get("authentication")
            if auth:
                if not self.password:
                    raise AuthError("OBS wants a password")
                ident["authentication"] = auth_string(self.password, auth["salt"], auth["challenge"])
            await ws.send(json.dumps({"op": 1, "d": ident}))
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
            except Exception as e:
                code = getattr(getattr(e, "rcvd", None), "code", None)
                if code == AUTH_FAILED:
                    raise AuthError("wrong OBS password") from None
                raise
            if msg.get("op") != 2:
                raise ConnectionError("identify failed")
            self._st["version"] = str(d.get("obsWebSocketVersion") or "")
        except BaseException:
            with contextlib.suppress(Exception):
                await ws.close()
            raise
        self._ws = ws
        self._reader = asyncio.create_task(self._read(ws), name="obs-reader")

    async def _read(self, ws: Any) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                op, d = msg.get("op"), msg.get("d") or {}
                if op == 7:
                    fut = self._pending.pop(str(d.get("requestId")), None)
                    if fut and not fut.done():
                        fut.set_result(d)
                elif op == 5:
                    self._on_event(str(d.get("eventType")), d.get("eventData") or {})
        except Exception:
            pass
        finally:
            if self._ws is ws:  # OBS quit or the link dropped: go idle and retry soon
                self._ws = None
                self._st.update(_idle("off", version=self._st.get("version", "")))
                self._publish()
                self._retry_at = time.time() + self._backoff.fail()
                self.refresh()

    async def request(self, rtype: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise ConnectionError("not connected")
        rid = str(next(self._ids))
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        msg: dict[str, Any] = {"requestType": rtype, "requestId": rid}
        if data:
            msg["requestData"] = data
        await self._ws.send(json.dumps({"op": 6, "d": msg}))
        try:
            d = await asyncio.wait_for(fut, 3)
        finally:
            self._pending.pop(rid, None)
        status = d.get("requestStatus") or {}
        if not status.get("result"):
            raise RuntimeError(f"{rtype}: {status.get('code')} {status.get('comment') or ''}".strip())
        return d.get("responseData") or {}

    # ------------------------------------------------------------ state
    def _publish(self) -> None:
        self.value = dict(self._st)
        self.updated = time.time()
        self.hub.on_change(self.name)

    def _on_event(self, etype: str, data: dict[str, Any]) -> None:
        now = time.time()
        if etype == "CurrentProgramSceneChanged":
            self._st["scene"] = str(data.get("sceneName") or "")
        elif etype == "StreamStateChanged":
            active = bool(data.get("outputActive"))
            if active and not self._st["streaming"]:
                self._st["stream_since"] = now
            self._st["streaming"] = active
            self._st["reconnecting"] = data.get("outputState") == "OBS_WEBSOCKET_OUTPUT_RECONNECTING"
            if not active:
                self._st["stream_since"] = None
        elif etype == "RecordStateChanged":
            active = bool(data.get("outputActive"))
            state = str(data.get("outputState") or "")
            if active and not self._st["recording"]:
                self._st["rec_since"] = now
            self._st["recording"] = active
            self._st["paused"] = state == "OBS_WEBSOCKET_OUTPUT_PAUSED"
            if not active:
                self._st["rec_since"] = None
        elif etype == "ExitStarted":
            self._drop_soon()
            self._st.update(_idle("off", version=self._st.get("version", "")))
        else:
            return
        self._publish()

    @staticmethod
    def _since(prev: float | None, duration_ms: Any, now: float) -> float | None:
        try:
            start = now - float(duration_ms) / 1000.0
        except (TypeError, ValueError):
            return prev
        return start if prev is None or abs(prev - start) > 1.5 else prev  # keep it steady between polls

    async def _poll(self) -> None:
        now = time.time()
        stream = await self.request("GetStreamStatus")
        rec = await self.request("GetRecordStatus")
        if not self._st["scene"]:
            sc = await self.request("GetCurrentProgramScene")
            if not self._st["scene"]:  # a CurrentProgramSceneChanged event may have beaten the reply
                self._st["scene"] = str(sc.get("sceneName") or sc.get("currentProgramSceneName") or "")
        st = self._st
        st["streaming"] = bool(stream.get("outputActive"))
        st["reconnecting"] = bool(stream.get("outputReconnecting"))
        st["stream_since"] = (
            self._since(st["stream_since"], stream.get("outputDuration"), now) if st["streaming"] else None
        )
        st["skipped"] = int(stream.get("outputSkippedFrames") or 0)
        st["total"] = int(stream.get("outputTotalFrames") or 0)
        st["congestion"] = float(stream.get("outputCongestion") or 0.0)
        st["recording"] = bool(rec.get("outputActive"))
        st["paused"] = bool(rec.get("outputPaused"))
        st["rec_bytes"] = int(rec.get("outputBytes") or 0)
        st["rec_since"] = (
            self._since(st["rec_since"], rec.get("outputDuration"), now) if st["recording"] else None
        )

    async def fetch(self) -> dict[str, Any]:
        if not self.host:
            self._st = _idle("unset")
            return dict(self._st)
        if self._ws is None:
            if time.time() < self._retry_at:
                return dict(self._st)
            try:
                self._st["scene"] = ""
                await self._connect()
                self._backoff.reset()
                self._retry_at = 0.0
                self._st["state"] = "on"
            except AuthError as e:
                self._retry_at = time.time() + 60.0  # a wrong password won't fix itself quickly
                self._st = _idle("auth", error=str(e))
                return dict(self._st)
            except Exception as e:  # OBS not running / unreachable: the normal idle case
                self._retry_at = time.time() + self._backoff.fail()
                self._st = _idle("off", error=safe_error(e, self.password, limit=80))
                return dict(self._st)
        try:
            await self._poll()
            self._st["state"] = "on"
            self._st.pop("error", None)
        except Exception as e:
            self._drop_soon()
            self._retry_at = time.time() + self._backoff.fail()
            self._st = _idle("off", error=safe_error(e, self.password, limit=80))
        return dict(self._st)

    # ------------------------------------------------------------ lifecycle
    async def _loop(self) -> None:
        try:
            await super()._loop()
        finally:  # nobody needs OBS any more (or shutdown): close the socket
            if self._ws is not None:
                ws, self._ws = self._ws, None
                await self._close(ws)
