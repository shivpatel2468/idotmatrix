""".github/workflows/release.yml: build provenance (GitHub artifact attestations) for the files GitHub builds.

Read as data; nothing runs. The attestation itself is checked on a real release with `gh attestation verify`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))


def test_the_installers_get_build_provenance_before_checksums_and_upload() -> None:
    steps = WORKFLOW["jobs"]["release"]["steps"]
    uses = [s.get("uses", "") for s in steps]
    names = [s.get("name", "") for s in steps]
    i = next(n for n, u in enumerate(uses) if u.startswith("actions/attest-build-provenance@"))
    assert steps[i]["with"]["subject-path"] == "out/*"  # every downloaded installer: exe, dmgs, CI-built APKs
    assert i > uses.index("actions/download-artifact@v4"), "attest the files after they're downloaded"
    assert i < names.index("Checksums"), "only installers in out/ when attesting (checksums.txt comes after)"
    assert i < names.index("Create the draft release")


def test_only_the_release_job_may_mint_attestations() -> None:
    assert WORKFLOW["permissions"] == {"contents": "read"}
    for name, job in WORKFLOW["jobs"].items():
        perms = job.get("permissions", {})
        if name == "release":
            assert perms == {"contents": "write", "id-token": "write", "attestations": "write"}
        else:
            assert "id-token" not in perms and "attestations" not in perms, name
