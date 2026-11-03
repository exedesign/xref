# -*- mode: python ; coding: utf-8 -*-

import os
import platform
from os.path import join
import sys

from xref import constants


block_cipher = None
appname = f'{constants.APPNAME}-{constants.VERSION}'

if sys.platform.startswith('win'):
    icon = 'logo.ico'
else:
    icon = 'logo.icns'  # For OSX; param gets ignored on Linux

f3d_binaries = []
f3d_datas = []
f3d_hiddenimports = []
usd_binaries = []
usd_datas = []
usd_hiddenimports = []
if (sys.platform == 'win32' and sys.version_info >= (3, 10)
        and platform.machine().lower() in ('amd64', 'x86_64')
        and sys.maxsize > 2**32):
    from PyInstaller.utils.hooks import collect_all
    f3d_datas, f3d_binaries, f3d_hiddenimports = collect_all('f3d')
    usd_datas, usd_binaries, usd_hiddenimports = collect_all('pxr')

a = Analysis(
    [join('xref', '__main__.py')],
    pathex=[os.getcwd()],
    binaries=f3d_binaries + usd_binaries,
    datas=[
        (join('xref', 'documentation'), join('xref', 'documentation')),
        (join('xref', 'assets', '*.png'), join('xref', 'assets')),
        (join('xref', 'assets', '*.svg'), join('xref', 'assets')),
        (join('xref', 'assets', '*.ico'), join('xref', 'assets')),
        (join('xref', 'assets', '*.icns'), join('xref', 'assets')),
        *f3d_datas,
        *usd_datas],
    # The WebRTC mirror stack is imported lazily/conditionally, so
    # PyInstaller's static analysis misses it
    hiddenimports=[
        'aiortc',
        'aiortc.mediastreams',
        'aiortc.rtcsctptransport',
        'aioice',
        'av',
        'av.logging',
        'numpy',
        'cffi',
        'pyee',
    ] + f3d_hiddenimports + usd_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[join('xref', 'pyi_rth_f3d.py')],
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
