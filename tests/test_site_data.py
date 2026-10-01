"""scripts/build_site_data.py produces the Apps explorer data for idotmatrix.com: valid JSON, every app covered."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import dotdeck.apps  # noqa: F401 — registers built-in apps
from dotdeck.engine import REGISTRY

ROOT = Path(__file__).resolve().parents[1]


def _load_script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_site_data", ROOT / "scripts" / "build_site_data.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_writes_valid_json_for_every_app(tmp_path: Path) -> None:
    out = tmp_path / "apps.json"
    assert _load_script().main(["--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))

    visible = {aid for aid, cls in REGISTRY.items() if not cls.hidden}
    ids = [a["id"] for a in data["apps"]]
    assert set(ids) == visible and len(ids) == len(set(ids)) == data["count"]
    assert sum(c["count"] for c in data["categories"]) == data["count"]

    for app in data["apps"]:
        assert app["name"] and app["category"] and app["kind"] in ("clip", "stream", "native")
        assert app["kind"] in app["kinds"]
        if app["gif"]:
            assert (ROOT / "docs" / app["gif"]).exists()
        schema_keys = set(REGISTRY[app["id"]].Settings.model_json_schema().get("properties", {}))
        assert {s["key"] for s in app["settings"]} == schema_keys
        for s in app["settings"]:
            assert s["title"] and s["type"]
            if s["type"] == "choice":
                assert s["options"] and all("label" in o for o in s["options"])
        if app["category"] == "games":
            assert app["game"]["max_players"] >= 1


def test_committed_site_data_is_current() -> None:
    """site/apps.json is what the generator makes today (re-run the script after changing an app)."""
    committed = json.loads((ROOT / "site" / "apps.json").read_text(encoding="utf-8"))
    visible = {aid for aid, cls in REGISTRY.items() if not cls.hidden}
    assert {a["id"] for a in committed["apps"]} == visible
