"""Release DeskDot everywhere with one command: laptop (Windows), Mac, Android phone (+ watch), website.

    uv run python scripts/release.py 3.10.0          # release 3.10.0 (write its WHATS_NEW.md section first)
    uv run python scripts/release.py --next minor    # 3.9.0 → 3.10.0 (or --next patch → 3.9.1)
    uv run python scripts/release.py                 # carry on with the release in progress
    uv run python scripts/release.py --status        # where the release is
    uv run python scripts/release.py 3.10.0 --dry-run   # the plan, nothing is done
    uv run python scripts/release.py --only android  # redo one part: github | android | website
    uv run python scripts/release.py --deploy        # also put the website live (costs 15 Netlify credits)

The guide in plain words: docs/RELEASING.md. Every step prints what it is doing, saves its progress in
tmp/release/state.json (git-ignored), and the next run carries on from the first step that isn't done.

Safe by default: nothing is merged unless you type y (or pass --yes), the website goes live only with --deploy or
a y at its prompt, nothing is force-pushed, no secret is printed, keystore files are never added to git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "tmp" / "release" / "state.json"
WEBSITE_DIR = ROOT.parent / "idotmatrix-website"
WEBSITE_BRANCH = "website"
MIN_FREE_RAM = 2 * 1024**3
NETLIFY_PROD_CREDITS = 15

#: files the version bump edits, and nothing else
VERSION_FILES = ("pyproject.toml", "src/deskdot/__init__.py", "uv.lock", "README.md")
#: files the owner may have edited before running (they go into the release PR)
NOTES_FILES = ("WHATS_NEW.md", "CHANGELOG.md")


# ================================================================== versions


_VER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> tuple[int, int, int]:
    m = _VER.match(text.strip())
    if not m:
        raise ValueError(f"{text!r} isn't a version like 3.10.0")
    return int(m[1]), int(m[2]), int(m[3])


def next_version(current: str, part: str) -> str:
    major, minor, patch = parse_version(current)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"--next takes major, minor or patch, not {part!r}")


def version_code(version: str) -> int:
    """The Android versionCode android/app/build.gradle.kts derives from __version__."""
    major, minor, patch = parse_version(version)
    return major * 10000 + minor * 100 + patch


def current_version(root: Path = ROOT) -> str:
    text = (root / "src/deskdot/__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__ = "([^"]+)"', text, re.M)
    if not m:
        raise RuntimeError("src/deskdot/__init__.py has no __version__")
    return m[1]


def _edit(path: Path, pattern: str, repl: str, *, count: int = 0, flags: int = re.M) -> None:
    with path.open(encoding="utf-8", newline="") as f:  # keep the file's own line endings
        text = f.read()
    new, n = re.subn(pattern, repl, text, count=count, flags=flags)
    if n == 0:
        raise RuntimeError(f"couldn't find the version in {path.name}")
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(new)


def bump_files(root: Path, new: str) -> list[str]:
    """Write `new` into exactly VERSION_FILES. The Android versionCode follows from __init__.py by itself."""
    parse_version(new)
    _edit(root / "pyproject.toml", r'^(version = ")[^"]+(")', rf"\g<1>{new}\g<2>", count=1)
    _edit(root / "src/deskdot/__init__.py", r'^(__version__ = ")[^"]+(")', rf"\g<1>{new}\g<2>", count=1)
    _edit(root / "uv.lock", r'(^name = "deskdot"\r?\nversion = ")[^"]+(")', rf"\g<1>{new}\g<2>", count=1)
    _edit(root / "README.md", r"(\[!\[Version )[\w.+-]+(\])", rf"\g<1>{new}\g<2>")
    _edit(root / "README.md", r"(badge/version-)[\w.+]+(-)", rf"\g<1>{new}\g<2>")
    return list(VERSION_FILES)


# ================================================================== WHATS_NEW.md


_HEADING = re.compile(r"^## (\S+) — (\d{1,2} [A-Z][a-z]{2} \d{4}) · (.+)$")
_JARGON = re.compile(
    r"`|\b\w+\.(py|ts|tsx|kt|js|mjs|yml|toml)\b|\bsrc/|\bR-[A-Z]+-\d|\bPR ?#\d|\brefactor|\bendpoint\b|"
    r"\bpydantic\b|\basyncio\b|\bregex\b",
    re.I,
)


def whats_new_section(text: str, version: str) -> str | None:
    """The `## <version> …` section of WHATS_NEW.md (heading included), or None."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"## {version} "):
            out = [line]
            for rest in lines[i + 1 :]:
                if rest.startswith("## "):
                    break
                out.append(rest)
            return "\n".join(out).strip() + "\n"
    return None


