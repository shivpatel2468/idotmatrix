"""3D printer status from OctoPrint or Moonraker (Klipper), normalised to one shape.

OctoPrint (REST, ``X-Api-Key`` header): ``GET /api/job`` (file, progress, times, state text) and
``GET /api/printer?exclude=sd`` (tool0/bed temperatures; 409 when no printer is connected).

Moonraker: ``GET /printer/objects/query?print_stats&display_status&extruder&heater_bed&virtual_sdcard``
(``X-Api-Key`` only if the instance requires one). Moonraker has no remaining-time field, so the ETA is
extrapolated from ``print_duration`` and progress.

A printer that is switched off is normal: the value says ``state: "offline"`` instead of raising, so the
log stays quiet. Transitions printing → done / failed are recorded as events (armed after the first poll)
and stamped in the value (``finished_at``) so apps can celebrate.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .base import Provider
from .radiator import EventLog, base_url, panel_text, safe_error

DEFAULT_PORT = {"octoprint": 80, "moonraker": 7125}
ACTIVE = {"printing", "paused"}

OCTO_STATES = {
    "printing": "printing",
    "printing from sd": "printing",
    "starting": "printing",
    "starting print from sd": "printing",
    "sending file to sd": "printing",
    "finishing": "printing",
    "cancelling": "printing",
    "pausing": "paused",
    "paused": "paused",
    "resuming": "paused",
    "operational": "idle",
    "error": "error",
    "offline after error": "error",
}
MOON_STATES = {
    "printing": "printing",
    "paused": "paused",
    "complete": "done",
    "cancelled": "failed",
    "error": "error",
    "standby": "idle",
}


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _temp(d: Any, actual: str = "actual", target: str = "target") -> list[float | None]:
    d = d if isinstance(d, dict) else {}
    return [_num(d.get(actual)), _num(d.get(target))]


def parse_octoprint(job: dict[str, Any], printer: dict[str, Any] | None) -> dict[str, Any]:
    """``/api/job`` + ``/api/printer`` JSON -> normalised status."""
    text = str(job.get("state") or "").strip()
    state = OCTO_STATES.get(
        text.lower(), "offline" if "offline" in text.lower() or "clos" in text.lower() else "idle"
    )
    progress = job.get("progress") or {}
    comp = _num(progress.get("completion"))
    f = (job.get("job") or {}).get("file") or {}
    name = str(f.get("display") or f.get("name") or "")
    if state == "idle" and comp is not None and comp >= 99.9 and name:
        state = "done"  # OctoPrint reports "Operational" with the finished job still loaded
    temps = (printer or {}).get("temperature") or {}
    return {
        "kind": "octoprint",
        "state": state,
        "state_text": text,
        "progress": comp / 100 if comp is not None else None,
        "file": name,
        "elapsed": _num(progress.get("printTime")),
        "left": _num(progress.get("printTimeLeft")),
        "nozzle": _temp(temps.get("tool0")),
        "bed": _temp(temps.get("bed")),
        "message": str(job.get("error") or ""),
    }


def parse_moonraker(payload: dict[str, Any]) -> dict[str, Any]:
    """``/printer/objects/query`` JSON -> normalised status."""
    st = ((payload.get("result") or {}).get("status")) or {}
    ps = st.get("print_stats") or {}
    ds = st.get("display_status") or {}
    vs = st.get("virtual_sdcard") or {}
    state = MOON_STATES.get(str(ps.get("state") or "").lower(), "idle")
    prog = _num(ds.get("progress"))
    if not prog:  # M73 not sent by the slicer: fall back to the file position
        prog = _num(vs.get("progress")) if vs else prog
    elapsed = _num(ps.get("print_duration"))
    left = None
    if state in ACTIVE and prog and prog > 0.01 and elapsed:
        left = max(0.0, elapsed / prog - elapsed)
    return {
        "kind": "moonraker",
        "state": state,
        "state_text": str(ps.get("state") or ""),
        "progress": prog,
        "file": str(ps.get("filename") or ""),
        "elapsed": elapsed,
        "left": left,
        "nozzle": _temp(st.get("extruder"), "temperature"),
        "bed": _temp(st.get("heater_bed"), "temperature"),
        "message": str(ps.get("message") or ds.get("message") or ""),
    }


class PrinterProvider(EventLog, Provider[dict[str, Any]]):
    """``value``: normalised status (see parsers) + ``finished_at``. Apps call ``configure(kind, host, …)``.

    Events: ``done`` / ``failed`` ``{"file"}``.
    """

    name = "printer"
    interval = 10.0
    idle_interval = 30.0
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._init_events()
        self.kind, self.host, self.port, self.key = "octoprint", "", 0, ""
        self._prev: str | None = None
        self._finished_at: float | None = None
        self._last_file = ""
        self._result: str | None = None

    def configure(self, kind: str, host: str, port: int, key: str) -> None:
        cfg = (kind, host.strip(), int(port), key)
        if cfg != (self.kind, self.host, self.port, self.key):
            self.kind, self.host, self.port, self.key = cfg
            self._prev, self._finished_at = None, None
            self.value = None
            self.refresh()

    @property
    def url(self) -> str:
        return base_url(self.host, self.port or DEFAULT_PORT.get(self.kind, 80))

    def next_interval(self) -> float:
        st = (self.value or {}).get("state")
        return self.interval if st in ACTIVE else self.idle_interval

    def _headers(self) -> dict[str, str]:
        return (
            {"X-Api-Key": self.key, "Accept": "application/json"}
            if self.key
            else {"Accept": "application/json"}
        )

    async def _octoprint(self) -> dict[str, Any]:
        http = self.hub.http
        r = await http.get(f"{self.url}/api/job", headers=self._headers())
        if r.status_code in (401, 403):
            return {"state": "auth", "kind": "octoprint"}
        r.raise_for_status()
        job = r.json()
        pr = await http.get(f"{self.url}/api/printer", params={"exclude": "sd"}, headers=self._headers())
        printer = pr.json() if pr.status_code == 200 else None  # 409: printer not connected
        out = parse_octoprint(job, printer)
        if pr.status_code == 409 and out["state"] == "idle":
            out["state"] = "offline"
        return out

    async def _moonraker(self) -> dict[str, Any]:
        r = await self.hub.http.get(
            f"{self.url}/printer/objects/query?print_stats&display_status&extruder&heater_bed&virtual_sdcard",
            headers=self._headers(),
        )
        if r.status_code in (401, 403):
            return {"state": "auth", "kind": "moonraker"}
        if r.status_code == 503:  # Klippy not ready / MCU shutdown
            return {"state": "error", "kind": "moonraker", "message": "KLIPPER NOT READY"}
        r.raise_for_status()
        return parse_moonraker(r.json())

    def _transition(self, out: dict[str, Any]) -> None:
        state = out.get("state")
        prev, self._prev = self._prev, state
        if out.get("file"):
            self._last_file = out["file"]
        if prev in ACTIVE and state in ("done", "failed", "error", "idle"):
            ok = state == "done"
            self._finished_at = time.time()
            if state == "idle":  # OctoPrint cancel: back to Operational without reaching 100 %
                out["state"] = state = "failed"
            self._result = "done" if ok else "failed"
            self._emit(self._result, file=panel_text(self._last_file, 60))
        if state in ACTIVE:
            self._finished_at, self._result = None, None

    async def fetch(self) -> dict[str, Any]:
        if not self.host:
            return {"state": "unset", "kind": self.kind}
        try:
            out = await (self._moonraker() if self.kind == "moonraker" else self._octoprint())
        except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as e:
            # switched off / unreachable is ordinary: a value, not an error (keeps the log quiet)
            out = {"state": "offline", "kind": self.kind, "message": safe_error(e, self.key, limit=80)}
        if out.get("state") not in ("offline", "auth", "unset"):
            self._transition(out)
        out["finished_at"] = self._finished_at
        out["result"] = self._result
        if out.get("state") in ("done", "failed") and not out.get("file"):
            out["file"] = self._last_file
        return out
