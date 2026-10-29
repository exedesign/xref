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

"""Minimize, full screen and close buttons for the frameless window.

The buttons stay out of the way and only appear when the pointer rests in
the top right corner of the window for a moment.
"""

import logging

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from xref.config import XRefSettings
from xref.i18n import tr


logger = logging.getLogger(__name__)


class WindowButtons(QtWidgets.QWidget):
    """The window controls that appear near the top right corner."""

    BUTTON_SIZE = 26
    ICON_SIZE = 18
    SPACING = 4
    PADDING = 6
    MARGIN = 8
    #: How close the pointer has to get to the corner (in pixels)
    PROXIMITY = 110
    POLL_INTERVAL_MS = 100
    FADE_MS = 140

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.settings = XRefSettings()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self.show_timer = QtCore.QTimer(self)
        self.show_timer.setSingleShot(True)
        self.show_timer.timeout.connect(self.show_buttons)

        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(
            self.PADDING, self.PADDING, self.PADDING, self.PADDING)
        self.layout.setSpacing(self.SPACING)
        self.minimize_button = self.create_button('minimize', self.on_minimize)
        self.fullscreen_button = self.create_button(
            'fullscreen', self.on_toggle_fullscreen)
        self.close_button = self.create_button('close', self.on_close)
        self.layout.addWidget(self.minimize_button)
        self.layout.addWidget(self.fullscreen_button)
        self.layout.addWidget(self.close_button)
        self.adjustSize()

        self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade = QtCore.QPropertyAnimation(
            self.opacity_effect, b'opacity', self)
        self.fade.setDuration(self.FADE_MS)
        self.opacity_effect.setOpacity(0)

        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.on_poll)
        self.poll_timer.start(self.POLL_INTERVAL_MS)

        self.hide()
        self.retranslate()

    # -- Buttons -----------------------------------------------------------

    def create_button(self, kind, callback):
        button = QtWidgets.QToolButton(self)
        button.setAutoRaise(True)
        button.setFixedSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        button.setStyleSheet(
            'QToolButton { border: none; border-radius: 5px; }'
            'QToolButton:hover { background: rgba(255, 255, 255, 45); }'
            'QToolButton:pressed { background: rgba(255, 255, 255, 80); }')
        button.setProperty('kind', kind)
        button.setIcon(QtGui.QIcon(self.glyph(kind)))
        button.setIconSize(QtCore.QSize(self.ICON_SIZE, self.ICON_SIZE))
        button.clicked.connect(callback)
        return button

    def glyph(self, kind, size=None):
        """Paints the icon of a button (no icon theme needed)."""

        size = size or self.ICON_SIZE * 2
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(235, 235, 235))
        pen.setWidthF(max(1.2, size / 12))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        unit = float(size)
        margin = unit * 0.24
        if kind == 'minimize':
            y = unit * 0.58
            painter.drawLine(QtCore.QPointF(margin, y),
                             QtCore.QPointF(unit - margin, y))
        elif kind in ('fullscreen', 'restore'):
            arm = unit * 0.2
            direction = 1 if kind == 'fullscreen' else -1
            for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                x = margin if sx > 0 else unit - margin
                y = margin if sy > 0 else unit - margin
                painter.drawLine(
                    QtCore.QPointF(x, y),
                    QtCore.QPointF(x + sx * arm * direction, y))
                painter.drawLine(
                    QtCore.QPointF(x, y),
                    QtCore.QPointF(x, y + sy * arm * direction))
        else:  # close
            painter.drawLine(QtCore.QPointF(margin, margin),
                             QtCore.QPointF(unit - margin, unit - margin))
            painter.drawLine(QtCore.QPointF(unit - margin, margin),
                             QtCore.QPointF(margin, unit - margin))
        painter.end()
        return pixmap

    def retranslate(self):
        self.minimize_button.setToolTip(tr('Minimize'))
        self.fullscreen_button.setToolTip(tr('Full screen'))
        self.close_button.setToolTip(tr('Close window'))

    def update_fullscreen_button(self):
        fullscreen = self.main_window.isFullScreen()
        kind = 'restore' if fullscreen else 'fullscreen'
        self.fullscreen_button.setIcon(QtGui.QIcon(self.glyph(kind)))

    # -- Window actions ----------------------------------------------------

    def on_minimize(self):
        self.hide_buttons()
        self.main_window.showMinimized()

    def on_toggle_fullscreen(self):
        view = getattr(self.main_window, 'view', None)
        if view is not None:
            view.toggle_fullscreen()
        self.update_fullscreen_button()

    def on_close(self):
        view = getattr(self.main_window, 'view', None)
        if view is not None and not view.get_confirmation_unsaved_changes(
                tr('There are unsaved changes. '
                   'Are you sure you want to quit?')):
            return
        self.main_window.close()

    # -- Showing and hiding ------------------------------------------------

    def delay_ms(self):
        """How long the pointer has to stay near the corner (in ms)."""

        try:
            seconds = int(self.settings.valueOrDefault(
                'View/window_buttons_delay'))
        except (TypeError, ValueError):
            seconds = 3
        return max(0, seconds) * 1000

    def corner_geometry(self):
        """The geometry of the buttons inside the main window."""

        parent = self.main_window
        self.adjustSize()
        x = parent.width() - self.width() - self.MARGIN
        y = self.MARGIN
        menu_bar = parent.findChild(QtWidgets.QMenuBar)
        if menu_bar is not None and menu_bar.isVisible():
            y += menu_bar.height()
        return QtCore.QRect(x, y, self.width(), self.height())

    def is_near_corner(self, global_pos):
        """Whether the given screen position is close to the top right."""

        parent = self.main_window
        if not parent.isVisible():
            return False
        local = parent.mapFromGlobal(global_pos)
        if self.isVisible() and self.geometry().contains(local):
            return True
        return (local.x() >= parent.width() - self.PROXIMITY
                and 0 <= local.y() <= self.PROXIMITY)

    def check_position(self, global_pos):
        """Shows or hides the buttons for the given pointer position."""

        if not self.main_window.isVisible():
            self.show_timer.stop()
            if self.isVisible():
                self.hide_buttons()
            return
        if self.is_near_corner(global_pos):
            if not self.isVisible() and not self.show_timer.isActive():
                delay = self.delay_ms()
                if delay <= 0:
                    self.show_buttons()
                else:
                    self.show_timer.start(delay)
        else:
            self.show_timer.stop()
            if self.isVisible():
                self.hide_buttons()

    def on_poll(self):
        self.reposition()
        self.check_position(QtGui.QCursor.pos())

    def reposition(self):
        if not self.isVisible():
            return
        geometry = self.corner_geometry()
        if geometry != self.geometry():
            self.setGeometry(geometry)

    def show_buttons(self):
        self.show_timer.stop()
        self.update_fullscreen_button()
        self.setGeometry(self.corner_geometry())
        self.raise_()
        self.show()
        self.fade.stop()
        self.fade.setStartValue(self.opacity_effect.opacity())
        self.fade.setEndValue(1.0)
        self.fade.start()

    def hide_buttons(self):
        self.show_timer.stop()
        if not self.isVisible():
            return
        self.fade.stop()
        self.fade.setStartValue(self.opacity_effect.opacity())
        self.fade.setEndValue(0.0)
        self.fade.start()
        QtCore.QTimer.singleShot(self.FADE_MS, self.on_fade_finished)

    def on_fade_finished(self):
        if self.opacity_effect.opacity() < 0.05:
            self.hide()

    # -- Painting ----------------------------------------------------------

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 45)))
        painter.setBrush(QtGui.QColor(20, 20, 24, 210))
        painter.drawRoundedRect(
            QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            8, 8)

    def showEvent(self, event):
        super().showEvent(event)
        self.reposition()
