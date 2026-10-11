"""The App SDK. Everything the panel shows is an App.

An App is a small class with a pydantic `Settings` model and a `render()`
method that paints one 32x32 frame. The studio UI builds its settings form
from the model's JSON schema, so a new app needs **zero** frontend code.

Render contract (enforced by review and tests/test_apps.py):
    * `render()` is synchronous, pure and fast (< 2 ms). No I/O, no sleeping.
    * Data comes from providers (`self.ctx.provider("weather").value`), which
      fetch in the background. Handle `None` (not loaded yet) gracefully.
    * Use only `Frame` primitives; they clip, so nothing can overflow the panel.

Output kinds:
    * "stream" — rendered every tick at `fps`; frames are pushed over BLE.
    * "clip"   — a deterministic loop baked once into a GIF that the panel
                 plays natively (perfectly smooth, zero BLE traffic after upload).
                 Implement `clip_frames()` or rely on the default, which samples
                 `render()` over `clip_seconds`.
    * "native" — the panel's own firmware feature (`native_command()`).

Minimal example::

    @register
    class Hello(App):
        id = "hello"
        name = "Hello"
        class Settings(AppSettings):
            color: Color = "#00ffaa"
        def render(self, f, t):
            f.text_center(13, "HELLO", self.settings.color, font="small")
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from ..gfx import Frame, to_rgb
from ..gfx.color import RGB, ColorLike
from ..gfx.themes import DEFAULT_THEME, ROLES, PageTheme

if TYPE_CHECKING:
    from .runtime import AppContext

log = logging.getLogger("deskdot.apps")

Category = Literal[
    "time", "data", "media", "creative", "pets", "games", "casino", "ambient", "productivity", "device"
]
Kind = Literal["stream", "clip", "native"]

# A colour field: the UI renders a colour picker with the LED palette as swatches.
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$", json_schema_extra={"format": "color"})]


def Choice(
    default: str,
    options: list[str] | dict[str, str],
    title: str | None = None,
    group: str | None = None,
    platforms: dict[str, list[str]] | None = None,
    **kw: Any,
) -> Any:
    """A select field. `options` is a list or {value: label}; `group` puts it in a collapsible studio section.

    `platforms` marks options that only work on some hosts, e.g. ``{"window": ["windows", "macos"]}``
    (see `deskdot.platforms`); the studio disables them elsewhere and the app shows its "not here" state.
    """
    opts = options if isinstance(options, dict) else {o: o.replace("_", " ").title() for o in options}
    extra: dict[str, Any] = {"enum": list(opts), "enumLabels": opts}
    if group:
        extra["group"] = group
    if platforms:
        extra["enumPlatforms"] = {k: list(v) for k, v in platforms.items()}
    return Field(default=default, title=title, json_schema_extra=extra, **kw)


class AppSettings(BaseModel):
    """Base for every app's settings. Unknown keys are ignored so old state files keep loading."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    @model_validator(mode="after")
    def _check_choices(self) -> AppSettings:
        """Enforce `Choice(...)` options (they live in json_schema_extra so the UI can render a select)."""
        for name, info in type(self).model_fields.items():
            extra = info.json_schema_extra
            if isinstance(extra, dict) and "enum" in extra:
                allowed = extra["enum"]
                if getattr(self, name) not in allowed:  # type: ignore[operator]
                    raise ValueError(f"{name} must be one of {allowed}")
        return self


@dataclass(frozen=True)
class Action:
    """A button the studio shows for the running app; handled by `App.action()`."""

    id: str
    label: str
    icon: str = "play"


@dataclass
class Clip:
    frames: list[Frame]
    durations_ms: list[int]

    def frame_at(self, t: float) -> Frame:
        total = sum(self.durations_ms) or 1
        ms = int(t * 1000) % total
        for f, d in zip(self.frames, self.durations_ms, strict=True):
            if ms < d:
                return f
            ms -= d
        return self.frames[-1]


@dataclass
class AppMeta:
    id: str
    name: str
    description: str
    icon: str
    category: Category
    actions: list[Action] = field(default_factory=list)
    settings_schema: dict[str, Any] = field(default_factory=dict)
    platforms: list[str] | None = None  # hosts the app works on (None = everywhere)


