"""DeskDot MCP server — lets Claude (or any MCP client) see and drive the panel live.

It is a thin client over the running engine's HTTP API, because only one
process can own the Bluetooth link. Start the engine first (`deskdot serve`),
then register this server (see .mcp.json / docs/MCP.md):

    uv run deskdot-mcp            # stdio transport
    DESKDOT_URL=http://host:8765  # if the engine runs elsewhere
"""

from __future__ import annotations

import os
from typing import Any, Literal

import httpx

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import Image
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]
    from mcp.server.fastmcp import Image  # type: ignore[no-redef]

BASE = os.environ.get("DESKDOT_URL") or os.environ.get("DOTDECK_URL", "http://127.0.0.1:8765").rstrip("/")

mcp = _Server(
    "deskdot",
    instructions=(
        "Controls a physical 32x32 RGB LED matrix (iDotMatrix) through the DeskDot engine. "
        "Call `panel_snapshot` to SEE what is on the panel right now. "
        "Coordinates are 0..31, origin top-left. Text is upper-case bitmap type: 'tiny' 5 px tall "
        "(~8 chars per row), 'small' 7 px (~5 chars). Saturated colours read best on LEDs; avoid mid-greys. "
        "Read the resource deskdot://design-guide before composing pixel art."
    ),
)

_client = httpx.Client(base_url=BASE, timeout=10.0)


def _call(method: str, path: str, **kw: Any) -> Any:
    try:
        r = _client.request(method, path, **kw)
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"DeskDot engine not reachable at {BASE}. Start it with `uv run deskdot serve`."
        ) from e
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    ct = r.headers.get("content-type", "")
    return r.json() if "json" in ct else r.content


# ------------------------------------------------------------------ observe
@mcp.tool()
def panel_snapshot(scale: int = 12) -> Image:
    """Return a PNG of exactly what the 32x32 panel is showing right now (upscaled for viewing)."""
    return Image(data=_call("GET", "/api/frame.png", params={"scale": max(1, min(32, scale))}), format="png")


@mcp.tool()
def panel_status() -> dict[str, Any]:
    """Connection state, active app and its status, playlist, brightness and data-provider health."""
    s = _call("GET", "/api/state")
    eng = s["engine"]
    return {
        "device": {
            k: s["device"][k] for k in ("status", "name", "address", "mode", "last_error", "link_fps")
        },
        "current": eng["current"],
        "mode": eng["mode"],
        "playlist": {
            "enabled": eng["playlist"]["enabled"],
            "items": [i["app"] for i in eng["playlist"]["items"]],
        },
        "overlay": eng["overlay"],
        "on_air": eng.get("onair"),
        "indicators": eng.get("indicators"),
        "custom_apps": eng.get("custom"),
        "settings": {k: v for k, v in s["settings"].items() if k != "integrations"},
    }


@mcp.tool()
def list_apps() -> list[dict[str, Any]]:
    """Every app the panel can run, with its settings (name, type, allowed values, default)."""
    out = []
    for a in _call("GET", "/api/meta")["apps"]:
        props = a["schema"].get("properties", {})
        out.append(
            {
                "id": a["id"],
                "name": a["name"],
                "description": a["description"],
                "settings": {
                    k: {
                        kk: v[kk]
                        for kk in ("type", "default", "enum", "minimum", "maximum", "title")
                        if kk in v
                    }
                    for k, v in props.items()
                },
                "actions": [x["id"] for x in a["actions"]],
            }
        )
    return out


# ------------------------------------------------------------------ control
@mcp.tool()
def show_app(
    app: str, settings: dict[str, Any] | None = None, revert_after_seconds: float | None = None
) -> str:
    """Switch the panel to an app (e.g. 'clock', 'weather', 'nowplaying', 'ambient'), optionally with settings.

    With revert_after_seconds, the previous content returns afterwards.
    """
    _call(
        "POST", f"/api/apps/{app}/activate", json={"settings": settings, "revert_after": revert_after_seconds}
    )
    return f"showing {app}"


