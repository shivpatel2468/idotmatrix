"""Settings for the platform integrations: On Air, Eye break, ntfy and Home Assistant.

Each section is a pydantic model persisted in the store under its own key. Secrets (the Home Assistant
long-lived token, the ntfy access token) are write-only through the API: responses and snapshots carry a
mask (`••••` + last 4) and a `token_set` flag. A PATCH that sends the mask back (or omits the token) keeps
the stored token; an empty string clears it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..providers.homeassistant import mask


class _Section(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OnAirConfig(_Section):
    enabled: bool = False
    style: Literal["full", "badge", "glow"] = "full"
    look: Literal["sign", "outline"] = "sign"  # full-screen look
    webcam: bool = True
    microphone: bool = True
    exclude: str = Field("", max_length=300, description="comma-separated app names / path parts to ignore")


class EyeBreakConfig(_Section):
    enabled: bool = False
    interval_min: int = Field(20, ge=5, le=120)
    style: Literal["breathe", "ring"] = "breathe"


class NtfyConfig(_Section):
    enabled: bool = False
    server: str = Field("https://ntfy.sh", max_length=200)
    topics: str = Field("", max_length=300)
    token: str = Field("", max_length=200)
    style: Literal["auto", "banner", "full"] = "auto"
    duration: int = Field(8, ge=2, le=60)
    route_prefix: str = Field("app-", max_length=16)
    lifetime: int = Field(3600, ge=0, le=7 * 86400)

    @field_validator("server")
    @classmethod
    def _server(cls, v: str) -> str:
        v = v.strip().rstrip("/") or "https://ntfy.sh"
        if not v.startswith(("http://", "https://")):
            raise ValueError("server must start with http:// or https://")
        return v


class HomeAssistantConfig(_Section):
    url: str = Field("", max_length=200)
    token: str = Field("", max_length=400)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


SECTIONS: dict[str, type[_Section]] = {
    "onair": OnAirConfig,
    "eyebreak": EyeBreakConfig,
    "ntfy": NtfyConfig,
    "homeassistant": HomeAssistantConfig,
}
SECRET = "token"


def load(store: Any, section: str) -> dict[str, Any]:
    """Stored section merged over defaults; stale keys are dropped (rule 15)."""
    cls = SECTIONS[section]
    raw = store.get(section) or {}
    try:
        return cls.model_validate(raw).model_dump()
    except Exception:
        good = {}
        for k, v in raw.items() if isinstance(raw, dict) else []:
            try:
                cls.model_validate({k: v})
                good[k] = v
            except Exception:
                continue
        return cls.model_validate(good).model_dump()


def public(section: str, data: dict[str, Any]) -> dict[str, Any]:
    """A copy safe to send anywhere: secrets masked."""
    out = dict(data)
    if SECRET in SECTIONS[section].model_fields:
        token = str(out.get(SECRET) or "")
        out[SECRET] = mask(token)
        out["token_set"] = bool(token)
    return out


def merge(store: Any, section: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Validate `patch` over the stored section and persist it. Returns the full (unmasked) section."""
    cur = load(store, section)
    patch = dict(patch)
    patch.pop("token_set", None)
    if SECRET in patch:
        tok = patch[SECRET]
        if tok is None or (isinstance(tok, str) and tok.startswith("••••")):
            patch.pop(SECRET)  # the mask came back unchanged: keep the stored secret
    data = SECTIONS[section].model_validate({**cur, **patch}).model_dump()
    store.set(section, data)
    return data


Section = Literal["onair", "eyebreak", "ntfy", "homeassistant"]