class App:
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    icon: ClassVar[str] = "square"  # lucide.dev icon name, used by the studio
    category: ClassVar[Category] = "productivity"
    Settings: ClassVar[type[AppSettings]] = AppSettings
    fps: ClassVar[float] = 1.0
    uses: ClassVar[tuple[str, ...]] = ()  # provider names acquired while running
    actions: ClassVar[tuple[Action, ...]] = ()
    clip_seconds: ClassVar[float] = 4.0
    clip_fps: ClassVar[float] = 12.0
    clip_colors: ClassVar[int] = 256  # palette cap for the baked GIF (smaller = faster upload/decode)
    hidden: ClassVar[bool] = False  # not shown in the library (e.g. internal apps)
    #: hosts the app can work on, e.g. ("windows", "macos") — empty = everywhere (see deskdot.platforms).
    #: Elsewhere the studio greys it out, the playlist skips it and render() should show `_kit.unsupported()`.
    platforms: ClassVar[tuple[str, ...]] = ()
    #: why the app can't work in a browser tab (required when `platforms` leaves out "web"); the web app's studio
    #: shows it in the "not here" banner and the library tooltip (docs/WEB_APP.md)
    web_reason: ClassVar[str] = ""
    #: library / website previews: settings patched in for the preview only (e.g. a self-playing demo view)
    preview_patch: ClassVar[dict[str, Any]] = {}
    #: library / website previews: (first render time s, seconds to show, frames per second); None = the default
    preview_span: ClassVar[tuple[float, float, float] | None] = None
    #: page theme (docs/APP_SDK.md § Page theme): {colour setting: role}. While a setting is at its default, it takes
    #: the page theme's LED colour for that role (roles: gfx.themes.ROLES). A changed colour is the person's: kept.
    theme_colors: ClassVar[dict[str, str]] = {}
    #: True: the app's own code also asks for themed colours (`self.themed(role, own)`). Apps with `theme_colors` follow
    #: automatically. Leave both empty where the app's colours carry meaning (photos, flags, weather icons, game genres).
    follows_theme: ClassVar[bool] = False

    def __init__(self, ctx: AppContext, settings: AppSettings) -> None:
        self.ctx = ctx
        self.settings: Any = settings

    # ---------------------------------------------------------- lifecycle
    def on_start(self) -> None:
        """Called when the app becomes visible."""

    def on_stop(self) -> None:
        """Called when the app is hidden."""

    def on_settings(self) -> None:
        """Called after `self.settings` was replaced."""

    # -------------------------------------------------------------- output
    def kind(self) -> Kind:
        return "stream"

    def render(self, f: Frame, t: float) -> None:
        """Paint the frame. `t` is seconds since the app started. Keep it fast and pure."""

    def clip_frames(self) -> Clip:
        n = max(1, round(self.clip_seconds * self.clip_fps))
        dt = 1.0 / self.clip_fps
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i * dt)
            frames.append(f)
        return Clip(frames, [round(1000 * dt)] * n)

    def clip_key(self) -> str:
        """Identity of the baked clip; when it changes the clip is re-baked and re-uploaded."""
        key = json.dumps(self.settings.model_dump(mode="json"), sort_keys=True)
        th = self.theme
        return f"{key}|theme={th.id}" if th else key  # a new page theme re-bakes clips that follow it

    # ------------------------------------------------------------- page theme
    @classmethod
    def theme_aware(cls) -> bool:
        """Whether this app follows the page theme at all (it declares `theme_colors` or `follows_theme`)."""
        return bool(cls.theme_colors) or cls.follows_theme

    @property
    def theme(self) -> PageTheme | None:
        """The page theme this app is drawing with, or None: the app doesn't follow themes, the person turned
        "Follow page theme" off for it, or the theme is the default (DeskDot = every app's own colours)."""
        if not type(self).theme_aware() or not getattr(self.settings, "follow_theme", True):
            return None
        th: PageTheme | None = getattr(self.ctx, "page_theme", None)
        return th if th is not None and th.id != DEFAULT_THEME else None

    def themed(self, role: str, own: ColorLike) -> RGB:
        """The page theme's LED colour for `role` (gfx.themes.ROLES) — or `own`, the app's own colour, when the app
        isn't following a theme right now. Use it for colours that are chrome (accents, rings, labels), never for
        colours that mean something (up / down, a team, a flag, a photo)."""
        th = self.theme
        return th.panel.role(role) if th else to_rgb(own)

    #: minimum seconds between re-bakes that only advance `clip_chunk()` (identity unchanged)
    clip_refresh: ClassVar[float] = 0.0

    def clip_chunk(self) -> str:
        """Which time-slice of a long-running clip this is (e.g. the next 24 s of Pet World). A change re-bakes,
        but no more often than `clip_refresh` seconds; settings changes (`clip_key`) always re-bake at once."""
        return ""

    def native_command(self) -> bytes | list[bytes]:
        raise NotImplementedError

    # ----------------------------------------------------------- scheduling
    def relevant(self) -> bool:
        """False lets the playlist skip this app (e.g. no live games right now, or not on this OS)."""
        return self.supported_here()

    @classmethod
    def supported_here(cls) -> bool:
        """Whether this app can work on the host the engine runs on (`platforms`)."""
        from ..platforms import current

        return not cls.platforms or current() in cls.platforms

    def wants_focus(self) -> bool:
        """True asks the playlist to show this app now (e.g. music started)."""
        return False

    def watches_focus(self) -> bool:
        """True keeps the app's providers alive while in the playlist so wants_focus() can fire."""
        return False

    def fly_telemetry(self, t: float) -> dict[str, Any] | None:
        """The fruit-fly brain's activity when a fly is playing this app (docs/FLY_BRAIN.md), else None.
        Shown in the studio only, never on the panel."""
        return None

    def status(self) -> dict[str, Any]:
        """Small JSON blob shown by the studio next to the live preview."""
        return {}

    def private_status(self, seat: int) -> dict[str, Any] | None:
        """What only the phone in lobby `seat` may see (its credits, bets, hole cards), or None.

        The phone controller socket merges it into its `state` message as `private`; it never reaches the
        studio, the other phones or `status()` (docs/CASINO.md §4)."""
        return None

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        raise KeyError(f"{self.id} has no action {name!r}")

    # ---------------------------------------------------------------- meta
    @classmethod
    def meta(cls) -> AppMeta:
        schema = cls.Settings.model_json_schema()
        if cls.platforms:
            schema["platforms"] = list(cls.platforms)  # the studio's schema form shows a "not here" banner
            if cls.web_reason:
                schema["webReason"] = cls.web_reason
        return AppMeta(
            id=cls.id,
            name=cls.name,
            description=cls.description,
            icon=cls.icon,
            category=cls.category,
            actions=list(cls.actions),
            settings_schema=schema,
            platforms=list(cls.platforms) or None,
        )


