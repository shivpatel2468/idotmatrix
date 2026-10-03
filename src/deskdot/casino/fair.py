"""Provably fair randomness: one commit–reveal RNG for every casino game (docs/CASINO.md §1).

Per round:

1. Before betting opens the round gets a fresh **server seed** (`new_server_seed()`, 32 random bytes). Only its
   SHA-256 (`commit()`) is published, so the house is locked in before anyone bets.
2. When betting closes, the **client seed** is fixed: every seated player's own seed, joined in seat order
   (`client_seed()`), so no single party (house or player) controls the outcome.
3. The outcome stream is ``HMAC-SHA256(key=server_seed, msg=f"{client_seed}:{nonce}:{counter}")`` read as
   big-endian 32-bit words (8 per block, counter 0, 1, 2 …). Integers in a range use **rejection sampling** (no
   modulo bias); shuffles are **Fisher–Yates** (from the top, ``j = randint(0, i)``).
4. After settlement the server seed is revealed and `verify()` lets anyone recompute the outcome.

The same algorithm is implemented in JavaScript in ``casino.html`` (the phone's "Verify this round" sheet);
`tests/test_casino.py` pins known vectors so the two can never drift apart.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable, MutableSequence, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")
U32 = 1 << 32
#: client seed used when nobody at the table sent one (the outcome is still fixed by the committed server seed)
HOUSE_CLIENT_SEED = "deskdot"
CLIENT_SEED_MAX = 64


def new_server_seed() -> bytes:
    return secrets.token_bytes(32)


def commit(server_seed: bytes) -> str:
    """The public commitment to a server seed: its SHA-256, hex."""
    return hashlib.sha256(server_seed).hexdigest()


def clean_client_seed(value: Any) -> str | None:
    """A player's seed: 1–64 printable ASCII characters without ':' (the field separator), else None."""
    if not isinstance(value, str):
        return None
    s = "".join(ch for ch in value if 33 <= ord(ch) < 127 and ch != ":")[:CLIENT_SEED_MAX]
    return s or None


def client_seed(seeds: Sequence[str]) -> str:
    """The round's client seed: the seated players' seeds in seat order, joined with '.'."""
    parts = [s for s in seeds if s]
    return ".".join(parts) if parts else HOUSE_CLIENT_SEED


class Rng:
    """The deterministic outcome stream of one round."""

    def __init__(self, server_seed: bytes, client_seed: str, nonce: int) -> None:
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce = int(nonce)
        self.counter = 0
        self._words: list[int] = []
        self.draws = 0  # 32-bit words consumed (for tests / diagnostics)

    def _refill(self) -> None:
        msg = f"{self.client_seed}:{self.nonce}:{self.counter}".encode()
        block = hmac.new(self.server_seed, msg, hashlib.sha256).digest()
        self.counter += 1
        self._words = [int.from_bytes(block[i : i + 4], "big") for i in range(0, 32, 4)]
        self._words.reverse()  # pop() from the end = read in order

    def u32(self) -> int:
        if not self._words:
            self._refill()
        self.draws += 1
        return self._words.pop()

    def below(self, n: int) -> int:
        """Uniform integer in [0, n) by rejection sampling (no modulo bias)."""
        if not 1 <= n <= U32:
            raise ValueError(f"range size {n} out of bounds")
        limit = U32 - (U32 % n)  # largest multiple of n that fits in 32 bits
        while True:
            x = self.u32()
            if x < limit:
                return x % n

    def randint(self, lo: int, hi: int) -> int:
        """Uniform integer in [lo, hi], both inclusive."""
        if hi < lo:
            raise ValueError("empty range")
        return lo + self.below(hi - lo + 1)

    def choice(self, seq: Sequence[T]) -> T:
        if not seq:
            raise ValueError("empty sequence")
        return seq[self.below(len(seq))]

    def shuffle(self, seq: MutableSequence[T]) -> MutableSequence[T]:
        """Fisher–Yates in place (i from the top down to 1, j = randint(0, i)); also returns `seq`."""
        for i in range(len(seq) - 1, 0, -1):
            j = self.randint(0, i)
            seq[i], seq[j] = seq[j], seq[i]
        return seq


@dataclass
class Round:
    """One round's fairness record. `server_seed` stays secret until `reveal()`."""

    nonce: int
    server_seed: bytes
    hash: str
    client_seed: str | None = None  # fixed when betting closes
    revealed: bool = False

    @classmethod
    def fresh(cls, nonce: int) -> Round:
        seed = new_server_seed()
        return cls(nonce=nonce, server_seed=seed, hash=commit(seed))

    def lock(self, seeds: Sequence[str]) -> Rng:
        self.client_seed = client_seed(seeds)
        return Rng(self.server_seed, self.client_seed, self.nonce)

    def proof(self) -> dict[str, Any]:
        """Public fairness data: always the commitment; the seed only once revealed."""
        out: dict[str, Any] = {"nonce": self.nonce, "hash": self.hash, "client_seed": self.client_seed}
        out["server_seed"] = self.server_seed.hex() if self.revealed else None
        return out


def verify[T](
    server_seed_hex: str,
    hash_hex: str,
    client_seed_: str,
    nonce: int,
    draw: Callable[[Rng], T] | None = None,
) -> dict[str, Any]:
    """Check a revealed round: the seed matches its commitment, and (with `draw`) recompute the outcome.

    Returns ``{"ok": bool, "hash_ok": bool, "outcome": <draw(rng)> | None, "error": str | None}``.
    """
    try:
        seed = bytes.fromhex(server_seed_hex)
    except (ValueError, TypeError):
        return {"ok": False, "hash_ok": False, "outcome": None, "error": "server seed is not hex"}
    hash_ok = hmac.compare_digest(commit(seed), str(hash_hex).lower())
    outcome = draw(Rng(seed, client_seed_, nonce)) if draw is not None else None
    return {
        "ok": hash_ok,
        "hash_ok": hash_ok,
        "outcome": outcome,
        "error": None if hash_ok else "seed does not match the hash",
    }
