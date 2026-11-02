"""Check the Android app's XML (resources + manifests) is well-formed, without Gradle or the Android SDK.

    python scripts/check_android_res.py          # exit 1 and list the problems, or print "ok"

Why: aapt2 refuses malformed XML at `:app:mergeReleaseResources`, so a stray "--" inside an XML comment broke the
3.9.0 Android build after the tag was already pushed. This runs in a second in CI (`android-resources` job in
.github/workflows/ci.yml) and in `scripts/release.py`'s checks before anything is tagged. Pure standard library.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_COMMENT = re.compile(r"<!--(.*?)-->", re.S)


def xml_files(android: Path) -> list[Path]:
    """Every resource XML and AndroidManifest.xml under android/<module>/src (app, wear, …), build output excluded."""
    out: list[Path] = []
    for src in sorted(android.glob("*/src")):
        for p in sorted(src.rglob("*.xml")):
            if "build" in p.relative_to(android).parts:
                continue
            if p.name == "AndroidManifest.xml" or "res" in p.relative_to(src).parts:
                out.append(p)
    return out


def check_text(text: str) -> list[str]:
    """Problems in one XML document, in plain words (empty = fine)."""
    problems: list[str] = []
    for m in _COMMENT.finditer(text):
        body = m.group(1)
        if "--" in body or body.endswith("-"):
            line = text.count("\n", 0, m.start()) + 1
            problems.append(
                f'line {line}: "--" inside an XML comment (Android refuses it; use a dash or "—")'
            )
    try:
        ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        if not problems:  # the comment rule above already explains the usual cause
            problems.append(f"not well-formed XML: {e}")
    return problems


def check(android: Path | None = None) -> list[str]:
    android = android or ROOT / "android"
    out: list[str] = []
    for p in xml_files(android):
        for problem in check_text(p.read_text(encoding="utf-8")):
            out.append(f"{p.relative_to(android.parent).as_posix()}: {problem}")
    return out


def main() -> int:
    problems = check()
    if problems:
        print("Android XML problems (the APK build would fail):")
        for p in problems:
            print("  " + p)
        return 1
    print(f"ok: {len(xml_files(ROOT / 'android'))} Android XML files are well-formed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
