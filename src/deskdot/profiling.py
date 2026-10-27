"""A tiny in-process sampling profiler (GET /api/debug/profile).

py-spy can't attach to the Chaquopy interpreter on the watch (32-bit, no root, no ptrace of app processes), so
the engine samples itself: a background thread reads every Python thread's current stack through
`sys._current_frames()` at a fixed rate and counts where each one is. Cheap enough to run on the watch for a
minute (one stack walk per thread per sample) and needs nothing outside the standard library.

A sample whose innermost frame is the event loop's `select()` (or a lock/condition wait) means "this thread was
idle"; everything else is real work. `busy_pct` is the share of samples that were not idle.
"""

from __future__ import annotations

import sys
import threading
import time
from collections import Counter
from typing import Any

#: Innermost frames that mean "parked, not working" (the event loop's selector, a thread waiting on a lock).
_IDLE_LEAVES = frozenset(
    {
        ("selectors.py", "select"),
        ("threading.py", "wait"),
        ("threading.py", "_wait_for_tstate_lock"),
        ("queue.py", "get"),
        ("thread.py", "_worker"),  # concurrent.futures pool worker blocked on its work queue
    }
)


def _where(code: Any, lineno: int) -> str:
    path = code.co_filename.replace("\\", "/")
    short = "/".join(path.rsplit("/", 2)[-2:])
    return f"{short}:{code.co_name}:{lineno}"


def sample_stacks(seconds: float = 10.0, hz: float = 50.0, depth: int = 25, top: int = 25) -> dict[str, Any]:
    """Sample every other Python thread for `seconds` at `hz`. Blocking: run it in a worker thread."""
    me = threading.get_ident()
    names = {t.ident: t.name for t in threading.enumerate()}
    per_thread: dict[str, dict[str, Any]] = {}
    period = 1.0 / max(1.0, hz)
    end = time.monotonic() + max(0.5, seconds)
    samples = 0
    cpu0 = time.process_time()
    t0 = time.monotonic()
    while time.monotonic() < end:
        samples += 1
        for ident, frame in sys._current_frames().items():
            if ident == me:
                continue
            name = names.get(ident) or f"thread-{ident}"
            st = per_thread.setdefault(
                name, {"samples": 0, "idle": 0, "leaf": Counter(), "incl": Counter(), "stacks": Counter()}
            )
            st["samples"] += 1
            code = frame.f_code
            leaf_key = (code.co_filename.replace("\\", "/").rsplit("/", 1)[-1], code.co_name)
            if leaf_key in _IDLE_LEAVES:
                st["idle"] += 1
                continue
            st["leaf"][_where(code, frame.f_lineno)] += 1
            chain: list[str] = []
            seen: set[str] = set()
            f: Any = frame
            while f is not None and len(chain) < depth:
                w = f"{'/'.join(f.f_code.co_filename.replace(chr(92), '/').rsplit('/', 2)[-2:])}:{f.f_code.co_name}"
                chain.append(w)
                if w not in seen:  # recursion counts once per sample
                    seen.add(w)
                    st["incl"][w] += 1
                f = f.f_back
            st["stacks"][" < ".join(chain[:8])] += 1
        time.sleep(period)
    wall = time.monotonic() - t0
    out: dict[str, Any] = {
        "seconds": round(wall, 2),
        "samples": samples,
        "hz": hz,
        # CPU of the whole process (all threads, Java ones too) over the window, as a share of one core
        "process_cpu_pct_of_one_core": round(100 * (time.process_time() - cpu0) / max(wall, 1e-6), 1),
        "threads": {},
    }
    for name, st in sorted(per_thread.items(), key=lambda kv: kv[1]["idle"] - kv[1]["samples"]):
        n = max(1, st["samples"])
        out["threads"][name] = {
            "busy_pct": round(100 * (st["samples"] - st["idle"]) / n, 1),
            "top_self": st["leaf"].most_common(top),
            "top_inclusive": st["incl"].most_common(top),
            "top_stacks": st["stacks"].most_common(10),
        }
    return out
