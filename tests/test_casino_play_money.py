"""I-CAS-1 / I-ROOT-4: casino credits are play money. No code path turns them into anything of value.

- The HTTP API has no purchase / cash-out / payment / transfer route, and no casino op (host, player or game) is one.
- The bank is an isolated, whole-number ledger with a pinned API: nothing in it sends credits anywhere; credits are
  granted only by the host (a phone asking for credits, a reset or new settings is refused).
- What phones, the studio and the TV receive carries no payment field (price, currency, card, account…).
- No payment SDK is a dependency or imported anywhere (Python, the studio, the web app, the Android app, Netlify).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

from deskdot.casino.bank import Bank

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "deskdot"

#: words that would mean credits are bought, sold, paid out or moved out of the game (matched as whole tokens of a
#: route, op or payload key: `cash_out` → cash, out; `buyCredits` → buy, credits)
MONEY_WORDS = {
    "buy", "purchase", "sell", "sale", "cash", "cashout", "withdraw", "withdrawal", "deposit", "transfer",
    "redeem", "exchange", "payment", "payments", "pay", "checkout", "topup", "invoice", "billing", "price",
    "cost", "currency", "usd", "eur", "gbp", "inr", "iban", "stripe", "paypal", "upi", "crypto", "btc", "eth",
    "voucher", "rake", "gift", "donate", "tip",
}  # fmt: skip

#: (game id, op) that look like money words but aren't: what they really do
ALLOWED_OPS = {
    ("housie", "buy"): "buys Housie tickets with play credits: the stake goes to escrow like any bet",
}
#: routes whose path happens to use a money word
ALLOWED_ROUTES = {
    "/api/calibration/transfer": "colour calibration transferred between panels, nothing to do with credits",
}
#: payload keys that are game vocabulary for amounts of play credits
GAME_TERMS = {
    "buy_in": "Hold'em / Teen Patti: the stack a seat starts a hand with, in credits",
    "ticket_price": "Housie: a ticket's cost in credits (a host setting)",
    "price": "Housie: the same ticket cost in the public status",
    "can_buy": "Housie: whether tickets (bets) are open",
    "buy_seconds": "Housie: how long tickets are on sale (the betting phase)",
}
#: KNOWN VIOLATION of the I-CAS-1 wording "no rake" (src/deskdot/casino/SPEC.md § Open questions): Hold'em and
#: Housie have an optional host-set rake (default 0) that the house keeps out of the pot, in play credits. It isn't
#: money, but it contradicts the spec; it stays listed here until the spec or the code changes.
KNOWN_RAKE = {"rake", "rake_cap", "rake_percent"}


def _tokens(name: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return {t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t}


# ===================================================================== routes and ops
def test_no_route_buys_sells_or_moves_credits(tmp_path: Path) -> None:
    from deskdot.config import Config
    from deskdot.server import create_app

    app = create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins"))
    bad = []
    for r in app.routes:
        path, name = getattr(r, "path", ""), getattr(r, "name", "") or ""
        hit = (_tokens(path) | _tokens(name)) & MONEY_WORDS
        if hit and not any(path.startswith(a) for a in ALLOWED_ROUTES):
            bad.append(f"{path} ({name}): {sorted(hit)}")
    assert len(app.routes) > 50, "create_app() lost its routes? the scan would prove nothing"
    assert not bad, "routes that look like they buy, sell or move credits (I-CAS-1):\n" + "\n".join(bad)


def _op_literals(path: Path) -> set[str]:
    """Every string an `op` variable is compared with (`op == "x"`, `op in ("x", "y")`)."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Compare) or not (
            isinstance(node.left, ast.Name) and node.left.id == "op"
        ):
            continue
        for comp in node.comparators:
            consts = comp.elts if isinstance(comp, (ast.Tuple, ast.List, ast.Set)) else [comp]
            out |= {c.value for c in consts if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return out


def test_no_casino_op_buys_sells_or_moves_credits() -> None:
    from deskdot.casino.session import HOST_OPS

    files = [
        *sorted((SRC / "casino").rglob("*.py")),
        SRC / "apps" / "_casino.py",
        SRC / "apps" / "_pvpapp.py",
        *sorted((SRC / "apps").glob("casino_*.py")),
    ]
    ops: dict[str, set[str]] = {"session": set(HOST_OPS)}
    for f in files:
        ops.setdefault(f.stem, set()).update(_op_literals(f))
    assert {"bet", "credits", "hit", "pull", "fold"} <= set().union(*ops.values()), "op scan found too little"
    bad = [
        f"{where}: {op!r}"
        for where, names in ops.items()
        for op in sorted(names)
        if _tokens(op) & MONEY_WORDS and (where, op) not in ALLOWED_OPS
    ]
    assert not bad, "casino ops that look like money (I-CAS-1):\n" + "\n".join(bad)
    stale = [k for k in ALLOWED_OPS if k[1] not in ops.get(k[0], set())]
    assert not stale, f"ALLOWED_OPS entries no longer in the code (remove them): {stale}"


# ===================================================================== the bank
def test_the_bank_is_an_isolated_whole_number_ledger() -> None:
    public = {n for n in vars(Bank) if not n.startswith("_")}
    # every way credits change; a new method here must be checked against I-CAS-1 (and this list updated)
    assert public == {
        "has", "open", "get", "credits", "stake", "release", "settle", "set_credits", "add_credits", "reset",
        "remove", "leaderboard", "save",
    }  # fmt: skip
    section: dict[str, Any] = {}
    b = Bank(section)
    b.open("a", 1000)
    b.open("b", 1000)
    for bad in (2.5, True, "10", -5, 0, 1001):
        assert b.stake("a", bad, round_=1, game="roulette", seat=2) is False  # type: ignore[arg-type]
    assert b.stake("a", 100, round_=1, game="roulette", seat=2)
    b.settle("a", 100, 0, round_=1, game="roulette", seat=2)
    b.set_credits("b", 12.9)  # type: ignore[arg-type]  # host grants are coerced to whole credits
    for w in b.wallets.values():
        for v in (w.credits, w.escrow, w.won, w.lost, w.biggest, w.rounds, w.wagered):
            assert type(v) is int and v >= 0
    # credits never leave the session: a loss goes to the house (nobody's wallet), every change is a ledger entry,
    # and the only state is the store section the bank was given
    assert b.credits("a") == 900 and b.credits("b") == 12
    assert sum(e["delta"] for e in b.ledger if e["pid"] == "a") == 900
    assert set(section) == {"wallets", "ledger"}
    assert json.loads(json.dumps(section)) == section


async def test_only_the_host_grants_credits(engine: Any) -> None:
    app = engine._slot("casino_roulette").app
    await app.action("seat", {"player": 2, "joined": True, "name": "ADA", "pid": "pidAAAA"})
    before = app.private_status(2)["credits"]
    for op in (
        {"op": "credits", "set": 99_999},
        {"op": "credits", "add": 5000, "all": True},
        {"op": "reset_session", "base_credits": 1_000_000},
        {"op": "settings", "base_credits": 1_000_000},
    ):
        r = await app.action("casino", {"player": 2, **op})
        assert r["ok"] is False, op
    assert app.private_status(2)["credits"] == before
    # the host can (the studio is local-only, LanGate keeps it off the LAN)
    r = await app.action("casino", {"player": "host", "op": "credits", "seat": 2, "add": 50})
    assert r["ok"] and app.private_status(2)["credits"] == before + 50


# ===================================================================== payloads
def _keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(map(str, obj)).union(*(_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(_keys(v) for v in obj))
    return set()


def _credit_values(obj: Any) -> list[Any]:
    if isinstance(obj, dict):
        own = [v for k, v in obj.items() if k in ("credits", "escrow", "staked")]
        return own + [x for v in obj.values() for x in _credit_values(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in _credit_values(v)]
    return []


CASINO_APPS = (
    "casino_roulette", "casino_sevens", "casino_blackjack", "casino_baccarat", "casino_andarbahar",
    "casino_bigsix", "casino_slots", "casino_housie", "casino_holdem", "casino_teenpatti",
)  # fmt: skip


@pytest.mark.parametrize("app_id", CASINO_APPS)
async def test_phone_and_tv_payloads_carry_no_payment_fields(engine: Any, app_id: str) -> None:
    app = engine._slot(app_id).app
    for seat, pid in ((2, "pidAAAA"), (3, "pidBBBB")):
        await app.action("seat", {"player": seat, "joined": True, "name": pid[-4:], "pid": pid})
    await app.action("casino", {"player": 2, "op": "bet", "spot": "red", "amount": 10})
    payloads = [app.status(), app.private_status(2), app.private_status(3), app.host_view(True)]
    keys = set().union(*(_keys(p) for p in payloads))
    bad = sorted(k for k in keys if _tokens(k) & MONEY_WORDS and k not in GAME_TERMS and k not in KNOWN_RAKE)
    assert not bad, f"{app_id}: payload keys that look like payment data: {bad}"
    vals = [v for p in payloads for v in _credit_values(p)]
    assert vals, "no credits in the payloads? the check would prove nothing"
    assert all(type(v) is int for v in vals), f"{app_id}: credits must be whole numbers: {vals}"


# ===================================================================== no payment SDKs
PY_PAYMENT = {
    "stripe", "paypalrestsdk", "paypalcheckoutsdk", "paypalserversdk", "braintree", "square", "squareup",
    "adyen", "Adyen", "razorpay", "mollie", "paddle", "paddle_billing", "lemonsqueezy", "coinbase_commerce",
    "web3", "eth_account", "chargebee", "recurly", "gocardless_pro", "checkout_sdk",
}  # fmt: skip
#: SDK packages, script hosts and browser / Play payment APIs ("stripe" alone is a visual stripe, so not that)
PAYMENT_TEXT = re.compile(
    r"stripe\.com|@stripe/|\bStripe\(|paypal|braintree|razorpay|adyen|lemonsqueezy|revenuecat|billingclient"
    r"|com\.android\.vending\.billing|play-services-wallet|PaymentRequest\(|coinbase|\bethers\b|\bweb3\b|@square/",
    re.I,
)
SKIP = {"node_modules", "dist", "build", ".gradle", "__pycache__", "legacy", "wheels"}


def _files(base: Path, exts: tuple[str, ...]) -> list[Path]:
    if not base.exists():
        return []
    return [
        p
        for p in base.rglob("*")
        if p.suffix in exts and p.is_file() and not (SKIP & set(p.relative_to(ROOT).parts))
    ]


def test_no_payment_sdk_anywhere() -> None:
    bad: list[str] = []
    for f in _files(SRC, (".py",)) + _files(ROOT / "plugins", (".py",)):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom) and not node.level
                else []
            )
            bad += [
                f"{f.relative_to(ROOT)}:{node.lineno} imports {m}"
                for m in mods
                if m.split(".")[0] in PY_PAYMENT
            ]
    # dependency manifests and client code (the studio, the web app, the phone/TV pages, Android, Netlify functions)
    manifests = [
        ROOT / "pyproject.toml",
        ROOT / "web" / "package.json",
        ROOT / "android" / "app" / "build.gradle.kts",
    ]
    code = (
        _files(SRC, (".js", ".html"))
        + _files(ROOT / "web" / "src", (".ts", ".tsx", ".js"))
        + _files(ROOT / "web" / "webapp", (".js", ".html", ".mjs"))
        + _files(ROOT / "android" / "app" / "src", (".kt", ".java", ".xml"))
        + _files(ROOT / "netlify", (".js", ".mjs", ".ts"))
    )
    for f in [m for m in manifests if m.is_file()] + code:
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if m := PAYMENT_TEXT.search(line):
                bad.append(f"{f.relative_to(ROOT)}:{i} mentions {m.group(0)!r}")
    assert len(code) > 20, "the client-code scan found too few files to prove anything"
    assert not bad, "payment SDKs or APIs (I-CAS-1: credits are never bought or sold):\n" + "\n".join(bad)
