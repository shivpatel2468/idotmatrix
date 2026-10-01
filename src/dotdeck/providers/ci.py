"""GitHub Actions status for a handful of repositories (public REST API, keyless or with a token).

Requests per poll: one ``GET /repos/{owner}/{repo}/actions/runs?per_page=5&branch=…`` per repo, plus a
``GET /repos/{owner}/{repo}`` every 12 h to learn the default branch (skipped when a branch is set).

Rate budget: GitHub allows 60 requests/hour per IP without a token and 5000 with one. The poll interval is
derived from the number of repos so a full hour of polling stays under ``BUDGET_ANON`` (50/h, a margin for
the branch lookups and for other tools on the same IP). The ``X-RateLimit-Remaining``/``Reset`` headers
are honoured too: when the budget is nearly spent we wait for the reset instead of hammering. ETags are
sent so unchanged responses come back as tiny 304s.

The token is only ever put in the ``Authorization`` header; error strings are redacted (never logged).
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from .base import Provider
from .radiator import EventLog, safe_error

API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
MAX_REPOS = 16
BUDGET_ANON = 50  # requests/hour we allow ourselves without a token (GitHub's limit is 60)
BUDGET_TOKEN = 3000  # with a token (limit 5000)
BRANCH_TTL = 12 * 3600

PASS = {"success", "neutral", "skipped"}
FAIL = {"failure", "timed_out", "startup_failure"}
RUNNING = {"queued", "in_progress", "waiting", "requested", "pending"}


def parse_repos(text: str) -> list[str]:
    """'python/cpython, https://github.com/psf/black' -> ['python/cpython', 'psf/black'] (valid, unique)."""
    out: list[str] = []
    for part in re.split(r"[,\s;]+", text or ""):
        p = re.sub(r"^(https?://)?(www\.)?github\.com/", "", part.strip(), flags=re.I).strip("/")
        p = re.sub(r"\.git$", "", p)
        p = "/".join(p.split("/")[:2])
        if REPO_RE.match(p) and p.lower() not in (o.lower() for o in out):
            out.append(p)
    return out[:MAX_REPOS]


def iso_ts(s: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def run_state(run: dict[str, Any]) -> str:
    """One workflow run -> pass | fail | running | cancelled."""
    status = str(run.get("status") or "")
    if status in RUNNING or (status and status != "completed"):
        return "running"
    c = str(run.get("conclusion") or "")
    if c in PASS:
        return "pass"
    if c in FAIL:
        return "fail"
    return "cancelled"


def combine(states: list[str]) -> str:
    if not states:
        return "none"
    if "fail" in states:
        return "fail"
    if "running" in states:
        return "running"
    if all(s == "pass" for s in states):
        return "pass"
    return "cancelled" if "pass" not in states else "pass"


def _head_state(runs: list[dict[str, Any]]) -> str:
    """Combined state of the newest commit's runs (latest attempt per workflow)."""
    if not runs:
        return "none"
    sha = runs[0].get("head_sha")
    seen: dict[Any, str] = {}
    for r in runs:
        if r.get("head_sha") != sha:
            continue
        key = r.get("workflow_id") or r.get("name")
        seen.setdefault(key, run_state(r))
    return combine(list(seen.values()))


