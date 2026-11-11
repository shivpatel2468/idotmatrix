"""Is this release's `checksums.txt` really from DeskDot's owner? (ADR 0017, packaging/SPEC.md R-REL-17…19)

At release time `scripts/release.py` signs the final `checksums.txt` with the owner's private key (ECDSA P-256 over
SHA-256) and uploads the signature as `checksums.txt.sig` (base64 of the DER signature, one line). Before installing
anything the in-app updater checks that signature against the public key built in here, then the download's SHA-256
against its line in that same, verified file. Someone who can change the GitHub release can change both files, but
can't make a signature the built-in key accepts.

Verification only (no secret is involved, so constant time doesn't matter), in plain Python so it works the same in
the desktop build, on Android (Chaquopy) and in tests without a new dependency. The Android app checks the APK a
second time in Kotlin (`ReleaseVerifier.kt`, `java.security.Signature("SHA256withECDSA")`) with the same key;
`tests/test_update_signature.py` keeps the two copies of the key equal.
"""

from __future__ import annotations

import base64
import binascii
import hashlib

#: the public half of the owner's update-signing key, base64 SubjectPublicKeyInfo (made once by
#: scripts/make_release_key.py; the private half never leaves the owner's PC). More than one entry only while
#: moving to a new key (ADR 0017 § If the key is lost).
RELEASE_KEYS: tuple[str, ...] = (
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEjyM+LJLWaOWUjObKCIXsAQgpYQCG"
    "gTFqT00Hi9dO1AEgnlaH6wcxO1Lk8LHBSvUf0Uum+37mdPCwZCrWSnRgdw==",
)
SIGNATURE_NAME = "checksums.txt.sig"
#: SubjectPublicKeyInfo header of an uncompressed P-256 (prime256v1) public key; the 65-byte point follows
_SPKI_P256 = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")

# NIST P-256 (FIPS 186-4 D.1.2.3)
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)

Point = tuple[int, int] | None  # None is the point at infinity


def _on_curve(pt: tuple[int, int]) -> bool:
    x, y = pt
    return 0 <= x < _P and 0 <= y < _P and (y * y - (x * x * x + _A * x + _B)) % _P == 0


def _add(p: Point, q: Point) -> Point:
    if p is None:
        return q
    if q is None:
        return p
    x1, y1 = p
    x2, y2 = q
    if x1 == x2:
        if (y1 + y2) % _P == 0:
            return None
        lam = (3 * x1 * x1 + _A) * pow(2 * y1, -1, _P) % _P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (lam * lam - x1 - x2) % _P
    return x3, (lam * (x1 - x3) - y1) % _P


def _mul(k: int, p: Point) -> Point:
    out: Point = None
    while k:
        if k & 1:
            out = _add(out, p)
        p = _add(p, p)
        k >>= 1
    return out


def public_point(spki_b64: str) -> tuple[int, int]:
    """The curve point of a base64 P-256 SubjectPublicKeyInfo. ValueError for anything else."""
    try:
        der = base64.b64decode(spki_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("the public key isn't base64") from e
    if len(der) != len(_SPKI_P256) + 65 or not der.startswith(_SPKI_P256) or der[len(_SPKI_P256)] != 4:
        raise ValueError("not an uncompressed P-256 public key")
    raw = der[len(_SPKI_P256) + 1 :]
    pt = int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    if not _on_curve(pt):
        raise ValueError("the public key isn't on the P-256 curve")
    return pt


def _der_int(buf: bytes, i: int) -> tuple[int, int]:
    if i + 2 > len(buf) or buf[i] != 0x02:
        raise ValueError("bad signature")
    n = buf[i + 1]
    body = buf[i + 2 : i + 2 + n]
    if (
        n == 0
        or n > 33
        or len(body) != n
        or body[0] & 0x80
        or (n > 1 and body[0] == 0 and not body[1] & 0x80)
    ):
        raise ValueError("bad signature")  # empty, too long, negative or not minimal
    return int.from_bytes(body, "big"), i + 2 + n


def parse_signature(der: bytes) -> tuple[int, int]:
    """(r, s) from a DER ECDSA signature (what Java's SHA256withECDSA and `cryptography` produce). Strict."""
    if len(der) < 8 or der[0] != 0x30 or der[1] != len(der) - 2:
        raise ValueError("bad signature")
    r, i = _der_int(der, 2)
    s, i = _der_int(der, i)
    if i != len(der):
        raise ValueError("bad signature")
    return r, s


def verify(message: bytes, signature_der: bytes, spki_b64: str) -> bool:
    """True when `signature_der` is a valid ECDSA P-256 / SHA-256 signature of `message` by that public key."""
    try:
        q = public_point(spki_b64)
        r, s = parse_signature(signature_der)
    except ValueError:
        return False
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, _N)
    xy = _add(_mul(e * w % _N, _G), _mul(r * w % _N, q))
    return xy is not None and xy[0] % _N == r


def decode_signature_file(text: bytes) -> bytes:
    """The DER bytes in a `checksums.txt.sig` (one line of base64). ValueError if it isn't that."""
    try:
        raw = base64.b64decode(b"".join(text.split()), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("the signature file isn't base64") from e
    if not raw:
        raise ValueError("the signature file is empty")
    return raw


def checksums_are_signed(
    checksums: bytes, signature_file: bytes, keys: tuple[str, ...] = RELEASE_KEYS
) -> bool:
    """True when `signature_file` (the `checksums.txt.sig` asset) signs exactly these `checksums.txt` bytes with one
    of the built-in keys."""
    try:
        der = decode_signature_file(signature_file)
    except ValueError:
        return False
    return any(verify(checksums, der, k) for k in keys)
