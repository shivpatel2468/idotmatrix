"""Living specs (docs/SPECS.md): the graph of SPEC.md files stays connected and honest.

- every spec in the root map exists, and every SPEC.md in the repo is in the map;
- every cited test file exists, and every cited `::test_name` is defined in it;
- requirement / invariant ids are unique, and each requirement cites a test or says it's a gap;
- each spec has the standard sections and a "Last verified" date.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_SPEC = ROOT / "SPEC.md"
SKIP_DIRS = {"node_modules", "legacy", "build", "dist", "site", "__pycache__"}

MAP_LINK = re.compile(r"\]\(([^)]*SPEC\.md)\)")
TEST_REF = re.compile(r"`((?:tests|\.github/workflows)/[^`:\s]+)(?:::([A-Za-z_][A-Za-z0-9_]*))?`")
ID_DEF = re.compile(r"^- \*\*([RI]-[A-Z]+-\d+)\*\*")
SECTIONS = ("## Purpose", "## Requirements", "## Invariants", "## Interfaces", "## Open questions")
VERIFIED = re.compile(r"^Last verified: \d{4}-\d{2}-\d{2}$", re.M)


def mapped_specs() -> list[Path]:
    text = ROOT_SPEC.read_text(encoding="utf-8")
    section = text.split("## Map of child specs", 1)[1].split("\n## ", 1)[0]
    return [ROOT / m for m in MAP_LINK.findall(section)]


def all_specs() -> list[Path]:
    return [ROOT_SPEC, *mapped_specs()]


def specs_on_disk() -> set[Path]:
    found: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        if "SPEC.md" in filenames:
            found.add(Path(dirpath) / "SPEC.md")
    return found


def list_items(text: str) -> list[str]:
    """Top-level `- ` list items, each with its continuation lines joined."""
    items: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("- "):
            if current is not None:
                items.append(" ".join(current))
            current = [line]
        elif current is not None and line.startswith("  ") and line.strip():
            current.append(line.strip())
        else:
            if current is not None:
                items.append(" ".join(current))
            current = None
    if current is not None:
        items.append(" ".join(current))
    return items


def test_root_map_lists_existing_specs_and_every_spec_is_mapped() -> None:
    mapped = mapped_specs()
    assert len(mapped) >= 11, "the root map lost child specs"
    missing = [str(p.relative_to(ROOT)) for p in mapped if not p.is_file()]
    assert not missing, f"specs in the root map that don't exist: {missing}"
    unmapped = specs_on_disk() - {p.resolve() for p in all_specs()}
    assert not unmapped, f"SPEC.md files missing from the root map: {sorted(str(p) for p in unmapped)}"


def test_cited_tests_exist() -> None:
    bad: list[str] = []
    for spec in all_specs():
        text = spec.read_text(encoding="utf-8")
        for path, name in TEST_REF.findall(text):
            f = ROOT / path
            where = f"{spec.relative_to(ROOT)}: {path}"
            if "*" in path:  # a glob such as tests/js/*.test.mjs must match something
                if not any(ROOT.glob(path)):
                    bad.append(f"{where} (matches no file)")
            elif not f.is_file():
                bad.append(f"{where} (no such file)")
            elif name and not re.search(rf"^(?:async )?def {name}\(", f.read_text(encoding="utf-8"), re.M):
                bad.append(f"{where}::{name} (no such test)")
    assert not bad, "specs cite tests that don't exist:\n" + "\n".join(bad)


def test_ids_are_unique_and_requirements_cite_tests() -> None:
    seen: dict[str, str] = {}
    dupes: list[str] = []
    untested: list[str] = []
    for spec in all_specs():
        rel = str(spec.relative_to(ROOT))
        for item in list_items(spec.read_text(encoding="utf-8")):
            m = ID_DEF.match(item)
            if not m:
                continue
            rid = m.group(1)
            if rid in seen:
                dupes.append(f"{rid} in {rel} and {seen[rid]}")
            seen[rid] = rel
            if rid.startswith("R-") and not (TEST_REF.search(item) or "gap" in item):
                untested.append(f"{rid} ({rel})")
    assert not dupes, f"duplicate ids: {dupes}"
    assert not untested, f"requirements that cite no test and aren't marked as a gap: {untested}"
    assert any(r.startswith("R-") for r in seen) and any(r.startswith("I-") for r in seen)


def test_every_spec_has_the_standard_sections() -> None:
    bad: list[str] = []
    for spec in all_specs():
        text = spec.read_text(encoding="utf-8")
        rel = spec.relative_to(ROOT)
        bad += [f"{rel}: no '{s}'" for s in SECTIONS if not re.search(rf"^{re.escape(s)}\b", text, re.M)]
        if not VERIFIED.search(text):
            bad.append(f"{rel}: no 'Last verified: YYYY-MM-DD'")
    assert not bad, "\n".join(bad)
