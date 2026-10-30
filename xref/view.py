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

from functools import partial
import logging
import os
import os.path

from PyQt6 import QtCore, QtGui, QtWidgets, sip
from PyQt6.QtCore import Qt

from xref.actions import ActionsMixin, actions
from xref import collab, i18n
from xref.assets import XRefAssets
from xref import commands
from xref.config import CommandlineArgs, XRefSettings, KeyboardSettings
from xref import constants
from xref import fileio
from xref.fileio.errors import IMG_LOADING_ERROR_MSG
from xref.fileio.export import exporter_registry, ImagesToDirectoryExporter
from xref.i18n import tr
from xref import widgets
from xref.items import XRefPixmapItem, XRefTextItem
from xref.main_controls import MainControlsMixin
from xref.scene import XRefGraphicsScene
from xref.utils import get_file_extension_from_format, qcolor_to_hex


commandline_args = CommandlineArgs()
logger = logging.getLogger(__name__)


class AltDoubleTapFilter(QtCore.QObject):
    """Detects two quick presses and releases of the Alt key on its own
    (i.e. not used as a modifier for another key or mouse button)."""

    INTERVAL_MS = 450

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.last_tap = None
        self.alt_down = False
        self.alt_used_as_modifier = False
        self.timer = QtCore.QElapsedTimer()
        self.timer.start()

    def is_alt(self, event):
        return event.key() in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr)

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QtCore.QEvent.Type.KeyPress:
            if self.is_alt(event):
                if not event.isAutoRepeat() and not self.alt_down:
                    self.alt_down = True
                    self.alt_used_as_modifier = False
            elif self.alt_down:
                self.alt_used_as_modifier = True
        elif etype == QtCore.QEvent.Type.KeyRelease:
            if (self.is_alt(event) and not event.isAutoRepeat()
                    and self.alt_down):
                self.alt_down = False
                if self.alt_used_as_modifier:
                    self.last_tap = None
                    return False
                now = self.timer.elapsed()
                if (self.last_tap is not None
                        and now - self.last_tap <= self.INTERVAL_MS):
                    self.last_tap = None
                    self.callback()
                    # Don't let the menu bar grab focus on this release
                    return True
                self.last_tap = now
        elif etype in (QtCore.QEvent.Type.MouseButtonPress,
                       QtCore.QEvent.Type.Wheel):
            if self.alt_down:
                self.alt_used_as_modifier = True
            self.last_tap = None
        return False


class MenuBarDragFilter(QtCore.QObject):
    """Drags the window by the empty part of the menu bar.

    Frameless windows have no title bar, so the menu bar doubles as one.
    """

    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def eventFilter(self, obj, event):
        if (event.type() == QtCore.QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and obj.actionAt(event.pos()) is None):
            return self.view.start_window_move()
        return False


