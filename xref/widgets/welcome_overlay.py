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
from xref.config import XRefSettings
from xref.i18n import tr
from xref.main_controls import MainControlsMixin


logger = logging.getLogger(__name__)


class RecentFilesModel(QtCore.QAbstractListModel):
    """The 'Recent Files' list: thumbnails, pin state and last used."""

    THUMB = 96

    def __init__(self, files, settings):
        super().__init__()
        self.files = files or []
        self.settings = settings
        self.thumbnails = {}
        self.pin_states = {}

    def rowCount(self, parent):
        return len(self.files)

    def flags(self, index):
        return (QtCore.Qt.ItemFlag.ItemIsEnabled
                | QtCore.Qt.ItemFlag.ItemIsSelectable)

    def refresh_metadata(self):
        """Loads thumbnails and pin states (cheap enough for the list)."""

        from xref.fileio import thumbnails
        self.thumbnails = {}
        self.pin_states = {}
        for path in self.files:
            image = thumbnails.board_thumbnail(path, self.THUMB)
            if not image.isNull():
                self.thumbnails[path] = QtGui.QIcon(
                    QtGui.QPixmap.fromImage(image))
            self.pin_states[path] = \
                self.settings.is_pinned_recent_file(path)

    def data(self, index, role):
        if not index.isValid():
            return None
        path = self.files[index.row()]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            name = os.path.basename(path)
            mtime = os.path.getmtime(path) if os.path.exists(path) else 0
            when = ''
            if mtime:
                from datetime import datetime
                age_days = (datetime.now() - datetime.fromtimestamp(
                    mtime)).days
                if age_days == 0:
                    when = tr('today')
                elif age_days == 1:
                    when = tr('yesterday')
                else:
                    when = tr('{days} days ago', days=age_days)
            pin = '  \u2605' if self.pin_states.get(path) else ''
            return f'{name}\n{when}{pin}'
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            return self.thumbnails.get(path)
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return path
        if role == QtCore.Qt.ItemDataRole.FontRole:
            font = QtGui.QFont()
            font.setUnderline(True)
            return font
        return None


class RecentFilesView(QtWidgets.QListView):

    PIN_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent, view, files=None):
        super().__init__(parent)
        self.view = view
        self.files = files or []
        self.clicked.connect(self.on_clicked)
        self.setModel(RecentFilesModel(self.files, XRefSettings()))
        self.setMouseTracking(True)
        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.setIconSize(QtCore.QSize(96, 96))
        self.setGridSize(QtCore.QSize(140, 150))
        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)

    def on_clicked(self, index):
        self.view.open_from_file(self.files[index.row()])

    def toggle_pin(self, index):
        """Pins/unpins the file at the given index."""

        path = self.files[index.row()]
        XRefSettings().toggle_pinned_recent_file(path)
        self.model().refresh_metadata()
        self.model().layoutChanged.emit()
        # Pinned files come first
        self.update_files(sorted(
            self.files,
            key=lambda f: not XRefSettings().is_pinned_recent_file(f)))

    def update_files(self, files):
        self.files = files
        self.model().files = files
        self.model().refresh_metadata()
        self.reset()

    def mouseMoveEvent(self, event):
        index = self.indexAt(
            QtCore.QPoint(int(event.position().x()),
                          int(event.position().y())))
        if index.isValid():
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        path = self.files[index.row()]
        pinned = XRefSettings().is_pinned_recent_file(path)
        menu = QtWidgets.QMenu(self)
        pin_action = menu.addAction(
            tr('Unpin') if pinned else tr('Pin to top'))
        folder_action = menu.addAction(tr('Open file location'))
        action = menu.exec(event.globalPos())
        if action == pin_action:
            self.toggle_pin(index)
        elif action == folder_action:
            folder = os.path.dirname(path)
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(folder))


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

        # Recent files
        self.files_widget = QtWidgets.QWidget(self)
        files_layout = QtWidgets.QVBoxLayout()
        files_layout.addStretch(50)
        files_layout.addWidget(
            QtWidgets.QLabel(
                f'<h3>{tr("Recent Files")}</h3>', self))
        self.files_view = RecentFilesView(self, parent)
        files_layout.addWidget(self.files_view)
        files_layout.addStretch(50)
        self.files_widget.setLayout(files_layout)
        self.files_widget.hide()

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
        files = XRefSettings().get_recent_files(existing_only=True)
        self.files_view.update_files(files)
        if files and self.layout.indexOf(self.files_widget) < 0:
            self.layout.insertWidget(0, self.files_widget)
            self.files_widget.show()
        super().show()

    def disable_mouse_events(self):
        self.files_view.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.center_widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def enable_mouse_events(self):
        self.files_view.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            on=False)
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