def summarize(repo: str, branch: str, payload: dict[str, Any]) -> dict[str, Any]:
    """``/actions/runs`` JSON -> the repo entry apps draw (newest run first)."""
    runs = [r for r in payload.get("workflow_runs") or [] if isinstance(r, dict)]
    runs.sort(key=lambda r: iso_ts(r.get("created_at")) or 0, reverse=True)
    completed = [r for r in runs if run_state(r) != "running"]
    last = runs[0] if runs else None
    entry: dict[str, Any] = {
        "repo": repo,
        "branch": branch,
        "state": _head_state(runs),  # newest commit, may be running
        "settled": _head_state(completed),  # newest commit whose runs finished
        "runs": [
            {"name": str(r.get("name") or "?"), "state": run_state(r), "created": iso_ts(r.get("created_at"))}
            for r in runs[:5]
        ],
        "last": None,
    }
    if last:
        entry["last"] = {
            "name": str(last.get("name") or "?"),
            "title": str(last.get("display_title") or ""),
            "state": run_state(last),
            "conclusion": last.get("conclusion"),
            "created": iso_ts(last.get("created_at")),
            "updated": iso_ts(last.get("updated_at")),
            "sha": str(last.get("head_sha") or "")[:7],
            "run_number": last.get("run_number"),
            "event": last.get("event"),
            "url": last.get("html_url"),
        }
    return entry


