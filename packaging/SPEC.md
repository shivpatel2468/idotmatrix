# Packaging, releases and updates spec (`packaging/`, `desktop.py`, `updates.py`, `release.yml`)

Parent: [root SPEC.md](../SPEC.md). How: [docs/DEPLOY.md](../docs/DEPLOY.md) § Installers, § Releases, § How in-app
updates work; [docs/API.md](../docs/API.md) § Updates. Android signing: [android spec](../android/SPEC.md).

## Purpose

People who don't want a terminal install DeskDot from a GitHub release (Windows installer, macOS dmg, Android APK) and
update it from inside the app. Developers release by pushing a version tag on `main`.

## Requirements

- **R-REL-1** A release is a tag `v<version>` on `main`; `release.yml` refuses a tag that doesn't match
  `src/deskdot/__init__.py` or has no `## <version>` section in WHATS_NEW.md, runs ruff + the fast tests, builds the
  studio, the Windows installer and both dmgs (each smoke-tested on `/api/health`), writes `checksums.txt` and creates
  a **draft** release with that WHATS_NEW section. Tests: the `checks` job of `.github/workflows/release.yml`.
- **R-REL-2** The frozen app writes only to its own data folder (`%LOCALAPPDATA%\DeskDot`,
  `~/Library/Application Support/DeskDot`, or `DESKDOT_HOME`), never to the install folder; first run copies the
  example config once. Tests: `tests/test_desktop.py::test_home_dir_per_platform`,
  `tests/test_desktop.py::test_first_run_copies_the_example_once`.
- **R-REL-3** Every CLI command still works in the frozen build. Tests: `tests/test_desktop.py::test_frozen_commands`.
- **R-REL-4** The update check asks GitHub at most every 6 h (opt-out), copes with no releases and offline, and
  compares versions correctly. Tests: `tests/test_updates.py::test_check_caches_for_six_hours`,
  `tests/test_updates.py::test_no_releases_yet_and_offline`, `tests/test_updates.py::test_version_comparison`.
- **R-REL-5** Install downloads only this platform's asset from this repo's releases over https, verifies its SHA-256
  against `checksums.txt` (or a sidecar), and refuses a mismatch, a missing checksum, a plain-http redirect, a source
  install or an up-to-date install. Tests: `tests/test_updates.py::test_asset_selection_per_platform`,
  `tests/test_updates.py::test_assets_outside_the_repo_are_ignored`,
  `tests/test_updates.py::test_checksum_mismatch_is_refused`, `tests/test_updates.py::test_missing_checksums_is_refused`,
  `tests/test_updates.py::test_sidecar_sha256_is_accepted`, `tests/test_updates.py::test_redirect_to_plain_http_is_refused`,
  `tests/test_updates.py::test_source_and_up_to_date_installs_are_refused`.
- **R-REL-6** The hand-off to the installer exits the engine the normal way (the panel gets its hand-off); the macOS
  swap script quotes paths. Tests: `tests/test_updates.py::test_install_downloads_verifies_and_hands_off`,
  `tests/test_updates.py::test_mac_swap_script_quotes_paths`, `tests/test_updates.py::test_install_kind_detection`.
- **R-REL-7** The updates API reports state and installs only on request. Tests: `tests/test_updates.py::test_updates_api`.
- **R-REL-8** The shipped example config contains no personal values. Tests:
  `tests/test_desktop.py::test_the_repo_example_config_has_no_personal_values`.
- **R-REL-9** Start-with-login is written only when the user enables it. Tests:
  `tests/test_launcher.py::test_launcher_main_never_writes_autostart_by_default`,
  `tests/test_launcher.py::test_autostart_windows_registry_only_when_enabled`.

## Invariants

- **I-REL-1** No signing secret in git. Windows / macOS certificates are optional repository secrets; the Android
  release key is never a CI secret and never leaves the maintainer's machine.
- **I-REL-2** Releases come only from tags on `main`; a draft is reviewed (files, notes, the APK and its checksum
  added) before it is published.
- **I-REL-3** WHATS_NEW.md is the user-facing list in plain words; CHANGELOG.md is the technical log. Both change in
  the release PR.
- **I-REL-4** Tests, `legacy/`, the MCP server and Android/browser-only modules are not shipped in the desktop build;
  SPEC.md files aren't either.

## Interfaces

`GET /api/updates`, `POST /api/updates/check`, `PUT /api/updates`, `POST /api/updates/install`; `state.updates`;
release assets `DeskDot-Setup-<v>-x64.exe`, `DeskDot-<v>-macOS-{arm64,x64}.dmg`, `DeskDot-<v>.apk`, `checksums.txt`.

## Open questions

- Builds are unsigned (SmartScreen / Gatekeeper warnings on first start) until certificates exist.

Last verified: 2026-10-29
