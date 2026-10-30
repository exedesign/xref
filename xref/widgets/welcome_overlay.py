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

import logging
import os.path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from xref.assets import XRefAssets
from xref.i18n import tr
from xref.main_controls import MainControlsMixin


logger = logging.getLogger(__name__)


class WelcomeOverlay(MainControlsMixin, QtWidgets.QWidget):
    """Some basic info to be displayed when the scene is empty."""

    @property
    def txt(self):
        return (f'<p>{tr("Paste or drop images and videos here.")}</p>'
                f'<p>{tr("Right-click for more options.")}</p>'
                f'<p>{tr("Double-click the empty canvas to go full screen.")}'
                f'</p>'
                f'<p>'
                f'{tr("Drag just inside a window edge to move the window.")}'
                f'</p>')

    def __init__(self, parent):
        super().__init__(parent)
        self.control_target = parent
        # Transparent, so the canvas (colour, grid) stays visible behind
        # the hints on the empty board
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.init_main_controls(main_window=parent.parent)

        # Help text
        self.label = QtWidgets.QLabel(self.txt, self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignVCenter
                                | Qt.AlignmentFlag.AlignCenter)

        # Branding
        self.logo = QtWidgets.QLabel(self)
        self.logo.setPixmap(
            XRefAssets().logo_pixmap('logo-vertical.png', 180))
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.center_widget = QtWidgets.QWidget(self)
        center_layout = QtWidgets.QVBoxLayout()
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.logo)
        center_layout.addWidget(self.label)
        self.center_widget.setLayout(center_layout)

        self.layout = QtWidgets.QHBoxLayout()
        self.layout.addStretch(50)
        self.layout.addWidget(self.center_widget)
        self.layout.addStretch(50)
        self.setLayout(self.layout)

    def retranslate(self):
        """Updates the labels after a language change."""

        self.label.setText(self.txt)

    def show(self):
        # Recent boards live in the context menu (File -> Open Recent),
        # not on the canvas
        super().show()

    def disable_mouse_events(self):
        self.center_widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def enable_mouse_events(self):
        self.center_widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            on=False)

    def mousePressEvent(self, event):
        if self.control_target.handle_window_edge_press(event):
            event.accept()
            return
        if self.mousePressEventMainControls(event):
            return
        # The overlay covers the empty board, so it has to hand the events
        # to the view; panning, zooming and the context menu keep working
        self.control_target.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.control_target.update_window_edge_cursor(event.pos(),
                                                      widget=self)
        if self.mouseMoveEventMainControls(event):
            return
        self.control_target.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mouseReleaseEventMainControls(event):
            return
        self.control_target.mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.control_target.wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        """A double click on the empty overlay switches to full screen."""

        if event.button() == Qt.MouseButton.LeftButton:
            self.control_target.toggle_fullscreen()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if self.keyPressEventMainControls(event):
            return
        super().keyPressEvent(event)
