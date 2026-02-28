# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('pydantic')


a = Analysis(
    ['C:\\Users\\lenovo\\Documents\\cursor\\codex\\projects\\nordhold\\\\src\\\\nordhold\\\\launcher.py'],
    pathex=['C:\\Users\\lenovo\\Documents\\cursor\\codex\\projects\\nordhold\\src'],
    binaries=[],
    datas=[('C:\\Users\\lenovo\\Documents\\cursor\\codex\\projects\\nordhold\\\\data', 'data'), ('C:\\Users\\lenovo\\Documents\\cursor\\codex\\projects\\nordhold\\\\web\\\\dist', 'web\\\\dist')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NordholdRealtimeLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NordholdRealtimeLauncher',
)
