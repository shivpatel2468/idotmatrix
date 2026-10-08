"""Probe every external API the providers call and write docs/API_HEALTH.md.

    uv run python scripts/api_health.py                 # probe all, print a table, rewrite docs/API_HEALTH.md
    uv run python scripts/api_health.py --only space,iss --no-write
    uv run python scripts/api_health.py --json health.json

Endpoints come from code: every provider lists the URLs it calls in `Provider.endpoints` (`providers/base.py`
`Endpoint`), each with a concrete sample request and a check that runs the provider's own parser on the answer.
For each one this reports:

* **status** — OK · SLOW (> 3 s) · SHAPE (answers, but the provider's parser no longer understands it) · KEY
  (401/402: now needs a key) · BLOCKED (403/451) · LIMIT (429) · DNS (the name doesn't resolve here — often an ISP
  block, check from another network) · DOWN (anything else);
* HTTP code and latency;
* **web** — how the browser app reaches it: ``CORS`` (direct, the API allows https://idotmatrix.com), ``proxy`` (on
  the allowlist in netlify/functions/cors-proxy.mjs) or ``NO`` (neither: the web app can't use it).

The hand-written part of docs/API_HEALTH.md below the ``<!-- generated:end -->`` marker is kept. Exit code 1 when a
primary endpoint isn't OK/SLOW (so it can run in CI on a schedule). Never run from the test suite (live network).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deskdot.providers import ALL  # noqa: E402
from deskdot.providers.base import Endpoint, dig  # noqa: E402

DOC = ROOT / "docs" / "API_HEALTH.md"
PROXY = ROOT / "netlify" / "functions" / "cors-proxy.mjs"
ORIGIN = "https://idotmatrix.com"
UA = "DeskDot/3 (+https://github.com/)"  # the engine's default (providers/base.py Hub)
SLOW_MS = 3000
END = "<!-- generated:end -->"
GOOD = ("OK", "SLOW")


@dataclass
class Result:
    provider: str
    ep: Endpoint
    status: str = "DOWN"
    code: int | None = None
    ms: int | None = None
    web: str = ""
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def proxy_allowlist() -> set[str]:
    src = PROXY.read_text(encoding="utf-8")
    block = re.search(r"const ALLOW = new Set\(\[(.*?)\]\);", src, re.S)
    return set(re.findall(r'"([^"]+)"', block.group(1))) if block else set()


def web_access(url: str, acao: str | None, allow: set[str]) -> str:
    host = urlparse(url).hostname or ""
    if url.startswith("https://") and acao and (acao == "*" or acao.rstrip("/") == ORIGIN):
        return "CORS"
    return "proxy" if host in allow else "NO"


def check_body(ep: Endpoint, r: httpx.Response) -> str | None:
    """None when the answer still has the shape the provider parses, else a short reason."""
    try:
        body: Any = r.json() if ep.body == "json" else r.text if ep.body == "text" else r.content
    except ValueError:
        return f"not {ep.body} ({r.headers.get('content-type', '?')})"
    missing = [p for p in ep.expect if dig(body, p) is None]
    if missing:
        return "missing " + ", ".join(missing)
    if ep.check is not None:
        try:
            got = ep.check(body)
        except Exception as e:  # the parser choked: that is exactly what we are looking for
            return f"parser: {type(e).__name__}: {e}"[:120]
        if got is None or got is False:
            return "parser returned nothing"
        # an empty list is a real answer only where `expect` already proved the shape (e.g. no games today)
        if isinstance(got, (list, dict, str, tuple)) and not got and not ep.expect:
            return "parser returned nothing"
    return None


async def probe(
    http: httpx.AsyncClient, provider: str, ep: Endpoint, allow: set[str], lock: asyncio.Lock
) -> Result:
    res = Result(provider, ep)
    headers = {"User-Agent": UA, "Origin": ORIGIN, **dict(ep.headers)}
    async with lock:  # one request per host at a time (Open Trivia DB: 1 / 5 s, ZenQuotes, LL2…)
        t0 = time.perf_counter()
        try:
            r = await http.get(ep.url, headers=headers)
        except httpx.ConnectError as e:
            res.status = "DNS" if "getaddrinfo" in str(e) or "resolve" in str(e).lower() else "DOWN"
            res.detail = f"{type(e).__name__}: {e}"[:120]
            res.web = web_access(ep.url, None, allow)
            return res
        except httpx.HTTPError as e:
            res.detail = f"{type(e).__name__}: {e}"[:120] or type(e).__name__
            res.web = web_access(ep.url, None, allow)
            return res
        finally:
            res.ms = round((time.perf_counter() - t0) * 1000)
        if "opentdb.com" in ep.url:
            await asyncio.sleep(5.2)
    res.code = r.status_code
    res.web = web_access(ep.url, r.headers.get("access-control-allow-origin"), allow)
    if r.status_code in (401, 402):
        res.status, res.detail = "KEY", r.text[:100]
    elif r.status_code in (403, 451):
        res.status, res.detail = "BLOCKED", r.text[:100]
    elif r.status_code == 429:
        res.status, res.detail = "LIMIT", "rate limited"
    elif r.status_code >= 400:
        res.status, res.detail = "DOWN", f"HTTP {r.status_code}"
    else:
        why = check_body(ep, r)
        if why:
            res.status, res.detail = "SHAPE", why
        else:
            res.status = "SLOW" if (res.ms or 0) > SLOW_MS else "OK"
    res.detail = re.sub(r"\s+", " ", res.detail).replace("|", "/").strip()
    return res


async def run(only: set[str]) -> list[Result]:
    allow = proxy_allowlist()
    jobs: list[tuple[str, Endpoint]] = [
        (p.name, ep) for p in ALL for ep in p.endpoints if not only or p.name in only
    ]
    locks: dict[str, asyncio.Lock] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=True) as http:
        coros = []
        for name, ep in jobs:
            lock = locks.setdefault(urlparse(ep.url).hostname or "", asyncio.Lock())
            coros.append(probe(http, name, ep, allow, lock))
        return list(await asyncio.gather(*coros))


def table(results: list[Result]) -> str:
    rows = [
        "| Provider | Endpoint | Role | Status | HTTP | ms | Web | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        notes = "; ".join(x for x in (r.detail, r.ep.note) if x)
        host = urlparse(r.ep.url).hostname
        rows.append(
            f"| `{r.provider}` | {r.ep.label} (`{host}`) | {r.ep.role} | **{r.status}** | {r.code or '-'} | "
            f"{r.ms if r.ms is not None else '-'} | {r.web} | {notes} |"
        )
    return "\n".join(rows)


def summary(results: list[Result]) -> str:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    order = ("OK", "SLOW", "SHAPE", "KEY", "BLOCKED", "LIMIT", "DNS", "DOWN")
    return " · ".join(f"{k} {counts[k]}" for k in order if k in counts)


def write_doc(results: list[Result]) -> None:
    keep = ""
    if DOC.exists():
        old = DOC.read_text(encoding="utf-8")
        if END in old:
            keep = old.split(END, 1)[1]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    head = f"""# API health

