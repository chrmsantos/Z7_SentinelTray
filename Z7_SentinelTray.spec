# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\csantos\\AppData\\Local\\Z7\\Dev\\Z7_SentinelTray\\main.py'],
    pathex=['C:\\Users\\csantos\\AppData\\Local\\Z7\\Dev\\Z7_SentinelTray\\src'],
    binaries=[],
    datas=[('config/config.local.yaml.example', 'config')],
    hiddenimports=["unicodedata"],
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
    a.binaries,
    a.datas,
    [],
    name='Z7_SentinelTray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='C:\\Users\\csantos\\AppData\\Local\\Z7\\Dev\\Z7_SentinelTray\\assets\\icon.ico',
)
