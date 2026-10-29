#!/usr/bin/env python3

# This file is part of XRef.
#
# XRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# XRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with XRef.  If not, see <https://www.gnu.org/licenses/>.

from importlib.resources import files as rsc_files
import logging

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt


logger = logging.getLogger(__name__)


class XRefAssets:
    _instance = None
    PATH = rsc_files('xref.assets')

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.on_new()
        return cls._instance

    #: The sizes of the application icon that ship with XRef
    ICON_SIZES = (16, 32, 180, 192, 512, 1024)

    def on_new(self):
        logger.debug(f'Assets path: {self.PATH}')

        self.logo = self.create_logo()
        self.logo_vertical = self.create_pixmap('logo-vertical.png')
        self.logo_horizontal = self.create_pixmap('logo-horizontal.png')
        self.cursor_rotate = self.cursor_from_image(
            'cursor_rotate.png', (20, 20))
        self.cursor_flip_h = self.cursor_from_image(
            'cursor_flip_h.png', (20, 20))
        self.cursor_flip_v = self.cursor_from_image(
            'cursor_flip_v.png', (20, 20))

    def create_logo(self):
        """The application icon in every size that ships with XRef."""

        icon = QtGui.QIcon()
        for size in self.ICON_SIZES:
            path = self.PATH.joinpath(f'icon-{size}.png')
            if path.is_file():
                icon.addFile(str(path), QtCore.QSize(size, size))
        vector = self.PATH.joinpath('icon.svg')
        if vector.is_file():
            icon.addFile(str(vector))
        assert icon.isNull() is False
        return icon

    def create_pixmap(self, filename):
        pixmap = QtGui.QPixmap(str(self.PATH.joinpath(filename)))
        assert pixmap.isNull() is False
        return pixmap

    def logo_pixmap(self, filename, width):
        """A logo scaled to the given width (for dialogs and overlays)."""

        pixmap = QtGui.QPixmap(str(self.PATH.joinpath(filename)))
        assert pixmap.isNull() is False
        return pixmap.scaledToWidth(
            width, Qt.TransformationMode.SmoothTransformation)

    def cursor_from_image(self, filename, hotspot):
        app = QtWidgets.QApplication.instance()
        scaling = app.primaryScreen().devicePixelRatio()
        img = QtGui.QImage(str(self.PATH.joinpath(filename)))
        assert img.isNull() is False
        pixmap = QtGui.QPixmap.fromImage(img)
        pixmap.setDevicePixelRatio(scaling)
        return QtGui.QCursor(
            pixmap, int(hotspot[0]/scaling), int(hotspot[1]/scaling))