def lint_whats_new(section: str) -> tuple[list[str], list[str]]:
    """(problems that stop the release, things worth a second look) for one WHATS_NEW section."""
    errors: list[str] = []
    warnings: list[str] = []
    lines = section.splitlines()
    if not lines or not _HEADING.match(lines[0]):
        errors.append("the heading must look like '## 3.10.0 — 7 Nov 2026 · One-line headline'")
    groups = [ln[4:].strip() for ln in lines if ln.startswith("### ")]
    if not groups:
        errors.append("it needs at least one '### New', '### Better' or '### Fixed' group")
    for g in groups:
        if g not in ("New", "Better", "Fixed"):
            errors.append(f"'### {g}': use New, Better or Fixed")
    items = [ln for ln in lines if ln.startswith("- **")]
    if not items:
        errors.append("it has no items ('- **Title**' with 'Before:' and 'Now:' lines under it)")
    if items and not any(ln.strip().startswith("- Now:") for ln in lines):
        errors.append("items need a '- Now:' line saying what changed, in plain words")
    for ln in lines[1:]:
        m = _JARGON.search(ln)
        if m:
            warnings.append(f"developer words ({m.group(0)!r}) in: {ln.strip()[:90]}")
    return errors, warnings


# ================================================================== release assets


def asset_names(version: str, *, watch: bool = False) -> dict[str, str]:
    """What each platform's file on the GitHub release is called (src/deskdot/updates.py picks them by these names).

    The watch APK deliberately doesn't match the phone's `DeskDot-<v>.apk` pattern, so a phone never offers it.
    """
    names = {
        "windows": f"DeskDot-Setup-{version}-x64.exe",
        "macos-arm64": f"DeskDot-{version}-macOS-arm64.dmg",
        "macos-x64": f"DeskDot-{version}-macOS-x64.dmg",
        "android": f"DeskDot-{version}.apk",
    }
    if watch:
        names["wear"] = f"DeskDot-Wear-{version}.apk"
    return names


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def append_checksums(text: str, new: dict[str, str]) -> str:
    """checksums.txt (`sha256sum` format) with `new` {name: sha256} added; an older line for the same name goes."""
    keep = []
    for line in text.splitlines():
        m = re.match(r"^[0-9a-fA-F]{64}\s+\*?(.+?)\s*$", line.strip())
        if m and m[1] in new:
            continue
        if line.strip():
            keep.append(line.rstrip())
    keep += [f"{sha.lower()}  {name}" for name, sha in new.items()]
    return "\n".join(keep) + "\n"


def checksum_names(text: str) -> set[str]:
    return {
        m[1]
        for line in text.splitlines()
        if (m := re.match(r"^[0-9a-fA-F]{64}\s+\*?(.+?)\s*$", line.strip()))
    }


def read_properties(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "!")) and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().replace("\\:", ":").replace("\\\\", "\\")
    return out


def cert_digest(text: str) -> str | None:
    """The SHA-256 certificate digest from `apksigner verify --print-certs` or `keytool -list -v`, as lower hex."""
    m = re.search(r"SHA-?256(?: digest)?:\s*([0-9A-Fa-f:]{64,95})", text)
    return m[1].replace(":", "").lower() if m else None


# ================================================================== steps and state


@dataclass(frozen=True)
class Step:
    id: str
    part: str  # github | android | website
    title: str


STEPS: tuple[Step, ...] = (
    Step("pr", "github", "Open the release pull request (version bump + WHATS_NEW)"),
    Step("ci", "github", "Wait for CI on the pull request"),
    Step("merge", "github", "Merge the pull request (asks you first)"),
    Step("tag", "github", "Tag the release and push the tag"),
    Step("build", "github", "Wait for GitHub to build the Windows installer and the two Mac disk images"),
    Step(
        "android",
        "android",
        "Build and sign the Android APK(s) here (skipped when GitHub already signed them)",
    ),
    Step("publish", "github", "Add the APK(s) and their checksums, publish the release as the latest"),
    Step("website_sync", "website", "Bring the website copy up to date (cherry-pick the new main commits)"),
    Step("website_build", "website", "Rebuild the web app (/app) and the website pages"),
    Step("website_preview", "website", "Free preview deploy of the website"),
    Step(
        "website_prod",
        "website",
        f"Production deploy of the website (only if you say so: {NETLIFY_PROD_CREDITS} credits)",
    ),
)
STEP_IDS = tuple(s.id for s in STEPS)
#: done once, never redone by `--only`
ONE_WAY = ("pr", "ci", "merge", "tag")
#: `--only android` rebuilds the APKs and re-attaches them
PARTS = {
    "github": [s.id for s in STEPS if s.part == "github"],
    "android": ["android", "publish"],
    "website": [s.id for s in STEPS if s.part == "website"],
}


@dataclass
class State:
    version: str
    done: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def finished(self) -> bool:
        return all(s in self.done for s in STEP_IDS if s != "website_prod")

    def to_json(self) -> dict[str, Any]:
        return {"version": self.version, "done": self.done, "data": self.data}


def load_state(path: Path | None = None) -> State | None:
    path = path or STATE_FILE
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
        return State(j["version"], list(j.get("done", [])), dict(j.get("data", {})))
    except (OSError, ValueError, KeyError):
        return None


def save_state(state: State, path: Path | None = None) -> None:
    path = path or STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_json(), indent=2) + "\n", encoding="utf-8")


def plan(state: State, only: str | None = None) -> list[str]:
    """The step ids this run does, in order. `only` redoes one part even where it was done before (except the
    one-way steps: a merged pull request and a pushed tag stay done)."""
    if only:
        return [s for s in PARTS[only] if not (s in ONE_WAY and s in state.done)]
    return [s for s in STEP_IDS if s not in state.done]


# ================================================================== the release


class Stop(Exception):
    """Stop here with a message in plain words; the next run carries on from this step."""


