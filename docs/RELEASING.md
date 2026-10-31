# Releasing DeskDot

One command ships a new version to every device: the Windows laptop, both kinds of Mac, the Android phone (and the
Wear OS watch once it exists), the browser version and the website.

## To release

1. Write the new version's section at the top of **WHATS_NEW.md** (the format is in the comment at the top of that
   file: `## 3.10.0 — 7 Nov 2026 · One-line headline`, then New / Better / Fixed items with *Before:* and *Now:*), and
   its entry in CHANGELOG.md. Leave them uncommitted, or commit them in a normal PR first. Either works.
2. On `main`, up to date with GitHub, run:

   ```powershell
   uv run python scripts/release.py 3.10.0       # or: --next minor / --next patch
   ```

3. Answer **y** twice: once to merge the release pull request, once to put the website live (that one costs 15 of
   the month's 300 Netlify credits; answer n to keep only the free preview).

That's it. It takes about 40 minutes, most of it waiting for GitHub to build the installers. If it stops, read the
message, fix what it says, and **run the same command again**: it carries on from where it stopped.

```powershell
uv run python scripts/release.py --status            # where the release is
uv run python scripts/release.py 3.10.0 --dry-run    # the plan, nothing is done
uv run python scripts/release.py --only android      # redo one part: github | android | website
uv run python scripts/release.py --only website --deploy   # put the website live later
uv run python scripts/release.py --reset             # forget the saved progress (nothing on GitHub is undone)
```

`--yes` merges without asking (it never deploys the website: only `--deploy` or a typed y does that).
`--website-dir` points at the website copy if it isn't at `..\idotmatrix-website`.

## What each step does

| Step | What happens |
| --- | --- |
| Checks | GitHub CLI logged in; on `main`, the same as GitHub's, nothing uncommitted except WHATS_NEW.md / CHANGELOG.md; the WHATS_NEW section exists, has the right shape and reads as plain words (it warns about code words like file names); Android's XML is well-formed (`scripts/check_android_res.py`); the JDK, Android SDK, `android/keystore.properties` and npm are there; the website copy is clean and on its branch. |
| Release pull request | Branch `release/v<version>`: the version goes into `pyproject.toml`, `src/deskdot/__init__.py` (the Android version code follows from it: 3.10.0 → 31000), `uv.lock` and the README badge, with your WHATS_NEW / CHANGELOG edits. Pushed, and a pull request opened. |
| CI | Waits for the checks on the pull request (every 15 s, then a bit longer each time, up to 2 min). If one fails, it prints the failing lines and stops; push a fix to the branch and run again. |
| Merge | Asks **Merge release PR #N? [y/N]**. Nothing is merged unless you type y (or passed `--yes`). Squash-merges and updates your `main`. |
| Tag | Checks GitHub's `main` really has the new version and Android's XML is fine, then tags `v<version>` and pushes only the tag. |
| GitHub build | `release.yml` runs the checks again, builds the Windows installer, the Apple-silicon and Intel Mac disk images (each one started and asked `/api/health`), writes `checksums.txt` and makes a **draft** release with the WHATS_NEW section as its notes. About 25 minutes. If it fails it shows the failing lines; `gh run rerun <id> --failed`, then run again. |
| Android | Skipped when GitHub already signed the APK (see below). Otherwise: needs 2 GB of free memory, builds the studio (`npm run build`, it goes inside the APK), then `gradlew assembleRelease` with the JDK in `%LOCALAPPDATA%\DotDeckAndroid\jdk`. The watch APK too, once `android/wear` exists. Then it checks each APK is signed with the release key (`apksigner` against `keytool`'s fingerprint of the keystore): an APK signed with any other key stops the release, because phones would refuse it as an update. |
| Publish | Adds each APK's SHA-256 to `checksums.txt`, uploads them, checks the release has every file and that `checksums.txt` lists all of them, then publishes it as the latest release. |
| Website: catch up | In the website copy (`..\idotmatrix-website`, branch `website`), cherry-picks the commits between the previous release tag and this one that it doesn't have yet. On a conflict it stops and lists the files (see below). |
| Website: rebuild | `scripts/build_webapp.py` (the browser version at /app), `build_site_data.py`, `build_site_pages.py`, and commits `site/`. |
| Website: preview | A free Netlify preview deploy; prints its address. Look at it: the home page, /app/ and What's new. |
| Website: live | Only with `--deploy`, or if you type y at the prompt that says it costs 15 credits. |

Progress is saved in `tmp/release/state.json` (git-ignored); the APKs and `checksums.txt` are kept in
`tmp/release/v<version>/`. Nothing is ever force-pushed, no password is printed (the keystore password reaches
`keytool` through an environment variable), and no keystore file is ever added to git.

## How people get it

| Device | File on the release | How it arrives |
| --- | --- | --- |
| Windows laptop | `DeskDot-Setup-<v>-x64.exe` | Settings → Device → Updates offers it within 6 hours; Install runs the installer and restarts DeskDot |
| Mac (Apple silicon / Intel) | `DeskDot-<v>-macOS-arm64.dmg` / `…-x64.dmg` | the same; the app is swapped in place |
| Android phone | `DeskDot-<v>.apk` | the same; Android's installer opens (same signing key, so it updates in place) |
| Wear OS watch | `DeskDot-Wear-<v>.apk` | named so the phone never mistakes it for its own update |
| Browser (idotmatrix.com/app/) | — | the website deploy; open tabs offer a reload |
| From source / Raspberry Pi | — | `git pull`, `uv sync`, `cd web && npm run build`, restart |

Every download is checked against `checksums.txt` before it's installed (src/deskdot/updates.py).

## When it stops

- **CI or the GitHub build failed**: the failing lines are printed. Fix it on the release branch (CI) or in a new
  pull request (build; then tag again by hand or rerun the failed jobs), and run the command again.
- **"Not merged"**: you answered n. Run again when you want to merge.
- **Website conflict**: the website copy couldn't take a commit by itself. In `..\idotmatrix-website`: fix the listed
  files, `git add` them, `git cherry-pick --continue`, then
  `uv run python scripts/release.py --only website`. To skip that commit: `git cherry-pick --abort`.
- **Not enough memory**: close the browser or other big programs (ask before stopping an engine that has the panel)
  and run again.
- **Wrong signing key**: check `android/keystore.properties` points at the release keystore (android/README.md §
  Release signing). Never publish an APK signed with another key.
- Anything else: `--status` shows where it is; each step can be redone on its own with `--only`.

## Signing the APK on GitHub (optional)

By default the APK is built and signed on your machine, and the release key never leaves it. If you'd rather GitHub
did it (no Android toolchain needed on the laptop), add these four repository secrets once. `release.yml`'s `android`
job then builds and signs the phone APK (and the watch APK) and attaches them, and `release.py` skips its local build.
Without all four, the job is skipped and nothing changes.

```powershell
# from the repo folder; each command asks for the value (nothing ends up in your shell history)
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:LOCALAPPDATA\DotDeckAndroid\release\deskdot-release.jks")) | gh secret set ANDROID_KEYSTORE_B64
gh secret set ANDROID_KEYSTORE_PASSWORD
gh secret set ANDROID_KEY_ALIAS          # e.g. deskdot (keyAlias in android/keystore.properties)
gh secret set ANDROID_KEY_PASSWORD
```

The trade-off: anyone who can change the workflow on `main` could then use the key. Keep the backup of the keystore
either way; to stop, `gh secret delete ANDROID_KEYSTORE_B64` (one missing secret switches the job off).

## By hand

The steps the script runs are ordinary commands (each is printed as it runs); docs/DEPLOY.md § Releases lists them.
