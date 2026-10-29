"""Get packaging/build/ ready for PyInstaller: the app icons (the launcher's dot-matrix glyph: deskdot.ico,
deskdot.icns, deskdot.png) and the Windows version resource (version_info.txt). Prints the version.

    uv run python packaging/prepare.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deskdot import __version__  # noqa: E402
from deskdot.launcher import tray_image  # noqa: E402

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={v4}, prodvers={v4}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'DeskDot'),
      StringStruct('FileDescription', 'DeskDot'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'DeskDot'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'DeskDot.exe'),
      StringStruct('ProductName', 'DeskDot'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    out = ROOT / "packaging" / "build"
    out.mkdir(parents=True, exist_ok=True)
    big = tray_image(1024)
    big.save(out / "deskdot.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    big.save(out / "deskdot.icns")
    big.resize((512, 512)).save(out / "deskdot.png")
    nums = [int(p) for p in __version__.split("-")[0].split(".")][:3]
    v4 = tuple([*nums, 0])
    (out / "version_info.txt").write_text(VERSION_INFO.format(v4=v4, v=__version__), encoding="utf-8")
    print(__version__)


if __name__ == "__main__":
    main()