Runner = Callable[..., subprocess.CompletedProcess]


def _default_run(cmd: Sequence[str], **kw: Any) -> subprocess.CompletedProcess:
    exe = shutil.which(cmd[0]) or cmd[0]  # npm.cmd, gradlew.bat, gh.exe on Windows
    return subprocess.run([exe, *cmd[1:]], **kw)


def _default_ask(prompt: str) -> bool:
    if not sys.stdin.isatty():
        print(prompt + " (no terminal to ask in: taking that as no)")
        return False
    return input(prompt + " ").strip().lower() in ("y", "yes")


class Release:
    def __init__(
        self,
        state: State,
        *,
        root: Path = ROOT,
        website: Path = WEBSITE_DIR,
        yes: bool = False,
        deploy: bool = False,
        run: Runner = _default_run,
        ask: Callable[[str], bool] = _default_ask,
        sleep: Callable[[float], None] = time.sleep,
        state_file: Path | None = None,
        out: Callable[[str], None] = print,
    ) -> None:
        self.state = state
        self.v = state.version
        self.tag = f"v{state.version}"
        self.branch = f"release/v{state.version}"
        self.root = root
        self.website = website
        self.yes = yes
        self.deploy = deploy
        self._run = run
        self.ask = ask
        self.sleep = sleep
        self.state_file = state_file or STATE_FILE
        self.say = out
        self.out_dir = root / "tmp" / "release" / self.tag

    # ---------------------------------------------------------------- helpers

    def sh(
        self,
        *cmd: str,
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
        quiet=False,
    ) -> str:
        """Run a command, return its stdout. Only the command is printed — never env values."""
        if not quiet:
            self.say(f"    $ {' '.join(cmd)}")
        full_env = {**os.environ, **env} if env else None
        p = self._run(list(cmd), cwd=str(cwd or self.root), capture_output=True, text=True, env=full_env)
        if check and p.returncode != 0:
            tail = "\n".join(((p.stderr or "") + (p.stdout or "")).strip().splitlines()[-15:])
            raise Stop(f"`{' '.join(cmd[:3])}…` failed:\n{tail}")
        return (p.stdout or "").strip()

    def gh_json(self, *args: str, quiet: bool = True) -> Any:
        text = self.sh("gh", *args, quiet=quiet)
        return json.loads(text) if text else None

    def save(self) -> None:
        save_state(self.state, self.state_file)

    def mark(self, step: str) -> None:
        if step not in self.state.done:
            self.state.done.append(step)
        self.save()

    def wait(
        self,
        what: str,
        poll: Callable[[], str | None],
        *,
        timeout: float = 3600,
        first: float = 15,
        most: float = 120,
    ) -> str:
        """Poll until `poll` returns a result (not None). Waits 15 s, then a bit longer each time, up to 2 min."""
        delay, waited = first, 0.0
        while True:
            result = poll()
            if result is not None:
                return result
            if waited >= timeout:
                raise Stop(
                    f"gave up waiting for {what} after {int(waited // 60)} min; run again to keep waiting"
                )
            self.say(f"    … {what}: still running, checking again in {int(delay)} s")
            self.sleep(delay)
            waited += delay
            delay = min(delay * 1.5, most)

    def failed_lines(self, run_id: str) -> str:
        log = self.sh("gh", "run", "view", run_id, "--log-failed", check=False, quiet=True)
        hits = [ln for ln in log.splitlines() if re.search(r"FAILED|Error|error:|assert|failed|✗", ln)]
        return "\n".join(ln[-200:] for ln in (hits or log.splitlines())[-40:])

    # ---------------------------------------------------------------- checks

    def preflight(self, steps: list[str]) -> None:
        self.say("Checking everything is ready")
        problems: list[str] = []
        need_gh = any(s in steps for s in ("pr", "ci", "merge", "tag", "build", "android", "publish"))
        if need_gh and self._run(["gh", "auth", "status"], capture_output=True, text=True).returncode != 0:
            problems.append("GitHub CLI isn't logged in: run `gh auth login`")
        if "pr" in steps:
            problems += self.check_repo()
            problems += self.check_notes()
            problems += self.check_android_xml()
        elif "tag" in steps:
            problems += self.check_android_xml()
        if "android" in steps:
            tools = self.check_android_tools()
            if "build" in steps:  # GitHub may sign the APK itself (docs/RELEASING.md § Signing in CI)
                for p in tools:
                    self.say(f"  note: {p} — fine only if GitHub signs the APK (the ANDROID_* secrets)")
            else:
                problems += tools
        if any(s.startswith("website") for s in steps):
            problems += self.check_website()
        if problems:
            raise Stop("Not ready yet:\n" + "\n".join(f"  - {p}" for p in problems))
        self.say("  ready")

    def check_repo(self) -> list[str]:
        problems = []
        self.sh("git", "fetch", "--quiet", "origin", "--tags", quiet=True)
        branch = self.sh("git", "rev-parse", "--abbrev-ref", "HEAD", quiet=True)
        dirty = [
            ln[3:].strip()
            for ln in self.sh("git", "status", "--porcelain", quiet=True).splitlines()
            if ln.strip() and ln[3:].strip() not in NOTES_FILES
        ]
        if dirty:
            problems.append(
                "uncommitted changes (only WHATS_NEW.md and CHANGELOG.md may be edited): " + ", ".join(dirty)
            )
        if branch == self.branch:
            pass  # a run that stopped right after creating the branch
        elif branch != "main":
            problems.append(f"you're on {branch!r}: switch to main first (`git switch main`)")
        elif self.sh("git", "rev-parse", "HEAD", quiet=True) != self.sh(
            "git", "rev-parse", "origin/main", quiet=True
        ):
            problems.append(
                "main isn't the same as GitHub's main: `git pull --ff-only` (and push or drop local commits)"
            )
        try:
            cur = current_version(self.root)
            if parse_version(self.v) <= parse_version(cur) and branch != self.branch:
                problems.append(f"{self.v} isn't newer than the current version {cur}")
        except ValueError as e:
            problems.append(str(e))
        if self.sh("git", "tag", "-l", self.tag, quiet=True):
            problems.append(f"the tag {self.tag} already exists")
        return problems

    def check_notes(self) -> list[str]:
        text = (self.root / "WHATS_NEW.md").read_text(encoding="utf-8")
        section = whats_new_section(text, self.v)
        if section is None:
            return [
                f"WHATS_NEW.md has no section for {self.v}: add '## {self.v} — <d Mon yyyy> · <headline>' with "
                "New / Better / Fixed items (Before: / Now:) — the format is at the top of the file"
            ]
        errors, warnings = lint_whats_new(section)
        for w in warnings:
            self.say(f"  note: WHATS_NEW.md has {w} — users read this, keep it plain")
        if not re.search(
            rf"^## {re.escape(self.v)} ", (self.root / "CHANGELOG.md").read_text(encoding="utf-8"), re.M
        ):
            self.say(f"  note: CHANGELOG.md has no '## {self.v}' entry (the technical log); worth adding")
        return [f"WHATS_NEW.md {self.v}: {e}" for e in errors]

    def check_android_xml(self) -> list[str]:
        sys.path.insert(0, str(self.root / "scripts"))
        try:
            import check_android_res
        finally:
            sys.path.pop(0)
        return [f"Android: {p}" for p in check_android_res.check(self.root / "android")]

    def java_home(self) -> Path | None:
        for cand in (
            os.environ.get("DESKDOT_JAVA_HOME"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "DotDeckAndroid", "jdk")
            if os.environ.get("LOCALAPPDATA")
            else None,
            os.environ.get("JAVA_HOME"),
        ):
            if cand and (Path(cand) / "bin").is_dir():
                return Path(cand)
        return None

    def sdk_dir(self) -> Path | None:
        lp = self.root / "android" / "local.properties"
        sdk = read_properties(lp).get("sdk.dir") if lp.is_file() else None
        sdk = sdk or os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        return Path(sdk) if sdk and Path(sdk).is_dir() else None

    def check_android_tools(self, *, local: bool = False) -> list[str]:
        if self.state.data.get("ci_signed_apk") and not local:
            return []
        problems = []
        if not (self.root / "android" / "keystore.properties").is_file():
            problems.append(
                "android/keystore.properties is missing (release signing; android/README.md § Release signing)"
            )
        if self.java_home() is None:
            problems.append(
                "no JDK 17: expected %LOCALAPPDATA%\\DotDeckAndroid\\jdk (or set DESKDOT_JAVA_HOME)"
            )
        if self.sdk_dir() is None:
            problems.append("no Android SDK: set sdk.dir in android/local.properties")
        if shutil.which("npm") is None:
            problems.append("npm isn't installed (the studio is built into the APK)")
        return problems

    def check_website(self) -> list[str]:
        w = self.website
        if not (w / ".git").exists():
            return [f"the website copy isn't at {w} (pass --website-dir)"]
        problems = []
        branch = self.sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=w, quiet=True)
        if branch != WEBSITE_BRANCH:
            problems.append(f"the website copy is on {branch!r}, not {WEBSITE_BRANCH!r}")
        if self.sh("git", "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD", cwd=w, check=False, quiet=True):
            problems.append(
                "the website copy is in the middle of a cherry-pick: fix the files, then "
                "`git cherry-pick --continue` (or `--abort`) there, and run this again"
            )
        elif self.sh("git", "status", "--porcelain", "--untracked-files=no", cwd=w, quiet=True):
            problems.append(f"the website copy has uncommitted changes ({w})")
        return problems

    def free_ram(self) -> int | None:
        try:
            import psutil

            return int(psutil.virtual_memory().available)
        except Exception:
            return None

    # ---------------------------------------------------------------- github steps

    def step_pr(self) -> None:
        pr = self.find_pr()
        if pr:
            self.state.data.update(pr=pr["number"], pr_url=pr["url"])
            self.say(f"  the pull request is already open: {pr['url']}")
            if self.sh("git", "rev-parse", "--abbrev-ref", "HEAD", quiet=True) == self.branch:
                self.sh("git", "switch", "main")
            return
        branch = self.sh("git", "rev-parse", "--abbrev-ref", "HEAD", quiet=True)
        if branch != self.branch:
            self.sh("git", "switch", "-c", self.branch)
        if current_version(self.root) != self.v:
            changed = bump_files(self.root, self.v)
            self.say(
                f"  version {self.v} written to {', '.join(changed)} (Android versionCode {version_code(self.v)})"
            )
            self.sh("git", "add", "--", *changed, *NOTES_FILES)
            self.sh("git", "commit", "-m", f"DeskDot {self.v}")
        self.sh("git", "push", "-u", "origin", self.branch)
        section = whats_new_section((self.root / "WHATS_NEW.md").read_text(encoding="utf-8"), self.v) or ""
        headline = section.splitlines()[0].split("·", 1)[-1].strip() if section else ""
        body = (
            f"Release {self.v}: {headline}\n\n"
            f"This sets the version to {self.v} everywhere (the Android app's version code becomes "
            f"{version_code(self.v)}) and carries the WHATS_NEW.md section users will read.\n\n"
            "After it's merged, `scripts/release.py` tags it; GitHub then builds the Windows installer and the "
            "Mac disk images, the Android APK is added and the release is published (docs/RELEASING.md).\n\n"
            "🤖 Opened by scripts/release.py"
        )
        url = self.sh(
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            self.branch,
            "--title",
            f"DeskDot {self.v}",
            "--body",
            body,
        )
        m = re.search(r"/pull/(\d+)", url)
        if not m:
            raise Stop(f"couldn't read the pull request number from: {url}")
        self.state.data.update(pr=int(m[1]), pr_url=url.strip())
        self.say(f"  opened {url.strip()}")
        self.sh("git", "switch", "main")

    def find_pr(self) -> dict[str, Any] | None:
        prs = self.gh_json(
            "pr",
            "list",
            "--head",
            self.branch,
            "--state",
            "all",
            "--json",
            "number,url,state",
            "--limit",
            "1",
        )
        return prs[0] if prs else None

    def pr_state(self) -> str:
        return str(self.gh_json("pr", "view", str(self.state.data["pr"]), "--json", "state")["state"])

    def step_ci(self) -> None:
        pr = str(self.state.data["pr"])
        if self.pr_state() == "MERGED":
            self.say("  already merged")
            return

        def poll() -> str | None:
            p = self._run(
                ["gh", "pr", "checks", pr, "--json", "name,bucket,link"],
                capture_output=True,
                text=True,
                cwd=str(self.root),
            )
            try:
                checks = json.loads(p.stdout or "[]")
            except ValueError:
                checks = []
            if not checks:
                return None  # not started yet
            buckets = {c["bucket"] for c in checks}
            if "fail" in buckets or "cancel" in buckets:
                bad = [c for c in checks if c["bucket"] in ("fail", "cancel")]
                lines = []
                for c in bad:
                    m = re.search(r"/runs/(\d+)", c.get("link", ""))
                    lines.append(f"  ✗ {c['name']}  {c.get('link', '')}")
                    if m:
                        lines.append(self.failed_lines(m[1]))
                raise Stop(
                    "CI failed on the release pull request:\n" + "\n".join(lines) + "\nFix it on the branch "
                    f"{self.branch} (push a commit), then run this again."
                )
            if "pending" in buckets:
                return None
            return "green"

        self.wait("CI", poll, timeout=90 * 60)
        self.say("  CI is green")

    def step_merge(self) -> None:
        pr = self.state.data["pr"]
        if self.pr_state() == "MERGED":
            self.say("  already merged")
        else:
            url = self.state.data.get("pr_url", f"#{pr}")
            if not (self.yes or self.ask(f"  Merge release PR #{pr} ({url})? [y/N]")):
                raise Stop(f"Not merged. Run this again when you want to merge PR #{pr}.")
            self.sh("gh", "pr", "merge", str(pr), "--squash", "--delete-branch")
        if self.sh("git", "rev-parse", "--abbrev-ref", "HEAD", quiet=True) != "main":
            self.sh("git", "switch", "main")
        self.sh("git", "pull", "--ff-only", "origin", "main")

    def step_tag(self) -> None:
        if self.sh("git", "ls-remote", "--tags", "origin", f"refs/tags/{self.tag}", quiet=True):
            self.say(f"  {self.tag} is already on GitHub")
            return
        self.sh("git", "fetch", "--quiet", "origin", "main", quiet=True)
        code = self.sh("git", "show", "origin/main:src/deskdot/__init__.py", quiet=True)
        if f'__version__ = "{self.v}"' not in code:
            raise Stop(f"GitHub's main isn't at {self.v} yet (is the pull request merged?)")
        problems = self.check_android_xml()
        if problems:
            raise Stop("The Android build would fail, so nothing is tagged:\n" + "\n".join(problems))
        prev = self.sh("git", "describe", "--tags", "--abbrev=0", "origin/main", check=False, quiet=True)
        if prev:
            self.state.data["prev_tag"] = prev
        if not self.sh("git", "tag", "-l", self.tag, quiet=True):
            self.sh("git", "tag", "-a", self.tag, "-m", f"DeskDot {self.v}", "origin/main")
        self.sh("git", "push", "origin", self.tag)

    def release_assets(self) -> dict[str, Any]:
        j = self.gh_json("release", "view", self.tag, "--json", "assets,isDraft,url")
        return {
            "names": [a["name"] for a in j.get("assets", [])],
            "draft": j.get("isDraft"),
            "url": j.get("url"),
        }

    def step_build(self) -> None:
        def poll() -> str | None:
            runs = (
                self.gh_json(
                    "run",
                    "list",
                    "--workflow",
                    "release.yml",
                    "--limit",
                    "20",
                    "--json",
                    "databaseId,status,conclusion,headBranch,url",
                )
                or []
            )
            mine = [r for r in runs if r.get("headBranch") == self.tag]
            if not mine:
                return None
            r = mine[0]
            if r["status"] != "completed":
                return None
            if r["conclusion"] != "success":
                raise Stop(
                    f"The GitHub build failed ({r['url']}):\n{self.failed_lines(str(r['databaseId']))}\n"
                    f"Fix it, then `gh run rerun {r['databaseId']} --failed` (or tag again after a fix PR), "
                    "and run this again."
                )
            return str(r["url"])

        url = self.wait("the GitHub build (Windows + Mac, ~25 min)", poll, timeout=120 * 60, first=60)
        names = self.release_assets()["names"]
        self.say(f"  built: {url}\n  on the draft release: {', '.join(names)}")
        self.state.data["ci_signed_apk"] = asset_names(self.v)["android"] in names

    # ---------------------------------------------------------------- android

    def has_watch(self) -> bool:
        return (self.root / "android" / "wear" / "build.gradle.kts").is_file()

    def step_android(self) -> None:
        names = asset_names(self.v, watch=self.has_watch())
        if self.state.data.get("ci_signed_apk") and "android" not in (self.state.data.get("redo") or []):
            self.say("  GitHub built and signed the APK(s) already; nothing to build here")
            return
        problems = self.check_android_tools(local=True)
        if problems:
            raise Stop("Can't build the APK here:\n" + "\n".join(f"  - {p}" for p in problems))
        free = self.free_ram()
        if free is not None and free < MIN_FREE_RAM:
            raise Stop(
                f"Only {free / 1024**3:.1f} GB of memory is free; the Android build needs 2 GB. Close the browser "
                "or the engine (ask first if the panel is in use), then run this again."
            )
        java = self.java_home()
        env = {"JAVA_HOME": str(java)}
        self.say("  building the studio (it goes inside the APK)")
        web = self.root / "web"
        if not (web / "node_modules").is_dir():
            self.sh("npm", "ci", cwd=web)
        self.sh("npm", "run", "build", cwd=web)
        tasks = [":app:assembleRelease"] + ([":wear:assembleRelease"] if self.has_watch() else [])
        gradlew = self.root / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
        self.say("  building the APK(s) — a few minutes")
        self.sh(str(gradlew), "--no-daemon", *tasks, cwd=self.root / "android", env=env)
        built = {"android": self.root / "android/app/build/outputs/apk/release" / names["android"]}
        if "wear" in names:
            wear = sorted((self.root / "android/wear/build/outputs/apk/release").glob("*.apk"))
            if not wear:
                raise Stop("the watch build made no APK in android/wear/build/outputs/apk/release")
            built["wear"] = wear[-1]
        self.out_dir.mkdir(parents=True, exist_ok=True)
        expected = self.release_key_digest()
        apks = {}
        for kind, path in built.items():
            if not path.is_file():
                raise Stop(f"the build didn't produce {path}")
            got = self.apk_digest(path)
            if got != expected:
                raise Stop(
                    f"{path.name} isn't signed with the DeskDot release key (got {got}, expected {expected}). "
                    "Phones would refuse the update. Check android/keystore.properties."
                )
            dest = self.out_dir / names[kind]
            shutil.copyfile(path, dest)
            apks[names[kind]] = sha256_file(dest)
            self.say(f"  {names[kind]}: signed with the release key ✓  sha256 {apks[names[kind]][:12]}…")
        self.state.data["apks"] = apks

    def release_key_digest(self) -> str:
        """The release certificate's SHA-256, read with keytool (the password goes through an env var, never argv)."""
        props = read_properties(self.root / "android" / "keystore.properties")
        store = Path(props["storeFile"])
        if not store.is_absolute():
            store = self.root / "android" / "app" / store
        keytool = str(self.java_home() / "bin" / ("keytool.exe" if os.name == "nt" else "keytool"))
        text = self.sh(
            keytool,
            "-list",
            "-v",
            "-keystore",
            str(store),
            "-alias",
            props["keyAlias"],
            "-storepass:env",
            "DESKDOT_KS_PASS",
            env={"DESKDOT_KS_PASS": props["storePassword"]},
            quiet=True,
        )
        digest = cert_digest(text)
        if not digest:
            raise Stop("couldn't read the release key's fingerprint with keytool")
        return digest

    def apk_digest(self, apk: Path) -> str | None:
        sdk = self.sdk_dir()
        tools = sorted((sdk / "build-tools").iterdir()) if sdk and (sdk / "build-tools").is_dir() else []
        if not tools:
            raise Stop("no Android build-tools (apksigner) in the SDK")
        apksigner = tools[-1] / ("apksigner.bat" if os.name == "nt" else "apksigner")
        env = {"JAVA_HOME": str(self.java_home())}
        return cert_digest(self.sh(str(apksigner), "verify", "--print-certs", str(apk), env=env, quiet=True))

    # ---------------------------------------------------------------- publish

    def step_publish(self) -> None:
        apks: dict[str, str] = self.state.data.get("apks") or {}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if apks:
            self.sh(
                "gh",
                "release",
                "download",
                self.tag,
                "-p",
                "checksums.txt",
                "-D",
                str(self.out_dir),
                "--clobber",
            )
            sums = self.out_dir / "checksums.txt"
            sums.write_text(
                append_checksums(sums.read_text(encoding="utf-8"), apks), encoding="ascii", newline="\n"
            )
            files = [str(self.out_dir / n) for n in apks] + [str(sums)]
            self.say("  uploading " + ", ".join(Path(f).name for f in files))
            self.sh("gh", "release", "upload", self.tag, *files, "--clobber")
        info = self.release_assets()
        names = set(info["names"])
        want = set(asset_names(self.v, watch=self.has_watch()).values()) | {"checksums.txt"}
        missing = sorted(want - names)
        if missing:
            raise Stop(f"the release is missing {', '.join(missing)}; not publishing")
        self.sh(
            "gh",
            "release",
            "download",
            self.tag,
            "-p",
            "checksums.txt",
            "-D",
            str(self.out_dir),
            "--clobber",
            quiet=True,
        )
        listed = checksum_names((self.out_dir / "checksums.txt").read_text(encoding="utf-8"))
        unlisted = sorted(n for n in names - {"checksums.txt"} if n not in listed)
        if unlisted:
            raise Stop(
                f"checksums.txt doesn't list {', '.join(unlisted)}; the in-app updater would refuse them"
            )
        if info["draft"]:
            self.sh("gh", "release", "edit", self.tag, "--draft=false", "--latest")
            self.say(f"  published {info['url']}: every DeskDot that checks for updates now offers {self.v}")
        else:
            self.say(f"  already published: {info['url']}")

    # ---------------------------------------------------------------- website

    def step_website_sync(self) -> None:
        w = self.website
        prev = self.state.data.get("prev_tag") or self.sh(
            "git", "describe", "--tags", "--abbrev=0", f"{self.tag}^", check=False, quiet=True
        )
        if not prev:
            raise Stop("no earlier release tag to start from; cherry-pick by hand this once")
        picked: list[str] = self.state.data.setdefault("website_picked", [])
        pending = self.state.data.pop("website_pending", None)
        if pending:  # last run stopped on a conflict; did the owner finish it?
            subject = self.sh("git", "log", "-1", "--format=%s", pending, quiet=True)
            if (
                subject
                in self.sh("git", "log", "-30", "--format=%s", WEBSITE_BRANCH, cwd=w, quiet=True).splitlines()
            ):
                picked.append(pending)
        out = self.sh("git", "cherry", WEBSITE_BRANCH, self.tag, prev, cwd=w, quiet=True)
        todo = [ln[2:].strip() for ln in out.splitlines() if ln.startswith("+ ")]
        todo = [c for c in todo if c not in picked]
        if not todo:
            self.say("  the website copy already has every change since " + prev)
        for sha in todo:
            subject = self.sh("git", "log", "-1", "--format=%s", sha, quiet=True)
            self.say(f"  cherry-pick {sha[:9]} {subject}")
            p = self._run(["git", "cherry-pick", sha], cwd=str(w), capture_output=True, text=True)
            if p.returncode != 0:
                self.state.data["website_pending"] = sha
                self.save()
                files = self.sh(
                    "git", "diff", "--name-only", "--diff-filter=U", cwd=w, check=False, quiet=True
                )
                raise Stop(
                    f"The website copy can't take {sha[:9]} ({subject}) by itself; these files conflict:\n"
                    + "\n".join(f"  {f}" for f in files.splitlines())
                    + f"\nIn {w}: fix those files, `git add` them, `git cherry-pick --continue`, then run "
                    "`uv run python scripts/release.py --only website`. To give up on it: `git cherry-pick --abort`."
                )
            picked.append(sha)
            self.save()

    def step_website_build(self) -> None:
        w = self.website
        free = self.free_ram()
        if free is not None and free < MIN_FREE_RAM:
            raise Stop(f"Only {free / 1024**3:.1f} GB of memory is free; the web app build needs 2 GB.")
        for script in ("build_webapp.py", "build_site_data.py", "build_site_pages.py"):
            self.say(f"  {script}")
            self.sh("uv", "run", "python", f"scripts/{script}", cwd=w)
        self.sh("git", "add", "-A", "--", "site", cwd=w)
        staged = self.sh("git", "diff", "--cached", "--name-only", cwd=w, quiet=True).splitlines()
        if any(re.search(r"\.(jks|keystore|p12|pem)$|keystore\.properties$", f) for f in staged):
            raise Stop("a key file is staged in the website copy; refusing to commit it")
        if staged:
            self.sh("git", "commit", "-m", f"Website: /app and pages rebuilt for DeskDot {self.v}", cwd=w)
        else:
            self.say("  nothing changed in site/")

    def netlify(self) -> list[str]:
        return ["netlify"] if shutil.which("netlify") else ["npx", "--yes", "netlify-cli"]

    def step_website_preview(self) -> None:
        out = self.sh(
            *self.netlify(),
            "deploy",
            "--dir",
            "site",
            "--functions",
            "netlify/functions",
            "--json",
            "--message",
            f"DeskDot {self.v} preview",
            cwd=self.website,
        )
        m = re.search(r"\{.*\}", out, re.S)
        url = json.loads(m[0]).get("deploy_url") if m else None
        if not url:
            raise Stop(f"Netlify didn't say where the preview is:\n{out[-500:]}")
        self.state.data["preview_url"] = url
        self.say(f"  preview (free): {url}\n  Look at it (home page, /app/, What's new) before going live.")

    def step_website_prod(self) -> bool:
        prompt = (
            f"  Put the website live at idotmatrix.com? It costs {NETLIFY_PROD_CREDITS} of the month's 300 Netlify "
            "credits. [y/N]"
        )
        if not (self.deploy or self.ask(prompt)):
            self.say("  not deployed. Later: `uv run python scripts/release.py --only website --deploy`")
            return False
        self.sh(
            *self.netlify(),
            "deploy",
            "--prod",
            "--dir",
            "site",
            "--functions",
            "netlify/functions",
            "--message",
            f"DeskDot {self.v}",
            cwd=self.website,
        )
        self.say("  live at https://idotmatrix.com")
        return True

    # ---------------------------------------------------------------- run

    def run(self, steps: list[str]) -> None:
        self.preflight(steps)
        for i, sid in enumerate(steps, 1):
            step = next(s for s in STEPS if s.id == sid)
            self.say(f"\n[{i}/{len(steps)}] {step.title}")
            needs_pr = sid in ("ci", "merge") and "pr" not in self.state.data
            if needs_pr:
                pr = self.find_pr()
                if not pr:
                    raise Stop("there's no release pull request yet; run without --only first")
                self.state.data.update(pr=pr["number"], pr_url=pr["url"])
            result = getattr(self, f"step_{sid}")()
            if result is False:  # declined (website_prod): not done, nothing after it
                self.save()
                continue
            self.mark(sid)
        self.say(f"\nDone: DeskDot {self.v}.")


