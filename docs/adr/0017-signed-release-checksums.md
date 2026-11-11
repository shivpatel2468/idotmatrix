# ADR 0017: Sign each release's checksums.txt; the apps install only what the owner signed

- **Status:** Proposed (accept after the first signed release has updated a Windows PC, a Mac and the phone)
- **Date:** 2026-11-11
- **Changes:** how in-app updates decide a download is genuine (packaging/SPEC.md R-REL-5, android/SPEC.md R-AND-7)

## Context

Every release carries `checksums.txt` (the SHA-256 of each file). The in-app updaters (`src/deskdot/updates.py` on
Windows, macOS and inside the Android app; `Updater.kt` on the phone) downloaded the installer and compared its
SHA-256 with that file. That catches a broken download, but not a hostile one: anyone who can change the GitHub
release (a stolen token, a compromised account or workflow) can replace the installer **and** its line in
`checksums.txt`, and every DeskDot would install it on the next *Install*. On Android, the "same signing key" check
protects the phone app; Windows and Mac installers have no such check (they are unsigned until certificates exist).

## Decision

**The owner signs the final `checksums.txt` on his own PC; the apps refuse any update whose `checksums.txt` isn't
signed by the key built into them.**

- **Algorithm: ECDSA on P-256 with SHA-256**, signature in DER, published as `checksums.txt.sig` (one line of
  base64). Why this one:
  - Android verifies it with `java.security.Signature("SHA256withECDSA")` and `KeyFactory("EC")`, present on every
    Android version the app supports (minSdk 26) with no library. Ed25519 is not available from the platform's
    built-in providers across that range (it is a recent addition), so it would need a new library on the phone —
    ruled out.
  - The desktop and Chaquopy apps verify in plain Python (`src/deskdot/update_signature.py`, ~100 lines: the curve
    arithmetic and a strict DER parser). Verification has no secret in it, so constant-time code isn't needed. That
    keeps `cryptography` (a compiled wheel; no Chaquopy build we ship) out of the installers and the APK. The tests
    check this verifier against `cryptography`'s signatures, and Kotlin's against Java's.
  - Signing needs `cryptography`, which the developer environment has (dev dependency group); it never ships.
- **What is signed:** exactly the bytes of `checksums.txt` as it will be published, after the APK lines are added.
  `scripts/release.py` signs it in its *publish* step, uploads `checksums.txt.sig`, downloads both files back from
  GitHub and checks them with the apps' own verifier and built-in key before it publishes. A draft that fails that
  check is not published.
- **What the apps check before installing** (all of it, or nothing is installed, the download is deleted and the
  current version keeps running, with a one-sentence message):
  1. `checksums.txt` and `checksums.txt.sig` are assets of this repository's release (HTTPS, as before);
  2. the signature is valid for `checksums.txt` under a built-in public key;
  3. the installer's file name carries the release's version (so an older, genuinely signed installer can't be
     replayed under a new tag to downgrade people);
  4. the installer's SHA-256 equals its line in that verified file.
  The `<asset>.sha256` side file is no longer accepted (it isn't signed). On Android, the Kotlin side
  (`ReleaseVerifier.kt`) repeats 2 and 4 with the same key before it opens the system installer, and then still
  requires the same APK signing key as before.
- **The public key** is in two places, `RELEASE_KEYS` in `src/deskdot/update_signature.py` and in
  `ReleaseVerifier.kt`; `tests/test_update_signature.py` fails if they differ. The browser app has no installer to
  verify (it updates with the website) and has no key.
- **The private key** was made once on the owner's PC by `scripts/make_release_key.py` and lives outside every git
  checkout, next to the Android release key: `%LOCALAPPDATA%\DotDeckAndroid\release\deskdot-update-signing.pem`.
  The checkout finds it through the git-ignored `release-signing.local.toml` (`key_file = '…'`), the same way
  `android/keystore.properties` points at the keystore. It is never printed, logged, committed, uploaded or put in
  GitHub Actions secrets; `release.py` only reads it to sign. It is not encrypted with a passphrase, for the same
  reason the keystore's password sits in `keystore.properties`: the protection is that the file never leaves the
  owner's PC and its backup.

## Transition

- **Releases made before this have no `checksums.txt.sig`.** An app with this change refuses to install them
  automatically ("This release isn't signed…; you can download the new one from GitHub yourself"). That only matters
  if someone runs the new app against an old release, which can't happen in the normal order: the first release that
  contains this code is also the first one `release.py` signs.
- **Apps already installed (3.10.2 and older)** don't know about signatures. They keep updating exactly as before,
  checking only `checksums.txt` — including to the first signed release, which still has a correct `checksums.txt`.
  From that version on, every update is signature-checked. So the protection starts with the *second* signed
  release for people updating from an old version; nothing breaks on the way.

## If the key is lost (or leaks)

- **Lost:** no update can be signed. Apps with the old key refuse every new release, so people must download the new
  version from GitHub by hand once. Recovery: make a new key (`scripts/make_release_key.py --key <new path>`), put its
  public key into both `RELEASE_KEYS` lists, release; from then on that version updates itself again. Hence the
  backup: the owner keeps a copy of the `.pem` in his private keys folder.
- **Leaked:** the same steps, and the release notes ask people to install the new version by hand. To make a future
  change smoother, both lists may hold two keys for one release while moving from the old to the new one.

## Consequences

- Changing a GitHub release can no longer make DeskDot install something the owner didn't sign; the attacker would
  also need the key on the owner's PC.
- `release.py` refuses to start a release that would publish (`publish` in the plan) unless the key is there, is a
  P-256 key and is the one built into the apps.
- The apps do one more small download (`checksums.txt.sig`, ~100 bytes) per install; verifying takes ~50 ms.
- GitHub's own build provenance (artifact attestations) is a separate, complementary check of *where* an installer
  was built; it doesn't replace this, because the apps can't verify it offline and the APK is built on the owner's PC.
