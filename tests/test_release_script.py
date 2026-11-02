"""scripts/release.py (docs/RELEASING.md) and scripts/check_android_res.py: the one-command release.

Nothing here touches git, GitHub, Gradle or Netlify: every command goes through a fake runner that records it.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from deskdot import updates

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


release = _load("release")
check_android_res = _load("check_android_res")


# ---------------------------------------------------------------- fakes


class FakeRun:
    """Stands in for subprocess.run: answers by command prefix, records every command."""

    def __init__(self, answers: dict[str, object] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        line = " ".join(cmd)
        best = max((k for k in self.answers if line.startswith(k)), key=len, default=None)
        out = self.answers.get(best, "") if best is not None else ""
        if callable(out):
            out = out()
        code = 0
        if isinstance(out, tuple):
            code, out = out
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr="")

    def ran(self, prefix: str) -> bool:
        return any(" ".join(c).startswith(prefix) for c in self.calls)


def make(tmp_path: Path, run: FakeRun, *, asks: list[bool] | None = None, **kw):
    asked: list[str] = []
    answers = list(asks or [])

    def ask(prompt: str) -> bool:
        asked.append(prompt)
        return answers.pop(0) if answers else False

    state = release.State("3.10.0", data={"pr": 42, "pr_url": "https://github.com/o/r/pull/42"})
    rel = release.Release(
        state,
        root=tmp_path,
        website=tmp_path / "web-site",
        run=run,
        ask=ask,
        sleep=lambda s: None,
        state_file=tmp_path / "state.json",
        out=lambda s: None,
        **kw,
    )
    return rel, asked


# ---------------------------------------------------------------- versions


def test_version_bump_edits_exactly_the_version_files(tmp_path):
    for rel_path in (*release.VERSION_FILES, "WHATS_NEW.md", "android/app/build.gradle.kts"):
        dest = tmp_path / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel_path, dest)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    old = release.current_version(tmp_path)

    changed = release.bump_files(tmp_path, "7.8.9")

    assert sorted(changed) == sorted(release.VERSION_FILES)
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    edited = sorted(p.relative_to(tmp_path).as_posix() for p in before if before[p] != after[p])
    assert edited == sorted(release.VERSION_FILES)
    assert release.current_version(tmp_path) == "7.8.9"
    assert 'version = "7.8.9"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    lock = (tmp_path / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "deskdot"\nversion = "7.8.9"' in lock.replace("\r\n", "\n")
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Version 7.8.9" in readme and "badge/version-7.8.9-" in readme and f"version-{old}-" not in readme
    # only the deskdot package's version moved in uv.lock, nothing else
    assert (
        sum(
            a != b
            for a, b in zip(
                before[tmp_path / "uv.lock"].splitlines(), lock.encode().splitlines(), strict=False
            )
        )
        == 1
    )


def test_next_version_and_android_version_code():
    assert release.next_version("3.9.0", "minor") == "3.10.0"
    assert release.next_version("3.9.0", "patch") == "3.9.1"
    assert release.next_version("3.9.4", "major") == "4.0.0"
    assert release.version_code("3.10.0") == 31000 > release.version_code("3.9.0") == 30900
    with pytest.raises(ValueError):
        release.parse_version("3.10")


# ---------------------------------------------------------------- WHATS_NEW


GOOD = """# What's new

## 3.10.0 — 7 Nov 2026 · Faster updates

### New

- **Updates in one click**
  - Before: you downloaded the installer yourself.
  - Now: DeskDot installs the new version for you.

