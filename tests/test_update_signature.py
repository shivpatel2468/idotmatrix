"""The update-signature check (src/deskdot/update_signature.py, ADR 0017).

Signatures here come from throwaway keys made by `cryptography` (never the real release key), so the plain-Python
verifier is checked against an independent implementation.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature

from deskdot import update_signature as S

ROOT = Path(__file__).resolve().parents[1]
KOTLIN = ROOT / "android/app/src/main/java/com/deskdot/app/ReleaseVerifier.kt"


def _pub(key: ec.EllipticCurvePrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(der).decode()


def test_signatures_from_cryptography_verify_and_anything_else_does_not() -> None:
    key, other = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    pub = _pub(key)
    for i in range(5):
        msg = f"{'ab' * 32}  DeskDot-3.{i}.0.apk\n".encode()
        sig = key.sign(msg, ec.ECDSA(hashes.SHA256()))
        assert S.verify(msg, sig, pub)
        assert not S.verify(msg + b" ", sig, pub)  # one byte more
        assert not S.verify(msg, sig, _pub(other))  # another key
        r, s = decode_dss_signature(sig)
        assert not S.verify(msg, encode_dss_signature(r, (s + 1) % S._N), pub)
        assert not S.verify(msg, encode_dss_signature(0, s), pub)  # out of range
        assert not S.verify(msg, sig[:-1], pub)  # truncated DER
        assert not S.verify(msg, sig + b"\x00", pub)  # trailing bytes


def test_signature_file_and_checksums_are_signed() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    sums = b"0" * 64 + b"  DeskDot-Setup-3.11.0-x64.exe\n"
    sig_file = base64.b64encode(key.sign(sums, ec.ECDSA(hashes.SHA256()))) + b"\r\n"
    assert S.checksums_are_signed(sums, sig_file, (_pub(key),))
    # a second trusted key (only while moving to a new key) doesn't weaken anything
    assert S.checksums_are_signed(sums, sig_file, (_pub(ec.generate_private_key(ec.SECP256R1())), _pub(key)))
    assert not S.checksums_are_signed(sums.replace(b"0", b"1", 1), sig_file, (_pub(key),))
    assert not S.checksums_are_signed(sums, b"", (_pub(key),))
    assert not S.checksums_are_signed(sums, b"%%%", (_pub(key),))
    assert not S.checksums_are_signed(sums, sig_file, ())


def test_public_keys_must_be_p256() -> None:
    with pytest.raises(ValueError):
        S.public_point("not base64!")
    other_curve = ec.generate_private_key(ec.SECP384R1())
    with pytest.raises(ValueError):
        S.public_point(_pub(other_curve))  # type: ignore[arg-type]
    # a point that isn't on the curve
    good = base64.b64decode(_pub(ec.generate_private_key(ec.SECP256R1())))
    bad = good[:-1] + bytes([good[-1] ^ 1])
    with pytest.raises(ValueError):
        S.public_point(base64.b64encode(bad).decode())


def test_the_built_in_key_is_a_valid_p256_key_and_the_android_app_has_the_same_one() -> None:
    assert S.RELEASE_KEYS, "the apps need at least one release key"
    for k in S.RELEASE_KEYS:
        S.public_point(k)
    kotlin = KOTLIN.read_text(encoding="utf-8")
    block = re.search(r"val RELEASE_KEYS = listOf\((.*?)\)", kotlin, re.S)
    assert block, "ReleaseVerifier.kt must list RELEASE_KEYS"
    kt_keys = ["".join(re.findall(r'"([^"]*)"', part)) for part in block[1].split(",") if '"' in part]
    assert kt_keys == list(S.RELEASE_KEYS)
