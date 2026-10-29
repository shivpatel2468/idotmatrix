# PyInstaller spec for the installed DeskDot app (onedir). Build from the repo root:
#
#     uv run --group packaging pyinstaller packaging/deskdot.spec --noconfirm --distpath packaging/build/dist --workpath packaging/build/work
#
# Needs: the studio built (web/dist), icons (packaging/prepare.py). Output: packaging/build/dist/DeskDot/
# (Windows: DeskDot.exe = the windowed app, deskdot-cli.exe = the same with a console) or DeskDot.app (macOS).
# Only files from the repo are bundled: never deskdot.toml, data/, .env or anything else machine-local.
# ruff: noqa
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
BUILD = ROOT / "packaging" / "build"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "src" / "deskdot" / "__init__.py").read_text()).group(1)
WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"

if not (ROOT / "web" / "dist" / "index.html").is_file():
    raise SystemExit("web/dist is missing: run `cd web && npm run build` first")

# modules only the Android app / the browser app use (they import java / pyodide)
NOT_HERE = {"deskdot.android_main", "deskdot.web_main", "deskdot.device.android", "deskdot.device.web"}
hidden = [m for m in collect_submodules("deskdot") if m not in NOT_HERE]
hidden += collect_submodules("uvicorn")  # loops / protocols are picked by name at run time
hidden += collect_submodules("bleak")
hidden += collect_submodules("pystray")
if WIN:
    hidden += ["winrt.windows.media.control", "winrt.windows.storage.streams", "winrt.windows.foundation"]

datas = [
    (str(ROOT / "web" / "dist"), "web/dist"),
    (str(ROOT / "deskdot.example.toml"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
datas += collect_data_files("deskdot", excludes=["**/__pycache__/*", "**/*.pyc", "**/SPEC.md"])  # casino.html, tv/*, …
datas += collect_data_files("soundcard")  # its cffi headers are read at import

excludes = [
    "tkinter",
    "pytest",
    "_pytest",
    "mypy",
    "ruff",
    "IPython",
    "matplotlib",
    "pandas",
    "scipy",
    "mcp",
    "legacy",
    *NOT_HERE,
]

a = Analysis(
    [str(ROOT / "packaging" / "deskdot_app.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = str(BUILD / ("deskdot.ico" if WIN else "deskdot.icns"))
version_file = str(BUILD / "version_info.txt") if WIN and (BUILD / "version_info.txt").is_file() else None

app_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DeskDot",
    console=False,  # a desktop app: no console window (logs go to <app data>/data/deskdot.log)
    icon=icon,
    version=version_file,
    upx=False,
    target_arch=None,
)
exes = [app_exe]
if WIN:
    exes.append(
        EXE(
            pyz,
            a.scripts,
            [],
            exclude_binaries=True,
            name="deskdot-cli",
            console=True,  # the same program with a console: `deskdot-cli scan`, `deskdot-cli serve --sim`
            icon=icon,
            version=version_file,
            upx=False,
        )
    )

coll = COLLECT(*exes, a.binaries, a.datas, name="DeskDot", upx=False)

if MAC:
    app = BUNDLE(
        coll,
        name="DeskDot.app",
        icon=icon,
        bundle_identifier="com.deskdot.desktop",
        version=VERSION,
        info_plist={
            "CFBundleName": "DeskDot",
            "CFBundleDisplayName": "DeskDot",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSBluetoothAlwaysUsageDescription": "DeskDot connects to your iDotMatrix LED panel over Bluetooth.",
            "NSBluetoothPeripheralUsageDescription": "DeskDot connects to your iDotMatrix LED panel over Bluetooth.",
            "NSMicrophoneUsageDescription": "Sound-reactive apps can listen to the microphone if you choose it.",
            "NSCameraUsageDescription": "The camera mirror and On Air can use the camera if you turn them on.",
            "NSAppleEventsUsageDescription": "Now Playing asks Music and Spotify what song is playing.",
            "NSLocalNetworkUsageDescription": "Friends' phones on your Wi-Fi can join games as controllers.",
        },
    )
