# -*- mode: python ; coding: utf-8 -*-
import os
import sys

import certifi
import customtkinter

block_cipher = None
project_root = os.path.abspath(os.path.join(SPECPATH, ".."))
src_dir = os.path.join(project_root, "src")
ctk_path = os.path.dirname(customtkinter.__file__)
certifi_pem = certifi.where()

sys.path.insert(0, src_dir)

# Explicitly collect every src module used at runtime.
# Critical: `version` is imported by help_dialog / update_checker / main —
# previous 1.4.1 frozen build crashed with ModuleNotFoundError: version.
_src_hiddenimports = sorted(
    {
        os.path.splitext(name)[0]
        for name in os.listdir(src_dir)
        if name.endswith(".py") and name != "__init__.py"
    }
)

a = Analysis(
    [os.path.join(src_dir, "main.py")],
    pathex=[src_dir],
    binaries=[],
    datas=[
        (ctk_path, "customtkinter"),
        (os.path.join(project_root, "config"), "config"),
        (os.path.join(project_root, "assets"), "assets"),
        (certifi_pem, "certifi"),
    ],
    hiddenimports=["PIL._tkinter_finder", "certifi", *_src_hiddenimports],
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
    name="GROMOV-RestorePlus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_root, "assets", "icon.ico") if os.path.exists(os.path.join(project_root, "assets", "icon.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GROMOV-RestorePlus",
)
