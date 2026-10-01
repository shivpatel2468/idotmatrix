"""Chess.com puzzles (keyless, verified live 2026-09-24) plus a tiny chess core to replay their solutions.

* ``https://api.chess.com/pub/puzzle`` — the daily puzzle; ``/pub/puzzle/random`` — a random past one.
  Both return ``title``, ``fen`` and ``pgn`` (the solution in SAN, e.g. ``45... Qe1+ 46. Rxe1 Rxe1+``).

No chess library: FEN is parsed here, and SAN is resolved with a minimal move generator (piece movement,
blocking, castling, en passant, promotion) plus a king-safety filter for ambiguous moves. That is all a
puzzle solution needs.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from .base import Provider

DAILY = "https://api.chess.com/pub/puzzle"
RANDOM = "https://api.chess.com/pub/puzzle/random"

Board = list[list[str]]  # board[rank][file], rank 0 = rank 1, '.' = empty; white upper-case
Sq = tuple[int, int]  # (file 0..7, rank 0..7)

KNIGHT = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
ROOK_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))


@dataclass
class Move:
    san: str
    piece: str  # as on the board ('N' / 'n')
    frm: Sq
    to: Sq
    capture: bool = False
    promo: str = ""
    rook: tuple[Sq, Sq] | None = None  # castling rook (from, to)
    ep: Sq | None = None  # square of a pawn taken en passant
    check: bool = False
    mate: bool = False


@dataclass
class Puzzle:
    title: str
    url: str
    fen: str
    side: str  # "w" / "b" to move
    boards: list[Board]  # position before each move, then the final position
    moves: list[Move] = field(default_factory=list)
    published: int = 0
    kind: str = "daily"


# ------------------------------------------------------------------------------ board basics
def parse_fen(fen: str) -> tuple[Board, str, str, Sq | None]:
    """→ (board, side, castling rights, en-passant square)."""
    parts = fen.split()
    rows = parts[0].split("/")
    if len(rows) != 8:
        raise ValueError(f"bad FEN: {fen!r}")
    board: Board = [["."] * 8 for _ in range(8)]
    for i, row in enumerate(rows):
        r = 7 - i
        f = 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
            else:
                if f > 7 or ch.lower() not in "kqrbnp":
                    raise ValueError(f"bad FEN row {row!r}")
                board[r][f] = ch
                f += 1
        if f != 8:
            raise ValueError(f"bad FEN row {row!r}")
    side = parts[1] if len(parts) > 1 and parts[1] in ("w", "b") else "w"
    castling = parts[2] if len(parts) > 2 else "-"
    ep = sq(parts[3]) if len(parts) > 3 and parts[3] != "-" else None
    return board, side, castling, ep


def sq(name: str) -> Sq:
    return ord(name[0]) - 97, int(name[1]) - 1


def sq_name(s: Sq) -> str:
    return f"{chr(97 + s[0])}{s[1] + 1}"


def color_of(p: str) -> str:
    return "w" if p.isupper() else "b"


def on_board(f: int, r: int) -> bool:
    return 0 <= f < 8 and 0 <= r < 8


def attacks(board: Board, frm: Sq) -> list[Sq]:
    """Squares the piece on `frm` attacks (pawns: diagonals only)."""
    f, r = frm
    p = board[r][f]
    kind = p.upper()
    out: list[Sq] = []
    if kind == "P":
        d = 1 if p.isupper() else -1
        out = [(f + df, r + d) for df in (-1, 1) if on_board(f + df, r + d)]
    elif kind in "NK":
        out = [(f + a, r + b) for a, b in (KNIGHT if kind == "N" else KING) if on_board(f + a, r + b)]
    else:
        dirs = {"R": ROOK_DIRS, "B": BISHOP_DIRS, "Q": ROOK_DIRS + BISHOP_DIRS}[kind]
        for a, b in dirs:
            x, y = f + a, r + b
            while on_board(x, y):
                out.append((x, y))
                if board[y][x] != ".":
                    break
                x, y = x + a, y + b
    return out


def attacked(board: Board, target: Sq, by: str) -> bool:
    for r in range(8):
        for f in range(8):
            p = board[r][f]
            if p != "." and color_of(p) == by and target in attacks(board, (f, r)):
                return True
    return False


def king_sq(board: Board, side: str) -> Sq | None:
    k = "K" if side == "w" else "k"
    for r in range(8):
        for f in range(8):
            if board[r][f] == k:
                return f, r
    return None


def apply(board: Board, m: Move) -> Board:
    b = [row[:] for row in board]
    (ff, fr), (tf, tr) = m.frm, m.to
    p = b[fr][ff]
    b[fr][ff] = "."
    if m.ep:
        b[m.ep[1]][m.ep[0]] = "."
    if m.promo:
        p = m.promo.upper() if p.isupper() else m.promo.lower()
    b[tr][tf] = p
    if m.rook:
        (rf, rr), (rtf, rtr) = m.rook
        b[rtr][rtf] = b[rr][rf]
        b[rr][rf] = "."
    return b


def _pawn_sources(
    board: Board, side: str, to: Sq, capture: bool, ep: Sq | None
) -> list[tuple[Sq, Sq | None]]:
    """Pawns of `side` that can move to `to` → [(from, en-passant victim square)]."""
    d = 1 if side == "w" else -1
    p = "P" if side == "w" else "p"
    tf, tr = to
    out: list[tuple[Sq, Sq | None]] = []
    if capture:
        for df in (-1, 1):
            f, r = tf + df, tr - d
            if on_board(f, r) and board[r][f] == p:
                if board[tr][tf] != "." and color_of(board[tr][tf]) != side:
                    out.append(((f, r), None))
                elif board[tr][tf] == "." and ep == to:
                    out.append(((f, r), (tf, tr - d)))
        return out
    if board[tr][tf] != ".":
        return out
    if on_board(tf, tr - d) and board[tr - d][tf] == p:
        out.append(((tf, tr - d), None))
    start = 1 if side == "w" else 6
    if tr - 2 * d == start and board[tr - d][tf] == "." and board[start][tf] == p:
        out.append(((tf, start), None))
    return out


SAN_RE = re.compile(r"^([KQRBN])?([a-h])?([1-8])?(x)?([a-h][1-8])(?:=?([QRBNqrbn]))?$")


def resolve_san(board: Board, side: str, san: str, ep: Sq | None = None) -> Move:
    """One SAN move for `side` on `board` → a `Move` (raises ValueError if it is impossible or ambiguous)."""
    raw = san
    clean = san.strip().rstrip("!?")
    check, mate = clean.endswith("+"), clean.endswith("#")
    clean = clean.rstrip("+#").replace("0", "O")
    rank = 0 if side == "w" else 7
    if clean in ("O-O", "O-O-O"):
        long = clean == "O-O-O"
        k = "K" if side == "w" else "k"
        if board[rank][4] != k:
            raise ValueError(f"{raw}: king not on its castling square")
        to = (2 if long else 6, rank)
        rook = ((0, rank), (3, rank)) if long else ((7, rank), (5, rank))
        return Move(raw, k, (4, rank), to, rook=rook, check=check, mate=mate)
    m = SAN_RE.match(clean)
    if not m:
        raise ValueError(f"unreadable SAN {raw!r}")
    kind, dfile, drank, cap, dest, promo = m.groups()
    kind = kind or "P"
    to = sq(dest)
    piece = kind if side == "w" else kind.lower()
    target = board[to[1]][to[0]]
    if target != "." and color_of(target) == side:
        raise ValueError(f"{raw}: own piece on {dest}")
    cands: list[tuple[Sq, Sq | None]] = []
    if kind == "P":
        cands = _pawn_sources(board, side, to, bool(cap), ep)
    else:
        for r in range(8):
            for f in range(8):
                if board[r][f] == piece and to in attacks(board, (f, r)):
                    cands.append(((f, r), None))
    if dfile:
        cands = [c for c in cands if c[0][0] == ord(dfile) - 97]
    if drank:
        cands = [c for c in cands if c[0][1] == int(drank) - 1]
    if len(cands) > 1:  # keep only moves that don't leave our king in check
        legal = []
        for frm, epv in cands:
            nb = apply(board, Move(raw, piece, frm, to, ep=epv))
            k = king_sq(nb, side)
            if k is None or not attacked(nb, k, "b" if side == "w" else "w"):
                legal.append((frm, epv))
        cands = legal
    if len(cands) != 1:
        raise ValueError(f"{raw}: {len(cands)} candidate moves")
    frm, epv = cands[0]
    return Move(
        raw,
        piece,
        frm,
        to,
        capture=bool(cap) or epv is not None,
        promo=(promo or "").upper(),
        ep=epv,
        check=check,
        mate=mate,
    )


def pgn_moves(pgn: str) -> list[str]:
    """SAN tokens of a PGN body: headers, comments, variations, NAGs, move numbers and results removed."""
    body = re.sub(r"\[[^\]]*\]", " ", pgn)
    body = re.sub(r"\{[^}]*\}", " ", body)
    while re.search(r"\([^()]*\)", body):
        body = re.sub(r"\([^()]*\)", " ", body)
    body = re.sub(r"\$\d+", " ", body)
    out = []
    for tok in body.split():
        tok = re.sub(r"^\d+\.(\.\.)?", "", tok)
        if not tok or tok in ("1-0", "0-1", "1/2-1/2", "*") or re.fullmatch(r"\d+\.*", tok):
            continue
        out.append(tok)
    return out


def replay(fen: str, sans: list[str]) -> tuple[list[Board], list[Move], str]:
    """Positions before every move and after the last; stops quietly at the first unresolvable move."""
    board, side, _castling, ep = parse_fen(fen)
    first = side
    boards, moves = [board], []
    for san in sans:
        try:
            mv = resolve_san(board, side, san, ep)
        except ValueError:
            break
        ep = None
        if mv.piece.upper() == "P" and abs(mv.to[1] - mv.frm[1]) == 2:
            ep = (mv.frm[0], (mv.frm[1] + mv.to[1]) // 2)
        board = apply(board, mv)
        boards.append(board)
        moves.append(mv)
        side = "b" if side == "w" else "w"
    return boards, moves, first


def parse_puzzle(d: dict[str, Any], kind: str = "daily") -> Puzzle:
    fen = str(d.get("fen") or "")
    boards, moves, side = replay(fen, pgn_moves(str(d.get("pgn") or "")))
    return Puzzle(
        title=re.sub(r"[^\x20-\x7e]", "", str(d.get("title") or "")).strip() or "PUZZLE",
        url=str(d.get("url") or ""),
        fen=fen,
        side=side,
        boards=boards,
        moves=moves,
        published=int(d.get("publish_time") or 0),
        kind=kind,
    )


# ------------------------------------------------------------------------------ provider
class ChessProvider(Provider[dict[str, Puzzle]]):
    """``value = {"daily": Puzzle, "random": Puzzle}`` (whichever were asked for)."""

    name = "chess"
    interval = 3600.0
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.kinds: set[str] = {"daily"}
        self.random_every = 0.0  # seconds; 0 = only on request
        self._random_at = 0.0
        self._want_new = False

    def want(self, kind: str, random_every: float = 0.0) -> None:
        new = kind not in self.kinds
        self.kinds.add(kind)
        self.random_every = random_every
        if new or (self.value is not None and kind not in self.value):
            self.refresh()

    def next_random(self) -> None:
        self._want_new = True
        self.kinds.add("random")
        self.refresh()

    def next_interval(self) -> float:
        if "random" in self.kinds and self.random_every:
            return max(5.0, min(self.interval, self._random_at + self.random_every - time.time()))
        return self.interval

    async def _get(self, url: str, kind: str) -> Puzzle:
        r = await self.hub.http.get(url)
        r.raise_for_status()
        p = parse_puzzle(r.json(), kind)
        if not p.moves:
            raise ValueError(f"{kind}: solution unreadable")
        return p

    async def fetch(self) -> dict[str, Puzzle]:
        out = dict(self.value or {})
        now = time.time()
        errors = []
        if "daily" in self.kinds:
            try:
                out["daily"] = await self._get(DAILY, "daily")
            except Exception as e:
                errors.append(f"daily: {type(e).__name__}: {e}")
        stale = self.random_every and now - self._random_at >= self.random_every
        if "random" in self.kinds and ("random" not in out or self._want_new or stale):
            for _ in range(3):  # skip the odd puzzle whose PGN we can't replay
                try:
                    out["random"] = await self._get(RANDOM, "random")
                    self._random_at = now
                    self._want_new = False
                    break
                except Exception as e:
                    errors.append(f"random: {type(e).__name__}: {e}")
        if errors and not out:
            raise RuntimeError("; ".join(errors)[:200])
        return out
