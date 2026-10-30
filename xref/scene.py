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
import math
import random
from queue import Queue

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtCore import Qt

import rpack

from xref import commands
from xref.config import XRefSettings
from xref.items import item_registry, XRefErrorItem, XRefDrawItem, \
    sort_by_filename
from xref.selection import MultiSelectItem, RubberbandItem


logger = logging.getLogger(__name__)


class XRefGraphicsScene(QtWidgets.QGraphicsScene):
    cursor_changed = QtCore.pyqtSignal(QtGui.QCursor)
    cursor_cleared = QtCore.pyqtSignal()
    #: Emitted when a node link was created (source/parent, target/child)
    link_created = QtCore.pyqtSignal(object, object)
    #: Emitted when links were removed
    links_removed = QtCore.pyqtSignal(int)
    #: Emitted whenever the set of links changed (created or removed)
    links_changed = QtCore.pyqtSignal()

    MOVE_MODE = 1
    RUBBERBAND_MODE = 2
    LINK_MODE = 3
    DRAW_MODE = 4
    GROUP_MOVE_MODE = 5

    def __init__(self, undo_stack):
        super().__init__()
        self.active_mode = None
        # Node links between media items (list of (source, target) items)
        self.links = []
        self._link_preview_item = None
        self._link_preview_origin = None
        self._link_preview_pos = None
        # Pen/draw mode
        self.draw_mode = False
        self._draw_item = None
        self._draw_start = None
        # The active tool in pen mode: 'freehand', 'rect', 'ellipse',
        # 'line' (shapes need Shift for squares/circles)
        self.draw_shape = 'freehand'
        # Pen settings for new strokes (colour as RGB tuple, width in
        # screen pixels)
        self.pen_color = XRefDrawItem.DEFAULT_COLOR
        self.pen_width = XRefDrawItem.DEFAULT_WIDTH
        # Item under the mouse (used to show the link port)
        self._hover_link_item = None
        self._port_cursor_active = False
        self._mouse_scene_pos = None
        # The link selected by clicking it (Delete removes it)
        self.selected_link = None
        self._group_move_items = []
        self._group_move_last = None
        self._group_move_total = QtCore.QPointF(0, 0)
        self.undo_stack = undo_stack
        self.max_z = 0
        self.min_z = 0
        self.Z_STEP = 0.001
        self.selectionChanged.connect(self.on_selection_change)
        self.changed.connect(self.on_change)
        self.items_to_add = Queue()
        self.edit_item = None
        self.crop_item = None
        self.settings = XRefSettings()
        self.clear()
        self._clear_ongoing = False

    def clear(self):
        self._clear_ongoing = True
        super().clear()
        self.internal_clipboard = []
        self.rubberband_item = RubberbandItem()
        self.multi_select_item = MultiSelectItem()
        self.links = []
        self.selected_link = None
        self.links_changed.emit()
        self._clear_ongoing = False

    def addItem(self, item):
        logger.debug(f'Adding item {item}')
        super().addItem(item)

    def removeItem(self, item):
        logger.debug(f'Removing item {item}')
        super().removeItem(item)

    def cancel_active_modes(self):
        """Cancels ongoing crop modes, rubberband modes etc, if there are
        any.
        """
        self.cancel_crop_mode()
        self.end_rubberband_mode()
        self.end_link_mode()
        self.end_draw_mode()

    # -- Node links ---------------------------------------------------------

    def end_link_mode(self):
        """Cancels an ongoing link creation (Shift+drag)."""

        self._link_preview_origin = None
        self._link_preview_pos = None
        if self.active_mode == self.LINK_MODE:
            self.active_mode = None
        self.update()

    def add_link(self, source, target):
        """Creates a link from ``source`` (parent) to ``target`` (child).

        Returns True if the link was added.
        """

        if source is target:
            return False
        if source in self.linked_children(target):
            logger.info('Refusing to link: would create a cycle')
            return False
        if (source, target) in self.links or (target, source) in self.links:
            return False
        self.links.append((source, target))
        self.update()
        self.link_created.emit(source, target)
        self.links_changed.emit()
        logger.debug(f'Linked {source} -> {target}')
        return True

    def remove_link(self, source, target):
        """Removes the link between ``source`` and ``target``.

        Returns True if the link was removed.
        """

        if (source, target) in self.links:
            self.links.remove((source, target))
            self.update()
            self.links_changed.emit()
            return True
        if (target, source) in self.links:
            self.links.remove((target, source))
            self.update()
            self.links_changed.emit()
            return True
        return False

    def links_for(self, item):
        """All links (as (source, target) tuples) touching ``item``."""

        return [link for link in self.links
                if item in (link[0], link[1])]

    def linked_children(self, item):
        """All items below ``item`` in the link hierarchy, i.e. all items
        reachable by following links from source (parent) to target
        (child), transitively."""

        children = set()
        frontier = [item]
        while frontier:
            current = frontier.pop()
            for source, target in self.links:
                if (source is current and target is not item
                        and target not in children):
                    children.add(target)
                    frontier.append(target)
        return children

    def remove_links_of(self, items):
        """Removes all links touching any of the given items."""

        items = set(items)
        before = len(self.links)
        self.links = [link for link in self.links
                      if link[0] not in items and link[1] not in items]
        removed = before - len(self.links)
        self.update()
        if removed:
            self.links_removed.emit(removed)
            self.links_changed.emit()
        return removed

    def link_items(self, parent, child):
        """Links two items (parent -> child); returns True on success."""

        return self.add_link(parent, child)

    def link_selected_items(self):
        """Links exactly two selected items.

        The topmost item (smallest y) becomes the parent, matching the
        node-editor mental model of "the item above is the parent".
        """

        items = self.selectedItems(user_only=True)
        if len(items) != 2:
            return False
        parent, child = sorted(
            items, key=lambda i: (i.pos().y(), i.pos().x()))
        return self.add_link(parent, child)

    def unlink_selected_items(self):
        """Removes all links of the selected items."""

        items = self.selectedItems(user_only=True)
        if not items:
            return 0
        return self.remove_links_of(items)
    def active_links(self):
        """Links whose items are both currently in the scene. Links of
        deleted items are kept (so that undo restores them) but are
        neither drawn nor saved."""

        return [link for link in self.links
                if link[0].scene() is self and link[1].scene() is self]
    # -- Ctrl+drag group move -------------------------------------------------

    def start_group_move(self, item, scene_pos):
        """Starts moving ``item`` together with all its linked children
        (Ctrl+drag on a parent media)."""

        group = [item] + [i for i in self.linked_children(item)
                          if hasattr(i, 'save_id') and i.scene() is self]
        self.clearSelection()
        for member in group:
            member.setSelected(True)
        self._group_move_items = group
        self._group_move_last = scene_pos
        self._group_move_total = QtCore.QPointF(0, 0)
        self.active_mode = self.GROUP_MOVE_MODE
        logger.debug(f'Group move with {len(group)} items')

    def update_group_move(self, scene_pos):
        delta = scene_pos - self._group_move_last
        self._group_move_last = scene_pos
        if delta.isNull():
            return
        for member in self._group_move_items:
            member.moveBy(delta.x(), delta.y())
        self._group_move_total += delta
        self.views()[0].reset_previous_transform()

    def finish_group_move(self):
        if not self._group_move_total.isNull():
            self.undo_stack.push(commands.MoveItemsBy(
                list(self._group_move_items), self._group_move_total,
                ignore_first_redo=True))
        self._group_move_items = []
        self._group_move_total = QtCore.QPointF(0, 0)
        self.active_mode = None

    # -- Pen / draw mode ------------------------------------------------------

    def _set_view_cursor(self, cursor):
        for view in self.views():
            if cursor is None:
                view.viewport().unsetCursor()
            else:
                view.viewport().setCursor(cursor)

    def enter_draw_mode(self):
        """Enters pen mode: freehand drawing of notes/sketches."""

        self.cancel_crop_mode()
        if self.edit_item:
            self.edit_item.exit_edit_mode()
        self.clearSelection()
        self.draw_mode = True
        self._set_view_cursor(QtGui.QCursor(Qt.CursorShape.CrossCursor))
        logger.debug('Entered draw mode')

    def end_draw_mode(self):
        """Commits an ongoing freehand stroke (called by
        cancel_active_modes); pen mode itself stays active."""

        if self._draw_item is not None:
            self.finish_draw_stroke()
        if self.active_mode == self.DRAW_MODE:
            self.active_mode = None

    def exit_draw_mode(self):
        """Exits pen mode and goes back to the default selection tool."""

        self.end_draw_mode()
        self.draw_mode = False
        self._set_view_cursor(None)
        logger.debug('Exited draw mode')

    def toggle_draw_mode(self):
        """Toggles pen mode on/off."""

        if self.draw_mode:
            self.exit_draw_mode()
        else:
            self.enter_draw_mode()

    # -- Pen settings ---------------------------------------------------------

    def pen_scale(self):
        """Current view scale (used to keep the brush size constant on
        screen while drawing)."""

        views = self.views()
        try:
            return max(views[0].get_scale(), 0.01) if views else 1.0
        except Exception:  # noqa: BLE001 - view not ready yet
            return 1.0

    def set_pen_color(self, color):
        """Sets the colour of new strokes (and of selected strokes)."""

        color = QtGui.QColor(color)
        self.pen_color = (color.red(), color.green(), color.blue())
        items = [i for i in self.selectedItems(user_only=True)
                 if getattr(i, 'is_draw', False)]
        if items:
            self.undo_stack.push(commands.ChangeDrawStyle(
                items, color=color))

    def set_pen_width(self, screen_pixels):
        """Sets the brush size (in screen pixels) for new strokes."""

        self.pen_width = max(1, int(screen_pixels))
        items = [i for i in self.selectedItems(user_only=True)
                 if getattr(i, 'is_draw', False)]
        if items:
            self.undo_stack.push(commands.ChangeDrawStyle(
                items, width=self.pen_width / self.pen_scale()))

    def draw_start(self, scene_pos):
        """Starts a new stroke or shape at the given scene position."""

        shape = self.draw_shape if self.draw_shape != 'freehand' else None
        self._draw_item = XRefDrawItem(
            stroke_color=self.pen_color,
            # Store the width in item units so the brush keeps its size
            # on screen regardless of the current zoom level
            stroke_width=self.pen_width / self.pen_scale(),
            shape=shape)
        # The live stroke must not react to the mouse (it would otherwise
        # be picked up by itemAt/hover handling while drawing)
        self._draw_item.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag(0))
        self._draw_item.setAcceptHoverEvents(False)
        self.addItem(self._draw_item)
        self._draw_item.bring_to_front()
        self._draw_start = QtCore.QPointF(scene_pos)
        if shape:
            self._draw_item.set_shape_points(scene_pos, scene_pos)
        else:
            self._draw_item.add_point(scene_pos)

    def draw_move(self, scene_pos, constrain=False):
        """Continues the current stroke or shape to the given position.

        ``constrain`` makes squares/circles out of rectangles/ellipses and
        straight angles out of lines (Shift key).
        """

        if not self._draw_item:
            return
        if self._draw_item._shape != XRefDrawItem.SHAPE_FREEHAND:
            self._draw_item._constrain_active = constrain
            self._draw_item.set_shape_points(self._draw_start, scene_pos)
        else:
            self._draw_item.add_point(scene_pos)

    def finish_draw_stroke(self):
        """Commits the current stroke as an undoable item."""

        if self._draw_item is None:
            return
        item = self._draw_item
        self._draw_item = None
        self.removeItem(item)
        if item.path().elementCount() == 0:
            return
        item.init_selectable()
        self.undo_stack.push(commands.InsertItems(self, [item]))
        # Stay in pen mode: don't leave the stroke selected
        item.setSelected(False)
    def end_rubberband_mode(self):
        if self.rubberband_item.scene():
            logger.debug('Ending rubberband selection')
            self.removeItem(self.rubberband_item)
        self.active_mode = None

    def cancel_crop_mode(self):
        """Cancels an ongoing crop mode, if there is any."""
        if self.crop_item:
            self.crop_item.exit_crop_mode(confirm=False)

    def copy_selection_to_internal_clipboard(self):
        self.internal_clipboard = []
        for item in self.selectedItems(user_only=True):
            self.internal_clipboard.append(item)

    def paste_from_internal_clipboard(self, position):
        copies = []
        for item in self.internal_clipboard:
            copy = item.create_copy()
            copies.append(copy)
        self.undo_stack.push(commands.InsertItems(self, copies, position))

    def raise_to_top(self):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        z_values = map(lambda i: i.zValue(), items)
        delta = self.max_z + self.Z_STEP - min(z_values)
        logger.debug(f'Raise to top, delta: {delta}')
        for item in items:
            item.setZValue(item.zValue() + delta)

    def lower_to_bottom(self):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        z_values = map(lambda i: i.zValue(), items)
        delta = self.min_z - self.Z_STEP - max(z_values)
        logger.debug(f'Lower to bottom, delta: {delta}')

        for item in items:
            item.setZValue(item.zValue() + delta)

    def normalize_width_or_height(self, mode):
        """Scale the selected images to have the same width or height, as
        specified by ``mode``.

        :param mode: "width" or "height".
        """

        self.cancel_active_modes()
        values = []
        items = self.selectedItems(user_only=True)
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            values.append(getattr(rect, mode)())
        if len(values) < 2:
            return
        avg = sum(values) / len(values)
        logger.debug(f'Calculated average {mode} {avg}')

        scale_factors = []
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            scale_factors.append(avg / getattr(rect, mode)())
        self.undo_stack.push(
            commands.NormalizeItems(items, scale_factors))

    def normalize_height(self):
        """Scale selected images to the same height."""
        return self.normalize_width_or_height('height')

    def normalize_width(self):
        """Scale selected images to the same width."""
        return self.normalize_width_or_height('width')

    def normalize_size(self):
        """Scale selected images to the same size.

        Size meaning the area = widh * height.
        """

        self.cancel_active_modes()
        sizes = []
        items = self.selectedItems(user_only=True)
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            sizes.append(rect.width() * rect.height())

        if len(sizes) < 2:
            return

        avg = sum(sizes) / len(sizes)
        logger.debug(f'Calculated average size {avg}')

        scale_factors = []
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            scale_factors.append(math.sqrt(avg / rect.width() / rect.height()))
        self.undo_stack.push(
            commands.NormalizeItems(items, scale_factors))

    def arrange_default(self):
        default = self.settings.valueOrDefault('Items/arrange_default')
        MAPPING = {
            'optimal': self.arrange_optimal,
            'horizontal': self.arrange,
            'vertical': partial(self.arrange, vertical=True),
            'square': self.arrange_square,
        }

        MAPPING[default]()

    def arrange(self, vertical=False):
        """Arrange items in a line (horizontally or vertically)."""

        self.cancel_active_modes()

        items = sort_by_filename(self.selectedItems(user_only=True))
        if len(items) < 2:
            return

        gap = self.settings.valueOrDefault('Items/arrange_gap')
        center = self.get_selection_center()
        positions = []
        rects = []
        for item in items:
            rects.append({
                'rect': self.itemsBoundingRect(items=[item]),
                'item': item})

        if vertical:
            rects.sort(key=lambda r: r['rect'].topLeft().y())
            sum_height = sum(map(lambda r: r['rect'].height(), rects))
            y = round(center.y() - sum_height/2)
            for rect in rects:
                positions.append(
                    QtCore.QPointF(
                        round(center.x() - rect['rect'].width()/2), y))
                y += rect['rect'].height() + gap

        else:
            rects.sort(key=lambda r: r['rect'].topLeft().x())
            sum_width = sum(map(lambda r: r['rect'].width(), rects))
            x = round(center.x() - sum_width/2)
            for rect in rects:
                positions.append(
                    QtCore.QPointF(
                        x, round(center.y() - rect['rect'].height()/2)))
                x += rect['rect'].width() + gap

        self.undo_stack.push(
            commands.ArrangeItems(self,
                                  [r['item'] for r in rects],
                                  positions))

    def arrange_optimal(self):
        self.cancel_active_modes()

        items = self.selectedItems(user_only=True)
        if len(items) < 2:
            return

        gap = self.settings.valueOrDefault('Items/arrange_gap')

        sizes = []
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            sizes.append((round(rect.width() + gap),
                          round(rect.height() + gap)))

        # The minimal area the items need if they could be packed optimally;
        # we use this as a starting shape for the packing algorithm
        min_area = sum(map(lambda s: s[0] * s[1], sizes))
        width = math.ceil(math.sqrt(min_area))

        positions = None
        while not positions:
            try:
                positions = rpack.pack(
                    sizes, max_width=width, max_height=width)
            except rpack.PackingImpossibleError:
                width = math.ceil(width * 1.2)

        # We want the items to center around the selection's center,
        # not (0, 0)
        center = self.get_selection_center()
        bounds = rpack.bbox_size(sizes, positions)
        diff = center - QtCore.QPointF(bounds[0]/2, bounds[1]/2)
        positions = [QtCore.QPointF(*pos) + diff for pos in positions]

        self.undo_stack.push(commands.ArrangeItems(self, items, positions))

    def arrange_randomly(self):
        """Scatters the selection randomly around its current center."""

        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        if len(items) < 2:
            return
        gap = self.settings.valueOrDefault('Items/arrange_gap')
        center = self.get_selection_center()
        rects = [self.itemsBoundingRect(items=[item]) for item in items]
        max_width = max(rect.width() for rect in rects)
        max_height = max(rect.height() for rect in rects)
        # Scatter within a square that comfortably fits all items
        span = (max_width + gap) * math.sqrt(len(items))
        positions = []
        for item in items:
            positions.append(
                QtCore.QPointF(
                    round(center.x() - max_width / 2
                          + random.uniform(0, max(1, span - max_width))),
                    round(center.y() - max_height / 2
                          + random.uniform(0, max(1, span - max_height)))))
        self.undo_stack.push(
            commands.MoveItemsTo(items, positions))

    def arrange_square(self):
        self.cancel_active_modes()
        max_width = 0
        max_height = 0
        gap = self.settings.valueOrDefault('Items/arrange_gap')
        items = sort_by_filename(self.selectedItems(user_only=True))

        if len(items) < 2:
            return

        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            max_width = max(max_width, rect.width() + gap)
            max_height = max(max_height, rect.height() + gap)

        # We want the items to center around the selection's center,
        # not (0, 0)
        num_rows = math.ceil(math.sqrt(len(items)))
        center = self.get_selection_center()
        diff = center - num_rows/2 * QtCore.QPointF(max_width, max_height)

        iter_items = iter(items)
        positions = []
        for j in range(num_rows):
            for i in range(num_rows):
                try:
                    item = next(iter_items)
                    rect = self.itemsBoundingRect(items=[item])
                    point = QtCore.QPointF(
                        i * max_width + (max_width - rect.width())/2,
                        j * max_height + (max_height - rect.height())/2)
                    positions.append(point + diff)
                except StopIteration:
                    break

        self.undo_stack.push(commands.ArrangeItems(self, items, positions))

    def flip_items(self, vertical=False):
        """Flip selected items."""
        self.cancel_active_modes()
        self.undo_stack.push(
            commands.FlipItems(self.selectedItems(user_only=True),
                               self.get_selection_center(),
                               vertical=vertical))

    def crop_items(self):
        """Crop selected item."""

        if self.crop_item:
            return
        if self.has_single_image_selection():
            item = self.selectedItems(user_only=True)[0]
            if item.is_image:
                item.enter_crop_mode()

    def sample_color_at(self, position):
        item_at_pos = self.itemAt(position, self.views()[0].transform())
        if item_at_pos:
            return item_at_pos.sample_color_at(position)

    def select_all_items(self):
        self.cancel_active_modes()
        path = QtGui.QPainterPath()
        path.addRect(self.itemsBoundingRect())
        # This is faster than looping through all items and calling setSelected
        self.setSelectionArea(path)

    def deselect_all_items(self):
        self.cancel_active_modes()
        self.clearSelection()

    def has_selection(self):
        """Checks whether there are currently items selected."""

        return bool(self.selectedItems(user_only=True))

    def has_single_selection(self):
        """Checks whether there's currently exactly one item selected."""

        return len(self.selectedItems(user_only=True)) == 1

    def has_multi_selection(self):
        """Checks whether there are currently more than one items selected."""

        return len(self.selectedItems(user_only=True)) > 1

    def has_single_image_selection(self):
        """Checks whether the current selection is a single image."""

        if self.has_single_selection():
            return self.selectedItems(user_only=True)[0].is_image
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            # Right-click invokes the context menu on the
            # GraphicsView. We don't need it here.
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self.event_start = event.scenePos()
            item_at_pos = self.itemAt(
                event.scenePos(), self.views()[0].transform())

            if self.draw_mode:
                # In pen mode, left-click starts a freehand stroke
                self.active_mode = self.DRAW_MODE
                self.draw_start(event.scenePos())
                event.accept()
                return

            mods = event.modifiers()
            link_mods = (Qt.KeyboardModifier.ShiftModifier
                         | Qt.KeyboardModifier.ControlModifier)
            target = None
            if isinstance(mods, Qt.KeyboardModifier) and mods & link_mods:
                target = self.link_target_at(event.scenePos())

            # Dragging from the link port of an item connects it, just
            # like dragging a wire from a node socket
            port_item = self.port_hit(event.scenePos())
            if (port_item is not None
                    and not (mods & Qt.KeyboardModifier.ControlModifier)):
                self.active_mode = self.LINK_MODE
                self._link_preview_origin = port_item
                self._update_link_preview(event.scenePos())
                event.accept()
                return

            # Clicking a link selects it (Delete/Backspace removes it)
            if item_at_pos is None:
                clicked_link = self.link_at(event.scenePos())
                if clicked_link is not None:
                    self.select_link(clicked_link)
                    self.active_mode = None
                    event.accept()
                    return
                self.clear_link_selection()
            else:
                self.clear_link_selection()

            if target is not None and mods & Qt.KeyboardModifier.ShiftModifier:
                # Shift+drag from a media item draws a node link
                self.active_mode = self.LINK_MODE
                self._link_preview_origin = target
                self._update_link_preview(event.scenePos())
                event.accept()
                return

            if (target is not None
                    and mods & Qt.KeyboardModifier.ControlModifier
                    and not (getattr(target, 'is_video', False)
                             and target.is_control_hit(event.scenePos()))):
                # Ctrl+drag on a parent media moves all linked children
                # along with it
                self.start_group_move(target, event.scenePos())
                event.accept()
                return
            if self.edit_item:
                if item_at_pos != self.edit_item:
                    self.edit_item.exit_edit_mode()
                else:
                    super().mousePressEvent(event)
                    return
            if self.crop_item:
                if item_at_pos != self.crop_item:
                    self.cancel_crop_mode()
                else:
                    super().mousePressEvent(event)
                    return
            if item_at_pos:
                self.active_mode = self.MOVE_MODE
            elif self.items():
                self.active_mode = self.RUBBERBAND_MODE

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.draw_mode:
            # Double clicks in pen mode just start another stroke
            self.mousePressEvent(event)
            return
        self.cancel_active_modes()
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if getattr(item, 'is_video', False):
            if not item.isSelected():
                item.setSelected(True)
            item.mouseDoubleClickEvent(event)
            return
        if item:
            if not item.isSelected():
                item.setSelected(True)
            if item.is_editable:
                item.enter_edit_mode()
                self.mousePressEvent(event)
            else:
                self.views()[0].fit_rect(
                    self.itemsBoundingRect(items=[item]),
                    toggle_item=item)
            return
        super().mouseDoubleClickEvent(event)

    # -- Link rendering / hit testing -----------------------------------------

    def link_target_at(self, scene_pos):
        """The topmost media item (not a drawing/UI item) at the given
        scene position, or None."""

        for item in self.items(scene_pos):
            if (hasattr(item, 'save_id')
                    and not getattr(item, 'is_draw', False)
                    and item is not self._draw_item):
                return item
        return None

    def _item_rect(self, item):
        return item.mapRectToScene(item.bounding_rect_unselected())

    @staticmethod
    def _rect_edge_point(rect, towards):
        """Point where the line from ``rect``'s center to ``towards``
        leaves the rect."""

        center = rect.center()
        dx = towards.x() - center.x()
        dy = towards.y() - center.y()
        if dx == 0 and dy == 0:
            return center
        scales = []
        if dx:
            scales.append((rect.width() / 2) / abs(dx))
        if dy:
            scales.append((rect.height() / 2) / abs(dy))
        t = min(min(scales), 1.0)
        return QtCore.QPointF(center.x() + dx * t, center.y() + dy * t)

    def link_line(self, source, target):
        """The visible line of a link: edge midpoint to edge midpoint, so
        it matches the link ports (node-editor style)."""

        src = self._item_rect(source)
        tgt = self._item_rect(target)
        if abs(tgt.center().x() - src.center().x()) >= abs(
                tgt.center().y() - src.center().y()):
            if tgt.center().x() >= src.center().x():
                start = QtCore.QPointF(src.right(), src.center().y())
                end = QtCore.QPointF(tgt.left(), tgt.center().y())
            else:
                start = QtCore.QPointF(src.left(), src.center().y())
                end = QtCore.QPointF(tgt.right(), tgt.center().y())
        else:
            if tgt.center().y() >= src.center().y():
                start = QtCore.QPointF(src.center().x(), src.bottom())
                end = QtCore.QPointF(tgt.center().x(), tgt.top())
            else:
                start = QtCore.QPointF(src.center().x(), src.top())
                end = QtCore.QPointF(tgt.center().x(), tgt.bottom())
        return QtCore.QLineF(start, end)

    PORT_RADIUS = 8  # screen pixels
    PORT_GAP = 3  # screen pixels between the item edge and the port

    def port_items(self):
        """Items whose link ports are shown: the item under the mouse plus
        the selected items (so linking is discoverable)."""

        if self.draw_mode:
            return []
        items = []
        if (self._hover_link_item is not None
                and self._hover_link_item.scene() is self
                and not getattr(self._hover_link_item, 'is_draw', False)):
            items.append(self._hover_link_item)
        for item in self.selectedItems(user_only=True):
            if (item not in items
                    and not getattr(item, 'is_draw', False)
                    and item.scene() is self):
                items.append(item)
        return items

    def link_port_pos(self, item, ref=None):
        """Scene position of an item's link port.

        The port sits on the edge closest to ``ref`` (the mouse position),
        so it always appears on the side the pointer approaches from.
        """

        rect = self._item_rect(item)
        center = rect.center()
        scale = max(self._view_scale(), 0.01)
        gap = self.PORT_GAP / scale
        if ref is None:
            # No pointer reference: default to the classic output side
            return QtCore.QPointF(rect.right() + gap, center.y())
        # The port appears on the side the pointer approaches from
        dx = ref.x() - center.x()
        dy = ref.y() - center.y()
        if abs(dx) >= abs(dy):
            if dx >= 0:
                return QtCore.QPointF(rect.right() + gap, center.y())
            return QtCore.QPointF(rect.left() - gap, center.y())
        if dy >= 0:
            return QtCore.QPointF(center.x(), rect.bottom() + gap)
        return QtCore.QPointF(center.x(), rect.top() - gap)

    def port_hit(self, scene_pos):
        """The item whose link port is under the given position, or None."""

        radius = self.PORT_RADIUS / max(self._view_scale(), 0.01)
        best = None
        best_distance = radius * 1.6
        for item in self.port_items():
            pos = self.link_port_pos(item, scene_pos)
            distance = (pos - scene_pos).manhattanLength()
            if distance <= best_distance:
                best, best_distance = item, distance
        return best
    def _view_scale(self):
        views = self.views()
        return views[0].get_scale() if views else 1

    def _link_path(self, line):
        """The smooth curve drawn for a link (also used for hit testing)."""

        scale = self._view_scale() or 1
        start, end = line.p1(), line.p2()
        bend = max(abs(end.x() - start.x()), 40 / scale) * 0.5
        if abs(end.x() - start.x()) >= abs(end.y() - start.y()):
            direction = 1 if end.x() >= start.x() else -1
            c1 = QtCore.QPointF(start.x() + bend * direction, start.y())
            c2 = QtCore.QPointF(end.x() - bend * direction, end.y())
        else:
            bend = max(abs(end.y() - start.y()), 40 / scale) * 0.5
            direction = 1 if end.y() >= start.y() else -1
            c1 = QtCore.QPointF(start.x(), start.y() + bend * direction)
            c2 = QtCore.QPointF(end.x(), end.y() - bend * direction)
        path = QtGui.QPainterPath(start)
        path.cubicTo(c1, c2, end)
        return path, c2

    def _draw_link(self, painter, line, color, dashed=False, width=2.5):
        scale = self._view_scale() or 1
        pen = QtGui.QPen(color)
        pen.setWidthF(width)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path, c2 = self._link_path(line)
        painter.drawPath(path)

        # Sockets and arrow head (constant size on screen)
        start, end = line.p1(), line.p2()
        radius = 5 / scale
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(start, radius, radius)
        angle = math.atan2(end.y() - c2.y(), end.x() - c2.x())
        length = 14 / scale
        arrow = QtGui.QPolygonF([
            end,
            end - QtCore.QPointF(
                length * math.cos(angle - 0.45),
                length * math.sin(angle - 0.45)),
            end - QtCore.QPointF(
                length * math.cos(angle + 0.45),
                length * math.sin(angle + 0.45)),
        ])
        painter.drawPolygon(arrow)

    # -- Selecting / removing links by clicking them -------------------------

    def link_at(self, scene_pos):
        """The link whose curve passes near the given position, or None."""

        tolerance = 8 / max(self._view_scale(), 0.01)
        for source, target in self.active_links():
            path, _ = self._link_path(self.link_line(source, target))
            stroker = QtGui.QPainterPathStroker()
            stroker.setWidth(tolerance * 2)
            if stroker.createStroke(path).contains(scene_pos):
                return (source, target)
        return None

    def select_link(self, link):
        self.selected_link = link
        if link is not None:
            self.clearSelection()
            if self._hover_link_item is not None:
                self._hover_link_item = None
        self.update()
        # Let the view refresh its action states (Delete must be enabled
        # while a link is selected)
        self.selectionChanged.emit()

    def clear_link_selection(self):
        if self.selected_link is not None:
            self.selected_link = None
            self.update()
            self.selectionChanged.emit()

    def delete_selected_link(self):
        """Removes the currently selected link; returns True if removed."""

        if self.selected_link is None:
            return False
        source, target = self.selected_link
        self.selected_link = None
        removed = self.remove_link(source, target)
        self.update()
        if removed:
            self.links_removed.emit(1)
        return removed
    def drawForeground(self, painter, rect):
        """Draws node links (parent -> child arrows) above the items."""

        super().drawForeground(painter, rect)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for link in self.active_links():
            source, target = link
            if link == self.selected_link:
                # Selected links are highlighted so Delete can remove them
                self._draw_link(painter, self.link_line(source, target),
                                QtGui.QColor(255, 190, 60), width=4.5)
            else:
                self._draw_link(painter, self.link_line(source, target),
                                QtGui.QColor(0, 150, 255))
        if (self.active_mode == self.LINK_MODE
                and self._link_preview_origin is not None
                and self._link_preview_pos is not None):
            origin = self._link_preview_origin
            hover = self.link_target_at(self._link_preview_pos)
            if hover is not None and hover is not origin:
                line = self.link_line(origin, hover)
                color = QtGui.QColor(60, 200, 90)
                # Highlight the item that will become the child
                pen = QtGui.QPen(color)
                pen.setWidthF(3)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(self._item_rect(hover))
            else:
                start = self._rect_edge_point(
                    self._item_rect(origin), self._link_preview_pos)
                line = QtCore.QLineF(start, self._link_preview_pos)
                color = QtGui.QColor(0, 150, 255)
            self._draw_link(painter, line, color, dashed=True)
        if self.active_mode != self.LINK_MODE:
            self._draw_link_ports(painter)
        painter.restore()

    def _draw_link_ports(self, painter):
        """Draws the node-editor style link ports.

        Each port is a soft glowing disc with a crisp ring and a small
        core dot; it grows slightly when the pointer is on it.
        """

        scale = max(self._view_scale(), 0.01)
        radius = self.PORT_RADIUS / scale
        pointer = self._mouse_scene_pos
        for item in self.port_items():
            pos = self.link_port_pos(item, pointer)
            hovered = pointer is not None and (
                (pos - pointer).manhattanLength() <= radius * 2.2)
            r = radius * (1.15 if hovered else 1.0)

            # Soft outer glow
            glow = QtGui.QRadialGradient(pos, r * 2.6)
            glow.setColorAt(0.0, QtGui.QColor(120, 210, 255, 190))
            glow.setColorAt(0.45, QtGui.QColor(70, 165, 255, 80))
            glow.setColorAt(1.0, QtGui.QColor(70, 165, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QBrush(glow))
            painter.drawEllipse(pos, r * 2.6, r * 2.6)

            # Filled disc
            disc = QtGui.QRadialGradient(
                QtCore.QPointF(pos.x() - r * 0.3, pos.y() - r * 0.35),
                r * 1.4)
            disc.setColorAt(0.0, QtGui.QColor(235, 250, 255))
            disc.setColorAt(0.55, QtGui.QColor(60, 165, 255))
            disc.setColorAt(1.0, QtGui.QColor(25, 110, 205))
            painter.setBrush(QtGui.QBrush(disc))
            painter.drawEllipse(pos, r, r)

            # Crisp outline
            ring = QtGui.QPen(QtGui.QColor(225, 245, 255, 230))
            ring.setWidthF(max(1.0, radius * 0.28))
            ring.setCosmetic(True)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(pos, r, r)

            # Bright core so it reads as a "socket"
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(255, 255, 255, 235))
            painter.drawEllipse(pos, r * 0.34, r * 0.34)

    def mouseMoveEvent(self, event):
        if self.active_mode == self.LINK_MODE:
            self._update_link_preview(event.scenePos())
            event.accept()
            return
        if self.active_mode == self.DRAW_MODE:
            self.draw_move(
                event.scenePos(),
                constrain=bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            event.accept()
            return
        if self.active_mode == self.GROUP_MOVE_MODE:
            self.update_group_move(event.scenePos())
            event.accept()
            return
        if self.active_mode == self.RUBBERBAND_MODE:
            if not self.rubberband_item.scene():
                logger.debug('Activating rubberband selection')
                self.addItem(self.rubberband_item)
                self.rubberband_item.bring_to_front()
            self.rubberband_item.fit(self.event_start, event.scenePos())
            self.setSelectionArea(self.rubberband_item.shape())
            self.views()[0].reset_previous_transform()
        if self.active_mode is None and not self.draw_mode:
            pos = event.scenePos()
            self._mouse_scene_pos = pos
            # Show the link port for the item under the mouse
            hover = self.link_target_at(pos)
            if hover is None and self._hover_link_item is not None:
                # Keep the port reachable while the pointer is on it (the
                # port sits slightly outside the item)
                radius = self.PORT_RADIUS / max(self._view_scale(), 0.01)
                port = self.link_port_pos(self._hover_link_item, pos)
                if (port - pos).manhattanLength() <= radius * 4:
                    hover = self._hover_link_item
            if hover is not self._hover_link_item:
                self._hover_link_item = hover
                self.update()
            over_port = hover is not None and self.port_hit(pos) is not None
            if not over_port and self.link_at(pos) is not None:
                # Hovering a link: show that it can be clicked/removed
                over_port = True
            if over_port and not self._port_cursor_active:
                self._port_cursor_active = True
                self._set_view_cursor(
                    QtGui.QCursor(Qt.CursorShape.PointingHandCursor))
            elif not over_port and self._port_cursor_active:
                self._port_cursor_active = False
                self._set_view_cursor(None)
        super().mouseMoveEvent(event)

    def _update_link_preview(self, pos):
        """Updates the temporary link line while Shift+dragging."""

        self._link_preview_pos = pos
        self.update()
    def _finish_link(self, pos):
        """Creates a link from the drag origin (parent) to the media item
        at the given position (child).

        Dropping onto an item that is already linked keeps the link (it
        is not toggled off), dropping on empty space removes the links of
        the origin item.
        """

        origin = self._link_preview_origin
        target = self.link_target_at(pos)
        if origin is not None:
            if target is not None and target is not origin:
                self.add_link(origin, target)
            elif target is None:
                self.remove_links_of([origin])
        self.end_link_mode()

    def mouseReleaseEvent(self, event):
        if self.active_mode == self.LINK_MODE:
            self._finish_link(event.scenePos())
            return
        if self.active_mode == self.DRAW_MODE:
            self.finish_draw_stroke()
            self.active_mode = None
            event.accept()
            return
        if self.active_mode == self.GROUP_MOVE_MODE:
            self.finish_group_move()
            event.accept()
            return
        if self.active_mode == self.RUBBERBAND_MODE:
            self.end_rubberband_mode()
        if (self.active_mode == self.MOVE_MODE
                and self.has_selection()
                and self.multi_select_item.active_mode is None
                and self.selectedItems()[0].active_mode is None):
            self.finish_item_move(event.scenePos())
        self.active_mode = None
        super().mouseReleaseEvent(event)

    def finish_item_move(self, release_pos):
        """Commits a finished drag: the drag delta plus the grid snap.

        Qt has already moved the items visually, so the drag delta is
        recorded for undo only; the snap correction has to move the items
        again and is merged into the same undo step.
        """

        items = self.selectedItems()
        if not items:
            return
        delta = release_pos - self.event_start
        snap = self._grid_snap_delta(delta)
        if not snap.isNull():
            # The snap correction moves the items visibly; it merges
            # with the drag into one undo step
            self.undo_stack.push(commands.MoveItemsBy(items, snap))
        elif not delta.isNull():
            # Record the drag for undo (the move itself already happened)
            self.undo_stack.push(
                commands.MoveItemsBy(items, delta, ignore_first_redo=True))

    def _grid_snap_delta(self, delta):
        """Extra movement after a drag that snaps the selection to the grid.

        Returns a null vector when grid snapping is off.
        """

        views = self.views()
        if not views:
            return QtCore.QPointF()
        view = views[0]
        snap_target = getattr(view, 'snap_position_to_grid', None)
        if snap_target is None:
            return QtCore.QPointF()
        items = self.selectedItems()
        if not items:
            return QtCore.QPointF()
        # Snap the first item's position (all items moved by the same
        # delta, so snapping one aligns the whole selection)
        item = items[0]
        target = item.mapToScene(item.boundingRect().center())
        snapped = snap_target(target)
        return snapped - target

    def selectedItems(self, user_only=False):
        """If ``user_only`` is set to ``True``, only return items added
        by the user (i.e. no multi select outlines and other UI items).

        User items are items that have a ``save_id`` attribute.
        """

        items = super().selectedItems()
        if user_only:
            return list(filter(lambda i: hasattr(i, 'save_id'), items))
        return items

    def items_by_type(self, itype):
        """Returns all items of the given type."""

        return filter(lambda i: getattr(i, 'TYPE', None) == itype,
                      self.items())

    def items_for_save(self):

        """Returns the items that are to be saved.

        Items to be saved are items that have a save_id attribute.
        """

        return filter(lambda i: hasattr(i, 'save_id'),
                      self.items(order=Qt.SortOrder.AscendingOrder))

    def clear_save_ids(self):
        for item in self.items_for_save():
            item.save_id = None

    def on_view_scale_change(self):
        for item in self.selectedItems():
            item.on_view_scale_change()

    def itemsBoundingRect(self, selection_only=False, items=None):
        """Returns the bounding rect of the scene's items; either all of them
        or only selected ones, or the items givin in ``items``.

        Re-implemented to not include the items's selection handles.
        """

        def filter_user_items(ilist):
            return list(filter(lambda i: hasattr(i, 'save_id'), ilist))

        if selection_only:
            base = filter_user_items(self.selectedItems())
        elif items:
            base = items
        else:
            base = filter_user_items(self.items())

        if not base:
            return QtCore.QRectF(0, 0, 0, 0)

        x = []
        y = []

        for item in base:
            for corner in item.corners_scene_coords:
                x.append(corner.x())
                y.append(corner.y())

        return QtCore.QRectF(
            QtCore.QPointF(min(x), min(y)),
            QtCore.QPointF(max(x), max(y)))

    def get_selection_center(self):
        rect = self.itemsBoundingRect(selection_only=True)
        return (rect.topLeft() + rect.bottomRight()) / 2

    def on_selection_change(self):
        if self._clear_ongoing:
            # Ignore events while clearing the scene since the
            # multiselect item will get cleared, too
            return
        if self.has_multi_selection():
            self.multi_select_item.fit_selection_area(
                self.itemsBoundingRect(selection_only=True))
        if self.has_multi_selection() and not self.multi_select_item.scene():
            self.addItem(self.multi_select_item)
            self.multi_select_item.bring_to_front()
        if not self.has_multi_selection() and self.multi_select_item.scene():
            self.removeItem(self.multi_select_item)

    def on_change(self, region):
        if self._clear_ongoing:
            # Ignore events while clearing the scene since the
            # multiselect item will get cleared, too
            return
        if (self.multi_select_item.scene()
                and self.multi_select_item.active_mode is None):
            self.multi_select_item.fit_selection_area(
                self.itemsBoundingRect(selection_only=True))

    def add_item_later(self, itemdata, selected=False):
        """Keep an item for adding later via ``add_queued_items``

        :param dict itemdata: Defines the item's data
        :param bool selected: Whether the item is initialised as selected
        """

        self.items_to_add.put((itemdata, selected))

    def add_queued_items(self):
        """Adds items added via ``add_item_later``"""

        while not self.items_to_add.empty():
            data, selected = self.items_to_add.get()
            typ = data.pop('type')
            cls = item_registry.get(typ)
            if not cls:
                # Just in case we add new item types in future versions
                logger.warning(f'Encountered item of unknown type: {typ}')
                cls = XRefErrorItem
                data['data'] = {'text': f'Item of unknown type: {typ}'}
            item = cls.create_from_data(**data)
            # Set the values common to all item types:
            item.update_from_data(**data)
            self.addItem(item)
            # Force recalculation of min/max z values:
            item.setZValue(item.zValue())
            if selected:
                item.setSelected(True)
                item.bring_to_front()
