# PyInstaller spec — bundle backend + built React UI + Python into one .exe.
#   build:  pyinstaller --noconfirm DriveSpeedTest.spec   (run from repo root)
#   output: dist/DriveSpeedTest.exe
#
# Note: the React frontend must already be built (frontend/dist) — build.bat and
# the CI workflow do that first.

from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

# uvicorn/anyio/backend pull many modules in dynamically; collect them explicitly.
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("anyio")
    + collect_submodules("backend")
    + ["websockets", "httptools", "h11", "click", "backend.app"]
)

# Compiled extensions that conditional imports would otherwise hide.
binaries = collect_dynamic_libs("pydantic_core") + collect_dynamic_libs("httptools")

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=[("frontend/dist", "frontend/dist")],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["watchfiles", "tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DriveSpeedTest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # server logs + URL are useful; Ctrl+C to stop
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # No uac_admin here: run.py self-elevates and lets the user decline gracefully.
)