class CIProvider(EventLog, Provider[dict[str, Any]]):
    """``value = {"repos": {repo: entry}, "rate": {...}}``. Apps call ``configure(repos, token=…)``.

    Events: ``broke`` / ``fixed`` (``{"repo", "workflow"}``) when a repo's settled state crosses fail.
    """

    name = "ci"
    interval = 120.0
    retry = 120.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._init_events()
        self.repos: list[str] = []
        self.token = ""
        self.branch = ""
        self.event = "push"
        self.floor = 120.0
        self._default_branch: dict[str, tuple[str, float]] = {}
        self._etag: dict[str, tuple[str, dict[str, Any]]] = {}
        self._settled: dict[str, str] = {}  # armed repos -> last settled state
        self._rate: dict[str, Any] = {}
        self.requests: list[float] = []  # timestamps of requests in the last hour (for tests/status)
        self._hold_until = 0.0  # secondary rate limit / Retry-After: no requests before this

    # ------------------------------------------------------------ interface
    def configure(
        self, repos: list[str], token: str = "", branch: str = "", event: str = "push", floor: float = 120.0
    ) -> None:
        repos = repos[:MAX_REPOS]
        changed = (repos, token, branch.strip(), event) != (self.repos, self.token, self.branch, self.event)
        self.repos, self.token, self.branch, self.event = repos, token, branch.strip(), event
        self.floor = max(60.0, float(floor))
        if changed:
            self._etag.clear()
            self.refresh()

    def budget_interval(self) -> float:
        """Seconds between polls so one hour of polling stays within the budget."""
        per_hour = BUDGET_TOKEN if self.token else BUDGET_ANON
        n = max(1, len(self.repos))
        return max(self.floor, 3600.0 * n / per_hour)

    def next_interval(self) -> float:
        wait = self.budget_interval()
        rem, reset = self._rate.get("remaining"), self._rate.get("reset")
        if rem is not None and reset and rem <= len(self.repos) + 1:
            wait = max(wait, reset - time.time() + 5)
        wait = max(wait, self._hold_until - time.time() + 1)
        return min(wait, 3700.0)

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        def key(d: dict[str, Any] | None) -> Any:
            return {
                k: (v.get("state"), (v.get("last") or {}).get("updated"))
                for k, v in (d or {}).get("repos", {}).items()
            }

        return key(old) != key(new)

    # ------------------------------------------------------------ fetching
    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        key = path + repr(sorted((params or {}).items()))
        headers = self._headers()
        cached = self._etag.get(key)
        if cached:
            headers["If-None-Match"] = cached[0]
        now = time.time()
        self.requests = [t for t in self.requests if now - t < 3600] + [now]
        r = await self.hub.http.get(API + path, params=params, headers=headers)
        rem, reset = r.headers.get("x-ratelimit-remaining"), r.headers.get("x-ratelimit-reset")
        if rem is not None and rem.isdigit():
            self._rate = {
                "limit": int(r.headers.get("x-ratelimit-limit", "0") or 0),
                "remaining": int(rem),
                "reset": float(reset) if reset and reset.isdigit() else None,
            }
        if r.status_code == 304 and cached:
            return 200, cached[1]
        if r.status_code in (403, 429) and (
            self._rate.get("remaining") == 0 or "rate limit" in r.text.lower() or r.headers.get("retry-after")
        ):
            # primary limit spent, or GitHub's secondary (burst) limit: stop until it says we may retry
            ra = r.headers.get("retry-after", "")
            wait = float(ra) if ra.isdigit() else 60.0
            if self._rate.get("remaining") == 0 and self._rate.get("reset"):
                wait = max(wait, float(self._rate["reset"]) - time.time())
            self._hold_until = time.time() + max(wait, 30.0)
            raise RuntimeError("GitHub rate limit reached; add a token or wait")
        if r.status_code == 401:
            raise RuntimeError("GitHub rejected the token")
        if r.status_code == 404:
            return 404, {}
        r.raise_for_status()
        data = r.json()
        if etag := r.headers.get("etag"):
            self._etag[key] = (etag, data)
        return 200, data

    async def _branch_for(self, repo: str) -> str:
        if self.branch:
            return self.branch
        hit = self._default_branch.get(repo)
        if hit and time.time() - hit[1] < BRANCH_TTL:
            return hit[0]
        code, data = await self._get(f"/repos/{repo}")
        if code == 404:
            raise LookupError("repo not found (or private without a token)")
        b = str(data.get("default_branch") or "main")
        self._default_branch[repo] = (b, time.time())
        return b

    async def _repo(self, repo: str) -> dict[str, Any]:
        branch = await self._branch_for(repo)
        params: dict[str, Any] = {"per_page": 5, "branch": branch, "exclude_pull_requests": "true"}
        if self.event != "all":
            params["event"] = self.event
        code, data = await self._get(f"/repos/{repo}/actions/runs", params)
        if code == 404:
            raise LookupError("repo not found (or private without a token)")
        return summarize(repo, branch, data)

    def _transitions(self, repo: str, entry: dict[str, Any]) -> None:
        settled = entry.get("settled", "none")
        if settled == "none":
            return
        prev = self._settled.get(repo)
        self._settled[repo] = settled
        if prev is None:  # first observation arms the alert
            return
        wf = (entry.get("last") or {}).get("name", "")
        if settled == "fail" and prev != "fail":
            self._emit("broke", repo=repo, workflow=wf)
        elif prev == "fail" and settled == "pass":
            self._emit("fixed", repo=repo, workflow=wf)

    async def fetch(self) -> dict[str, Any]:
        if not self.repos:
            return {"repos": {}, "rate": dict(self._rate)}
        if time.time() < self._hold_until:
            raise RuntimeError("GitHub rate limit reached; add a token or wait")
        old = (self.value or {}).get("repos", {})
        out: dict[str, Any] = {}
        errors: list[str] = []
        # sequential on purpose: a handful of repos, and it keeps the request count predictable
        for repo in self.repos:
            try:
                entry = await self._repo(repo)
                entry["error"] = None
                self._transitions(repo, entry)
            except Exception as e:
                msg = safe_error(e, self.token)
                if time.time() < self._hold_until:  # rate limited: don't burn the rest of the poll
                    errors.append(f"{repo}: {msg}")
                    for rest in self.repos[self.repos.index(repo) :]:
                        out[rest] = dict(
                            old.get(rest)
                            or {
                                "repo": rest,
                                "branch": self.branch,
                                "state": "none",
                                "settled": "none",
                                "runs": [],
                            },
                            error=msg,
                        )
                    break
                errors.append(f"{repo}: {msg}")
                entry = dict(
                    old.get(repo)
                    or {"repo": repo, "branch": self.branch, "state": "none", "settled": "none", "runs": []}
                )
                entry["error"] = msg
            out[repo] = entry
        if errors and not any(v.get("last") for v in out.values()):
            raise RuntimeError("; ".join(errors)[:200])
        return {"repos": out, "rate": dict(self._rate), "fetched": time.time()}
