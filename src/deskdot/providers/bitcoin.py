"""The Bitcoin network from mempool.space's public REST API (keyless, CORS).

``/api/v1/fees/recommended`` (sat/vB tiers), ``/api/v1/blocks`` (the newest blocks), ``/api/mempool`` (backlog)
and ``/api/v1/difficulty-adjustment``. The halving is block arithmetic: every 210 000 blocks.

``value = {"fees": {fastest, half_hour, hour, economy, minimum}, "height", "last_block": unix, "tx_count",
"block_size", "mempool": {count, vsize}, "difficulty": {progress, change, remaining_blocks, eta},
"halving": {height, remaining, eta, progress, subsidy}, "updated"}``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import Endpoint, Provider

API = "https://mempool.space/api"
HALVING = 210_000
BLOCK_S = 600.0


def parse_fees(d: Any) -> dict[str, float]:
    if not isinstance(d, dict) or "fastestFee" not in d:
        raise ValueError("fees: unexpected shape")
    keys = {
        "fastest": "fastestFee",
        "half_hour": "halfHourFee",
        "hour": "hourFee",
        "economy": "economyFee",
        "minimum": "minimumFee",
    }
    return {k: float(d.get(src) or 0) for k, src in keys.items()}


def parse_blocks(d: Any) -> list[dict[str, Any]]:
    out = []
    for b in d if isinstance(d, list) else []:
        if isinstance(b, dict) and "height" in b and "timestamp" in b:
            out.append(
                {
                    "height": int(b["height"]),
                    "time": float(b["timestamp"]),
                    "tx_count": int(b.get("tx_count") or 0),
                    "size": int(b.get("size") or 0),
                }
            )
    out.sort(key=lambda b: -b["height"])
    return out


def parse_difficulty(d: Any) -> dict[str, Any]:
    if not isinstance(d, dict) or "progressPercent" not in d:
        raise ValueError("difficulty: unexpected shape")
    return {
        "progress": float(d.get("progressPercent") or 0) / 100,
        "change": float(d.get("difficultyChange") or 0),
        "remaining_blocks": int(d.get("remainingBlocks") or 0),
        "eta": float(d.get("estimatedRetargetDate") or 0) / 1000 or None,
    }


def halving(height: int, now: float | None = None) -> dict[str, Any]:
    """Next halving from the tip height: target height, blocks left, ETA (10 min/block), era progress, subsidy."""
    now = time.time() if now is None else now
    era = height // HALVING
    target = (era + 1) * HALVING
    remaining = target - height
    return {
        "height": target,
        "remaining": remaining,
        "eta": now + remaining * BLOCK_S,
        "progress": (height - era * HALVING) / HALVING,
        "subsidy": 50 / 2**era,
        "era": era + 1,
    }


class BitcoinProvider(Provider[dict[str, Any]]):
    name = "bitcoin"
    endpoints = (
        Endpoint("mempool.space fees", API + "/v1/fees/recommended", check=parse_fees),
        Endpoint("mempool.space blocks", API + "/v1/blocks", check=parse_blocks),
        Endpoint("mempool.space backlog", API + "/mempool", expect=("count", "vsize")),
        Endpoint("mempool.space difficulty", API + "/v1/difficulty-adjustment", check=parse_difficulty),
    )
    interval = 60.0  # a block every ~10 min; fees move faster
    retry = 30.0

    async def _json(self, path: str) -> Any:
        r = await self.hub.http.get(API + path)
        r.raise_for_status()
        return r.json()

    async def fetch(self) -> dict[str, Any]:
        fees, blocks, pool, diff = await asyncio.gather(
            self._json("/v1/fees/recommended"),
            self._json("/v1/blocks"),
            self._json("/mempool"),
            self._json("/v1/difficulty-adjustment"),
            return_exceptions=True,
        )
        if isinstance(blocks, BaseException):
            raise blocks
        bl = parse_blocks(blocks)
        if not bl:
            raise ValueError("mempool.space: no blocks")
        tip = bl[0]
        out: dict[str, Any] = {
            "height": tip["height"],
            "last_block": tip["time"],
            "tx_count": tip["tx_count"],
            "block_size": tip["size"],
            "recent": [b["time"] for b in bl[:8]],
            "halving": halving(tip["height"]),
            "fees": None if isinstance(fees, BaseException) else parse_fees(fees),
            "mempool": None,
            "difficulty": None,
            "updated": time.time(),
        }
        if isinstance(pool, dict):
            out["mempool"] = {"count": int(pool.get("count") or 0), "vsize": int(pool.get("vsize") or 0)}
        if not isinstance(diff, BaseException):
            try:
                out["difficulty"] = parse_difficulty(diff)
            except ValueError:
                pass
        return out