def themed_settings(cls: type[App], settings: AppSettings, theme: PageTheme | None) -> AppSettings:
    """`settings` with every `theme_colors` field that is still at its default replaced by the page theme's LED
    colour for its role. The stored settings never change (the studio shows and edits the person's values); only the
    instance the app draws with does. The default theme, an app that isn't theme-aware, or "Follow page theme" off:
    `settings` unchanged."""
    if theme is None or theme.id == DEFAULT_THEME or not cls.theme_colors:
        return settings
    if not getattr(settings, "follow_theme", True):
        return settings
    fields = type(settings).model_fields
    patch: dict[str, str] = {}
    for name, role in cls.theme_colors.items():
        info = fields.get(name)
        cur = getattr(settings, name, None)
        if info is None or not isinstance(cur, str) or not isinstance(info.default, str):
            continue
        if cur.lower() == info.default.lower():
            r, g, b = theme.panel.role(role)
            patch[name] = f"#{r:02x}{g:02x}{b:02x}"
    return settings.model_copy(update=patch) if patch else settings


REGISTRY: dict[str, type[App]] = {}


def _with_follow_theme(cls: type[App]) -> None:
    """Give a theme-aware app the "Follow page theme" switch (its per-app opt-out), next to its colours."""
    fields = cls.Settings.model_fields
    if "follow_theme" in fields:
        return
    for name, role in cls.theme_colors.items():
        if name not in fields or role not in ROLES:
            raise TypeError(
                f"{cls.__name__}.theme_colors: {name!r} → {role!r} (a colour setting → one of {ROLES})"
            )
    groups = [
        e.get("group")
        for f in fields.values()
        if isinstance(e := f.json_schema_extra, dict) and e.get("group")
    ]
    colour_groups = [
        e.get("group")
        for n in cls.theme_colors
        if isinstance(e := fields[n].json_schema_extra, dict) and e.get("group")
    ]
    group = (
        colour_groups[0] if colour_groups else ("Look" if "Look" in groups else "Colours" if groups else None)
    )
    extra: dict[str, Any] = {"group": group} if group else {}
    cls.Settings = create_model(  # type: ignore[call-overload]
        cls.Settings.__name__,
        __base__=cls.Settings,
        follow_theme=(
            bool,
            Field(
                True,
                title="Follow page theme",
                description="Use the page theme's colours (Settings → Display & colour) for the colours you "
                "haven't changed. Off = this app's own colours.",
                json_schema_extra=extra or None,
            ),
        ),
    )


def register(cls: type[App]) -> type[App]:
    if not getattr(cls, "id", None) or not getattr(cls, "name", None):
        raise TypeError(f"{cls.__name__} needs `id` and `name`")
    if cls.theme_aware():
        _with_follow_theme(cls)
    if cls.id in REGISTRY and REGISTRY[cls.id] is not cls:
        log.warning("app id %r registered twice; %s replaces %s", cls.id, cls, REGISTRY[cls.id])
    REGISTRY[cls.id] = cls
    return cls


def app_factory(app_id: str) -> Callable[..., App]:
    return REGISTRY[app_id]
