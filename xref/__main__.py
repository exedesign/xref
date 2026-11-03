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

import logging
import os
import platform
import signal
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

from xref import constants
from xref.assets import XRefAssets
from xref.config import CommandlineArgs, XRefSettings, logfile_name
from xref.file_associations import register_windows_file_associations
from xref.utils import create_palette_from_dict
from xref.view import XRefGraphicsView
from xref.widgets.window_buttons import WindowButtons

logger = logging.getLogger(__name__)


class XRefApplication(QtWidgets.QApplication):

    def event(self, event):
        if event.type() == QtCore.QEvent.Type.FileOpen:
            for widget in self.topLevelWidgets():
                if isinstance(widget, XRefMainWindow):
                    widget.view.open_from_file(event.file())
                    return True
            return False
        else:
            return super().event(event)


class XRefMainWindow(QtWidgets.QMainWindow):

    def __init__(self, app):
        super().__init__()
        app.setOrganizationName(constants.APPNAME)
        app.setApplicationName(constants.APPNAME)
        self.setWindowIcon(XRefAssets().logo)
        self.view = XRefGraphicsView(app, self)
        default_window_size = QtCore.QSize(500, 300)
        geom = self.view.settings.value('MainWindow/geometry')
        if geom is None:
            self.resize(default_window_size)
        else:
            if not self.restoreGeometry(geom):
                self.resize(default_window_size)
        self.setCentralWidget(self.view)
        app.installEventFilter(self)
        # Minimize/full screen/close buttons in the top right corner
        self.window_buttons = WindowButtons(self)
        self.show()

    def eventFilter(self, watched, event):
        event_type = event.type()
        if (event_type == QtCore.QEvent.Type.ContextMenu
                and isinstance(watched, QtWidgets.QWidget)
                and watched.window() is self
                and event.reason()
                == QtGui.QContextMenuEvent.Reason.Mouse):
            suppress_at = self.view._suppress_drag_context_menu_at
            context_pos = event.globalPos()
            if (suppress_at is not None
                    and (context_pos - suppress_at).manhattanLength() <= 3):
                self.view._suppress_drag_context_menu_at = None
                event.accept()
                return True

        if event_type in (QtCore.QEvent.Type.KeyPress,
                          QtCore.QEvent.Type.KeyRelease):
            if (not event.isAutoRepeat()
                    and event.key() in (QtCore.Qt.Key.Key_Alt,
                                        QtCore.Qt.Key.Key_AltGr)):
                self.view.set_before_after_active(
                    event_type == QtCore.QEvent.Type.KeyPress)
        elif event_type == QtCore.QEvent.Type.ApplicationDeactivate:
            self.view.set_before_after_active(False)

        if (isinstance(watched, QtWidgets.QWidget)
                and watched.window() is self):
            if event_type == QtCore.QEvent.Type.MouseMove:
                self.view.update_before_after_cursor(
                    event.globalPosition().toPoint())
            if (event_type == QtCore.QEvent.Type.MouseButtonPress
                    and event.button() == QtCore.Qt.MouseButton.RightButton
                    and not self.view.is_f3d_control_target_global(
                        event.globalPosition().toPoint())):
                self.view.begin_right_window_drag(event)
                return True
            if (event_type == QtCore.QEvent.Type.MouseMove
                    and self.view.continue_right_window_drag(event)):
                return True
            if (event_type == QtCore.QEvent.Type.MouseButtonRelease
                    and event.button() == QtCore.Qt.MouseButton.RightButton
                    and self.view.end_right_window_drag(event)):
                return True
        return super().eventFilter(watched, event)

    # -- Rounded corners (frameless window) --------------------------------

    def corner_radius(self):
        """The window corner radius, 0 for square corners.

        The default matches the window control buttons' rounded panel,
        so the window and its buttons share the same softness.
        """

        try:
            radius = int(self.view.settings.valueOrDefault(
                'View/window_corner_radius'))
        except (TypeError, ValueError):
            radius = 8
        return max(0, min(32, radius))

    def rounded_corners_on(self):
        """Whether the frameless window should have rounded corners."""

        return (self.is_frameless() and not self.isFullScreen()
                and self.corner_radius() > 0)

    def is_frameless(self):
        return bool(self.windowFlags()
                    & QtCore.Qt.WindowType.FramelessWindowHint)

    def apply_corner_shape(self):
        """(Re)applies the rounded-corner mask after settings changes.

        Must run after the window geometry is current, e.g. from a
        resize event or a settings change.
        """

        if self.rounded_corners_on():
            radius = self.corner_radius()
            bitmap = QtGui.QBitmap(self.size())
            bitmap.fill(QtCore.Qt.GlobalColor.color0)  # transparent
            painter = QtGui.QPainter(bitmap)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtCore.Qt.GlobalColor.color1)  # opaque
            painter.drawRoundedRect(QtCore.QRectF(self.rect()), radius,
                                    radius)
            painter.end()
            self.setMask(bitmap)
        else:
            self.clearMask()
        self.update()

    def paintEvent(self, event):
        if self.rounded_corners_on():
            painter = QtGui.QPainter(self)
            radius = self.corner_radius()
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 38)))
            painter.setBrush(QtWidgets.QApplication.palette()
                             .color(QtGui.QPalette.ColorRole.Window))
            painter.drawRoundedRect(
                QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                radius, radius)
        super().paintEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_corner_shape()

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_corner_shape()

    def save_scene_layout(self):
        """Stores the window geometry inside the scene file itself."""

        try:
            if not self.view.settings.valueOrDefault(
                    'View/remember_scene_layouts'):
                return
        except Exception:  # noqa: BLE001 - settings not ready
            return
        filename = self.view.filename
        if not filename or not os.path.isfile(filename):
            return
        try:
            import base64
            from xref.fileio import SQLiteIO
            store = SQLiteIO(filename, self.view.scene)
            store.set_meta('window_geometry',
                           base64.b64encode(self.saveGeometry()))
            store._close_connection()
        except Exception as e:  # noqa: BLE001 - board may be read-only
            logger.info(f'Could not store the scene layout: {e}')

    def restore_scene_layout(self):
        """Applies the window geometry stored in the scene file."""

        try:
            if not self.view.settings.valueOrDefault(
                    'View/remember_scene_layouts'):
                return False
        except Exception:  # noqa: BLE001 - settings not ready
            return False
        filename = self.view.filename
        if not filename or not os.path.isfile(filename):
            return False
        try:
            import base64
            from xref.fileio import SQLiteIO
            store = SQLiteIO(filename, self.view.scene, readonly=True)
            geom = store.get_meta('window_geometry')
            store._close_connection()
            if not geom:
                return False
            return self.restoreGeometry(base64.b64decode(geom))
        except Exception as e:  # noqa: BLE001 - damaged file etc.
            logger.info(f'Could not restore the scene layout: {e}')
            return False

    def closeEvent(self, event):
        self.save_scene_layout()
        geom = self.saveGeometry()
        self.view.settings.setValue('MainWindow/geometry', geom)
        event.accept()

    def __del__(self):
        try:
            del self.view
        except RuntimeError:  # already deleted by Qt on shutdown
            pass


