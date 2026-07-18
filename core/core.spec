# -*- mode: python ; coding: utf-8 -*-
#
# Builds the core sidecar as a single onefile exe. Onefile (not onedir) is
# deliberate: alembic loads its migration scripts (alembic/env.py,
# alembic/versions/*.py) from disk at runtime via importlib, not just as
# compiled bytecode, so they need to exist as real files next to a stable
# base path at run time -- onefile's per-launch extraction into
# sys._MEIPASS gives exactly that (see CORE_DIR in app/main.py), with a
# much simpler Tauri externalBin story than onedir + a separate resources
# directory would need.
#
# Build via: pyinstaller core.spec --distpath ../shell/src-tauri/binaries --noconfirm
# (see build.bat in the repo root).

block_cipher = None

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("alembic.ini", "."),
        ("alembic", "alembic"),
    ],
    hiddenimports=[
        # uvicorn picks these implementations dynamically at runtime rather
        # than importing them statically, so PyInstaller's import scanner
        # misses them unless listed explicitly.
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "aiosqlite",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
