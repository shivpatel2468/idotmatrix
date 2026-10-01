"""CI radiator — GitHub Actions status for your repos, and a "should I deploy?" verdict.

Layouts: ``tiles`` (a red/green/amber tile per repo), ``big`` (one repo per screen: hero badge, workflow,
age), ``verdict`` (SHIP? YES / NO / WAIT / FRI) and ``list`` (rows with the last five runs as a strip).
Data: the ``ci`` provider (public REST API, keyless at 60 req/h; the poll rate is budgeted to stay under).
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale
from ..gfx.color import RGB
from ..providers.ci import parse_repos
from ._kit import loading
from ._radiator import (
    STATE_COLORS,
    WHITE,
    Alerts,
    badge,
    dot,
    fit_chars,
    fmt_age,
    offline_screen,
    page_dots,
    provider,
    pulse,
    setup_screen,
    stale_mark,
)

ACCENT = PALETTE["sky"]
SPEED = 8.0  # marquee px/s: 1 px per streamed frame at fps 8


class CISettings(AppSettings):
    repos: str = Field(
        "python/cpython",
        max_length=400,
        title="Repositories",
        description="owner/repo, comma-separated (up to 16). GitHub URLs work too.",
        json_schema_extra={"group": "Repositories"},
    )
    token: str = Field(
        "",
        max_length=200,
        title="GitHub token (optional)",
        description="Raises the limit from 60 to 5000 requests/h and allows private repos. Never logged.",
        json_schema_extra={"group": "Repositories", "format": "password", "writeOnly": True},
    )
    branch: str = Field(
        "",
        max_length=100,
        title="Branch",
        description="Blank = each repo's default branch",
        json_schema_extra={"group": "Repositories"},
    )
    events: str = Choice(
        "push", {"push": "Pushes", "all": "Any event"}, title="Runs to watch", group="Repositories"
    )
    layout: str = Choice(
        "tiles",
        {"tiles": "Tiles", "big": "Big status", "verdict": "Deploy?", "list": "List"},
        title="Layout",
        group="Layout",
    )
    rotate: int = Field(8, ge=3, le=60, title="Seconds per repo", json_schema_extra={"group": "Layout"})
    deploy_rule: str = Choice(
        "friday",
        {"always": "Any time", "friday": "Not Friday afternoon", "weekend": "Not Fri pm or weekend"},
        title="Deploy window",
        group="Deploy verdict",
    )
    friday_hour: int = Field(
        15,
        ge=0,
        le=23,
        title="Friday cut-off (hour)",
        description="No deploys from this hour on Fridays (local time)",
        json_schema_extra={"group": "Deploy verdict"},
    )
    refresh: int = Field(
        120,
        ge=60,
        le=3600,
        title="Refresh (s)",
        description="Minimum; stretched automatically to stay under GitHub's rate limit",
        json_schema_extra={"group": "Alerts"},
    )
    alerts: bool = Field(True, title="Alert when a build breaks", json_schema_extra={"group": "Alerts"})

    @field_validator("repos")
    @classmethod
    def _clean(cls, v: str) -> str:
        return ",".join(parse_repos(v))


def repo_label(repo: str) -> str:
    return repo.split("/")[-1].upper()


def deploy_blocked(rule: str, cutoff: int, now: datetime) -> str | None:
    """Reason the deploy window is closed, or None."""
    wd = now.weekday()  # Mon 0 … Sun 6
    if rule in ("friday", "weekend") and wd == 4 and now.hour >= cutoff:
        return "FRI PM"
    if rule == "weekend" and wd >= 5:
        return "WEEKEND"
    return None


def verdict(repos: dict[str, Any], rule: str, cutoff: int, now: datetime) -> tuple[str, str, str]:
    """(word, state, reason): YES/pass, NO/fail, WAIT/running, NOPE/cancelled (window), ?/none."""
    entries = list(repos.values())
    known = [e for e in entries if e.get("settled", "none") != "none" or e.get("state", "none") != "none"]
    if not known:
        return "?", "none", "NO RUNS"
    red = [e for e in known if e.get("state") == "fail" or e.get("settled") == "fail"]
    if red:
        return "NO", "fail", f"{repo_label(red[0]['repo'])} RED" if len(red) == 1 else f"{len(red)} RED"
    blind = [e for e in entries if e.get("error") and not e.get("last")]
    if blind:  # can't vouch for a repo we couldn't read
        return "?", "none", "NO DATA"
    running = [e for e in known if e.get("state") == "running"]
    if running:
        return "WAIT", "running", "RUNNING" if len(running) == 1 else f"{len(running)} RUN"
    if any(e.get("settled") != "pass" for e in known):
        return "?", "cancelled", "CANCELED"
    blocked = deploy_blocked(rule, cutoff, now)
    if blocked:
        return "NOPE", "cancelled", blocked
    return "YES", "pass", "ALL GREEN"


@register
class CI(App):
    id = "ci"
    name = "CI Radiator"
    description = "GitHub Actions status tiles for your repos, and a should-I-deploy verdict."
    icon = "git-branch"
    category = "productivity"
    Settings = CISettings
    fps = 8.0  # marquees move 1 px per frame; static screens are deduped, so rest costs nothing
    uses = ("ci",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._alerts = Alerts(ctx, provider(ctx, "ci"))
        self._shown = ""
        self.on_settings()

    @property
    def repos(self) -> list[str]:
        return [r for r in self.settings.repos.split(",") if r]

    def on_start(self) -> None:
        p = provider(self.ctx, "ci")
        if p is not None and hasattr(p, "configure"):
            s = self.settings
            p.configure(self.repos, token=s.token, branch=s.branch, event=s.events, floor=s.refresh)

    def on_settings(self) -> None:
        self.on_start()

    # ------------------------------------------------------------ data
    def _data(self) -> tuple[Any, dict[str, Any]]:
        p = provider(self.ctx, "ci")
        v = (p.value if p is not None else None) or {}
        repos = v.get("repos") or {}
        return p, {r: repos[r] for r in self.repos if r in repos}

    def _check_events(self, p: Any) -> None:
        for ev in self._alerts.drain(p):
            if not self.settings.alerts:
                continue
            broke = ev["kind"] == "broke"
            self.ctx.notify(
                title=repo_label(ev["repo"])[:40],
                message=f"{'BUILD BROKE' if broke else 'FIXED'} {str(ev.get('workflow') or '').upper()}"[
                    :280
                ],
                icon="error" if broke else "ok",
                color="#ff143c" if broke else "#00ff78",
                style="full" if broke else "banner",
                duration=10 if broke else 5,
            )

    def watches_focus(self) -> bool:
        return self.settings.alerts

    def wants_focus(self) -> bool:
        self._check_events(provider(self.ctx, "ci"))  # alerts fire even while another app is showing
        return False

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        p, repos = self._data()
        self._check_events(p)
        if not self.repos:
            setup_screen(f, t, "ci", "CI", "ADD REPO", ACCENT)
            return
        if not repos:
            if p is not None and p.error:
                offline_screen(f, "ci", "GITHUB", "LIMIT" if "rate limit" in p.error else "OFFLINE")
            else:
                loading(f, t, "CI", ACCENT)
            return
        {"tiles": self._tiles, "big": self._big, "verdict": self._verdict, "list": self._list}[
            self.settings.layout
        ](f, t, repos)
        if p is not None and (p.error or any(e.get("error") for e in repos.values())):
            stale_mark(f)

    def _color(self, state: str, t: float) -> RGB:
        c = STATE_COLORS.get(state, STATE_COLORS["none"])
        return scale(c, pulse(t, 0.45, 4.0)) if state == "running" else c

    # tiles: header (CI · pass/total) + a tile per repo ------------------------------------------
    def _tiles(self, f: Frame, t: float, repos: dict[str, Any]) -> None:
        entries = [repos[r] for r in self.repos if r in repos]
        n = len(entries)
        green = sum(1 for e in entries if e.get("state") == "pass")
        red = sum(1 for e in entries if e.get("state") == "fail")
        f.text(1, 1, "CI", ACCENT)
        head = f"{green}/{n}"
        f.text_right(
            30, 1, head, PALETTE["bad"] if red else PALETTE["ok"] if green == n else PALETTE["amber"]
        )
        cols = 1 if n == 1 else 2 if n <= 4 else 3 if n <= 9 else 4
        rows = -(-n // cols)
        gap = 2 if cols <= 2 else 1
        x0, y0, w, h = 1, 8, 30, 23
        tw = (w - gap * (cols - 1)) // cols
        th = (h - gap * (rows - 1)) // rows
        for i, e in enumerate(entries):
            cx, cy = i % cols, i // cols
            x, y = x0 + cx * (tw + gap), y0 + cy * (th + gap)
            state = e.get("state", "none")
            c = self._color(state, t + i * 0.3)
            f.rect(x, y, tw, th, scale(c, 0.22) if state != "none" else PALETTE["ink"])
            f.rect(x, y, tw, th, c if state != "none" else PALETTE["dim"], fill=False)
            if tw >= 13 and th >= 9:
                lab = fit_chars(repo_label(e["repo"]), tw - 2)
                f.text(
                    x + (tw - measure(lab)) // 2,
                    y + (th - 5) // 2,
                    lab,
                    WHITE if state != "none" else PALETTE["mute"],
                )
            elif tw >= 5 and th >= 5:
                f.rect(x + 2, y + 2, tw - 4, th - 4, c)

    # big: one repo per screen ------------------------------------------------------------------
    def _current(self, t: float) -> tuple[int, str]:
        names = [r for r in self.repos]
        i = int(t // self.settings.rotate) % len(names)
        self._shown = names[i]
        return i, names[i]

    def _big(self, f: Frame, t: float, repos: dict[str, Any]) -> None:
        i, repo = self._current(t)
        e = repos.get(repo) or {"repo": repo, "state": "none"}
        last = e.get("last") or {}
        state = e.get("state", "none")
        c = STATE_COLORS.get(state, STATE_COLORS["none"])
        age = fmt_age(time.time() - last["updated"]) if last.get("updated") else ""
        aw = measure(age) + 2 if age else 0
        tr = t % self.settings.rotate
        draw_marquee(f, repo_label(repo), tr, 1, 1, 30 - aw, PALETTE["mute"], speed=SPEED)
        if age:
            f.text_right(30, 1, age, PALETTE["dim"])
        badge(f, 15, 15, 7, state, t)
        wf = str(last.get("name") or ("NO RUNS" if state == "none" else "")).upper()
        draw_marquee(f, wf, tr, 1, 25, 30, scale(c, 0.9) if state != "none" else PALETTE["dim"], speed=SPEED)
        page_dots(f, len(self.repos), i)

    # verdict: should I deploy? --------------------------------------------------------------------
    def _verdict(self, f: Frame, t: float, repos: dict[str, Any]) -> None:
        s = self.settings
        word, state, reason = verdict(repos, s.deploy_rule, s.friday_hour, datetime.now())
        c = STATE_COLORS.get(state, STATE_COLORS["none"]) if state != "cancelled" else PALETTE["amber"]
        if state == "running":
            c = scale(c, pulse(t, 0.55, 4.0))
        f.text_center(1, "DEPLOY?", PALETTE["mute"])
        # the hero: an outlined pill holding the answer (reads from across the room)
        if state == "none":
            f.rect(3, 9, 26, 13, PALETTE["shade"], fill=False)
            f.text_center(12, word, PALETTE["dim"], font="small")
        else:
            f.rect(3, 9, 26, 13, scale(c, 0.2))
            f.hline(4, 9, 24, c)
            f.hline(4, 21, 24, c)
            f.vline(3, 10, 11, c)
            f.vline(28, 10, 11, c)
            f.text_center(12, word, mix(c, WHITE, 0.25), font="small")
        draw_marquee(f, reason, t, 1, 25, 30, PALETTE["mute"], speed=SPEED)

    # list: rows with a five-run history strip ---------------------------------------------------
    def _list(self, f: Frame, t: float, repos: dict[str, Any]) -> None:
        names = self.repos
        pages = -(-len(names) // 4)
        pg = int(t // self.settings.rotate) % pages
        for row, repo in enumerate(names[pg * 4 : pg * 4 + 4]):
            y = 1 + row * 8
            e = repos.get(repo) or {"repo": repo, "state": "none", "runs": []}
            state = e.get("state", "none")
            dot(f, 1, y + 1, self._color(state, t))
            f.text(6, y, fit_chars(repo_label(repo), 25), WHITE if state == "fail" else PALETTE["mute"])
            runs = list(reversed(e.get("runs") or []))[-5:]  # oldest → newest, left → right
            for k, r in enumerate(runs):
                rc = STATE_COLORS.get(r.get("state", "none"), STATE_COLORS["none"])
                f.hline(6 + k * 5, y + 6, 4, scale(rc, 0.8))
        if pages > 1:
            f.set(0, 31 - (pages - 1 - pg), PALETTE["dim"])

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        p, repos = self._data()
        s = self.settings
        word, _state, reason = verdict(repos, s.deploy_rule, s.friday_hour, datetime.now())
        rate = ((p.value or {}).get("rate") if p is not None else None) or {}
        return {
            "repos": {r: (repos.get(r) or {}).get("state", "none") for r in self.repos},
            "deploy": word,
            "reason": reason,
            "token": "set" if s.token else "",
            "rate_remaining": rate.get("remaining"),
            "poll_s": round(p.budget_interval()) if p is not None and hasattr(p, "budget_interval") else None,
        }
