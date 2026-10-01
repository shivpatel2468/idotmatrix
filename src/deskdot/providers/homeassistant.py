"""Home Assistant bridge: entity states (and a short history) over HA's REST API.

Configuration lives in the store under "homeassistant": `{"url": "http://homeassistant.local:8123",
"token": "<long-lived access token>"}` (Profile → Security → Long-lived access tokens in HA).
The token is sent only as a Bearer header to that URL; it is never logged and the engine masks it in every
snapshot and API response.

Apps call `want(entity_id, poll_s, history_h)` from `on_start()`; the provider then polls
`GET /api/states/{entity_id}` every `poll_s` seconds and, when a history window is asked for,
`GET /api/history/period/{start}?filter_entity_id=…&minimal_response&no_attributes` at most every few minutes.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from .base import Provider

DEFAULTS: dict[str, Any] = {"url": "", "token": ""}


def mask(token: str) -> str:
    """Never echo a secret: '' stays '', anything else becomes '••••' + the last 4 characters."""
    return "" if not token else "••••" + token[-4:]


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def parse_state(d: dict[str, Any]) -> dict[str, Any]:
    """HA state object -> the fields the panel needs."""
    attrs = d.get("attributes") or {}
    state = str(d.get("state", ""))
    return {
        "entity_id": str(d.get("entity_id", "")),
        "state": state,
        "value": _num(state),
        "unit": str(attrs.get("unit_of_measurement") or ""),
        "name": str(attrs.get("friendly_name") or d.get("entity_id", "")),
        "device_class": str(attrs.get("device_class") or ""),
        "icon": str(attrs.get("icon") or ""),
        "changed": d.get("last_changed"),
    }


def parse_history(payload: Any) -> list[float]:
    """`/api/history/period` returns [[{state, last_changed}, …]] (one list per entity); numeric states only."""
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        return []
    out = []
    for row in payload[0]:
        if isinstance(row, dict):
            v = _num(row.get("state"))
            if v is not None:
                out.append(v)
    return out[-240:]


class HomeAssistantProvider(Provider[dict[str, Any]]):
    name = "homeassistant"
    interval = 10.0
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._wants: dict[str, tuple[float, float]] = {}  # entity -> (poll seconds, history hours)
        self._hist_at: dict[str, float] = {}
        self.entities: dict[str, dict[str, Any]] = {}

    def config(self) -> dict[str, Any]:
        d = dict(DEFAULTS)
        d.update(self.hub.store.get("homeassistant") or {})
        d["url"] = str(d.get("url") or "").strip().rstrip("/")
        return d

    @property
    def configured(self) -> bool:
        c = self.config()
        return bool(c["url"] and c["token"])

    def want(self, entity: str, poll_s: float = 10.0, history_h: float = 0.0) -> None:
        entity = entity.strip()
        if not entity:
            return
        new = entity not in self._wants or self._wants[entity][1] != history_h
        self._wants[entity] = (max(2.0, poll_s), max(0.0, history_h))
        if new:
            self._hist_at.pop(entity, None)
            self.refresh()

    def unwant(self, entity: str) -> None:
        self._wants.pop(entity.strip(), None)

    def reset(self) -> None:
        """URL or token changed: forget cached data and fetch again."""
        self.entities.clear()
        self._hist_at.clear()
        self.value = None
        self.error = None
        self.refresh()

    def next_interval(self) -> float:
        return min((p for p, _h in self._wants.values()), default=30.0)

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def check(self) -> dict[str, Any]:
        """Used by the studio's "Test connection" button: GET /api/ answers {"message": "API running."}."""
        c = self.config()
        if not (c["url"] and c["token"]):
            return {"ok": False, "message": "set the URL and a long-lived token first"}
        try:
            r = await self.hub.http.get(f"{c['url']}/api/", headers=self._headers(c["token"]))
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: cannot reach {c['url']}"}
        if r.status_code == 401:
            return {"ok": False, "message": "401 — the token was rejected"}
        if r.status_code >= 400:
            return {"ok": False, "message": f"HTTP {r.status_code}"}
        return {"ok": True, "message": str(r.json().get("message", "connected"))}

    async def fetch(self) -> dict[str, Any]:
        c = self.config()
        if not (c["url"] and c["token"]):
            raise RuntimeError("Home Assistant is not set up (Settings → Integrations)")
        headers = self._headers(c["token"])
        for entity, (_poll, hours) in list(self._wants.items()):
            r = await self.hub.http.get(f"{c['url']}/api/states/{entity}", headers=headers)
            if r.status_code == 401:
                raise RuntimeError("Home Assistant rejected the token (401)")
            if r.status_code == 404:
                self.entities[entity] = {"entity_id": entity, "missing": True}
                continue
            r.raise_for_status()
            st = parse_state(r.json())
            hist = self.entities.get(entity, {}).get("history", [])
            now = time.time()
            if hours and now - self._hist_at.get(entity, 0.0) > max(120.0, min(600.0, hours * 60)):
                start = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
                h = await self.hub.http.get(
                    f"{c['url']}/api/history/period/{start}",
                    params={"filter_entity_id": entity, "minimal_response": "", "no_attributes": ""},
                    headers=headers,
                )
                if h.status_code < 400:
                    hist = parse_history(h.json())
                    self._hist_at[entity] = now
            if st["value"] is not None and hours and (not hist or hist[-1] != st["value"]):
                hist = [*hist, st["value"]][-240:]
            self.entities[entity] = {**st, "history": hist if hours else [], "fetched": now}
        return dict(self.entities)
