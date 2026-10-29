#!/usr/bin/env python3
"""Rebuilds the multi-size window icons from the PNG app icons.

The Windows (``logo.ico``) and macOS (``logo.icns``) icons are generated
from ``xref/assets/icon-*.png`` so the branding only has to be replaced in
one place.

    python tools/make_icons.py
"""

import io
import os
import struct
import sys

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), 'xref', 'assets')

# Sizes stored inside the Windows icon (PNG compressed entries)
ICO_SIZES = (16, 32, 48, 64, 128, 256)
# (OSType, size) pairs for the macOS icon, all PNG compressed
ICNS_TYPES = (
    (b'icp4', 16),
    (b'icp5', 32),
    (b'icp6', 64),
    (b'ic07', 128),
    (b'ic08', 256),
    (b'ic09', 512),
    (b'ic10', 1024),
)


def load_source(size):
    """The app icon at the given size as PNG bytes."""

    candidates = (size, 1024, 512, 192, 180, 32, 16)
    for candidate in candidates:
        path = os.path.join(ASSETS, f'icon-{candidate}.png')
        if candidate >= size and os.path.isfile(path):
            image = QtGui.QImage(path)
            if image.isNull():
                continue
            if image.width() != size or image.height() != size:
                image = image.scaled(
                    size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            buffer = QtCore.QBuffer()
            buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, 'PNG')
            return bytes(buffer.data())
    raise SystemExit(f'Could not find an app icon for size {size}')


def write_ico(path, sizes):
    images = [load_source(size) for size in sizes]
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b''
    data = b''
    for size, image in zip(sizes, images):
        entries += struct.pack(
            '<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(image),
            offset)
        data += image
        offset += len(image)
    with io.open(path, 'wb') as f:
        f.write(header + entries + data)


def write_icns(path, types):
    elements = b''
    for ostype, size in types:
        image = load_source(size)
        elements += ostype + struct.pack('>I', len(image) + 8) + image
    with io.open(path, 'wb') as f:
        f.write(b'icns' + struct.pack('>I', len(elements) + 8) + elements)


def main():
    # QImage needs an application instance for the image plugins
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication(sys.argv)
    ico = os.path.join(ASSETS, 'logo.ico')
    icns = os.path.join(ASSETS, 'logo.icns')
    write_ico(ico, ICO_SIZES)
    write_icns(icns, ICNS_TYPES)
    print(f'Wrote {ico} ({os.path.getsize(ico)} bytes)')
    print(f'Wrote {icns} ({os.path.getsize(icns)} bytes)')
    del app


if __name__ == '__main__':
    main()