@mcp.tool()
def update_app_settings(app: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Change an app's saved settings without switching to it. Returns the full validated settings."""
    return _call("PATCH", f"/api/apps/{app}/settings", json=settings)


@mcp.tool()
def app_action(app: str, action: str, payload: dict[str, Any] | None = None) -> Any:
    """Trigger an app action, e.g. timer toggle/reset/skip, nowplaying next/prev/toggle, canvas clear."""
    return _call("POST", f"/api/apps/{app}/actions/{action}", json=payload or {})


@mcp.tool()
def show_text(
    text: str,
    color: str = "#ffffff",
    effect: Literal["solid", "rainbow", "gradient"] = "solid",
    revert_after_seconds: float | None = None,
) -> str:
    """Show a message. Short text is auto-fitted; long text scrolls smoothly."""
    _call(
        "POST",
        "/api/text",
        json={"text": text, "color": color, "effect": effect, "revert_after": revert_after_seconds},
    )
    return "ok"


@mcp.tool()
def draw_pixel_art(
    rows: list[str], palette: dict[str, str], revert_after_seconds: float | None = None
) -> Image:
    """Draw pixel art: up to 32 strings of up to 32 characters. '.' is black/off; every other
    character must map to a '#rrggbb' colour in `palette`. Returns a snapshot so you can check it.

    Example: rows=["..##..", ".#..#."], palette={"#": "#ff4818"}
    """
    _call(
        "POST", "/api/pixels", json={"rows": rows, "palette": palette, "revert_after": revert_after_seconds}
    )
    return panel_snapshot()


@mcp.tool()
def set_pixels(pixels: list[tuple[int, int, str]], clear_first: bool = False) -> str:
    """Paint individual pixels [[x, y, '#rrggbb'], ...] on the canvas (keeps the rest of the drawing)."""
    _call("POST", "/api/pixels", json={"pixels": pixels, "clear": clear_first})
    return f"painted {len(pixels)} pixels"


@mcp.tool()
def notify(
    message: str,
    title: str = "",
    color: str = "#00dcff",
    icon: Literal["bell", "info", "warn", "ok", "error", "mail", "chat", "heart", "claude"] | None = "bell",
    duration: float = 6.0,
    style: Literal["banner", "full", "celebrate"] = "banner",
) -> str:
    """Pop a notification over whatever is showing, then return to it."""
    _call(
        "POST",
        "/api/notify",
        json={
            "title": title,
            "message": message,
            "color": color,
            "icon": icon,
            "duration": duration,
            "style": style,
        },
    )
    return "queued"


@mcp.tool()
def agent_state(
    state: Literal["idle", "thinking", "working", "waiting", "done", "error", "sleeping"],
    hold_seconds: float | None = None,
) -> str:
    """Show the Claude mascot in a state, e.g. 'thinking' while you work, 'done' when finished.
    With hold_seconds the previous content comes back afterwards."""
    _call("POST", f"/api/agent/{state}", params={"hold": hold_seconds} if hold_seconds else None)
    return state


@mcp.tool()
def set_display(
    brightness: int | None = None,
    power: bool | None = None,
    flip: bool | None = None,
    transition: Literal["cut", "push", "fade", "wipe"] | None = None,
) -> dict[str, Any]:
    """Panel brightness (5-100), power on/off, 180° flip, and the app-switch transition."""
    body = {
        k: v
        for k, v in {"brightness": brightness, "power": power, "flip": flip, "transition": transition}.items()
        if v is not None
    }
    return _call("PATCH", "/api/settings", json=body)


@mcp.tool()
def playlist(op: Literal["get", "play", "stop", "next", "prev"] = "get") -> dict[str, Any]:
    """Inspect or control the rotating playlist of apps."""
    if op == "get":
        return _call("GET", "/api/playlist")
    return _call("POST", f"/api/playlist/{op}")


@mcp.tool()
def fly_brain(
    config: dict[str, Any] | None = None, preset: str = "", list_presets: bool = False
) -> dict[str, Any] | list[dict[str, Any]]:
    """Tune the fruit-fly brain that can play every game (docs/FLY_BRAIN.md). No arguments: the current config
    (phototaxis, looming, motion, leak, threshold, refractory, noise, escape, lure, preset). preset=<id> loads a
    preset (default, calm, curious, twitchy, hunter, daredevil); config={...} changes some knobs (out-of-range
    values are refused). list_presets=True lists the presets. To let the fly play a game: update_app_settings(game,
    {"pilot": "fly"}) then app_action(game, "fly").
    """
    if list_presets:
        return _call("GET", "/api/fly/presets")
    patch = dict(config or {})
    if preset:
        patch["preset"] = preset
    if patch:
        return _call("PATCH", "/api/fly/config", json=patch)
    return _call("GET", "/api/fly/config")


@mcp.tool()
def presets(
    action: Literal["list", "play", "save", "delete"] = "list",
    preset: str = "",
    shuffle: bool = False,
    name: str = "",
) -> Any:
    """One-tap playlists. action="list" returns every preset: id, name and its apps (e.g. "cat-games" plays every
    game in sequence, "cat-pets" all pets, "dashboard", "chill", "everything"). action="play" with preset=<id>
    starts it (shuffle=True to shuffle). action="save" with name=<name> saves the current playlist as a preset;
    action="delete" removes one of the user's own presets.
    """
    if action == "list":
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "builtin": p["builtin"],
                "apps": [i["app"] for i in p["items"]],
            }
            for p in _call("GET", "/api/presets")
        ]
    if action == "play":
        return _call("POST", f"/api/presets/{preset}/play", json={"shuffle": shuffle})
    if action == "save":
        return _call("POST", "/api/presets", json={"name": name})
    return _call("DELETE", f"/api/presets/{preset}")


