# Packaging, releases and updates spec (`packaging/`, `desktop.py`, `updates.py`, `release.yml`)

Parent: [root SPEC.md](../SPEC.md). How: [docs/RELEASING.md](../docs/RELEASING.md) (the one-command release),
[docs/DEPLOY.md](../docs/DEPLOY.md) § Installers, § Releases, § How in-app updates work; [docs/API.md](../docs/API.md) § Updates. Android signing: [android spec](../android/SPEC.md).

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
- **R-REL-10** `scripts/release.py <version>` does the whole release in order (PR → CI → merge → tag → GitHub build →
  APK → publish → website), saves its progress and carries on from the first unfinished step; `--only` redoes one part,
  `--dry-run` / `--status` change nothing. Tests: `tests/test_release_script.py::test_plan_resumes_after_the_last_done_step`,
  `tests/test_release_script.py::test_run_marks_steps_done_and_a_stop_keeps_the_rest`,
  `tests/test_release_script.py::test_cli_refuses_another_version_while_one_is_in_progress`.
- **R-REL-11** The version bump edits exactly `pyproject.toml`, `src/deskdot/__init__.py`, `uv.lock` (the deskdot entry)
  and the README badge; the release stops unless WHATS_NEW.md has a well-shaped plain-words section for the version.
  Tests: `tests/test_release_script.py::test_version_bump_edits_exactly_the_version_files`,
  `tests/test_release_script.py::test_whats_new_section_detection`,
  `tests/test_release_script.py::test_whats_new_lint_catches_structure_and_jargon`,
  `tests/test_release_script.py::test_the_real_whats_new_for_the_current_version_passes`.
- **R-REL-12** The release script never merges without the owner's y (or `--yes`) and never deploys the website to
  production without `--deploy` or a y at a prompt that names the Netlify cost; `--yes` doesn't deploy. Tests:
  `tests/test_release_script.py::test_merge_never_happens_without_a_yes`,
  `tests/test_release_script.py::test_merge_after_y_or_with_yes`,
  `tests/test_release_script.py::test_production_deploy_only_when_asked`,
  `tests/test_release_script.py::test_yes_does_not_deploy_the_website`.
- **R-REL-13** A CI failure on the release PR or the GitHub build stops the release with the failing lines. Tests:
  `tests/test_release_script.py::test_ci_failure_shows_the_failing_lines_and_stops`,
  `tests/test_release_script.py::test_ci_waits_with_backoff_then_passes`.
- **R-REL-14** Release asset names are the ones the in-app updater picks per platform (the watch APK,
  `DeskDot-Wear-<v>.apk`, is never picked by the phone); APK checksums are added to `checksums.txt` (replacing an
  older line), and a release missing a file or a checksum isn't published. An APK not signed with the release key
  stops the release. Tests: `tests/test_release_script.py::test_asset_names_are_what_the_in_app_updater_picks`,
  `tests/test_release_script.py::test_checksum_append_replaces_an_older_line_for_the_same_file`,
  `tests/test_release_script.py::test_publish_appends_apk_checksums_uploads_and_checks_every_asset`,
  `tests/test_release_script.py::test_publish_refuses_a_release_with_a_missing_file`,
  `tests/test_release_script.py::test_cert_digest_from_apksigner_and_keytool`.
- **R-REL-15** Android's XML resources and manifests must be well-formed (no "--" inside comments) before anything is
  tagged: CI's `android-resources` job and the release script's checks run `scripts/check_android_res.py`. Tests:
  `tests/test_release_script.py::test_android_xml_check_rejects_double_dash_in_comments`, the `android-resources`
  job of `.github/workflows/ci.yml`.
- **R-REL-16** When all four `ANDROID_*` secrets exist, `release.yml`'s `android` job builds the phone (and watch) APK,
  checks it is signed with the release key, attaches it and deletes the key; without them the job is skipped and the
  release still drafts. Tests: the `android` job of `.github/workflows/release.yml` (no unit test: needs the secrets).

## Invariants

- **I-REL-1** No signing secret in git, and none printed. Windows / macOS certificates are optional repository
  secrets; the Android release key stays on the maintainer's machine unless the owner adds the four `ANDROID_*`
  secrets on purpose.
- **I-REL-2** Releases come only from tags on `main`; a draft is checked (every file, the APK and its checksum
  added) before it is published.
- **I-REL-3** WHATS_NEW.md is the user-facing list in plain words; CHANGELOG.md is the technical log. Both change in
  the release PR.
- **I-REL-4** Tests, `legacy/`, the MCP server and Android/browser-only modules are not shipped in the desktop build;
  SPEC.md files aren't either.

## Interfaces

`GET /api/updates`, `POST /api/updates/check`, `PUT /api/updates`, `POST /api/updates/install`; `state.updates`;
release assets `DeskDot-Setup-<v>-x64.exe`, `DeskDot-<v>-macOS-{arm64,x64}.dmg`, `DeskDot-<v>.apk`,
`DeskDot-Wear-<v>.apk` (once the watch module exists), `checksums.txt`; `scripts/release.py` (its state in
`tmp/release/state.json`); `scripts/check_android_res.py`.

## Open questions

- Builds are unsigned (SmartScreen / Gatekeeper warnings on first start) until certificates exist.

Last verified: 2026-10-31
