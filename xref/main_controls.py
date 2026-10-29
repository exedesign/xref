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

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from xref import commands, widgets
from xref.i18n import tr
from xref.fileio.media import media_type
from xref.items import XRefPixmapItem
from xref import fileio


logger = logging.getLogger(__name__)


class MainControlsMixin:
    """Basic controls shared by the main view and the welcome overlay:

    * Right-click menu
    * Dropping files, images, texts and links
    * Moving the window without title bar
    """

    # Files with these extensions are inserted as text items
    TEXT_FILE_EXTENSIONS = (
        '.txt', '.md', '.markdown', '.rst', '.log', '.csv', '.tsv',
        '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
        '.xml', '.html', '.htm', '.css', '.scss', '.js', '.ts', '.jsx',
        '.tsx', '.py', '.rb', '.php', '.pl', '.lua', '.sql', '.sh',
        '.bash', '.zsh', '.ps1', '.bat', '.cmd', '.c', '.h', '.cpp',
        '.hpp', '.cc', '.cs', '.java', '.kt', '.go', '.rs', '.swift',
        '.srt', '.vtt', '.tex', '.diff', '.patch',
    )
    MAX_TEXT_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

    def init_main_controls(self, main_window):
        self.main_window = main_window
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            self.control_target.on_context_menu)
        self.setAcceptDrops(True)
        self.movewin_active = False
        # Hover events (video controls, link ports) need mouse tracking
        if hasattr(self, 'viewport'):
            self.viewport().setMouseTracking(True)

    @classmethod
    def is_text_file(cls, path):
        """Whether the given file should be inserted as a text item."""

        if os.path.splitext(path)[1].lower() not in cls.TEXT_FILE_EXTENSIONS:
            return False
        try:
            return os.path.getsize(path) <= cls.MAX_TEXT_FILE_SIZE
        except OSError:
            return False

    @staticmethod
    def read_text_file(path):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read().strip()
        except OSError as e:
            logger.info(f'Could not read text file {path}: {e}')
            return ''

    @staticmethod
    def dropped_text(mimedata):
        """The text contained in the mimedata (plain text or HTML)."""

        text = (mimedata.text() or '').strip()
        if text:
            return text
        if mimedata.hasHtml():
            doc = QtGui.QTextDocument()
            doc.setHtml(mimedata.html())
            return doc.toPlainText().strip()
        return ''

    def can_accept_drop(self, mimedata):
        """Whether anything in the mimedata can be inserted."""

        return bool(mimedata.hasUrls()
                    or mimedata.hasImage()
                    or mimedata.hasText()
                    or mimedata.hasHtml())

    def on_action_movewin_mode(self):
        if self.movewin_active:
            # Pressing the same shortcut again should end the action
            self.exit_movewin_mode()
        else:
            self.enter_movewin_mode()

    @property
    def viewport_or_self(self):
        if hasattr(self, 'viewport'):
            return self.viewport()
        return self

    def enter_movewin_mode(self):
        logger.debug('Entering movewin mode')
        self.setMouseTracking(True)
        self.movewin_active = True
        self.viewport_or_self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.event_start = QtCore.QPointF(self.cursor().pos())
        if hasattr(self, 'disable_mouse_events'):
            self.disable_mouse_events()

    def exit_movewin_mode(self):
        logger.debug('Exiting movewin mode')
        self.setMouseTracking(False)
        self.movewin_active = False
        self.viewport_or_self.unsetCursor()
        if hasattr(self, 'enable_mouse_events'):
            self.enable_mouse_events()

    def dragEnterEvent(self, event):
        mimedata = event.mimeData()
        logger.debug(f'Drag enter event: {mimedata.formats()}')
        if self.can_accept_drop(mimedata):
            event.acceptProposedAction()
        else:
            logger.info(f'Drop not supported: {mimedata.formats()}')

    def dragMoveEvent(self, event):
        if self.can_accept_drop(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        mimedata = event.mimeData()
        logger.debug(f'Handling drop: {mimedata.formats()}')
        pos = QtCore.QPoint(round(event.position().x()),
                            round(event.position().y()))
        target = self.control_target

        if mimedata.hasUrls():
            handled = self._drop_urls(mimedata.urls(), pos)
        elif mimedata.hasImage():
            handled = self._drop_image(mimedata, pos)
        else:
            handled = False

        if not handled:
            text = self.dropped_text(mimedata)
            if text:
                target.do_insert_text(text, pos)
                handled = True

        if not handled:
            logger.info('Nothing could be inserted from the drop')
            widgets.XRefNotification(
                target,
                tr('Nothing could be inserted from the dropped data'))

    def _drop_image(self, mimedata, pos):
        img = QtGui.QImage(mimedata.imageData())
        if img.isNull():
            return False
        item = XRefPixmapItem(img)
        self.control_target.undo_stack.push(
            commands.InsertItems(self.control_target.scene, [item],
                                 self.control_target.mapToScene(pos)))
        return True

    def _drop_urls(self, urls, pos):
        """Handles dropped files and links.

        * ``.bee`` files open a scene (when it is empty)
        * images and videos are inserted as media items
        * text-like files are inserted as text items
        * remote links are inserted as text items
        """

        target = self.control_target
        logger.debug(f'Found dropped urls: {urls}')
        local_urls = [u for u in urls if u.isLocalFile()]
        remote_urls = [u for u in urls if not u.isLocalFile()]

        bee_urls = [u for u in local_urls
                    if fileio.is_bee_file(u.toLocalFile())]
        if bee_urls and not target.scene.items():
            target.open_from_file(bee_urls[0].toLocalFile())
            return True

        text_urls = [u for u in local_urls
                     if self.is_text_file(u.toLocalFile())]
        media_urls = [u for u in local_urls if u not in text_urls]
        media_urls += [u for u in remote_urls
                       if media_type(u) in ('image', 'video')]

        handled = False
        if media_urls:
            target.do_insert_images(media_urls, pos)
            handled = True

        scale = target.get_scale()
        offset = 0
        for url in text_urls:
            text = self.read_text_file(url.toLocalFile())
            if text:
                target.do_insert_text(
                    text, pos + QtCore.QPoint(offset, offset))
                offset += int(24 / max(scale, 0.01))
                handled = True

        # Links dragged from a browser become text items
        for url in remote_urls:
            if url in media_urls:
                continue
            link = url.toString()
            if link:
                target.do_insert_text(link, pos)
                handled = True
        return handled

    def mousePressEventMainControls(self, event):
        if self.movewin_active:
            self.exit_movewin_mode()
            event.accept()
            return True

        action, inverted =\
            self.control_target.keyboard_settings.mouse_action_for_event(event)
        if action == 'movewindow':
            self.enter_movewin_mode()
            event.accept()
            return True

    def mouseMoveEventMainControls(self, event):
        if self.movewin_active:
            pos = self.mapToGlobal(event.position())
            delta = pos - self.event_start
            self.event_start = pos
            self.main_window.move(self.main_window.x() + int(delta.x()),
                                  self.main_window.y() + int(delta.y()))
            event.accept()
            return True

    def mouseReleaseEventMainControls(self, event):
        if self.movewin_active:
            self.exit_movewin_mode()
            event.accept()
            return True

    def keyPressEventMainControls(self, event):
        if self.movewin_active:
            self.exit_movewin_mode()
            event.accept()
            return True
