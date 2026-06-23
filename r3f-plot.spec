# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — R3F Converter

ビルド:
    python -m PyInstaller r3f-plot.spec

出力:
    dist/R3FConverter/R3FConverter.exe   (onedir 形式)

注意:
    - Tektronix の RSA_API.dll はバンドルしません。ユーザーが SDK を
      インストールし、初回起動時のダイアログで DLL パスを指定すると
      exe と同じフォルダに .env が作成されます。
    - onedir 形式（1フォルダ）にしているのは、起動が速く DLL の相性問題が
      少ないためです。onefile にしたい場合は EXE(...) の引数を変更してください。
"""

block_cipher = None

# --- Tektronix RSA_API DLL の同梱 ---
# 研究室内（Licensed Users）での内部利用に限定。社外配布は EULA 3.4.1/3.4.3 で禁止。
# DLL のあるフォルダ。環境に合わせて変更可。
import os
_DLL_DIR = os.environ.get("RSA_DLL_DIR", r"C:\Tektronix\RSA_API\lib\x64")
_DLL_NAMES = [
    "RSA_API.dll",
    "RSA300API.dll",
    "RSA500API.dll",
    "BaseDSPL.dll",
    "GPMeasDSP.dll",
    "SharedUtils.dll",
]
rsa_binaries = [
    (os.path.join(_DLL_DIR, name), ".")
    for name in _DLL_NAMES
    if os.path.exists(os.path.join(_DLL_DIR, name))
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=rsa_binaries,
    datas=[],
    hiddenimports=[
        'scipy.signal',
        'pyarrow',
        'pyarrow.parquet',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='R3FConverter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI アプリなのでコンソール非表示
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='R3FConverter',
)