Generated by `uv run python scripts/api_health.py` on **{now}** — {len(results)} endpoints from
{len({r.provider for r in results})} providers: {summary(results)}.

Every external URL a provider calls is declared next to its code (`Provider.endpoints`, see
`src/deskdot/providers/base.py`); the script requests a live sample of each and runs the provider's own parser on
the answer, so "OK" means "DeskDot still understands it", not just "HTTP 200". Statuses: OK · SLOW (> 3 s) ·
SHAPE (answers, but the parser no longer understands it) · KEY (now needs a key) · BLOCKED (403/451) · LIMIT
(429) · DNS (doesn't resolve from the probing network — often an ISP block) · DOWN. **Web**: how the browser app
reaches it — `CORS` (direct), `proxy` (netlify/functions/cors-proxy.mjs allowlist) or `NO`.
Roles: *primary* (the app needs it), *fallback* (used when the primary fails), *optional* (a bonus).

Results depend on where the probe runs (geo-blocks, ISP DNS filters, rate limits shared per IP).

{table(results)}

"""
    DOC.write_text(head + END + (keep or "\n"), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", default="", help="comma-separated provider names")
    ap.add_argument("--no-write", action="store_true", help="don't rewrite docs/API_HEALTH.md")
    ap.add_argument("--json", default="", help="also write the results as JSON to this path")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the Windows console defaults to cp1252
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    results = asyncio.run(run(only))
    w = max(len(f"{r.provider}: {r.ep.label}") for r in results) if results else 10
    for r in results:
        print(
            f"{r.status:8s} {r.code or '-'!s:>4s} {r.ms if r.ms is not None else '-'!s:>6s}ms "
            f"{r.web:5s} {r.ep.role:8s} {f'{r.provider}: {r.ep.label}':{w}s} {r.detail}"
        )
    print(summary(results))
    if not args.no_write and not only:
        write_doc(results)
        print(f"wrote {DOC.relative_to(ROOT)}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                [
                    {
                        "provider": r.provider,
                        "endpoint": r.ep.label,
                        "url": r.ep.url,
                        "role": r.ep.role,
                        "status": r.status,
                        "code": r.code,
                        "ms": r.ms,
                        "web": r.web,
                        "detail": r.detail,
                    }
                    for r in results
                ],
                indent=1,
            ),
            encoding="utf-8",
        )
    bad = [r for r in results if r.ep.role == "primary" and r.status not in GOOD]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