## 3.9.0 — 31 Oct 2026 · Older
"""


def test_whats_new_section_detection():
    section = release.whats_new_section(GOOD, "3.10.0")
    assert section.startswith("## 3.10.0 — 7 Nov 2026")
    assert "3.9.0" not in section
    assert release.whats_new_section(GOOD, "3.11.0") is None
    assert release.whats_new_section(GOOD, "3.1") is None  # "## 3.10.0" isn't "## 3.1 "
    assert release.lint_whats_new(section) == ([], [])


def test_whats_new_lint_catches_structure_and_jargon():
    errors, _ = release.lint_whats_new("## 3.10.0 - headline\n\nsome text\n")
    assert any("heading" in e for e in errors) and any("New" in e for e in errors)
    section = (
        GOOD.split("## 3.9.0")[0]
        .split("\n", 2)[2]
        .replace("installs the new", "calls `updates.py` for the new")
    )
    errors, warnings = release.lint_whats_new(section)
    assert errors == [] and warnings


def test_the_real_whats_new_for_the_current_version_passes():
    text = (ROOT / "WHATS_NEW.md").read_text(encoding="utf-8")
    section = release.whats_new_section(text, release.current_version())
    assert section is not None
    assert release.lint_whats_new(section)[0] == []


# ---------------------------------------------------------------- plan / resume


def test_plan_resumes_after_the_last_done_step(tmp_path):
    state = release.State("3.10.0")
    assert release.plan(state) == list(release.STEP_IDS)
    state.done = ["pr", "ci", "merge"]
    assert release.plan(state)[0] == "tag"
    assert release.plan(state, "android") == ["android", "publish"]
    assert release.plan(state, "website")[0] == "website_sync"
    assert release.plan(state, "github") == ["tag", "build", "publish"]  # a merged PR isn't redone
    path = tmp_path / "s.json"
    release.save_state(state, path)
    again = release.load_state(path)
    assert again.version == "3.10.0" and again.done == ["pr", "ci", "merge"]
    assert release.load_state(tmp_path / "missing.json") is None


def test_run_marks_steps_done_and_a_stop_keeps_the_rest(tmp_path):
    run = FakeRun()
    rel, _ = make(tmp_path, run)
    rel.preflight = lambda steps: None
    rel.step_tag = lambda: None
    rel.step_build = lambda: (_ for _ in ()).throw(release.Stop("build failed"))
    with pytest.raises(release.Stop):
        rel.run(["tag", "build", "android"])
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert saved["done"] == ["tag"]
    assert release.plan(release.load_state(tmp_path / "state.json"))[:4] == ["pr", "ci", "merge", "build"]


def test_cli_refuses_another_version_while_one_is_in_progress(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release, "STATE_FILE", tmp_path / "state.json")
    release.save_state(release.State("3.10.0", ["pr"]), tmp_path / "state.json")
    assert release.main(["3.11.0"]) == 2
    assert "in progress" in capsys.readouterr().out
    assert release.main(["--dry-run"]) == 0  # no version: carries on with 3.10.0
    out = capsys.readouterr().out
    assert "3.10.0" in out and "[done] github   Open the release" in out
    assert release.main(["--status"]) == 0


# ---------------------------------------------------------------- checksums & assets


def test_checksum_append_replaces_an_older_line_for_the_same_file():
    a, b, c = "a" * 64, "b" * 64, "c" * 64
    text = f"{a}  DeskDot-Setup-3.10.0-x64.exe\n{b}  DeskDot-3.10.0.apk\n"
    out = release.append_checksums(text, {"DeskDot-3.10.0.apk": c.upper(), "DeskDot-Wear-3.10.0.apk": a})
    assert out.endswith("\n")
    parsed = updates.parse_checksums(out)  # the in-app updater reads it back
    assert parsed == {
        "DeskDot-Setup-3.10.0-x64.exe": a,
        "DeskDot-3.10.0.apk": c,
        "DeskDot-Wear-3.10.0.apk": a,
    }


def test_asset_names_are_what_the_in_app_updater_picks():
    names = release.asset_names("3.10.0", watch=True)
    # the watch APK first, to prove the phone never picks it
    assets = [
        {"name": n, "browser_download_url": f"{updates.ASSET_PREFIX}v3.10.0/{n}"}
        for n in (names["wear"], *(v for k, v in names.items() if k != "wear"))
    ]
    pick = lambda kind, machine=None: updates.pick_asset(assets, kind, machine)["name"]  # noqa: E731
    assert pick("windows") == names["windows"] == "DeskDot-Setup-3.10.0-x64.exe"
    assert pick("macos", "arm64") == names["macos-arm64"]
    assert pick("macos", "x86_64") == names["macos-x64"]
    assert pick("android") == names["android"] == "DeskDot-3.10.0.apk"
    assert "wear" not in release.asset_names("3.10.0")


def test_cert_digest_from_apksigner_and_keytool():
    hexd = "ab" * 32
    apksigner = f"Signer #1 certificate DN: CN=DeskDot\nSigner #1 certificate SHA-256 digest: {hexd}\n"
    keytool = "Signature algorithm name: SHA256withRSA\n\t SHA256: " + ":".join(["AB"] * 32) + "\n"
    assert release.cert_digest(apksigner) == hexd == release.cert_digest(keytool)
    assert release.cert_digest("nothing here") is None


# ---------------------------------------------------------------- confirmation before merge / deploy


def test_merge_never_happens_without_a_yes(tmp_path):
    run = FakeRun({"gh pr view": '{"state": "OPEN"}', "git rev-parse": "main"})
    rel, asked = make(tmp_path, run, asks=[False])
    with pytest.raises(release.Stop, match="Not merged"):
        rel.step_merge()
    assert asked and "Merge release PR #42" in asked[0]
    assert not run.ran("gh pr merge")


def test_merge_after_y_or_with_yes(tmp_path):
    run = FakeRun({"gh pr view": '{"state": "OPEN"}', "git rev-parse": "main"})
    rel, _ = make(tmp_path, run, asks=[True])
    rel.step_merge()
    assert run.ran("gh pr merge 42 --squash --delete-branch")
    run2 = FakeRun({"gh pr view": '{"state": "OPEN"}', "git rev-parse": "main"})
    rel2, asked = make(tmp_path, run2, yes=True)
    rel2.step_merge()
    assert run2.ran("gh pr merge 42") and asked == []
    assert not any("--force" in c or "-f" in c for c in run.calls + run2.calls)


def test_production_deploy_only_when_asked(tmp_path):
    run = FakeRun()
    rel, asked = make(tmp_path, run, asks=[False])
    assert rel.step_website_prod() is False
    assert "15" in asked[0] and "credits" in asked[0]
    assert not any("--prod" in c for c in run.calls)
    # declined → not marked done, so `--only website --deploy` can do it later
    rel.preflight = lambda steps: None
    rel.run(["website_prod"])
    assert "website_prod" not in rel.state.done

    run2 = FakeRun()
    rel2, asked2 = make(tmp_path, run2, deploy=True)
    assert rel2.step_website_prod() is True
    assert asked2 == [] and any("--prod" in c for c in run2.calls)


def test_yes_does_not_deploy_the_website(tmp_path):
    run = FakeRun()
    rel, _ = make(tmp_path, run, yes=True)
    assert rel.step_website_prod() is False
    assert not any("--prod" in c for c in run.calls)


# ---------------------------------------------------------------- CI waits


def test_ci_waits_with_backoff_then_passes(tmp_path):
    seq = iter(["[]", json.dumps([{"name": "engine", "bucket": "pending", "link": ""}])])
    checks = lambda: next(seq, json.dumps([{"name": "engine", "bucket": "pass", "link": ""}]))  # noqa: E731
    run = FakeRun({"gh pr view": '{"state": "OPEN"}', "gh pr checks": checks})
    rel, _ = make(tmp_path, run)
    slept: list[float] = []
    rel.sleep = slept.append
    rel.step_ci()
    assert len(slept) == 2 and slept[1] > slept[0]


def test_ci_failure_shows_the_failing_lines_and_stops(tmp_path):
    failing = [{"name": "Engine — tests & lint", "bucket": "fail", "link": "https://x/actions/runs/77/job/1"}]
    run = FakeRun(
        {
            "gh pr view": '{"state": "OPEN"}',
            "gh pr checks": json.dumps(failing),
            "gh run view 77 --log-failed": "setup ok\nFAILED tests/test_x.py::test_y - assert 1 == 2\n",
        }
    )
    rel, _ = make(tmp_path, run)
    with pytest.raises(release.Stop) as e:
        rel.step_ci()
    assert "FAILED tests/test_x.py::test_y" in str(e.value) and "Engine" in str(e.value)
    assert not run.ran("gh pr merge")


# ---------------------------------------------------------------- publish


def test_publish_appends_apk_checksums_uploads_and_checks_every_asset(tmp_path):
    names = release.asset_names("3.10.0")
    existing = "".join(f"{'1' * 64}  {n}\n" for k, n in names.items() if k != "android")
    out_dir = tmp_path / "tmp" / "release" / "v3.10.0"

    def download():
        out_dir.mkdir(parents=True, exist_ok=True)
        if not (out_dir / "checksums.txt").exists():
            (out_dir / "checksums.txt").write_text(existing, encoding="ascii")
        return ""

    view = {"assets": [{"name": n} for n in [*names.values(), "checksums.txt"]], "isDraft": True, "url": "u"}
    run = FakeRun({"gh release download": download, "gh release view": json.dumps(view)})
    rel, _ = make(tmp_path, run)
    rel.state.data["apks"] = {names["android"]: "2" * 64}
    rel.step_publish()
    sums = updates.parse_checksums((out_dir / "checksums.txt").read_text(encoding="ascii"))
    assert sums[names["android"]] == "2" * 64 and len(sums) == 4
    assert run.ran("gh release upload v3.10.0")
    assert run.ran("gh release edit v3.10.0 --draft=false --latest")


def test_publish_refuses_a_release_with_a_missing_file(tmp_path):
    names = release.asset_names("3.10.0")
    view = {"assets": [{"name": names["windows"]}, {"name": "checksums.txt"}], "isDraft": True, "url": "u"}
    run = FakeRun({"gh release view": json.dumps(view)})
    rel, _ = make(tmp_path, run)
    with pytest.raises(release.Stop, match="missing"):
        rel.step_publish()
    assert not run.ran("gh release edit")


# ---------------------------------------------------------------- Android XML check


def test_android_xml_check_rejects_double_dash_in_comments(tmp_path):
    bad = '<resources>\n  <!-- page chassis-0 -- header -->\n  <color name="a">#fff</color>\n</resources>\n'
    good = '<resources>\n  <!-- page chassis-0 — header -->\n  <color name="a">#fff</color>\n</resources>\n'
    assert check_android_res.check_text(good) == []
    problems = check_android_res.check_text(bad)
    assert len(problems) == 1 and "line 2" in problems[0] and "--" in problems[0]
    assert check_android_res.check_text("<a><b></a>")  # plain malformed XML too

    res = tmp_path / "android" / "wear" / "src" / "main" / "res" / "values"
    res.mkdir(parents=True)
    (res / "colors.xml").write_text(bad, encoding="utf-8")
    (tmp_path / "android" / "app" / "src" / "main").mkdir(parents=True)
    (tmp_path / "android" / "app" / "src" / "main" / "AndroidManifest.xml").write_text(
        "<manifest/>", encoding="utf-8"
    )
    found = check_android_res.check(tmp_path / "android")
    assert len(found) == 1 and found[0].startswith("android/wear/src/main/res/values/colors.xml")
