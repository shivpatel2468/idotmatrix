"""Make the release-signing key pair, once (docs/RELEASING.md § The update-signing key, ADR 0017).

    uv run python scripts/make_release_key.py            # writes the key, points this checkout at it
    uv run python scripts/make_release_key.py --show     # prints the PUBLIC key of the key already made

`scripts/release.py` signs every release's `checksums.txt` with this key, and the apps refuse an update whose
signature doesn't check out against the public key built into them (`src/deskdot/update_signature.py`,
`android/app/src/main/java/com/deskdot/app/ReleaseVerifier.kt`).

The private key goes OUTSIDE every git checkout, next to the Android release key:
`%LOCALAPPDATA%\\DotDeckAndroid\\release\\deskdot-update-signing.pem` (or `--key`). This checkout's git-ignored
`release-signing.local.toml` records where it is. Nothing here ever prints, logs or copies the private key: only
the public key is printed, so it can be put into the apps.

It never overwrites an existing key: a new key means apps already installed can no longer check updates
(ADR 0017 § If the key is lost).
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_NAME = "release-signing.local.toml"
KEY_NAME = "deskdot-update-signing.pem"


def default_key_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "DotDeckAndroid" / "release" / KEY_NAME


def inside_git_checkout(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in [path, *path.parents])


def public_key_b64(private_key) -> str:
    from cryptography.hazmat.primitives import serialization

    der = private_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(der).decode("ascii")


def make_key(key_path: Path) -> str:
    """Write a new P-256 private key to `key_path` (never over an existing file); return the public key (base64
    SubjectPublicKeyInfo). The key file is created with owner-only permissions where the OS supports it."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key_path = key_path.resolve()
    if inside_git_checkout(key_path.parent):
        raise SystemExit(f"Refusing: {key_path.parent} is inside a git checkout. The key must live outside.")
    if key_path.exists():
        raise SystemExit(
            f"A key already exists at {key_path}; not overwriting it. (`--show` prints its public key.)"
        )
    key_path.parent.mkdir(parents=True, exist_ok=True)
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return public_key_b64(private)


def load_public(key_path: Path) -> str:
    from cryptography.hazmat.primitives import serialization

    private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    return public_key_b64(private)


def write_config(root: Path, key_path: Path) -> Path:
    cfg = root / CONFIG_NAME
    cfg.write_text(
        "# Where scripts/release.py finds the update-signing key (git-ignored; never put the key itself here).\n"
        f"key_file = '{key_path.resolve()}'\n",
        encoding="utf-8",
    )
    return cfg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--key", type=Path, default=None, help=f"where to write the key (default: {default_key_path()})"
    )
    ap.add_argument("--show", action="store_true", help="print the public key of the existing key")
    ap.add_argument(
        "--root", type=Path, default=ROOT, help="the checkout whose config should point at the key"
    )
    a = ap.parse_args(argv)
    key_path = a.key or default_key_path()
    if a.show:
        if not key_path.is_file():
            print(f"No key at {key_path}.")
            return 1
        print(load_public(key_path))
        return 0
    public = make_key(key_path)
    cfg = write_config(a.root, key_path)
    print(f"Made the update-signing key: {key_path.resolve()}")
    print(f"This checkout points at it in {cfg} (git-ignored).")
    print("Public key (goes into the apps; safe to share):")
    print(public)
    print(
        "\nBack up the key file into your private keys folder now. Without it no update can be signed, and apps "
        "already installed would need a manual download once (ADR 0017)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
