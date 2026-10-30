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

"""Thumbnails and metadata for recent board files."""

import logging
import os
import sqlite3

from PyQt6 import QtCore, QtGui

logger = logging.getLogger(__name__)

#: Size of the thumbnails shown in the recent files overview
THUMBNAIL_SIZE = 96


def board_thumbnail(path, size=THUMBNAIL_SIZE):
    """The first embedded image of a board, as a small preview.

    Reads only the sqlar table of the .xref/.bee file, so it is fast even
    for big boards. Returns a null pixmap when the board has no embedded
    images or cannot be read.
    """

    try:
        con = sqlite3.connect(
            'file:%s?mode=ro' % path.replace('?', '%3f'), uri=True)
        try:
            row = con.execute(
                'SELECT data FROM sqlar ORDER BY item_id LIMIT 1'
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return QtGui.QPixmap()
    if not row or not row[0]:
        return QtGui.QImage()
    image = QtGui.QImage()
    if not image.loadFromData(row[0]):
        return QtGui.QImage()
    # QImage (not QPixmap): safe to use from worker threads too
    return image.scaledToWidth(
        size, QtCore.Qt.TransformationMode.SmoothTransformation)


def board_mtime(path):
    """When the board file was last modified (as a timestamp)."""

    try:
        return os.path.getmtime(path)
    except OSError:
        return 0