# ================================================================== command line


def print_plan(state: State, steps: list[str], out: Callable[[str], None] = print) -> None:
    out(f"Release DeskDot {state.version}: the plan")
    for s in STEPS:
        mark = "do" if s.id in steps else ("done" if s.id in state.done else "skip")
        out(f"  [{mark:>4}] {s.part:<8} {s.title}")


def print_status(state: State | None, out: Callable[[str], None] = print) -> None:
    if state is None:
        out("No release in progress.")
        return
    out(f"DeskDot {state.version}: {len(state.done)} of {len(STEPS)} steps done")
    for s in STEPS:
        out(f"  [{'x' if s.id in state.done else ' '}] {s.title}")
    for k in ("pr_url", "preview_url"):
        if state.data.get(k):
            out(f"  {k.replace('_', ' ')}: {state.data[k]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", nargs="?", help="the new version, e.g. 3.10.0 (leave out to carry on)")
    ap.add_argument(
        "--next", choices=("major", "minor", "patch"), help="the next version after the current one"
    )
    ap.add_argument("--dry-run", action="store_true", help="print the plan, do nothing")
    ap.add_argument("--status", action="store_true", help="where the release in progress is")
    ap.add_argument("--only", choices=tuple(PARTS), help="redo one part")
    ap.add_argument("--yes", action="store_true", help="merge the release PR without asking")
    ap.add_argument(
        "--deploy", action="store_true", help=f"put the website live ({NETLIFY_PROD_CREDITS} credits)"
    )
    ap.add_argument(
        "--website-dir", type=Path, default=WEBSITE_DIR, help="the website worktree (branch website)"
    )
    ap.add_argument(
        "--reset", action="store_true", help="forget the saved progress (nothing on GitHub is undone)"
    )
    a = ap.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    saved = load_state()
    if a.status:
        print_status(saved)
        return 0
    if a.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        saved = None
        print("Forgot the saved progress.")
    try:
        version = a.version or (next_version(current_version(), a.next) if a.next else None)
        if version:
            parse_version(version)
    except ValueError as e:
        print(e)
        return 2
    if saved and not saved.finished() and version and version != saved.version and not a.only:
        print(
            f"A release of {saved.version} is in progress ({len(saved.done)} steps done). Carry on with "
            f"`uv run python scripts/release.py`, or start over with --reset."
        )
        return 2
    if version is None:
        if saved is None:
            ap.print_usage()
            print("Give the version to release, e.g. `uv run python scripts/release.py 3.10.0`.")
            return 2
        version = saved.version
    state = saved if saved and saved.version == version else State(version)
    steps = plan(state, a.only)
    if a.dry_run:
        print_plan(state, steps)
        return 0
    if not steps:
        print(f"DeskDot {version} is fully released. (`--only website --deploy` puts the website live.)")
        return 0
    if a.only:
        state.done = [s for s in state.done if s not in steps]
        state.data["redo"] = [a.only]
    rel = Release(state, website=a.website_dir, yes=a.yes, deploy=a.deploy)
    try:
        rel.run(steps)
    except Stop as e:
        rel.save()
        print(f"\nStopped: {e}")
        print("Run the same command again to carry on from here (`--status` shows where it is).")
        return 1
    except KeyboardInterrupt:
        rel.save()
        print("\nInterrupted; run again to carry on.")
        return 130
    finally:
        state.data.pop("redo", None)
        rel.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