@mcp.tool()
def set_playlist(items: list[dict[str, Any]], enabled: bool = True) -> dict[str, Any]:
    """Replace the playlist. items: [{"app": "clock", "duration": 20, "settings": {...}}, ...]."""
    return _call("PUT", "/api/playlist", json={"enabled": enabled, "items": items})


@mcp.tool()
def show_image(path: str) -> Image:
    """Upload a local image or GIF and show it (photos are LED-calibrated, pixel art stays crisp)."""
    with open(path, "rb") as fh:
        _call(
            "POST", "/api/media", files={"file": (os.path.basename(path), fh.read())}, params={"show": True}
        )
    return panel_snapshot()


@mcp.tool()
def compose(layers: list[dict[str, Any]], background: str = "none") -> Image:
    """Lay out the panel yourself with Text Studio layers, then see the result.

    Each layer: {"kind": "text"|"time"|"seconds"|"date"|"month"|"day"|"weather"|"cpu"|"ram"|"price",
    "text": "HELLO" (for price: a symbol like "BTC"; for cpu/ram: a label prefix), "x": 0-31, "y": 0-31,
    "font": "tiny"(5px)|"small"(7px)|"big"(10px digits), "color": "#rrggbb",
    "effect": "solid"|"rainbow"|"gradient"|"pulse"|"blink"|"glow"|"scroll", "align": "left"|"center"|"right"}.
    background: none | solid | gradient | border | stars.
    """
    _call(
        "POST", "/api/apps/composer/activate", json={"settings": {"layers": layers, "background": background}}
    )
    return panel_snapshot()


