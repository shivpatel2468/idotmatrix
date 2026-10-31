"""Import boundaries (I-ROOT-1, I-DEV-1, docs/MCP.md): who may import what, checked on the source with `ast`.

- `bleak` (the BLE stack) is imported only inside `src/deskdot/device/`: the engine is the one process that owns
  the link, everything else goes through the HTTP API.
- The MCP server is a thin HTTP client of the engine: it imports nothing from DeskDot itself (no engine, device,
  apps, providers…), only an HTTP client and the MCP SDK.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "deskdot"


def _imports(path: Path) -> list[tuple[int, str, int]]:
    """(line, module, relative level) of every import in a file, nested ones included."""
    out: list[tuple[int, str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append((node.lineno, node.module or "", node.level))
    return out


def test_bleak_is_imported_only_inside_the_device_package() -> None:
    device = SRC / "device"
    found_in_device = False
    bad: list[str] = []
    for f in sorted(SRC.rglob("*.py")):
        for line, mod, _level in _imports(f):
            if mod == "bleak" or mod.startswith("bleak."):
                if device in f.parents:
                    found_in_device = True
                else:
                    bad.append(f"{f.relative_to(ROOT)}:{line} imports {mod}")
    assert not bad, "bleak imported outside src/deskdot/device/ (CLAUDE.md rule 4):\n" + "\n".join(bad)
    assert found_in_device, "the desktop BLE backend no longer imports bleak? update this test"


def test_mcp_server_is_a_thin_http_client() -> None:
    f = SRC / "mcp_server.py"
    imports = _imports(f)
    internal = [
        f"line {line}: {'.' * level}{mod}"
        for line, mod, level in imports
        if level > 0 or mod == "deskdot" or mod.startswith("deskdot.")
    ]
    assert not internal, (
        "mcp_server.py must reach the engine only over HTTP, not import DeskDot:\n" + "\n".join(internal)
    )
    top = {mod.split(".")[0] for _line, mod, _level in imports}
    assert "httpx" in top, "the MCP server talks to the engine with httpx"
    assert "bleak" not in top