class XRefGraphicsView(MainControlsMixin,
                      QtWidgets.QGraphicsView,
                      ActionsMixin):

    PAN_MODE = 1
    ZOOM_MODE = 2
    SAMPLE_COLOR_MODE = 3

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.parent = parent
        self.settings = XRefSettings()
        self.keyboard_settings = KeyboardSettings()
        self.welcome_overlay = widgets.welcome_overlay.WelcomeOverlay(self)

        # The canvas colour can be set before the scene exists; invalid
        # colours fall back to the palette default
        self.setBackgroundBrush(QtGui.QBrush(
            self._canvas_color_from_settings()))
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        # Links are drawn in the foreground across large areas, so the
        # default minimal updates would leave trails behind moving items
        self.setViewportUpdateMode(
            QtWidgets.QGraphicsView.ViewportUpdateMode
            .BoundingRectViewportUpdate)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        self.undo_stack = QtGui.QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.undo_stack.canRedoChanged.connect(self.on_can_redo_changed)
        self.undo_stack.canUndoChanged.connect(self.on_can_undo_changed)
        self.undo_stack.cleanChanged.connect(self.on_undo_clean_changed)

        self.filename = None
        self.previous_transform = None
        self.active_mode = None
        self._native_resize_active = False

        self.scene = XRefGraphicsScene(self.undo_stack)
        self.scene.changed.connect(self.on_scene_changed)
        self.scene.selectionChanged.connect(self.on_selection_changed)
        self.scene.cursor_changed.connect(self.on_cursor_changed)
        self.scene.cursor_cleared.connect(self.on_cursor_cleared)
        self.scene.link_created.connect(self.on_link_created)
        self.scene.links_removed.connect(self.on_links_removed)
        self.scene.links_changed.connect(self.on_links_changed)

        # State for dragging media out of the window (copy to another app)
        self._drag_export_items = []
        self._drag_export_positions = []
        self._drag_export_start = None
        self.setScene(self.scene)

        i18n.language_events.changed.connect(self.on_language_changed)
        self.init_autosave()

        # Shared board session (see Collaborate menu)
        self.collab = collab.CollabSession(
            self.scene, name=self.get_collab_name(), parent=self)
        self.collab.status_changed.connect(self.on_collab_status)
        self.collab.peers_changed.connect(self.on_collab_peers_changed)
        self.collab.board_replaced.connect(self.on_collab_board_replaced)
        self.collab.became_host.connect(self.on_collab_became_host)

        # Context menu and actions
        self.build_menu_and_actions()
        self.control_target = self
        self.init_main_controls(main_window=parent)

        # Double-tapping Alt toggles pen mode. Alt is consumed by the
        # window system/menu bar before it reaches keyPressEvent, so we
        # watch it application-wide.
        self.alt_tap_filter = AltDoubleTapFilter(self.on_alt_double_tap)
        QtWidgets.QApplication.instance().installEventFilter(
            self.alt_tap_filter)

        # Load files given via command line
        if commandline_args.filenames:
            fn = commandline_args.filenames[0]
            if fileio.is_bee_file(fn):
                self.open_from_file(fn)
            else:
                self.do_insert_images(commandline_args.filenames)

        self.update_window_title()

    @property
    def filename(self):
        return self._filename

    @filename.setter
    def filename(self, value):
        self._filename = value
        self.update_window_title()
        if value:
            self.settings.update_recent_files(value)
            self.update_menu_and_actions()

    def cancel_active_modes(self):
        self.scene.cancel_active_modes()
        self.cancel_sample_color_mode()
        self.active_mode = None

    def cancel_sample_color_mode(self):
        logger.debug('Cancel sample color mode')
        self.active_mode = None
        self.viewport().unsetCursor()
        if hasattr(self, 'sample_color_widget'):
            self.sample_color_widget.hide()
            del self.sample_color_widget
        if self.scene.has_multi_selection():
            self.scene.multi_select_item.bring_to_front()

    def update_window_title(self):
        clean = self.undo_stack.isClean()
        if clean and not self.filename:
            title = constants.APPNAME
        else:
            name = (os.path.basename(self.filename)
                    if self.filename else f'[{tr("Untitled")}]')
            clean = '' if clean else '*'
            title = f'{name}{clean} - {constants.APPNAME}'
        session = getattr(self, 'collab', None)
        if session is not None and session.is_active():
            peers = session.peer_count()
            title = f'{title}  ·  {tr("shared ({count})", count=peers)}'
        self.parent.setWindowTitle(title)

    def on_scene_changed(self, region):
        if not self.scene.items():
            logger.debug('No items in scene')
            self.setTransform(QtGui.QTransform())
            self.welcome_overlay.setFocus()
            self.clearFocus()
            self.welcome_overlay.show()
            self.actiongroup_set_enabled('active_when_items_in_scene', False)
        else:
            self.setFocus()
            self.welcome_overlay.clearFocus()
            self.welcome_overlay.hide()
            self.actiongroup_set_enabled('active_when_items_in_scene', True)
        self.recalc_scene_rect()

    def on_can_redo_changed(self, can_redo):
        self.actiongroup_set_enabled('active_when_can_redo', can_redo)

    def on_can_undo_changed(self, can_undo):
        self.actiongroup_set_enabled('active_when_can_undo', can_undo)

    def on_undo_clean_changed(self, clean):
        self.update_window_title()

    def on_context_menu(self, point):
        self.context_menu.exec(self.mapToGlobal(point))

    def get_supported_image_formats(self, cls):
        formats = []

        for f in cls.supportedImageFormats():
            string = f'*.{f.data().decode()}'
            formats.extend((string, string.upper()))
        return ' '.join(formats)

    def get_view_center(self):
        return QtCore.QPoint(round(self.size().width() / 2),
                             round(self.size().height() / 2))

    def clear_scene(self):
        logging.debug('Clearing scene...')
        self.cancel_active_modes()
        self.scene.clear()
        self.undo_stack.clear()
        self.filename = None
        self.setTransform(QtGui.QTransform())

    def reset_previous_transform(self, toggle_item=None):
        if (self.previous_transform
                and self.previous_transform['toggle_item'] != toggle_item):
            self.previous_transform = None

    def fit_rect(self, rect, toggle_item=None):
        if toggle_item and self.previous_transform:
            logger.debug('Fit view: Reset to previous')
            self.setTransform(self.previous_transform['transform'])
            self.centerOn(self.previous_transform['center'])
            self.previous_transform = None
            return
        if toggle_item:
            self.previous_transform = {
                'toggle_item': toggle_item,
                'transform': QtGui.QTransform(self.transform()),
                'center': self.mapToScene(self.get_view_center()),
            }
        else:
            self.previous_transform = None

        logger.debug(f'Fit view: {rect}')
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.recalc_scene_rect()
        # It seems to be more reliable when we fit a second time
        # Sometimes a changing scene rect can mess up the fitting
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        logger.trace('Fit view done')

    def get_confirmation_unsaved_changes(self, msg):
        confirm = self.settings.valueOrDefault('Save/confirm_close_unsaved')
        if confirm and not self.undo_stack.isClean():
            answer = QtWidgets.QMessageBox.question(
                self,
                tr('Discard unsaved changes?'),
                msg,
                QtWidgets.QMessageBox.StandardButton.Yes |
                QtWidgets.QMessageBox.StandardButton.Cancel)
            return answer == QtWidgets.QMessageBox.StandardButton.Yes

        return True

    def on_action_new_scene(self):
        confirm = self.get_confirmation_unsaved_changes(
            tr('There are unsaved changes. '
               'Are you sure you want to open a new scene?'))
        if confirm:
            self.clear_scene()

    def _canvas_color_from_settings(self):
        color = QtGui.QColor(self.settings.valueOrDefault('View/canvas_color'))
        if not color.isValid():
            color = QtGui.QColor(*constants.COLORS['Scene:Canvas'])
        return color

    def apply_canvas_color(self):
        """Sets the background colour of the canvas from the settings."""

        brush = QtGui.QBrush(self._canvas_color_from_settings())
        self.setBackgroundBrush(brush)
        scene = getattr(self, 'scene', None)
        if scene is not None:
            scene.setBackgroundBrush(brush)

    def get_canvas_color(self):
        """The current canvas colour."""

        return self.backgroundBrush().color()

    def set_canvas_color(self, color):
        """Sets and stores a new canvas colour."""

        self.settings.setValue('View/canvas_color', color.name())
        self.apply_canvas_color()
        self.viewport().update()

    def on_action_fit_scene(self):
        self.fit_rect(self.scene.itemsBoundingRect())

    def on_action_fit_selection(self):
        self.fit_rect(self.scene.itemsBoundingRect(selection_only=True))

    def on_action_fullscreen(self, checked):
        centre = self.view_centre_scene()
        if checked:
            self.parent.showFullScreen()
        else:
            self.parent.showNormal()
        # The window manager may not apply full screen on offscreen/minimal
        # platforms; the action state still follows the user's intent
        self.schedule_recentre(centre)

    def view_centre_scene(self):
        """The scene point in the middle of the viewport."""

        viewport = self.viewport()
        return self.viewport_to_scene(
            QtCore.QPointF(viewport.width() / 2, viewport.height() / 2))

    def recentre_to(self, scene_point):
        """Puts the given scene point back into the middle of the view."""

        if scene_point is None:
            return
        # Make sure the scene rectangle has room before scrolling
        self.recalc_scene_rect()
        viewport = self.viewport()
        self.scroll_scene_point_to(
            scene_point, QtCore.QPointF(viewport.width() / 2,
                                        viewport.height() / 2))

    def schedule_recentre(self, scene_point, delays=(0, 80, 250)):
        """Re-centres the canvas after an asynchronous window change.

        The window manager reports the new geometry in several steps (and
        sometimes late), so the view is corrected a few times.
        """

        if scene_point is None:
            return
        for delay in delays:
            QtCore.QTimer.singleShot(
                delay, partial(self.recentre_to, scene_point))

    def is_frameless(self):
        """Whether the window has no OS title bar (PureRef-like look)."""

        return bool(self.parent.windowFlags()
                    & Qt.WindowType.FramelessWindowHint)

    def apply_window_flags(self, frameless=None, on_top=None):
        """Changes the window flags and keeps the window usable.

        Changing the flags hides the window, so it is shown again with the
        same geometry (and full screen state) as before.
        """

        window = self.parent
        flags = window.windowFlags()
        if frameless is not None:
            if frameless:
                flags |= Qt.WindowType.FramelessWindowHint
            else:
                flags &= ~Qt.WindowType.FramelessWindowHint
        if on_top is not None:
            if on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
        if flags == window.windowFlags():
            return
        visible = window.isVisible()
        fullscreen = window.isFullScreen()
        maximized = window.isMaximized()
        geometry = window.geometry()
        window.setWindowFlags(flags)
        window.setGeometry(geometry)
        if fullscreen:
            window.showFullScreen()
        elif maximized:
            window.showMaximized()
        elif visible:
            window.show()

    def toggle_fullscreen(self):
        """Switches between full screen and a normal window."""

        fullscreen = not self.parent.isFullScreen()
        action = actions.actions['fullscreen'].qaction
        if action is not None and action.isChecked() != fullscreen:
            action.blockSignals(True)
            action.setChecked(fullscreen)
            action.blockSignals(False)
        self.on_action_fullscreen(fullscreen)

    def on_action_always_on_top(self, checked):
        self.settings.setValue('View/always_on_top', checked)
        self.apply_window_flags(on_top=checked)

    RESIZE_EDGE_MARGIN = 6
    DEFAULT_MOVE_MARGIN = 10

    def start_window_move(self):
        """Starts a native window drag (used for frameless windows)."""

        handle = self.parent.windowHandle()
        return handle is not None and handle.startSystemMove()

    def start_window_resize(self, edges):
        """Starts a native window resize from the given edges."""

        handle = self.parent.windowHandle()
        if handle is None:
            return False
        self._native_resize_active = True
        try:
            return handle.startSystemResize(edges)
        finally:
            self._native_resize_active = False

    def make_menubar_dragable(self, menu_bar):
        """Lets the empty part of the menu bar move the window."""

        if menu_bar is None:
            return
        filt = getattr(self, '_menubar_drag_filter', None)
        if filt is None:
            filt = MenuBarDragFilter(self)
            self._menubar_drag_filter = filt
        menu_bar.installEventFilter(filt)

    def window_move_margin(self):
        """How many pixels inside the edge drag the window along."""

        return max(0, int(self.settings.valueOrDefault(
            'View/window_move_margin')))

    def window_edge_hit(self, pos):
        """What a left press at this viewport position does to the window.

        Frameless windows have neither a title bar nor an OS border, so the
        outermost pixels resize the window and the band right inside of it
        moves the window - on every edge and corner.

        :return: ``('resize', edges)``, ``('move', None)`` or ``None``
        """

        if not self.is_frameless():
            return None
        try:
            x = float(pos.x())
            y = float(pos.y())
        except (TypeError, ValueError):
            return None
        rect = self.rect()
        width, height = rect.width(), rect.height()
        if not (0 <= x <= width and 0 <= y <= height):
            return None
        # Scrollbars live at the very edge; leave them usable
        hbar = self.horizontalScrollBar()
        if hbar.isVisible() and y >= height - hbar.height():
            return None
        vbar = self.verticalScrollBar()
        if vbar.isVisible() and x >= width - vbar.width():
            return None
        Edge = Qt.Edge
        margin = self.RESIZE_EDGE_MARGIN
        band = margin + self.window_move_margin()
        left = x <= band
        right = x >= width - band
        top = y <= band
        bottom = y >= height - band
        horizontal = (Edge.LeftEdge if x <= margin
                      else Edge.RightEdge if x >= width - margin else None)
        vertical = (Edge.TopEdge if y <= margin
                    else Edge.BottomEdge if y >= height - margin else None)
        if (left or right) and (top or bottom):
            # Corners resize diagonally, like the border of a normal window
            corner = ((Edge.LeftEdge if left else Edge.RightEdge)
                      | (Edge.TopEdge if top else Edge.BottomEdge))
            return 'resize', corner
        if horizontal is not None:
            return 'resize', horizontal
        if vertical is not None:
            return 'resize', vertical
        if left or right or top or bottom:
            return 'move', None
        return None

    def resize_edges_at(self, pos):
        """The window edges under a viewport position.

        :rtype: Qt.Edge or None
        """

        hit = self.window_edge_hit(pos)
        if hit is None or hit[0] != 'resize':
            return None
        return hit[1]

    def resize_cursor(self, edges):
        """The mouse cursor for the given window edges."""

        cursor = Qt.CursorShape
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if left or right:
            if top or bottom:
                return QtGui.QCursor(
                    cursor.SizeFDiagCursor if left == top
                    else cursor.SizeBDiagCursor)
            return QtGui.QCursor(cursor.SizeHorCursor)
        return QtGui.QCursor(cursor.SizeVerCursor)

    def update_window_edge_cursor(self, pos, widget=None):
        """Shows a resize/move cursor while the pointer is on a window edge.

        Only the empty canvas is used for the window edges; over items, the
        items' own cursors (selection handles, video controls, link ports)
        take precedence.
        """

        widget = widget if widget is not None else self.viewport()
        scene = getattr(self, 'scene', None)
        if scene is not None and scene.mouseGrabberItem() is not None:
            return
        try:
            item_under = self.itemAt(pos)
        except (TypeError, RuntimeError):
            item_under = None
        if item_under is not None:
            if getattr(widget, '_window_edge_cursor_active', False):
                widget._window_edge_cursor_active = False
                widget.unsetCursor()
            return
        hit = self.window_edge_hit(pos)
        if hit is None:
            if getattr(widget, '_window_edge_cursor_active', False):
                widget._window_edge_cursor_active = False
                widget.unsetCursor()
            return
        widget._window_edge_cursor_active = True
        if hit[0] == 'move':
            widget.setCursor(QtGui.QCursor(Qt.CursorShape.SizeAllCursor))
        else:
            widget.setCursor(self.resize_cursor(hit[1]))

    def on_action_show_scrollbars(self, checked):
        if checked:
            self.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def on_action_show_menubar(self, checked):
        if checked:
            menu_bar = self.create_menubar()
            self.parent.setMenuBar(menu_bar)
            self.make_menubar_dragable(menu_bar)
        else:
            self.parent.setMenuBar(None)

    def on_action_show_titlebar(self, checked):
        self.settings.setValue('View/show_titlebar', checked)
        self.apply_window_flags(frameless=not checked)

    def on_action_move_window(self):
        if self.welcome_overlay.isHidden():
            self.on_action_movewin_mode()
        else:
            self.welcome_overlay.on_action_movewin_mode()

    def on_action_undo(self):
        logger.debug('Undo: %s' % self.undo_stack.undoText())
        self.cancel_active_modes()
        self.undo_stack.undo()

    def on_action_redo(self):
        logger.debug('Redo: %s' % self.undo_stack.redoText())
        self.cancel_active_modes()
        self.undo_stack.redo()

    def on_action_select_all(self):
        self.scene.select_all_items()

    def on_action_deselect_all(self):
        self.scene.deselect_all_items()

    def on_action_delete_items(self):
        logger.debug('Deleting items...')
        self.cancel_active_modes()
        if self.scene.selected_link is not None:
            # A clicked link can be deleted on its own (items stay)
            self.scene.delete_selected_link()
            return
        self.undo_stack.push(
            commands.DeleteItems(
                self.scene, self.scene.selectedItems(user_only=True)))

    def on_action_cut(self):
        logger.debug('Cutting items...')
        self.on_action_copy()
        self.undo_stack.push(
            commands.DeleteItems(
                self.scene, self.scene.selectedItems(user_only=True)))

    def on_action_raise_to_top(self):
        self.scene.raise_to_top()

    def on_action_lower_to_bottom(self):
        self.scene.lower_to_bottom()

    def on_action_normalize_height(self):
        self.scene.normalize_height()

    def on_action_normalize_width(self):
        self.scene.normalize_width()

    def on_action_normalize_size(self):
        self.scene.normalize_size()

    def on_action_arrange_horizontal(self):
        self.scene.arrange()

    def on_action_arrange_vertical(self):
        self.scene.arrange(vertical=True)

    def on_action_arrange_optimal(self):
        self.scene.arrange_optimal()

    def on_action_arrange_square(self):
        self.scene.arrange_square()

    def on_action_arrange_randomly(self):
        self.scene.arrange_randomly()

    def on_action_duplicate(self):
        """Duplicates the selection with a small offset (Ctrl+D)."""

        items = self.scene.selectedItems(user_only=True)
        if not items:
            return
        copies = [item.create_copy() for item in items]
        offset = 20 / max(self.get_scale(), 0.01)
        self.undo_stack.push(
            commands.InsertItems(self.scene, copies,
                                 QtCore.QPointF(offset, offset)))
        for copy in copies:
            copy.setSelected(True)

    def on_action_change_opacity(self):
        images = list(filter(
            lambda item: item.is_image,
            self.scene.selectedItems(user_only=True)))
        widgets.ChangeOpacityDialog(self, images, self.undo_stack)

    def on_action_grayscale(self, checked):
        images = list(filter(
            lambda item: item.is_image,
            self.scene.selectedItems(user_only=True)))
        if images:
            self.undo_stack.push(
                commands.ToggleGrayscale(images, checked))

    def on_action_crop(self):
        self.scene.crop_items()

    def on_action_flip_horizontally(self):
        self.scene.flip_items(vertical=False)

    def on_action_flip_vertically(self):
        self.scene.flip_items(vertical=True)

    def on_action_reset_scale(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetScale(
            self.scene.selectedItems(user_only=True)))

    def on_action_reset_rotation(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetRotation(
            self.scene.selectedItems(user_only=True)))

    def on_action_reset_flip(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetFlip(
            self.scene.selectedItems(user_only=True)))

    def on_action_reset_crop(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetCrop(
            self.scene.selectedItems(user_only=True)))

    def on_action_reset_transforms(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetTransforms(
            self.scene.selectedItems(user_only=True)))

    def on_action_show_color_gamut(self):
        widgets.color_gamut.GamutDialog(self, self.scene.selectedItems()[0])

    def on_action_sample_color(self):
        self.cancel_active_modes()
        logger.debug('Entering sample color mode')
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.active_mode = self.SAMPLE_COLOR_MODE

        if self.scene.has_multi_selection():
            # We don't want to sample the multi select item, so
            # temporarily send it to the back:
            self.scene.multi_select_item.lower_behind_selection()

        pos = self.mapFromGlobal(self.cursor().pos())
        self.sample_color_widget = widgets.SampleColorWidget(
            self,
            pos,
            self.scene.sample_color_at(self.mapToScene(pos)))

    def on_items_loaded(self, value):
        logger.debug('On items loaded: add queued items')
        self.scene.add_queued_items()

    def on_loading_finished(self, filename, errors):
        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                tr('Problem loading file'),
                tr('<p>Problem loading file {filename}</p>'
                   '<p>Not accessible or not a proper bee file</p>',
                   filename=filename))
        else:
            self.filename = filename
            self.scene.add_queued_items()
            # Restore the window layout stored for this scene, if any
            window = getattr(self.parent, 'restore_scene_layout', None)
            if window is not None:
                window()
            self.on_action_fit_scene()

    def on_action_open_recent_file(self, filename):
        confirm = self.get_confirmation_unsaved_changes(
            tr('There are unsaved changes. '
               'Are you sure you want to open a new scene?'))
        if confirm:
            self.open_from_file(filename)

    def open_from_file(self, filename):
        logger.info(f'Opening file {filename}')
        self.clear_scene()
        self.worker = fileio.ThreadedIO(
            fileio.load_bee, filename, self.scene)
        self.worker.progress.connect(self.on_items_loaded)
        self.worker.finished.connect(self.on_loading_finished)
        self.progress = widgets.XRefProgressDialog(
            f'Loading {filename}',
            worker=self.worker,
            parent=self)
        self.worker.start()

    def on_action_open(self):
        confirm = self.get_confirmation_unsaved_changes(
            tr('There are unsaved changes. '
               'Are you sure you want to open a new scene?'))
        if not confirm:
            return

        self.cancel_active_modes()
        filename, f = QtWidgets.QFileDialog.getOpenFileName(
            parent=self,
            caption=tr('Open file'),
            filter=f'{constants.APPNAME} Board (*.xref *.bee)')
        if filename:
            filename = os.path.normpath(filename)
            self.open_from_file(filename)
            self.filename = filename

    def on_saving_finished(self, filename, errors):
        if errors:
            if getattr(self, '_saving_quietly', False):
                # Autosave must not interrupt the user with dialogs
                logger.warning(f'Autosave failed for {filename}')
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    tr('Problem saving file'),
                    tr('<p>Problem saving file {filename}</p>'
                       '<p>File/directory not accessible</p>',
                       filename=filename))
        else:
            self.filename = filename
            self.undo_stack.setClean()
            self.update_window_title()
        self._saving_quietly = False

    def do_save(self, filename, create_new, quiet=False):
        if not fileio.is_bee_file(filename):
            filename = f'{filename}.{constants.FILE_EXTENSION}'
        self.worker = fileio.ThreadedIO(
            fileio.save_bee, filename, self.scene, create_new=create_new)
        self.worker.finished.connect(self.on_saving_finished)
        self._saving_quietly = quiet
        if quiet:
            self.worker.start()
            return
        self.progress = widgets.XRefProgressDialog(
            tr('Saving {filename}', filename=filename),
            worker=self.worker,
            parent=self)
        self.worker.start()

    # -- Autosave ----------------------------------------------------------

    def init_autosave(self):
        self._saving_quietly = False
        self._last_autosave = QtCore.QElapsedTimer()
        self._last_autosave.start()
        self.autosave_timer = QtCore.QTimer(self)
        self.autosave_timer.setInterval(15 * 1000)
        self.autosave_timer.timeout.connect(self.on_autosave_tick)
        self.autosave_timer.start()

    def autosave_enabled(self):
        return self.settings.valueOrDefault('Save/autosave')

    def on_autosave_tick(self, force=False):
        """Saves the board periodically if autosave is enabled."""

        if not self.autosave_enabled():
            return False
        worker = getattr(self, 'worker', None)
        if worker is not None and worker.isRunning():
            # A save is already in progress
            return False
        if not self.filename or self.undo_stack.isClean():
            return False
        interval = (self.settings.valueOrDefault('Save/autosave_interval')
                    * 60 * 1000)
        if not force and self._last_autosave.elapsed() < interval:
            return False
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        self._last_autosave.restart()
        logger.info('Autosaving...')
        self.do_save(self.filename, create_new=False, quiet=True)
        return True

    def on_action_save_as(self):
        self.cancel_active_modes()
        directory = os.path.dirname(self.filename) if self.filename else None
        filename, f = QtWidgets.QFileDialog.getSaveFileName(
            parent=self,
            caption=tr('Save file'),
            directory=directory,
            filter=f'{constants.APPNAME} Board (*.xref *.bee)')
        if filename:
            self.do_save(filename, create_new=True)

    def on_action_save(self):
        self.cancel_active_modes()
        if not self.filename:
            self.on_action_save_as()
        else:
            self.do_save(self.filename, create_new=False)

    def on_action_export_scene(self):
        directory = os.path.dirname(self.filename) if self.filename else None
        filename, formatstr = QtWidgets.QFileDialog.getSaveFileName(
            parent=self,
            caption=tr('Export Scene to Image'),
            directory=directory,
            filter=';;'.join(('Image Files (*.png *.jpg *.jpeg *.webp *.svg)',
                              'PNG (*.png)',
                              'JPEG (*.jpg *.jpeg)',
                              'WebP (*.webp)',
                              'SVG (*.svg)')))

        if not filename:
            return

        name, ext = os.path.splitext(filename)
        if not ext:
            ext = get_file_extension_from_format(formatstr)
            filename = f'{filename}.{ext}'
        logger.debug(f'Got export filename {filename}')

        exporter_cls = exporter_registry[ext]
        exporter = exporter_cls(self.scene)
        if not exporter.get_user_input(self):
            return

        self.worker = fileio.ThreadedIO(exporter.export, filename)
        self.worker.finished.connect(self.on_export_finished)
        self.progress = widgets.XRefProgressDialog(
            f'Exporting {filename}',
            worker=self.worker,
            parent=self)
        self.worker.start()

    def on_export_finished(self, filename, errors):
        if errors:
            err_msg = '</br>'.join(str(errors))
            QtWidgets.QMessageBox.warning(
                self,
                tr('Problem writing file'),
                tr('<p>Problem writing file {filename}</p>'
                   '<p>{error}</p>', filename=filename, error=err_msg))

    def on_action_export_images(self):
        directory = os.path.dirname(self.filename) if self.filename else None
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            parent=self,
            caption=tr('Export Images'),
            directory=directory)

        if not directory:
            return

        logger.debug(f'Got export directory {directory}')
        self.exporter = ImagesToDirectoryExporter(self.scene, directory)
        self.worker = fileio.ThreadedIO(self.exporter.export)
        self.worker.user_input_required.connect(
            self.on_export_images_file_exists)
        self.worker.finished.connect(self.on_export_finished)
        self.progress = widgets.XRefProgressDialog(
            f'Exporting to {directory}',
            worker=self.worker,
            parent=self)
        self.worker.start()

    def on_export_images_file_exists(self, filename):
        dlg = widgets.ExportImagesFileExistsDialog(self, filename)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.exporter.handle_existing = dlg.get_answer()
            directory = self.exporter.dirname
            self.progress = widgets.XRefProgressDialog(
                f'Exporting to {directory}',
                worker=self.worker,
                parent=self)
            self.worker.start()

    def on_action_open_scene_location(self):
        """Opens the folder of the current board in the file explorer."""

        filename = getattr(self, 'filename', None)
        if not filename:
            widgets.XRefNotification(self, tr('No file open'))
            return
        folder = os.path.dirname(os.path.abspath(filename))
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))

    def on_action_quit(self):
        confirm = self.get_confirmation_unsaved_changes(
            tr('There are unsaved changes. Are you sure you want to quit?'))
        if confirm:
            logger.info('User quit. Exiting...')
            self.app.quit()

    def on_action_settings(self):
        widgets.settings.SettingsDialog(self)

    def on_action_keyboard_settings(self):
        widgets.controls.ControlsDialog(self)

    def on_action_help(self):
        widgets.HelpDialog(self)

    def on_action_about(self):
        logo = XRefAssets().PATH.joinpath('logo-horizontal.png')
        logo_url = QtCore.QUrl.fromLocalFile(str(logo)).toString()
        QtWidgets.QMessageBox.about(
            self,
            tr('About {app}', app=constants.APPNAME),
            (f'<p><img src="{logo_url}" width="320"></p>'
             f'<h2>{constants.APPNAME} {constants.VERSION}</h2>'
             f'<p>{constants.APPNAME_FULL}</p>'
             f'<p>{constants.COPYRIGHT}</p>'
             f'<p><a href="{constants.WEBSITE}">'
             f'Visit the {constants.APPNAME} website</a></p>'))

    def on_action_debuglog(self):
        widgets.DebugLogDialog(self)

    def on_insert_images_finished(self, new_scene, filename, errors):
        """Callback for when loading of images is finished.

        :param new_scene: True if the scene was empty before, else False
        :param filename: Not used, for compatibility only
        :param errors: List of filenames that couldn't be loaded
        """

        logger.debug('Insert images finished')
        if errors:
            errornames = [
                f'<li>{fn}</li>' for fn in errors]
            errornames = '<ul>%s</ul>' % '\n'.join(errornames)
            num = len(errors)
            msg = f'{num} image(s) could not be opened.<br/>'
            QtWidgets.QMessageBox.warning(
                self,
                tr('Problem loading images'),
                msg + tr(IMG_LOADING_ERROR_MSG) + errornames)
        self.scene.add_queued_items()
        self.scene.arrange_default()
        self.undo_stack.endMacro()
        if new_scene:
            self.on_action_fit_scene()

    def do_insert_images(self, filenames, pos=None):
        if not pos:
            pos = self.get_view_center()
        self.scene.deselect_all_items()
        self.undo_stack.beginMacro('Insert Images')
        self.worker = fileio.ThreadedIO(
            fileio.load_media_items,
            filenames,
            self.mapToScene(pos),
            self.scene)
        self.worker.progress.connect(self.on_items_loaded)
        self.worker.finished.connect(
            partial(self.on_insert_images_finished,
                    not self.scene.items()))
        self.progress = widgets.XRefProgressDialog(
            'Loading media',
            worker=self.worker,
            parent=self)
        self.worker.start()

    def get_supported_video_formats(self):
        from xref.fileio.media import VIDEO_EXTENSIONS
        return ' '.join(VIDEO_EXTENSIONS)

    def on_action_insert_images(self):
        self.cancel_active_modes()
        formats = self.get_supported_image_formats(QtGui.QImageReader)
        logger.debug(f'Supported image types for reading: {formats}')
        filenames, f = QtWidgets.QFileDialog.getOpenFileNames(
            parent=self,
            caption=tr('Select one or more images or PDFs to open'),
            filter=(f'Images and PDFs ({formats} *.pdf);;'
                    f'PDF (*.pdf);;'
                    f'Images ({formats});;'
                    f'3D Models (*.obj *.stl *.ply *.fbx *.glb *.gltf '
                    f'*.usdz)'))
        self.do_insert_images(filenames)

    def on_action_insert_video(self):
        self.cancel_active_modes()
        formats = self.get_supported_video_formats()
        filenames, f = QtWidgets.QFileDialog.getOpenFileNames(
            parent=self,
            caption=tr('Select one or more videos to open'),
            filter=f'Videos ({formats})')
        self.do_insert_images(filenames)

    def on_action_insert_text(self):
        self.cancel_active_modes()
        item = XRefTextItem()
        pos = self.mapToScene(self.mapFromGlobal(self.cursor().pos()))
        item.setScale(1 / self.get_scale())
        self.undo_stack.push(commands.InsertItems(self.scene, [item], pos))

    def do_insert_text(self, text, pos=None):
        """Inserts a text item at the given view position.

        Used by the text tool and when text, text files or links are
        dropped onto the scene.

        :param str text: The text to insert
        :param QtCore.QPoint | None pos: Position in view coordinates
        :rtype: XRefTextItem | None
        """

        text = (text or '').strip()
        if not text:
            return None
        if pos is None:
            pos = self.get_view_center()
        self.cancel_active_modes()
        was_empty = not self.scene.items()
        item = XRefTextItem(text)
        item.setScale(1 / self.get_scale())
        if '\n' in text or len(text) > 40:
            # Wrap longer texts so they stay readable
            item.setTextWidth(XRefTextItem.DEFAULT_WRAP_WIDTH)
        self.undo_stack.push(
            commands.InsertItems(self.scene, [item], self.mapToScene(pos)))
        if was_empty:
            self.on_action_fit_scene()
        return item

    def on_action_play_video(self):
        """Plays the selected video item from the position it was last
        stopped at."""

        item = next(
            (i for i in self.scene.selectedItems(user_only=True)
             if getattr(i, 'is_video', False)),
            None)
        if item is None:
            widgets.XRefNotification(self, tr('Select a video item first'))
            return
        item.toggle_play()

    def on_action_toggle_draw(self, checked=None):
        """Toggles pen/draw mode (freehand notes & sketches)."""

        if checked is None:
            checked = not self.scene.draw_mode
            self.scene.toggle_draw_mode()
        elif checked:
            if not self.scene.draw_mode:
                self.scene.enter_draw_mode()
        else:
            if self.scene.draw_mode:
                self.scene.exit_draw_mode()
        # Keep the menu action's checked state in sync
        qaction = getattr(actions.actions['toggle_draw'], 'qaction', None)
        if qaction is not None:
            qaction.blockSignals(True)
            qaction.setChecked(self.scene.draw_mode)
            qaction.blockSignals(False)

    def set_pen_tool(self, shape):
        """Selects the pen mode tool (freehand or one of the shapes)."""

        self.scene.draw_shape = shape
        # Pen mode itself is toggled separately; picking a tool must not
        # enable it on its own (the actions start checked at startup)
        for tool, action_id in (
                ('freehand', 'pen_tool_freehand'),
                ('rect', 'pen_tool_rect'),
                ('ellipse', 'pen_tool_ellipse'),
                ('line', 'pen_tool_line')):
            action = actions.actions.get(action_id)
            if action is None or action.qaction is None:
                continue
            action.qaction.blockSignals(True)
            action.qaction.setChecked(tool == shape)
            action.qaction.blockSignals(False)

    def on_action_pen_tool_freehand(self, checked):
        if checked:
            self.set_pen_tool('freehand')

    def on_action_pen_tool_rect(self, checked):
        if checked:
            self.set_pen_tool('rect')

    def on_action_pen_tool_ellipse(self, checked):
        if checked:
            self.set_pen_tool('ellipse')

    def on_action_pen_tool_line(self, checked):
        if checked:
            self.set_pen_tool('line')

    def on_action_pen_color(self):
        """Picks the colour for the pen (applies to selected strokes)."""

        current = QtGui.QColor(*self.scene.pen_color)
        color = QtWidgets.QColorDialog.getColor(
            current, self, 'Pen Colour')
        if color.isValid():
            self.scene.set_pen_color(color)
            if self.scene.draw_mode:
                widgets.XRefNotification(
                    self, tr('Pen colour: {name}', name=color.name()))

    def _set_pen_width(self, width):
        self.scene.set_pen_width(width)
        if self.scene.draw_mode:
            widgets.XRefNotification(
                self, tr('Brush size: {width}px', width=width))

    def on_action_pen_width_thin(self):
        self._set_pen_width(4)

    def on_action_pen_width_normal(self):
        self._set_pen_width(10)

    def on_action_pen_width_thick(self):
        self._set_pen_width(18)

    def on_action_pen_width_huge(self):
        self._set_pen_width(30)

    def on_action_link_items(self):
        """Links the two selected items (first selected = parent)."""

        items = self.scene.selectedItems(user_only=True)
        if len(items) != 2:
            widgets.XRefNotification(
                self, tr('Select exactly two items to link them '
                          '(first selected becomes the parent)'))
            return
        if not self.scene.link_selected_items():
            widgets.XRefNotification(
                self, tr('These items are already linked'))
            return
        widgets.XRefNotification(
            self, tr('Linked "{source}" -> "{target}"',
                    source=self._item_label(items[0]),
                    target=self._item_label(items[1])))

    def on_action_unlink_items(self):
        removed = self.scene.unlink_selected_items()
        if removed:
            widgets.XRefNotification(
                self, tr('Removed {count} link(s)', count=removed))
        else:
            widgets.XRefNotification(
                self, tr('Selected items have no links'))

    @staticmethod
    def _item_label(item):
        name = getattr(item, 'filename', None) or getattr(item, 'text', None)
        if not name:
            return item.TYPE
        return os.path.basename(str(name))[:40]

    def on_link_created(self, source, target):
        widgets.XRefNotification(
            self, tr('Linked "{source}" -> "{target}"',
                    source=self._item_label(source),
                    target=self._item_label(target)))

    def on_links_removed(self, count):
        widgets.XRefNotification(
            self, tr('Removed {count} link(s)', count=count))

    def on_links_changed(self):
        self.update_viewport_mode()

    def update_viewport_mode(self):
        """Links are painted in the scene's foreground over large areas.

        With the default minimal updates, moving an item would only
        repaint the items and leave the old link curves (and selection
        outlines) behind as trails, so switch to full repaints while
        links are present.
        """

        ViewMode = QtWidgets.QGraphicsView.ViewportUpdateMode
        if sip.isdeleted(self.scene) or sip.isdeleted(self):
            return
        try:
            has_links = bool(self.scene.active_links())
        except RuntimeError:  # scene already deleted (shutdown)
            return
        mode = (ViewMode.FullViewportUpdate if has_links
                else ViewMode.BoundingRectViewportUpdate)
        if self.viewportUpdateMode() != mode:
            logger.debug(f'Viewport update mode: {mode.name}')
            self.setViewportUpdateMode(mode)
        self.viewport().update()

    # -- Dragging media out of the window -----------------------------------

    def _prepare_drag_export(self, event):
        """Remembers the items a drag starts on, so that dragging them out
        of the window can export (copy) them."""

        self._drag_export_items = []
        self._drag_export_positions = []
        self._drag_export_start = None
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mods = event.modifiers()
        if (isinstance(mods, Qt.KeyboardModifier)
                and mods & Qt.KeyboardModifier.ShiftModifier):
            # Shift+drag creates a link; leaving the window must not
            # start an export drag instead
            return
        if self.scene.active_mode == self.scene.LINK_MODE:
            return
        pos = event.position()
        if not isinstance(pos, QtCore.QPointF):
            return
        scene_pos = self.mapToScene(pos.toPoint())
        item = self.scene.itemAt(scene_pos, self.transform())
        if item is None or getattr(item, 'is_draw', False):
            return
        if getattr(item, 'is_video', False) and item.is_control_hit(scene_pos):
            # Interacting with the player controls, not dragging the item
            return
        items = [i for i in self.scene.selectedItems(user_only=True)
                 if not getattr(i, 'is_draw', False)]
        if item not in items:
            return
        self._drag_export_items = items
        self._drag_export_positions = [i.pos() for i in items]
        self._drag_export_start = event.position()

    def _maybe_start_export_drag(self, event):
        """Starts an OS drag when a selected item is dragged out of the
        viewport (copying the media somewhere else)."""

        if not self._drag_export_items:
            return False
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return False
        if self._drag_export_start is not None:
            moved = event.position() - self._drag_export_start
            if moved.manhattanLength() < 20:
                return False
        margin = 10
        inside = self.viewport().rect().adjusted(
            -margin, -margin, margin, margin)
        if inside.contains(event.position().toPoint()):
            return False
        self._start_export_drag()
        return True

    def _start_export_drag(self):
        items = self._drag_export_items
        positions = self._drag_export_positions
        self._drag_export_items = []
        self._drag_export_positions = []
        self._drag_export_start = None

        mime = self.build_export_mime_data(items)
        if mime is None:
            return
        # Dragging out copies the media, so the originals stay in place
        for item, pos in zip(items, positions):
            item.setPos(pos)
        self.scene.active_mode = None
        self.scene.update()

        drag = QtGui.QDrag(self.viewport())
        drag.setMimeData(mime)
        pixmap = self._export_drag_pixmap(items)
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QtCore.QPoint(pixmap.width() // 2,
                                          pixmap.height() // 2))
        logger.info(f'Dragging {len(items)} item(s) out of the window')
        drag.exec(Qt.DropAction.CopyAction)

    @staticmethod
    def build_export_mime_data(items):
        """Builds the mime data used to drag items to other applications."""

        urls = []
        texts = []
        image = None
        for item in items:
            if getattr(item, 'is_video', False):
                if item.has_source_file():
                    urls.append(QtCore.QUrl.fromLocalFile(item.video_path))
                continue
            if getattr(item, 'TYPE', None) == 'text':
                text = item.toPlainText().strip()
                if text:
                    texts.append(text)
                continue
            filename = getattr(item, 'filename', None)
            if filename and os.path.isfile(filename):
                urls.append(QtCore.QUrl.fromLocalFile(filename))
            elif image is None and hasattr(item, 'pixmap'):
                image = item.pixmap().toImage()
        has_image = image is not None and not image.isNull()
        if not urls and not texts and not has_image:
            return None
        mime = QtCore.QMimeData()
        if urls:
            mime.setUrls(urls)
        if texts:
            mime.setText('\n'.join(texts))
        if has_image:
            mime.setImageData(image)
        return mime

    def _export_drag_pixmap(self, items):
        """A small preview shown next to the cursor while dragging out."""

        rect = self.scene.itemsBoundingRect(items=items)
        if rect.isEmpty() or rect.width() <= 0 or rect.height() <= 0:
            return None
        limit = 200
        scale = min(1.0, limit / max(rect.width(), rect.height()))
        size = QtCore.QSize(max(1, round(rect.width() * scale)),
                            max(1, round(rect.height() * scale)))
        image = QtGui.QImage(
            size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        selected = self.scene.selectedItems()
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        try:
            for item in selected:
                item.setSelected(False)
            self.scene.render(
                painter,
                QtCore.QRectF(QtCore.QPointF(0, 0),
                              QtCore.QPointF(size.width(),
                                             size.height())),
                rect)
        finally:
            painter.end()
            for item in selected:
                item.setSelected(True)
        return QtGui.QPixmap.fromImage(image)

    def on_alt_double_tap(self):
        if not self.isActiveWindow():
            return
        logger.debug('Alt double tap: toggle pen mode')
        self.on_action_toggle_draw()
        state = 'on' if self.scene.draw_mode else 'off'
        widgets.XRefNotification(
            self, tr('Pen mode {state}', state=tr(state)))

    # -- Language ----------------------------------------------------------

    def on_language_changed(self, code):
        self.retranslate_ui()

    def retranslate_ui(self):
        """Re-applies the active language to menus and open windows."""

        logger.debug('Retranslating the user interface')
        self.retranslate_actions()
        self.update_window_title()
        overlay = getattr(self, 'welcome_overlay', None)
        if overlay is not None:
            overlay.retranslate()
        window_buttons = getattr(self.parent, 'window_buttons', None)
        if window_buttons is not None:
            window_buttons.retranslate()

    # -- Shared board sessions ---------------------------------------------

    def get_collab_name(self):
        name = None
        settings = getattr(self, 'settings', None)
        if settings is not None:
            try:
                name = settings.value('Collab/name')
            except Exception:  # noqa: BLE001 - settings not ready yet
                name = None
        if not name:
            import getpass
            try:
                name = getpass.getuser()
            except Exception:  # noqa: BLE001 - no user info available
                name = 'XRef user'
        return name

    def on_collab_status(self, status):
        self.update_window_title()
        self.actiongroup_set_enabled('active_when_collab',
                                     self.collab.is_active())
        lowered = status.lower()
        if ('could not' in lowered or 'error' in lowered
                or 'denied' in lowered):
            widgets.XRefNotification(self, status)

    def on_collab_peers_changed(self, count):
        self.update_window_title()
        if count:
            widgets.XRefNotification(
                self, tr('Shared board: {count} peer(s) connected',
                        count=count))

    def on_collab_became_host(self):
        """This peer continues the session after the host went away."""
        self.update_window_title()
        widgets.XRefNotification(
            self, tr('You are now hosting the shared board'))

    def on_collab_board_replaced(self):
        # The board was replaced by the host's snapshot
        self.cancel_active_modes()
        self.undo_stack.clear()
        self.on_action_fit_scene()
        self.update_window_title()

    def on_action_collab_host(self):
        """Shares this board; peers join with the generated session code."""

        self.cancel_active_modes()
        if self.collab.is_active():
            widgets.XRefNotification(
                self, tr('A session is already running; stop it first'))
            return
        self.collab.name = self.get_collab_name()
        action = actions.actions['collab_approval'].qaction
        self.collab.approval_callback = (
            self.approve_collab_peer if action.isChecked() else None)
        code = self.collab.host()
        if not code:
            widgets.XRefNotification(self, self.collab.status)
            return
        QtWidgets.QApplication.clipboard().setText(code)
        QtWidgets.QMessageBox.information(
            self, tr('Share Board'),
            tr('This board is now shared.\n\n'
               'Session code:\n\n    {code}\n\n'
               '(The code has been copied to the clipboard.)\n\n'
               'Other users start XRef, choose Collaborate -> Join Shared '
               'Board and type this code. They do not need to know your IP '
               'address.\n\n'
               'The code is never sent over the network, the connection is '
               'encrypted, and you will be asked before anyone joins.\n\n'
               'Note: the board is not saved automatically - use File -> '
               'Save As to keep a copy.', code=code))
        self.update_window_title()

    def approve_collab_peer(self, name, address):
        """Asks whether a peer that knows the code may join."""

        answer = QtWidgets.QMessageBox.question(
            self, tr('Join Request'),
            tr('"{name}" ({address}) knows the session code and wants to '
               'join this board.\n\nAllow?',
               name=name, address=address or tr('unknown device')))
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def on_action_collab_join(self):
        """Joins a board using its session code (no IP needed)."""

        self.cancel_active_modes()
        if self.collab.is_active():
            answer = QtWidgets.QMessageBox.question(
                self, tr('Join Shared Board'),
                tr('You are already in a session. Leave it and join '
                   'another?'))
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            self.collab.leave()
        code, ok = QtWidgets.QInputDialog.getText(
            self, tr('Join Shared Board'),
            tr('Session code (for example K7M4Q-9PXE2):'))
        if not ok:
            return
        code = collab.normalize_code(code)
        if not code:
            widgets.XRefNotification(
                self, tr('Please enter the session code'))
            return
        if self.scene.items():
            answer = QtWidgets.QMessageBox.question(
                self, tr('Join Shared Board'),
                tr('Joining loads the shared board and replaces the items '
                   'currently in this window. Continue?'))
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.collab.name = self.get_collab_name()
        self.collab.approval_callback = None
        if self.collab.join(code):
            widgets.XRefNotification(
                self, tr('Joined the shared board ({code})',
                         code=self.collab.session_code))
        else:
            widgets.XRefNotification(self, self.collab.last_error
                                    or self.collab.status)
        self.update_window_title()

    def on_action_collab_code(self):
        """Shows the current session code and who is connected."""

        if not self.collab.is_active():
            widgets.XRefNotification(self, tr('This board is not shared'))
            return
        code = self.collab.session_code or '-'
        QtWidgets.QApplication.clipboard().setText(code)
        if self.collab.is_host:
            peers = self.collab.peer_count()
            detail = (tr('{count} peer(s) connected.', count=peers)
                      if peers else tr('No one has joined yet.'))
            QtWidgets.QMessageBox.information(
                self, tr('Session Code'),
                tr('Session code:\n\n    {code}\n\n{detail}\n\n'
                   'The code has been copied to the clipboard.',
                   code=code, detail=detail))
        else:
            QtWidgets.QMessageBox.information(
                self, tr('Session Code'),
                tr('Connected to a shared board with code:\n\n'
                   '    {code}\n\n'
                   'The code has been copied to the clipboard.', code=code))

    def on_action_collab_approval(self, checked):
        """Toggles whether the host is asked before a peer joins."""

        if checked:
            self.collab.approval_callback = self.approve_collab_peer
        else:
            self.collab.approval_callback = None
        widgets.XRefNotification(
            self, tr('Peers are asked for approval before joining')
            if checked else tr('Peers can join without asking'))

    def on_action_collab_web_link(self):
        """Shares the board to browsers, over the internet when possible."""

        if not self.collab.is_active():
            widgets.XRefNotification(
                self, tr('Share the board first (Collaborate -> '
                         'Share Board)'))
            return
        widgets.XRefNotification(
            self, tr('Opening internet tunnel...'))
        link = self.collab.start_web_sharing(public=True)
        if link is None:
            widgets.XRefNotification(
                self, tr('Web sharing needs the aiohttp package'))
            return
        if '/lhr.' not in link:
            widgets.XRefNotification(
                self, tr('Internet tunnel could not be opened; '
                         'sharing on the local network instead: {link}',
                         link=link))
        else:
            widgets.XRefNotification(
                self, tr('Web link copied to clipboard: {link}', link=link))
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(link)

    def on_action_collab_leave(self):
        if not self.collab.is_active():
            widgets.XRefNotification(
                self, tr('Not in a shared session'))
            return
        self.collab.leave()
        widgets.XRefNotification(self, tr('Left the shared session'))
        self.update_window_title()

    def on_action_copy(self):
        logger.debug('Copying to clipboard...')
        self.cancel_active_modes()
        clipboard = QtWidgets.QApplication.clipboard()
        items = self.scene.selectedItems(user_only=True)

        # At the moment, we can only copy one image to the global
        # clipboard. (Later, we might create an image of the whole
        # selection for external copying.)
        items[0].copy_to_clipboard(clipboard)

        # However, we can copy all items to the internal clipboard:
        self.scene.copy_selection_to_internal_clipboard()

        # We set a marker for ourselves in the global clipboard so
        # that we know to look up the internal clipboard when pasting:
        clipboard.mimeData().setData(
            'xref/items', QtCore.QByteArray.number(len(items)))

    def on_action_paste(self):
        self.cancel_active_modes()
        logger.debug('Pasting from clipboard...')
        clipboard = QtWidgets.QApplication.clipboard()
        pos = self.mapToScene(self.mapFromGlobal(self.cursor().pos()))

        # See if we need to look up the internal clipboard:
        data = clipboard.mimeData().data('xref/items')
        logger.debug(f'Custom data in clipboard: {data}')
        if data and self.scene.internal_clipboard:
            # Checking that internal clipboard exists since the user
            # may have opened a new scene since copying.
            self.scene.paste_from_internal_clipboard(pos)
            return

        img = clipboard.image()
        if not img.isNull():
            item = XRefPixmapItem(img)
            self.undo_stack.push(commands.InsertItems(self.scene, [item], pos))
            if len(self.scene.items()) == 1:
                # This is the first image in the scene
                self.on_action_fit_scene()
            return
        text = clipboard.text()
        if text:
            item = XRefTextItem(text)
            item.setScale(1 / self.get_scale())
            self.undo_stack.push(commands.InsertItems(self.scene, [item], pos))
            return

        msg = 'No image data or text in clipboard or image too big'
        logger.info(msg)
        widgets.XRefNotification(self, msg)

    def on_action_open_settings_dir(self):
        dirname = os.path.dirname(self.settings.fileName())
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(dirname))

    def on_selection_changed(self):
        if sip.isdeleted(self.scene) or sip.isdeleted(self):
            # Emitted while the scene is being destroyed (app shutdown)
            return
        logger.debug('Currently selected items: %s',
                     len(self.scene.selectedItems(user_only=True)))
        self.actiongroup_set_enabled(
            'active_when_selection',
            self.scene.has_selection()
            or self.scene.selected_link is not None)
        self.actiongroup_set_enabled('active_when_single_image',
                                     self.scene.has_single_image_selection())

        if self.scene.has_selection():
            item = self.scene.selectedItems(user_only=True)[0]
            grayscale = getattr(item, 'grayscale', False)
            actions.actions['grayscale'].qaction.setChecked(grayscale)
        self.viewport().repaint()

    def on_cursor_changed(self, cursor):
        if self.active_mode is None and not self.scene.draw_mode:
            self._scene_cursor_active = True
            self.viewport().setCursor(cursor)

    def on_cursor_cleared(self):
        if self.active_mode is None and not self.scene.draw_mode:
            self._scene_cursor_active = False
            self.viewport().unsetCursor()

    # -- Background grid -----------------------------------------------------

    def grid_visible(self):
        """Whether the background grid is drawn."""

        try:
            return self.settings.valueOrDefault('View/grid_style') != 'none'
        except Exception:  # noqa: BLE001 - settings not ready
            return False

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        try:
            style = self.settings.valueOrDefault('View/grid_style')
        except Exception:  # noqa: BLE001
            return
        if style == 'none':
            return
        try:
            spacing = float(self.settings.valueOrDefault(
                'View/grid_spacing'))
        except (TypeError, ValueError):
            spacing = 50.0
        if spacing < 5:
            return

        # The grid keeps a constant size on screen: the cell distance is
        # measured in viewport pixels. The visible viewport area is
        # converted to scene coordinates and the lines are placed so they
        # are `spacing` pixels apart on screen at the current zoom.
        scale = max(self.get_scale(), 0.0001)
        cell = spacing / scale  # cell size in scene units

        area = self.mapToScene(self.viewport().rect()).boundingRect()
        left = area.left() - (area.left() % cell)
        top = area.top() - (area.top() % cell)

        color = self.backgroundBrush().color()
        grid_color = QtGui.QColor(
            255 - color.red(), 255 - color.green(), 255 - color.blue())
        grid_color.setAlpha(40 if style == 'lines' else 90)
        pen = QtGui.QPen(grid_color)
        pen.setCosmetic(True)
        painter.setPen(pen)

        if style == 'lines':
            x = left
            while x <= area.right():
                painter.drawLine(QtCore.QPointF(x, area.top()),
                                 QtCore.QPointF(x, area.bottom()))
                x += cell
            y = top
            while y <= area.bottom():
                painter.drawLine(QtCore.QPointF(area.left(), y),
                                 QtCore.QPointF(area.right(), y))
                y += cell
        else:  # dots
            painter.setBrush(grid_color)
            painter.setPen(Qt.PenStyle.NoPen)
            radius = 1.0 / scale  # constant 1 px on screen
            y = top
            while y <= area.bottom():
                x = left
                while x <= area.right():
                    painter.drawEllipse(QtCore.QPointF(x, y), radius,
                                        radius)
                    x += cell
                y += cell

    def snap_position_to_grid(self, scene_pos):
        """The scene position snapped to the grid (if snapping is on).

        The grid lives in scene coordinates, so snapped items stay put
        when the canvas is zoomed.
        """

        try:
            if not self.settings.valueOrDefault('View/grid_snap'):
                return scene_pos
            spacing = float(self.settings.valueOrDefault(
                'View/grid_spacing'))
        except (TypeError, ValueError):
            return scene_pos
        if spacing < 5:
            return scene_pos
        # The grid is a fixed distance apart on screen; convert it into
        # scene units at the current zoom level
        scale = max(self.get_scale(), 0.0001)
        cell = spacing / scale
        return QtCore.QPointF(
            round(scene_pos.x() / cell) * cell,
            round(scene_pos.y() / cell) * cell)

    def recalc_scene_rect(self):
        """Resize the scene rectangle so that it is always one view width
        wider than all items' bounding box at each side and one view
        width higher on top and bottom. This gives the impression of
        an infinite canvas."""

        if self.previous_transform:
            return
        if not self.scene.items():
            # An empty board has no items to expand around, but it still
            # has to be pannable and zoomable
            centre = self.mapToScene(self.get_view_center())
            half = self.viewport().width() + self.viewport().height()
            margin = abs(self.viewport_to_scene(
                QtCore.QPointF(half, half)).x() - centre.x())
            rect = QtCore.QRectF(centre, centre).adjusted(
                -margin, -margin, margin, margin)
            self.setSceneRect(rect)
            return
        logger.trace('Recalculating scene rectangle...')
        try:
            topleft = self.mapFromScene(
                self.scene.itemsBoundingRect().topLeft())
            topleft = self.mapToScene(QtCore.QPoint(
                topleft.x() - self.size().width(),
                topleft.y() - self.size().height()))
            bottomright = self.mapFromScene(
                self.scene.itemsBoundingRect().bottomRight())
            bottomright = self.mapToScene(QtCore.QPoint(
                bottomright.x() + self.size().width(),
                bottomright.y() + self.size().height()))
            self.setSceneRect(QtCore.QRectF(topleft, bottomright))
        except OverflowError:
            logger.info('Maximum scene size reached')
        logger.trace('Done recalculating scene rectangle')

    def get_zoom_size(self, func):
        """Calculates the size of all items' bounding box in the view's
        coordinates.

        This helps ensure that we never zoom out too much (scene
        becomes so tiny that items become invisible) or zoom in too
        much (causing overflow errors).

        :param func: Function which takes the width and height as
            arguments and turns it into a number, for ex. ``min`` or ``max``.
        """

        topleft = self.mapFromScene(
            self.scene.itemsBoundingRect().topLeft())
        bottomright = self.mapFromScene(
            self.scene.itemsBoundingRect().bottomRight())
        if bottomright.x() - topleft.x() < 1:
            # An empty board: use the scene rectangle as the reference
            topleft = self.mapFromScene(self.sceneRect().topLeft())
            bottomright = self.mapFromScene(self.sceneRect().bottomRight())
        return func(bottomright.x() - topleft.x(),
                    bottomright.y() - topleft.y())

    def scale(self, *args, **kwargs):
        super().scale(*args, **kwargs)
        self.scene.on_view_scale_change()
        self.recalc_scene_rect()

    def get_scale(self):
        return self.transform().m11()

    def pan(self, delta):
        hscroll = self.horizontalScrollBar()
        hscroll.setValue(int(hscroll.value() + delta.x()))
        vscroll = self.verticalScrollBar()
        vscroll.setValue(int(vscroll.value() + delta.y()))
        if not self.scene.items():
            # Keep the empty board scrollable in every direction
            self.recalc_scene_rect()

    def zoom(self, delta, anchor):
        if not self.scene.items():
            # An empty board has no items to limit the zoom, so use fixed
            # limits instead (the scene rectangle follows the view)
            scale = self.get_scale()
            if (delta > 0 and scale >= 50) or (delta < 0 and scale <= 0.05):
                return

        # We calculate where the anchor is before and after the zoom
        # and then move the view accordingly to keep the anchor fixed
        # We can't use QGraphicsView's AnchorUnderMouse since it
        # uses the current cursor position while we need the initial mouse
        # press position for zooming with Ctrl + Middle Drag
        anchor = QtCore.QPoint(round(anchor.x()),
                               round(anchor.y()))
        ref_point = self.mapToScene(anchor)
        if delta == 0:
            return
        factor = 1 + abs(delta / 1000)
        if delta > 0:
            if self.get_zoom_size(max) < 10000000:
                self.scale(factor, factor)
            else:
                logger.debug('Maximum zoom size reached')
                return
        else:
            if self.get_zoom_size(min) > 50:
                self.scale(1/factor, 1/factor)
            else:
                logger.debug('Minimum zoom size reached')
                return

        self.pan(self.mapFromScene(ref_point) - anchor)
        self.reset_previous_transform()

    def wheelEvent(self, event):
        action, inverted\
            = self.keyboard_settings.mousewheel_action_for_event(event)

        delta = event.angleDelta().y()
        if inverted:
            delta = delta * -1

        if action == 'zoom':
            self.zoom(delta, event.position())
            event.accept()
            return
        if action == 'pan_horizontal':
            self.pan(QtCore.QPointF(0, 0.5 * delta))
            event.accept()
            return
        if action == 'pan_vertical':
            self.pan(QtCore.QPointF(0.5 * delta, 0))
            event.accept()
            return

    def handle_window_edge_press(self, event):
        """Starts a native window move or resize for a frameless window.

        Used by the view and by the welcome overlay, so the window can be
        moved and resized even while the board is empty.
        """

        hit = self.window_edge_hit(event.pos())
        if hit is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        if hit[0] == 'resize':
            return self.start_window_resize(hit[1])
        return self.start_window_move()

    def mousePressEvent(self, event):
        if self.mousePressEventMainControls(event):
            return
        if self.handle_window_edge_press(event):
            event.accept()
            return
        if self.active_mode == self.SAMPLE_COLOR_MODE:
            if (event.button() == Qt.MouseButton.LeftButton):
                color = self.scene.sample_color_at(
                    self.mapToScene(event.pos()))
                if color:
                    name = qcolor_to_hex(color)
                    clipboard = QtWidgets.QApplication.clipboard()
                    clipboard.setText(name)
                    self.scene.internal_clipboard = []
                    msg = tr('Copied color to clipboard: {name}',
                             name=name)
                    logger.debug(msg)
                    widgets.XRefNotification(self, msg)
                else:
                    logger.debug('No color found')
            self.cancel_sample_color_mode()
            event.accept()
            return

        action, inverted = self.keyboard_settings.mouse_action_for_event(event)

        if action == 'zoom':
            self.active_mode = self.ZOOM_MODE
            self.event_start = event.position()
            self.event_anchor = event.position()
            self.event_inverted = inverted
            event.accept()
            return

        if action == 'pan':
            logger.trace('Begin pan')
            self.active_mode = self.PAN_MODE
            self.event_start = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            # ClosedHandCursor and OpenHandCursor don't work, but I
            # don't know if that's only on my system or a general
            # problem. It works with other cursors.
            event.accept()
            return

        super().mousePressEvent(event)
        self._prepare_drag_export(event)

    def mouseMoveEvent(self, event):
        if self._maybe_start_export_drag(event):
            return

        if self.active_mode == self.PAN_MODE:
            self.reset_previous_transform()
            pos = event.position()
            self.pan(self.event_start - pos)
            self.event_start = pos
            event.accept()
            return

        if self.active_mode == self.ZOOM_MODE:
            self.reset_previous_transform()
            pos = event.position()
            delta = (self.event_start - pos).y()
            if self.event_inverted:
                delta *= -1
            self.event_start = pos
            self.zoom(delta * 20, self.event_anchor)
            event.accept()
            return

        if self.active_mode == self.SAMPLE_COLOR_MODE:
            self.sample_color_widget.update(
                event.position(),
                self.scene.sample_color_at(self.mapToScene(event.pos())))
            event.accept()
            return

        if self.active_mode is None and not getattr(
                self, '_scene_cursor_active', False):
            self.update_window_edge_cursor(event.pos())

        if self.mouseMoveEventMainControls(event):
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        """A double click on the empty canvas switches to full screen."""

        if (event.button() == Qt.MouseButton.LeftButton
                and self.active_mode is None
                and self.itemAt(event.pos()) is None):
            self.toggle_fullscreen()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_export_items = []
        self._drag_export_positions = []
        self._drag_export_start = None
        if self.active_mode == self.PAN_MODE:
            logger.trace('End pan')
            self.viewport().unsetCursor()
            self.active_mode = None
            event.accept()
            return
        if self.active_mode == self.ZOOM_MODE:
            self.active_mode = None
            event.accept()
            return
        if self.mouseReleaseEventMainControls(event):
            return
        super().mouseReleaseEvent(event)

    def viewport_to_scene(self, point):
        """Maps a viewport position to the scene without rounding."""

        transform, invertible = self.viewportTransform().inverted()
        if not invertible:
            return QtCore.QPointF(point)
        return transform.map(QtCore.QPointF(point))

    def scene_to_viewport(self, point):
        """Maps a scene position to the viewport without rounding."""

        return self.viewportTransform().map(QtCore.QPointF(point))

    def resize_anchor(self):
        """The scene point that should stay put while the window is resized.

        Only used while the user drags a window edge: the point under the
        pointer stays under the pointer.

        :rtype: tuple(QtCore.QPointF, QtCore.QPoint)
        """

        global_pos = QtGui.QCursor.pos()
        local = QtCore.QPointF(self.mapFromGlobal(global_pos))
        return self.viewport_to_scene(local), global_pos

    def scroll_scene_point_to(self, scene_point, target):
        """Scrolls the view so a scene point ends up at a viewport position."""

        delta = QtCore.QPointF(target) - self.scene_to_viewport(scene_point)
        # Scrollbar units are viewport pixels, so the delta can be applied
        # directly. It is recomputed each time, so rounding can't add up.
        if abs(delta.x()) >= 0.5:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - round(delta.x()))
        if abs(delta.y()) >= 0.5:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - round(delta.y()))

    def restore_resize_anchor(self, anchor):
        """Keeps the anchor at the same screen position after a resize."""

        scene_point, global_pos = anchor
        target = QtCore.QPointF(self.mapFromGlobal(global_pos))
        self.scroll_scene_point_to(scene_point, target)

    def resizeEvent(self, event):
        old = event.oldSize()
        pointer_anchor = None
        centre = None
        if old.width() > 0 and old.height() > 0:
            # The canvas must not slide when the window is resized: the
            # point in the middle of the view stays in the middle (while an
            # edge is dragged, the point under the pointer stays put)
            centre = self.viewport_to_scene(
                QtCore.QPointF(old.width() / 2, old.height() / 2))
            if self._native_resize_active:
                pointer_anchor = self.resize_anchor()
        super().resizeEvent(event)
        self.recentre_to(centre)
        if pointer_anchor is not None:
            self.restore_resize_anchor(pointer_anchor)
        # The scene rectangle is expanded around the new view position, so
        # it has to be recalculated after the canvas was anchored
        self.recalc_scene_rect()
        self.welcome_overlay.resize(self.size())

    def keyPressEvent(self, event):
        if self.keyPressEventMainControls(event):
            return
        if self.active_mode == self.SAMPLE_COLOR_MODE:
            self.cancel_sample_color_mode()
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Escape and self.scene.draw_mode):
            self.on_action_toggle_draw(False)
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Escape
                and self.scene.selected_link is not None):
            self.scene.clear_link_selection()
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Escape
                and (self.parent.isFullScreen()
                     or actions.actions['fullscreen'].qaction.isChecked())):
            self.toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