def safe_timer(timeout, func, *args, **kwargs):
    """Create a timer that is safe against garbage collection and
    overlapping calls.
    See: http://ralsina.me/weblog/posts/BB974.html
    """
    def timer_event():
        try:
            func(*args, **kwargs)
        finally:
            QtCore.QTimer.singleShot(timeout, timer_event)
    QtCore.QTimer.singleShot(timeout, timer_event)


def handle_sigint(signum, frame):
    logger.info('Received interrupt. Exiting...')
    QtWidgets.QApplication.quit()


def handle_uncaught_exception(exc_type, exc, traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        logger.info('Received interrupt. Exiting...')
        QtWidgets.QApplication.quit()
        return
    # Errors in Qt event handlers (e.g. hovering a media item) shouldn't
    # take down the whole application and lose unsaved work; log and
    # keep running instead.
    logger.critical('Unhandled exception',
                    exc_info=(exc_type, exc, traceback))


sys.excepthook = handle_uncaught_exception


def main():
    logger.info(f'Starting {constants.APPNAME} version {constants.VERSION}')
    register_windows_file_associations()
    logger.debug('System: %s', ' '.join(platform.uname()))
    logger.debug('Python: %s', platform.python_version())
    logger.debug('LD_LIBRARY_PATH: %s', os.environ.get('LD_LIBRARY_PATH'))
    settings = XRefSettings()
    logger.info(f'Using settings: {settings.fileName()}')
    logger.info(f'Logging to: {logfile_name()}')
    settings.on_startup()
    # settings.on_startup() also applies the stored language
    args = CommandlineArgs(with_check=True)  # Force checking
    assert not args.debug_raise_error, args.debug_raise_error

    os.environ["QT_DEBUG_PLUGINS"] = "1"
    app = XRefApplication(sys.argv)
    palette = create_palette_from_dict(constants.COLORS)
    app.setPalette(palette)
    bee = XRefMainWindow(app)  # NOQA:F841

    signal.signal(signal.SIGINT, handle_sigint)
    # Repeatedly run python-noop to give the interpreter time to
    # handle signals
    safe_timer(50, lambda: None)

    app.exec()
    del bee
    del app
    logger.debug('XRef closed')
    QtCore.qInstallMessageHandler(None)


if __name__ == '__main__':
    main()  # pragma: no cover