@mcp.tool()
def autopilot(enabled: bool | None = None, rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Make the panel follow the foreground app. Rules: [{"match": "spotify", "app": "nowplaying"},
    {"match": "title:youtube", "app": "mirror"}]. Call with no arguments to read the current rules."""
    cur = _call("GET", "/api/autopilot")
    if enabled is None and rules is None:
        return cur
    return _call(
        "PUT",
        "/api/autopilot",
        json={
            "enabled": cur["enabled"] if enabled is None else enabled,
            "rules": cur["rules"] if rules is None else rules,
        },
    )


@mcp.tool()
def set_indicator(
    slot: Literal[1, 2, 3],
    color: str = "#ff143c",
    blink_ms: int = 0,
    fade_ms: int = 0,
    lifetime_s: float = 0,
    size: Literal[2, 3] = 2,
    clear: bool = False,
) -> dict[str, Any]:
    """Light a small status square on the panel's right edge, drawn on top of every app (AWTRIX-style).

    slot 1 = top-right, 2 = right-middle, 3 = bottom-right. color '#rrggbb' (e.g. '#00ff78' build green,
    '#ffaa00' pending, '#ff143c' failing). blink_ms / fade_ms: period in ms (0 = steady). lifetime_s: clears
    itself after that many seconds (0 = stays until cleared). clear=True turns the slot off.
    Example: set_indicator(1, "#00ff78", lifetime_s=600) after tests pass.
    """
    if clear:
        return _call("DELETE", f"/api/indicators/{slot}")
    return _call(
        "POST",
        f"/api/indicators/{slot}",
        json={"color": color, "blink": blink_ms, "fade": fade_ms, "lifetime_s": lifetime_s, "size": size},
    )


@mcp.tool()
def push_custom_app(
    name: str,
    text: str = "",
    icon: str | None = None,
    color: str | None = None,
    progress: int = -1,
    duration: float = 10,
    lifetime: float = 0,
    rainbow: bool = False,
    rows: list[str] | None = None,
    palette: dict[str, str] | None = None,
    remove: bool = False,
) -> dict[str, Any]:
    """Push (or replace) a named "icon + one value" screen that joins the playlist rotation (AWTRIX custom app).

    name: 1-32 chars [A-Za-z0-9_-]. text: the value, e.g. "21.5°" or "3 PRs" (long text scrolls).
    icon: a DeskDot icon name (bell info warn ok error mail chat heart home bolt drop temp sun cloud bulb
    battery door lock person fire star music clock eye mic cam claude) or pixel art via rows + palette
    (up to 16x16; 8x8 art is drawn 2x). progress 0-100 adds a bar. duration: seconds per rotation.
    lifetime: seconds until it is removed automatically (0 = keep). remove=True deletes it.
    It only shows while the playlist is playing; use show_app("custom", {"name": ...}) to pin it.
    """
    if remove:
        return _call("DELETE", f"/api/custom/{name}")
    body: dict[str, Any] = {
        "text": text,
        "progress": progress,
        "duration": duration,
        "lifetime": lifetime,
        "rainbow": rainbow,
    }
    for k, v in (("icon", icon), ("color", color), ("rows", rows), ("palette", palette)):
        if v is not None:
            body[k] = v
    return _call("POST", f"/api/custom/{name}", json=body)


@mcp.resource("deskdot://design-guide")
def design_guide() -> str:
    """How to design for a 32x32 LED panel."""
    return DESIGN_GUIDE


DESIGN_GUIDE = """\
DeskDot 32x32 design guide (for pixel art and layouts)

Grid: 32x32, x/y 0..31, origin top-left. Leave a 1 px margin at the edges for text.
Type: tiny = 5 px tall (3 px wide glyphs, M/W/N wider), small = 7 px (4-5 px wide), big = 10 px digits.
       Rows of tiny text every 6-7 px; small every 9 px. All caps.
Colour: LEDs are additive. Pure, saturated hues look best. Black = off (free contrast).
        Mid-greys look bluish and dim; use at most 2 neutral tones (#8c8ca0 secondary, #46465a tertiary).
        White is the brightest and draws the most power: reserve it for the single most important value.
Palette tokens: ember #ff4818 (brand), amber #ffaa00, gold #ffd600, mint #00ff8c, cyan #00dcff,
        sky #288cff, violet #8c3cff, magenta #ff00be, rose #ff1e5a, ok #00ff78, bad #ff143c.
Composition: one hero element per screen. Big shapes, 2-3 colours, strong silhouette.
        A 1 px dark outline or black gap separates overlapping shapes. Dither sparingly.
Motion: prefer loops (they upload once and play natively).
"""


def main() -> None:
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
