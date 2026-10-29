# -*- mode: python ; coding: utf-8 -*-

import os
from os.path import join
import sys

from xref import constants


block_cipher = None
appname = f'{constants.APPNAME}-{constants.VERSION}'

if sys.platform.startswith('win'):
    icon = 'logo.ico'
else:
    icon = 'logo.icns'  # For OSX; param gets ignored on Linux


a = Analysis(
    [join('xref', '__main__.py')],
    pathex=[os.getcwd()],
    binaries=[],
    datas=[
        (join('xref', 'documentation'), join('xref', 'documentation')),
        (join('xref', 'assets', '*.png'), join('xref', 'assets'))],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=appname,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None ,
    icon=join('xref', 'assets', icon))

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name=f'{constants.APPNAME}.app',
        icon=join('xref', 'assets', icon),
        bundle_identifier='org.xref.app',
        version=f'{constants.VERSION}',
        info_plist={
            'CFBundleDocumentTypes': [
                {
                    'CFBundleTypeExtensions': [ 'bee' ],
                    'CFBundleTypeRole': 'Viewer'
                }
            ]
        })
