# This file is part of BeeRef.
#
# BeeRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BeeRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BeeRef.  If not, see <https://www.gnu.org/licenses/>.

"""Classes for items that are added to the scene by the user (images,
text).
"""

from collections import defaultdict
from functools import cached_property
import logging
import os.path
import tempfile
import weakref

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref import commands
from beeref.config import BeeSettings
from beeref.constants import COLORS
from beeref.selection import SelectableMixin


logger = logging.getLogger(__name__)

item_registry = {}

def _to_qcolor(value, default=None):
    """Accepts a QColor, a (r, g, b) tuple/list or None."""

    if value is not None:
        if isinstance(value, (tuple, list)):
            return QtGui.QColor(*value)
        return QtGui.QColor(value)
    if default is None:
        return QtGui.QColor()
    return _to_qcolor(default)


def register_item(cls):
    item_registry[cls.TYPE] = cls
    return cls


def sort_by_filename(items):
    """Order items by filename.

    Items with a filename (ordered by filename) first, then items
    without a filename but with a save_id follow (ordered by
    save_id), then remaining items in the order that they have
    been inserted into the scene.
    """

    items_by_filename = []
    items_by_save_id = []
    items_remaining = []

    for item in items:
        if getattr(item, 'filename', None):
            items_by_filename.append(item)
        elif getattr(item, 'save_id', None):
            items_by_save_id.append(item)
        else:
            items_remaining.append(item)

    items_by_filename.sort(key=lambda x: x.filename)
    items_by_save_id.sort(key=lambda x: x.save_id)
    return items_by_filename + items_by_save_id + items_remaining


def _probe_video(path, timeout_ms=5000):
    """Probe a video for duration, frame size and its first frame.

    The video is opened in paused state (which decodes the first frame
    without starting audio output); the player is destroyed again
    afterwards. Runs its own event loop on the calling thread, so it
    can be called from a worker thread without blocking the GUI.

    :param str path: Local video file name
    :param int timeout_ms: Give up probing after this time
    :rtype: dict
    :return: {'duration': int, 'size': (int, int) or None,
              'preview': QImage or None}
    """

    from PyQt6 import QtMultimedia

    result = {'duration': -1, 'size': None, 'preview': None}
    loop = QtCore.QEventLoop()
    player = QtMultimedia.QMediaPlayer()
    sink = QtMultimedia.QVideoSink()
    player.setVideoOutput(sink)

    def check_done():
        if (result['duration'] > 0 and result['preview'] is not None
                and loop.isRunning()):
            loop.quit()

    def on_duration(duration):
        if duration > 0:
            result['duration'] = duration
        check_done()

    def on_frame(frame):
        if frame.isValid() and result['preview'] is None:
            image = frame.toImage()
            if not image.isNull():
                result['preview'] = image.copy()
                result['size'] = (image.width(), image.height())
        check_done()

    def on_status(status):
        if status in (QtMultimedia.QMediaPlayer.MediaStatus.InvalidMedia,
                      QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia):
            if loop.isRunning():
                loop.quit()

    player.durationChanged.connect(on_duration)
    sink.videoFrameChanged.connect(on_frame)
    player.mediaStatusChanged.connect(on_status)
    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)

    player.setSource(QtCore.QUrl.fromLocalFile(path))
    player.pause()
    try:
        if result['duration'] <= 0 or result['preview'] is None:
            loop.exec()
    finally:
        timer.stop()
        if player.duration() > 0:
            result['duration'] = player.duration()
        player.stop()
        player.setVideoOutput(None)
        player.deleteLater()
        sink.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete.value)
    return result

class BeeItemMixin(SelectableMixin):
    """Base for all items added by the user."""

    def set_pos_center(self, pos):
        """Sets the position using the item's center as the origin point."""

        self.setPos(pos - self.center_scene_coords)

    def has_selection_outline(self):
        return self.isSelected()

    def has_selection_handles(self):
        return (self.isSelected()
                and self.scene()
                and self.scene().has_single_selection())

    def selection_action_items(self):
        """The items affected by selection actions like scaling and rotating.
        """
        return [self]

    def on_selected_change(self, value):
        if (value and self.scene()
                and not self.scene().has_selection()
                and not self.scene().active_mode is None):
            self.bring_to_front()

    def update_from_data(self, **kwargs):
        self.save_id = kwargs.get('save_id', self.save_id)
        self.setPos(kwargs.get('x', self.pos().x()),
                    kwargs.get('y', self.pos().y()))
        self.setZValue(kwargs.get('z', self.zValue()))
        self.setScale(kwargs.get('scale', self.scale()))
        self.setRotation(kwargs.get('rotation', self.rotation()))
        if kwargs.get('flip', 1) != self.flip():
            self.do_flip()


@register_item
class BeePixmapItem(BeeItemMixin, QtWidgets.QGraphicsPixmapItem):
    """Class for images added by the user."""

    TYPE = 'pixmap'
    CROP_HANDLE_SIZE = 15

    def __init__(self, image, filename=None, **kwargs):
        super().__init__(QtGui.QPixmap.fromImage(image))
        self.save_id = None
        self.filename = filename
        self.reset_crop()
        logger.debug(f'Initialized {self}')
        self.is_image = True
        self.crop_mode = False
        self.init_selectable()
        self.settings = BeeSettings()
        self.grayscale = False

    @classmethod
    def create_from_data(self, **kwargs):
        item = kwargs.pop('item')
        data = kwargs.pop('data', {})
        item.filename = item.filename or data.get('filename')
        if 'crop' in data:
            item.crop = QtCore.QRectF(*data['crop'])
        item.setOpacity(data.get('opacity', 1))
        item.grayscale = data.get('grayscale', False)
        return item

    def __str__(self):
        size = self.pixmap().size()
        return (f'Image "{self.filename}" {size.width()} x {size.height()}')

    @property
    def crop(self):
        return self._crop

    @crop.setter
    def crop(self, value):
        logger.debug(f'Setting crop for {self} to {value}')
        self.prepareGeometryChange()
        self._crop = value
        self.update()

    @property
    def grayscale(self):
        return self._grayscale

    @grayscale.setter
    def grayscale(self, value):
        logger.debug('Setting grayscale for {self} to {value}')
        self._grayscale = value
        if value is True:
            # Using the grayscale image format to convert to grayscale
            # loses an image's tranparency. So the straightworward
            # following method gives us an ugly black replacement:
            # img = img.convertToFormat(QtGui.QImage.Format.Format_Grayscale8)

            # Instead, we will fill the background with the current
            # canvas colour, so the issue is only visible if the image
            # overlaps other images. The way we do it here only works
            # as long as the canvas colour is itself grayscale,
            # though.
            img = QtGui.QImage(
                self.pixmap().size(), QtGui.QImage.Format.Format_Grayscale8)
            img.fill(QtGui.QColor(*COLORS['Scene:Canvas']))
            painter = QtGui.QPainter(img)
            painter.drawPixmap(0, 0, self.pixmap())
            painter.end()
            self._grayscale_pixmap = QtGui.QPixmap.fromImage(img)

            # Alternative methods that have their own issues:
            #
            # 1. Use setAlphaChannel of the resulting grayscale
            # image. How do we get the original alpha channel? Using
            # the whole original image also takes color values into
            # account, not just their alpha values.
            #
            # 2. QtWidgets.QGraphicsColorizeEffect() with black colour
            # on the GraphicsItem. This applys to everything the paint
            # method does, so the selection outline/handles will also
            # be gray. setGraphicsEffect is only available on some
            # widgets, so we can't apply it selectively.
            #
            # 3. Going through every pixel and doing it manually — bad
            # performance.
        else:
            self._grayscale_pixmap = None

        self.update()

    def sample_color_at(self, pos):
        ipos = self.mapFromScene(pos)
        if self.grayscale:
            pm = self._grayscale_pixmap
        else:
            pm = self.pixmap()
        img = pm.toImage()

        color = img.pixelColor(int(ipos.x()), int(ipos.y()))
        if color.alpha():
            return color

    def bounding_rect_unselected(self):
        if self.crop_mode:
            return QtWidgets.QGraphicsPixmapItem.boundingRect(self)
        else:
            return self.crop

    def get_extra_save_data(self):
        return {'filename': self.filename,
                'opacity': self.opacity(),
                'grayscale': self.grayscale,
                'crop': [self.crop.topLeft().x(),
                         self.crop.topLeft().y(),
                         self.crop.width(),
                         self.crop.height()]}

    def get_filename_for_export(self, imgformat, save_id_default=None):
        save_id = self.save_id or save_id_default
        assert save_id is not None

        if self.filename:
            basename = os.path.splitext(os.path.basename(self.filename))[0]
            return f'{save_id:04}-{basename}.{imgformat}'
        else:
            return f'{save_id:04}.{imgformat}'

    def get_imgformat(self, img):
        """Determines the format for storing this image."""

        formt = self.settings.valueOrDefault('Items/image_storage_format')

        if formt == 'best':
            # Images with alpha channel and small images are stored as png
            if (img.hasAlphaChannel()
                    or (img.height() < 500 and img.width() < 500)):
                formt = 'png'
            else:
                formt = 'jpg'

        logger.debug(f'Found format {formt} for {self}')
        return formt

    def pixmap_to_bytes(self, apply_grayscale=False, apply_crop=False):
        """Convert the pixmap data to PNG bytestring."""
        barray = QtCore.QByteArray()
        buffer = QtCore.QBuffer(barray)
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        if apply_grayscale and self.grayscale:
            pm = self._grayscale_pixmap
        else:
            pm = self.pixmap()

        if apply_crop:
            pm = pm.copy(self.crop.toRect())

        img = pm.toImage()
        imgformat = self.get_imgformat(img)
        img.save(buffer, imgformat.upper(), quality=90)
        return (barray.data(), imgformat)

    def setPixmap(self, pixmap):
        super().setPixmap(pixmap)
        self.reset_crop()

    def pixmap_from_bytes(self, data):
        """Set image pimap from a bytestring."""
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(data)
        self.setPixmap(pixmap)

    def create_copy(self):
        item = BeePixmapItem(QtGui.QImage(), self.filename)
        item.setPixmap(self.pixmap())
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        item.setOpacity(self.opacity())
        item.grayscale = self.grayscale
        if self.flip() == -1:
            item.do_flip()
        item.crop = self.crop
        return item

    @cached_property
    def color_gamut(self):
        logger.debug(f'Calculating color gamut for {self}')
        gamut = defaultdict(int)
        img = self.pixmap().toImage()
        # Don't evaluate every pixel for larger images:
        step = max(1, int(max(img.width(), img.height()) / 1000))
        logger.debug(f'Considering every {step}. row/column')

        # Not actually faster than solution below :(
        # ptr = img.bits()
        # size = img.sizeInBytes()
        # pixelsize = int(img.sizeInBytes() / img.width() / img.height())
        # ptr.setsize(size)
        # for pixel in batched(ptr, n=pixelsize):
        #     r, g, b, alpha = tuple(map(ord, pixel))
        #     if 5 < alpha and 5 < r < 250 and 5 < g < 250 and 5 < b < 250:
        #         # Only consider pixels that aren't close to
        #         # transparent, white or black
        #         rgb = QtGui.QColor(r, g, b)
        #         gamut[rgb.hue(), rgb.saturation()] += 1

        for i in range(0, img.width(), step):
            for j in range(0, img.height(), step):
                rgb = img.pixelColor(i, j)
                rgbtuple = (rgb.red(), rgb.blue(), rgb.green())
                if (5 < rgb.alpha()
                        and min(rgbtuple) < 250 and max(rgbtuple) > 5):
                    # Only consider pixels that aren't close to
                    # transparent, white or black
                    gamut[rgb.hue(), rgb.saturation()] += 1

        logger.debug(f'Got {len(gamut)} color gamut values')
        return gamut

    def copy_to_clipboard(self, clipboard):
        clipboard.setPixmap(self.pixmap())

    def reset_crop(self):
        self.crop = QtCore.QRectF(
            0, 0, self.pixmap().size().width(), self.pixmap().size().height())

    @property
    def crop_handle_size(self):
        return self.fixed_length_for_viewport(self.CROP_HANDLE_SIZE)

    def crop_handle_topleft(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x(),
            topleft.y(),
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_bottomleft(self):
        bottomleft = self.crop_temp.bottomLeft()
        return QtCore.QRectF(
            bottomleft.x(),
            bottomleft.y() - self.crop_handle_size,
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_bottomright(self):
        bottomright = self.crop_temp.bottomRight()
        return QtCore.QRectF(
            bottomright.x() - self.crop_handle_size,
            bottomright.y() - self.crop_handle_size,
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_topright(self):
        topright = self.crop_temp.topRight()
        return QtCore.QRectF(
            topright.x() - self.crop_handle_size,
            topright.y(),
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handles(self):
        return (self.crop_handle_topleft,
                self.crop_handle_bottomleft,
                self.crop_handle_bottomright,
                self.crop_handle_topright)

    def crop_edge_top(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x() + self.crop_handle_size,
            topleft.y(),
            self.crop_temp.width() - 2 * self.crop_handle_size,
            self.crop_handle_size)

    def crop_edge_left(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x(),
            topleft.y() + self.crop_handle_size,
            self.crop_handle_size,
            self.crop_temp.height() - 2 * self.crop_handle_size)

    def crop_edge_bottom(self):
        bottomleft = self.crop_temp.bottomLeft()
        return QtCore.QRectF(
            bottomleft.x() + self.crop_handle_size,
            bottomleft.y() - self.crop_handle_size,
            self.crop_temp.width() - 2 * self.crop_handle_size,
            self.crop_handle_size)

    def crop_edge_right(self):
        topright = self.crop_temp.topRight()
        return QtCore.QRectF(
            topright.x() - self.crop_handle_size,
            topright.y() + self.crop_handle_size,
            self.crop_handle_size,
            self.crop_temp.height() - 2 * self.crop_handle_size)

    def crop_edges(self):
        return (self.crop_edge_top,
                self.crop_edge_left,
                self.crop_edge_bottom,
                self.crop_edge_right)

    def get_crop_handle_cursor(self, handle):
        """Gets the crop cursor for the given handle."""

        is_topleft_or_bottomright = handle in (
            self.crop_handle_topleft, self.crop_handle_bottomright)
        return self.get_diag_cursor(is_topleft_or_bottomright)

    def get_crop_edge_cursor(self, edge):
        """Gets the crop edge cursor for the given edge."""

        top_or_bottom = edge in (
            self.crop_edge_top, self.crop_edge_bottom)
        sideways = (45 < self.rotation() < 135
                    or 225 < self.rotation() < 315)

        if top_or_bottom is sideways:
            return Qt.CursorShape.SizeHorCursor
        else:
            return Qt.CursorShape.SizeVerCursor

    def draw_crop_rect(self, painter, rect):
        """Paint a dotted rectangle for the cropping UI."""
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255))
        pen.setWidth(2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(rect)
        pen.setColor(QtGui.QColor(0, 0, 0))
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawRect(rect)

    def paint(self, painter, option, widget):
        if abs(painter.combinedTransform().m11()) < 2:
            # We want image smoothing, but only for images where we
            # are not zoomed in a lot. This is to ensure that for
            # example icons and pixel sprites can be viewed correctly.
            painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform)

        if self.crop_mode:
            self.paint_debug(painter, option, widget)

            # Darken image outside of cropped area
            painter.drawPixmap(0, 0, self.pixmap())
            path = QtWidgets.QGraphicsPixmapItem.shape(self)
            path.addRect(self.crop_temp)
            color = QtGui.QColor(0, 0, 0)
            color.setAlpha(100)
            painter.setBrush(QtGui.QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)
            painter.setBrush(QtGui.QBrush())

            for handle in self.crop_handles():
                self.draw_crop_rect(painter, handle())
            self.draw_crop_rect(painter, self.crop_temp)
        else:
            pm = self._grayscale_pixmap if self.grayscale else self.pixmap()
            painter.drawPixmap(self.crop, pm, self.crop)
            self.paint_selectable(painter, option, widget)

    def enter_crop_mode(self):
        logger.debug(f'Entering crop mode on {self}')
        self.prepareGeometryChange()
        self.crop_mode = True
        self.crop_temp = QtCore.QRectF(self.crop)
        self.crop_mode_move = None
        self.crop_mode_event_start = None
        self.grabKeyboard()
        self.update()
        self.scene().crop_item = self

    def exit_crop_mode(self, confirm):
        logger.debug(f'Exiting crop mode with {confirm} on {self}')
        if confirm and self.crop != self.crop_temp:
            self.scene().undo_stack.push(
                commands.CropItem(self, self.crop_temp))
        self.prepareGeometryChange()
        self.crop_mode = False
        self.crop_temp = None
        self.crop_mode_move = None
        self.crop_mode_event_start = None
        self.ungrabKeyboard()
        self.update()
        self.scene().crop_item = None

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.exit_crop_mode(confirm=True)
        elif event.key() == Qt.Key.Key_Escape:
            self.exit_crop_mode(confirm=False)
        else:
            super().keyPressEvent(event)

    def hoverMoveEvent(self, event):
        if not self.crop_mode:
            return super().hoverMoveEvent(event)

        for handle in self.crop_handles():
            if handle().contains(event.pos()):
                self.set_cursor(self.get_crop_handle_cursor(handle))
                return
        for edge in self.crop_edges():
            if edge().contains(event.pos()):
                self.set_cursor(self.get_crop_edge_cursor(edge))
                return
        self.unset_cursor()

    def mousePressEvent(self, event):
        if not self.crop_mode:
            return super().mousePressEvent(event)

        event.accept()
        for handle in self.crop_handles():
            # Click into a handle?
            if handle().contains(event.pos()):
                self.crop_mode_event_start = event.pos()
                self.crop_mode_move = handle
                return
        for edge in self.crop_edges():
            # Click into an edge handle?
            if edge().contains(event.pos()):
                self.crop_mode_event_start = event.pos()
                self.crop_mode_move = edge
                return
        # Click not in handle, end cropping mode:
        self.exit_crop_mode(
            confirm=self.crop_temp.contains(event.pos()))

    def ensure_point_within_crop_bounds(self, point, handle):
        """Returns the point, or the nearest point within the pixmap."""

        if handle == self.crop_handle_topleft:
            topleft = QtCore.QPointF(0, 0)
            bottomright = self.crop_temp.bottomRight()
        if handle == self.crop_handle_bottomleft:
            topleft = QtCore.QPointF(0, self.crop_temp.top())
            bottomright = QtCore.QPointF(
                self.crop_temp.right(), self.pixmap().size().height())
        if handle == self.crop_handle_bottomright:
            topleft = self.crop_temp.topLeft()
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.pixmap().size().height())
        if handle == self.crop_handle_topright:
            topleft = QtCore.QPointF(self.crop_temp.left(), 0)
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.crop_temp.bottom())
        if handle == self.crop_edge_top:
            topleft = QtCore.QPointF(0, 0)
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.crop_temp.bottom())
        if handle == self.crop_edge_bottom:
            topleft = QtCore.QPointF(0, self.crop_temp.top())
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.pixmap().size().height())
        if handle == self.crop_edge_left:
            topleft = QtCore.QPointF(0, 0)
            bottomright = QtCore.QPointF(
                self.crop_temp.right(), self.pixmap().size().height())
        if handle == self.crop_edge_right:
            topleft = QtCore.QPointF(self.crop_temp.left(), 0)
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.pixmap().size().height())

        point.setX(min(bottomright.x(), max(topleft.x(), point.x())))
        point.setY(min(bottomright.y(), max(topleft.y(), point.y())))

        return point

    def mouseMoveEvent(self, event):
        if self.crop_mode and self.crop_mode_event_start:
            diff = event.pos() - self.crop_mode_event_start
            if self.crop_mode_move == self.crop_handle_topleft:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setTopLeft(new)
            if self.crop_mode_move == self.crop_handle_bottomleft:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomLeft() + diff, self.crop_mode_move)
                self.crop_temp.setBottomLeft(new)
            if self.crop_mode_move == self.crop_handle_bottomright:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomRight() + diff, self.crop_mode_move)
                self.crop_temp.setBottomRight(new)
            if self.crop_mode_move == self.crop_handle_topright:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topRight() + diff, self.crop_mode_move)
                self.crop_temp.setTopRight(new)
            if self.crop_mode_move == self.crop_edge_top:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setTop(new.y())
            if self.crop_mode_move == self.crop_edge_left:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setLeft(new.x())
            if self.crop_mode_move == self.crop_edge_bottom:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomLeft() + diff, self.crop_mode_move)
                self.crop_temp.setBottom(new.y())
            if self.crop_mode_move == self.crop_edge_right:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topRight() + diff, self.crop_mode_move)
                self.crop_temp.setRight(new.x())
            self.update()
            self.crop_mode_event_start = event.pos()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.crop_mode:
            self.crop_mode_move = None
            self.crop_mode_event_start = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)


@register_item
class BeeTextItem(BeeItemMixin, QtWidgets.QGraphicsTextItem):
    """Class for text added by the user."""

    TYPE = 'text'
    DEFAULT_WRAP_WIDTH = 360

    def __init__(self, text=None, text_width=None, **kwargs):
        super().__init__(text or "Text")
        self.save_id = None
        logger.debug(f'Initialized {self}')
        self.is_image = False
        self.init_selectable()
        self.is_editable = True
        self.edit_mode = False
        self.setDefaultTextColor(QtGui.QColor(*COLORS['Scene:Text']))
        if text_width and float(text_width) > 0:
            self.setTextWidth(float(text_width))

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {})
        item = cls(**data)
        return item

    def __str__(self):
        txt = self.toPlainText()[:40]
        return (f'Text "{txt}"')

    def get_extra_save_data(self):
        data = {'text': self.toPlainText()}
        width = self.textWidth()
        if width and width > 0:
            data['text_width'] = width
        return data

    def contains(self, point):
        return self.boundingRect().contains(point)

    def paint(self, painter, option, widget):
        painter.setPen(Qt.PenStyle.NoPen)
        color = QtGui.QColor(0, 0, 0)
        color.setAlpha(40)
        brush = QtGui.QBrush(color)
        painter.setBrush(brush)
        painter.drawRect(QtWidgets.QGraphicsTextItem.boundingRect(self))
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        super().paint(painter, option, widget)
        self.paint_selectable(painter, option, widget)

    def create_copy(self):
        item = BeeTextItem(self.toPlainText())
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        if self.flip() == -1:
            item.do_flip()
        return item

    def enter_edit_mode(self):
        logger.debug(f'Entering edit mode on {self}')
        self.edit_mode = True
        self.old_text = self.toPlainText()
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction)
        self.scene().edit_item = self

    def exit_edit_mode(self, commit=True):
        logger.debug(f'Exiting edit mode on {self}')
        self.edit_mode = False
        # reset selection:
        self.setTextCursor(QtGui.QTextCursor(self.document()))
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.scene().edit_item = None
        if commit:
            self.scene().undo_stack.push(
                commands.ChangeText(self, self.toPlainText(), self.old_text))
            if not self.toPlainText().strip():
                logger.debug('Removing empty text item')
                self.scene().undo_stack.push(
                    commands.DeleteItems(self.scene(), [self]))
        else:
            self.setPlainText(self.old_text)

    def has_selection_handles(self):
        return super().has_selection_handles() and not self.edit_mode

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return)
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.exit_edit_mode()
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Escape
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.exit_edit_mode(commit=False)
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_to_clipboard(self, clipboard):
        clipboard.setText(self.toPlainText())


@register_item
class BeeDrawItem(BeeItemMixin, QtWidgets.QGraphicsPathItem):
    """Freehand notes / sketches added by the user (pen mode).

    Recorded points are turned into a smoothed path (quadratic
    interpolation through the midpoints), so strokes look like a brush
    instead of a jagged polyline.
    """

    TYPE = 'draw'
    DEFAULT_COLOR = (255, 138, 61)
    DEFAULT_WIDTH = 10  # screen pixels

    def __init__(self, stroke_color=None, stroke_width=None, **kwargs):
        super().__init__()
        self.save_id = None
        self.is_image = False
        self.is_draw = True
        self.init_selectable()
        self._stroke_color = _to_qcolor(stroke_color, self.DEFAULT_COLOR)
        self._stroke_width = float(stroke_width or self.DEFAULT_WIDTH)
        self._points = []
        self._path = QtGui.QPainterPath()
        self.setPath(self._path)
        logger.debug(f'Initialized {self}')

    def __str__(self):
        if getattr(self, '_path', None) is None:
            return 'Drawing'
        return f'Drawing ({len(self._points)} points)'

    # -- API -----------------------------------------------------------------

    @property
    def stroke_color(self):
        return self._stroke_color

    @property
    def stroke_width(self):
        return self._stroke_width

    @property
    def points(self):
        return list(self._points)

    def set_stroke_color(self, color):
        self._stroke_color = _to_qcolor(color, self._stroke_color)
        self.update()

    def set_stroke_width(self, width):
        self.prepareGeometryChange()
        self._stroke_width = max(0.5, float(width))
        self.update()

    def add_point(self, point):
        """Append a new point to the freehand stroke."""

        point = QtCore.QPointF(point)
        if self._points and self._points[-1] == point:
            return
        self.prepareGeometryChange()
        self._points.append(point)
        self._rebuild_path()

    def _rebuild_path(self):
        """Turns the recorded points into a smooth, brush-like path."""

        pts = self._points
        path = QtGui.QPainterPath()
        if pts:
            path.moveTo(pts[0])
            if len(pts) == 2:
                path.lineTo(pts[1])
            elif len(pts) > 2:
                for i in range(1, len(pts) - 1):
                    mid = (pts[i] + pts[i + 1]) / 2
                    path.quadTo(pts[i], mid)
                path.lineTo(pts[-1])
        self._path = path
        self.setPath(path)
        self.update()

    def path(self):
        return self._path

    def bounding_rect_unselected(self):
        if not self._points:
            return QtCore.QRectF()
        margin = self._stroke_width / 2 + 2
        return self._path.boundingRect().adjusted(
            -margin, -margin, margin, margin)

    def _hit_test_path(self):
        """A widened copy of the stroke shape for hit testing."""
        if self._path.elementCount() == 0:
            return QtGui.QPainterPath()
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(self._stroke_width + 8)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(self._path)

    def shape(self):
        if self.has_selection_handles():
            return super().shape()
        return self._hit_test_path()

    def get_extra_save_data(self):
        return {
            'opacity': self.opacity(),
            'points': [[p.x(), p.y()] for p in self._points],
            'stroke_color': [self._stroke_color.red(),
                             self._stroke_color.green(),
                             self._stroke_color.blue()],
            'stroke_width': self._stroke_width,
        }

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {}) or {}
        item = cls(stroke_color=data.get('stroke_color'),
                   stroke_width=data.get('stroke_width'))
        for x, y in data.get('points', []):
            item.add_point(QtCore.QPointF(x, y))
        item.setOpacity(data.get('opacity', 1))
        return item

    def paint(self, painter, option, widget):
        # Only the stroke is painted; an open freehand path must never be
        # filled (that would leave a translucent "trail" between the
        # start point and the pen position).
        pen = QtGui.QPen(self._stroke_color)
        pen.setWidthF(self._stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if len(self._points) == 1:
            painter.drawPoint(self._points[0])
        else:
            painter.drawPath(self._path)
        self.paint_selectable(painter, option, widget)

    def contains(self, point):
        return self.shape().contains(point)

@register_item
class BeeErrorItem(BeeItemMixin, QtWidgets.QGraphicsTextItem):
    """Class for displaying error messages when an item can't be loaded
    from a bee file.

    This item will be displayed instead of the original item. It won't
    save to bee files. The original item will be preserved in the bee
    file, unless this item gets deleted by the user, or a new bee file
    is saved.
    """

    TYPE = 'error'

    def __init__(self, text=None, **kwargs):
        super().__init__(text or "Text")
        self.original_save_id = None
        logger.debug(f'Initialized {self}')
        self.is_image = False
        self.init_selectable()
        self.is_editable = False
        self.setDefaultTextColor(QtGui.QColor(*COLORS['Scene:Text']))

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {})
        item = cls(**data)
        return item

    def __str__(self):
        txt = self.toPlainText()[:40]
        return (f'Error "{txt}"')

    def contains(self, point):
        return self.boundingRect().contains(point)

    def paint(self, painter, option, widget):
        painter.setPen(Qt.PenStyle.NoPen)
        color = QtGui.QColor(200, 0, 0)
        brush = QtGui.QBrush(color)
        painter.setBrush(brush)
        painter.drawRect(QtWidgets.QGraphicsTextItem.boundingRect(self))
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        super().paint(painter, option, widget)
        self.paint_selectable(painter, option, widget)

    def update_from_data(self, **kwargs):
        self.original_save_id = kwargs.get('save_id', self.original_save_id)
        self.setPos(kwargs.get('x', self.pos().x()),
                    kwargs.get('y', self.pos().y()))
        self.setZValue(kwargs.get('z', self.zValue()))
        self.setScale(kwargs.get('scale', self.scale()))
        self.setRotation(kwargs.get('rotation', self.rotation()))

    def create_copy(self):
        item = BeeErrorItem(self.toPlainText())
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        return item

    def flip(self, *args, **kwargs):
        """Returns the flip value (1 or -1)"""
        # Never display error messages flipped
        return 1

    def do_flip(self, *args, **kwargs):
        """Flips the item."""
        # Never flip error messages
        pass

    def copy_to_clipboard(self, clipboard):
        clipboard.setText(self.toPlainText())




# -- Video ------------------------------------------------------------------

# Video items that currently own a media player (stopped on app exit so
# the multimedia threads can't block process shutdown)
_live_video_items = weakref.WeakSet()
_quit_hook_installed = False


def _release_all_video_players():
    for item in list(_live_video_items):
        try:
            item.release_player()
        except Exception:  # noqa: BLE001 - best effort on shutdown
            pass


def _format_ms(ms):
    seconds = max(0, int(ms // 1000))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}:{minutes:02}:{seconds:02}'
    return f'{minutes}:{seconds:02}'


@register_item
class BeeVideoItem(BeeItemMixin, QtWidgets.QGraphicsItem):
    """Class for videos added by the user.

    Videos are played directly from their source location on disk; the
    bee file only stores a reference to the file (plus position, size
    etc.). Behaviour:

    * The first frame (or the position where playback was last
      stopped) is shown as a still preview.
    * Moving the mouse horizontally over the video scrubs through it,
      similar to the hover scrub in DaVinci Resolve's media pool.
    * When hovered, media player controls (play/pause, seek bar, time)
      appear at the bottom.
    * The preview stays pinned to the position playback was stopped at;
      hover scrubbing is only a temporary preview.
    """

    TYPE = 'video'
    DEFAULT_SIZE = (400, 300)
    CONTROLS_HEIGHT = 30  # screen pixels
    CONTROLS_MARGIN = 8  # screen pixels
    VOLUME_WIDTH = 60  # screen pixels
    SEEK_THROTTLE_MS = 40
    # Decoded frames may arrive out of order after rapid seeks; a frame
    # is only shown when it belongs to the position we asked for
    FRAME_TOLERANCE_MS = 250

    def __init__(self, video_path=None, filename=None, size=None,
                 duration=-1, preview=None, **kwargs):
        super().__init__()
        self.save_id = None
        self.video_path = video_path
        self.filename = filename or (
            os.path.basename(video_path) if video_path else None)
        self.duration = duration
        self._width, self._height = size or self.DEFAULT_SIZE
        self.is_image = False
        self.is_video = True
        self.init_selectable()
        # Hover events drive the control bar; make sure they are enabled
        self.setAcceptHoverEvents(True)

        self._frame = (preview if preview is not None
                       and not preview.isNull() else None)
        # The pinned position: where playback was last stopped
        self._current_position = 0
        # The position currently shown (may differ while scrubbing)
        self._display_position = 0
        self._player = None
        self._sink = None
        self._audio = None
        self._seek_timer = None
        self._seek_target = None
        self._expected_position = None
        self._initial_seek = None
        self._playing = False
        self._hovered = False
        self._hover_pos = None
        # Volume/min/max controls state
        self._volume_dragging = False
        # Audio state (applied when the audio output is created)
        self._volume = 1.0
        self._muted = False
        self._temp_video_file = None
        logger.debug(f'Initialized {self}')

    def __del__(self):
        try:
            self.release_player()
        except Exception:  # noqa: BLE001 - __del__ must not raise
            pass

    @classmethod
    def create_from_data(cls, **kwargs):
        item = kwargs.get('item')
        data = kwargs.get('data', {})
        if item is None:
            item = cls()
        item.filename = item.filename or data.get('filename')
        if not item.video_path and data.get('video_path'):
            item.video_path = data['video_path']
        size = data.get('size')
        if size:
            item._width, item._height = size
        item.duration = data.get('duration', item.duration)
        item.setOpacity(data.get('opacity', 1))
        try:
            position = max(0, int(data.get('position', 0)))
        except (TypeError, ValueError):
            position = 0
        item._current_position = item._display_position = position
        try:
            item._volume = max(0.0, min(1.0, float(data.get('volume', 1.0))))
        except (TypeError, ValueError):
            item._volume = 1.0
        item._muted = bool(data.get('muted', False))
        return item

    def __str__(self):
        return (f'Video "{self.filename}" '
                f'{self._width} x {self._height}')

    # -- Size / geometry ---------------------------------------------------

    @property
    def size(self):
        return (self._width, self._height)

    def set_video_size(self, size):
        self.prepareGeometryChange()
        self._width, self._height = size
        self.update()

    def bounding_rect_unselected(self):
        return QtCore.QRectF(0, 0, self._width, self._height)

    # -- Persistence -------------------------------------------------------

    def get_extra_save_data(self):
        return {
            'filename': self.filename,
            'opacity': self.opacity(),
            'size': [self._width, self._height],
            'duration': self.duration,
            'video_path': self.video_path,
            'position': int(self._current_position),
            'volume': round(self._volume, 3),
            'muted': self._muted,
        }

    def get_filename_for_export(self, fmt, save_id_default=None):
        save_id = self.save_id or save_id_default or 0
        if self.filename:
            basename = os.path.splitext(os.path.basename(self.filename))[0]
            return f'{save_id:04}-{basename}.{fmt}'
        return f'{save_id:04}.{fmt}'

    def has_source_file(self):
        return bool(self.video_path and os.path.isfile(self.video_path))

    def video_to_bytes(self):
        if getattr(self, 'video_bytes', None) is not None:
            return self.video_bytes
        if self.has_source_file():
            with open(self.video_path, 'rb') as f:
                return f.read()
        return None

    def embedded_video_bytes(self):
        """Video data that needs to be embedded in the bee file.

        Videos are referenced by their source path; only videos loaded
        from older bee files (which embedded the data) and whose source
        file is gone keep their embedded data, so nothing is lost.
        """

        if self.has_source_file():
            return None
        return getattr(self, 'video_bytes', None)

    def video_from_bytes(self, data):
        self.video_bytes = data

    def get_video_extension(self):
        ext = os.path.splitext(self.filename or '')[1]
        return ext or '.mp4'

    def _local_video_path(self):
        """A playable local file: the source file, or (for old bee files
        with embedded data) a temporary copy of the embedded data."""

        if self.has_source_file():
            return self.video_path
        if (self._temp_video_file
                and os.path.isfile(self._temp_video_file)):
            return self._temp_video_file
        if getattr(self, 'video_bytes', None) is not None:
            tmp = tempfile.NamedTemporaryFile(
                prefix='beeref_video_', suffix=self.get_video_extension(),
                delete=False)
            with tmp:
                tmp.write(self.video_bytes)
            self._temp_video_file = tmp.name
            return tmp.name
        return None

    def _has_source(self):
        return self._local_video_path() is not None

    # -- Player ------------------------------------------------------------

    def _duration(self):
        if self._player is not None and self._player.duration() > 0:
            return self._player.duration()
        return self.duration

    def _media_loaded(self):
        from PyQt6.QtMultimedia import QMediaPlayer
        status = self._player.mediaStatus()
        return status in (QMediaPlayer.MediaStatus.LoadedMedia,
                          QMediaPlayer.MediaStatus.BufferingMedia,
                          QMediaPlayer.MediaStatus.BufferedMedia,
                          QMediaPlayer.MediaStatus.EndOfMedia)

    def _ensure_player(self):
        """Creates the media player (lazily, on the GUI thread)."""

        global _quit_hook_installed
        if self._player is not None:
            return True
        try:
            from PyQt6 import QtMultimedia
        except ImportError:
            return False
        path = self._local_video_path()
        if path is None:
            return False
        self._player = QtMultimedia.QMediaPlayer()
        self._sink = QtMultimedia.QVideoSink()
        self._player.setVideoOutput(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame_changed)
        self._player.mediaStatusChanged.connect(
            self._on_media_status_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.errorOccurred.connect(
            lambda error, msg: logger.warning(
                f'Video playback error for {self}: {msg}'))
        self._seek_timer = QtCore.QTimer()
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(self.SEEK_THROTTLE_MS)
        self._seek_timer.timeout.connect(self._flush_seek)

        if self._display_position > 0:
            self._initial_seek = self._display_position
        if self._current_position > 0:
            # Restore the frame playback was pinned to
            self._initial_seek = self._current_position
            self._expected_position = self._current_position
        self._player.setSource(QtCore.QUrl.fromLocalFile(path))
        # Pausing (rather than playing) decodes the first frame without
        # starting audio output
        self._player.pause()

        _live_video_items.add(self)
        app = QtCore.QCoreApplication.instance()
        if app is not None and not _quit_hook_installed:
            app.aboutToQuit.connect(_release_all_video_players)
            _quit_hook_installed = True
        return True

    def release_player(self):
        """Stops and deletes the media player. The preview frame and the
        pinned position are kept."""

        if getattr(self, '_seek_timer', None) is not None:
            self._seek_timer.stop()
            self._seek_timer.deleteLater()
            self._seek_timer = None
        if getattr(self, '_player', None) is not None:
            self._playing = False
            self._player.stop()
            self._detach_audio()
            self._player.deleteLater()
            self._player = None
        if getattr(self, '_sink', None) is not None:
            self._sink.deleteLater()
            self._sink = None
        self._initial_seek = None
        _live_video_items.discard(self)

    def _attach_audio(self):
        from PyQt6.QtMultimedia import QAudioOutput
        if self._audio is None:
            self._audio = QAudioOutput()
            self._player.setAudioOutput(self._audio)
            self._apply_audio_state()

    def _apply_audio_state(self):
        """Pushes the current volume/mute state to the audio output."""

        if self._audio is None:
            return
        effective = 0.0 if self._muted else self._volume
        self._audio.setMuted(effective <= 0.001)
        self._audio.setVolume(effective)

    @property
    def volume(self):
        return self._volume

    @property
    def is_muted(self):
        return self._muted

    def set_volume(self, volume):
        """Sets the playback volume (0.0 - 1.0)."""

        self._volume = max(0.0, min(1.0, float(volume)))
        if self._volume > 0.001:
            # Turning the volume up unmutes
            self._muted = False
        self._apply_audio_state()
        self.update()

    def toggle_mute(self):
        """Mutes/unmutes playback."""

        if self._muted:
            self._muted = False
        elif self._volume > 0.001:
            self._muted = True
        else:
            # Muted by a zero volume: restore a usable level
            self._volume = 1.0
            self._muted = False
        self._apply_audio_state()
        self.update()
        logger.debug(f'{self}: muted={self._muted} volume={self._volume}')

    def _volume_from_x(self, x):
        """Sets the volume from a local x coordinate on the slider."""

        rect = self._volume_slider_rect()
        if rect.isEmpty():
            return
        self.set_volume((x - rect.left()) / max(rect.width(), 1))

    def _detach_audio(self):
        if self._audio is not None:
            if self._player is not None:
                self._player.setAudioOutput(None)
            self._audio.deleteLater()
            self._audio = None

    def _on_frame_changed(self, frame):
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        # Ignore frames that were decoded for an older seek request, so a
        # scrub preview can't overwrite the pinned frame
        if not self._playing and self._expected_position is not None:
            start = frame.startTime()  # microseconds; -1 when unknown
            if start is not None and start >= 0:
                if abs(start / 1000 - self._expected_position) > \
                        self.FRAME_TOLERANCE_MS:
                    return
        self._frame = image
        self.update()

    def _on_media_status_changed(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer
        if (status == QMediaPlayer.MediaStatus.LoadedMedia
                and self._initial_seek is not None):
            self._player.setPosition(int(self._initial_seek))
            self._initial_seek = None
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._playing:
            self._playing = False
            self._detach_audio()
            self._current_position = max(0, self._duration())
            self._display_position = self._current_position
            self.update()

    def _on_position_changed(self, position):
        if self._playing:
            self._display_position = position
            self.update()

    def _on_duration_changed(self, duration):
        if duration > 0:
            self.duration = duration

    def _set_player_position(self, position):
        self._expected_position = int(position)
        if self._media_loaded():
            self._player.setPosition(int(position))
        else:
            self._initial_seek = int(position)

    def _clamp(self, position):
        duration = self._duration()
        position = max(0, int(position))
        if duration > 0:
            position = min(position, duration - 1)
        return position

    def seek_preview(self, position, pin=False):
        """Shows the frame at the given position (throttled, async).

        With ``pin`` the position also becomes the remembered position the
        item keeps showing after the pointer leaves.
        """

        if not self._ensure_player():
            return
        self._seek_target = self._clamp(position)
        self._display_position = self._seek_target
        if pin:
            self._current_position = self._seek_target
        if not self._seek_timer.isActive():
            self._flush_seek()
            self._seek_timer.start()
        self.update()

    def _flush_seek(self):
        if self._seek_target is None or self._player is None:
            return
        self._set_player_position(self._seek_target)
        self._seek_target = None

    def set_position(self, position):
        """Pins the preview to the given position (ms)."""

        self._current_position = self._display_position = max(
            0, int(position))
        if self._player is not None:
            self.seek_preview(self._current_position)

    def _load_preview(self):
        if self._has_source():
            self._ensure_player()

    def play(self, position_ms=None):
        """Starts playback from the pinned position (or the given one)."""

        if not self._ensure_player():
            logger.info(f'No playable video source for {self}')
            return
        if position_ms is not None:
            self._current_position = max(0, int(position_ms))
        start = self._current_position
        duration = self._duration()
        if duration > 0 and start >= duration - 100:
            start = 0
        self._seek_target = None
        if self._seek_timer is not None:
            self._seek_timer.stop()
        self._attach_audio()
        # While playing, every decoded frame is current
        self._expected_position = None
        self._set_player_position(start)
        self._display_position = start
        self._player.play()
        self._playing = True
        self.update()
        logger.debug(f'Started playback of {self} at {start} ms')

    def pause(self):
        """Pauses playback and pins the preview to the current position."""

        if not self._playing:
            return
        self._playing = False
        if self._player is not None:
            self._player.pause()
            self._current_position = self._clamp(self._player.position())
            self._display_position = self._current_position
            self._expected_position = self._current_position
            self._detach_audio()
        self.update()
        logger.debug(f'Paused {self} at {self._current_position} ms')

    def stop_playback(self):
        self.pause()

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    @property
    def is_playing(self):
        return self._playing

    def itemChange(self, change, value):
        GIC = QtWidgets.QGraphicsItem.GraphicsItemChange
        if change == GIC.ItemSceneHasChanged:
            if value is None:
                self.release_player()
            else:
                self._load_preview()
        return super().itemChange(change, value)

    # -- Controls ----------------------------------------------------------

    def _ui(self, pixels):
        """Converts screen pixels to item units (constant on screen)."""
        return self.fixed_length_for_viewport(pixels)

    def _controls_visible(self):
        # The controls stay visible for the selected item as well, so they
        # are easy to find and don't depend on a fragile hover state
        return (self._hovered or self._playing or self._volume_dragging
                or self.isSelected())

    def _controls_rect(self):
        margin = min(self._ui(self.CONTROLS_MARGIN), self._width * 0.05)
        height = min(self._ui(self.CONTROLS_HEIGHT), self._height * 0.4)
        return QtCore.QRectF(
            margin, self._height - height - margin,
            max(0, self._width - 2 * margin), height)

    def _play_button_rect(self):
        rect = self._controls_rect()
        return QtCore.QRectF(rect.left(), rect.top(),
                             rect.height(), rect.height())

    def _mute_button_rect(self):
        """The mute/unmute button, directly right of play/pause."""

        rect = self._controls_rect()
        play = self._play_button_rect()
        if rect.width() < play.width() * 2.2:
            return QtCore.QRectF()
        return QtCore.QRectF(play.right(), play.top(),
                             play.width(), play.height())

    def _volume_slider_rect(self):
        """The volume slider, right of the mute button."""

        rect = self._controls_rect()
        mute = self._mute_button_rect()
        if mute.isEmpty() or rect.width() < mute.width() * 3.4:
            return QtCore.QRectF()
        width = min(self._ui(self.VOLUME_WIDTH), rect.width() * 0.2)
        if width < self._ui(26):
            return QtCore.QRectF()
        pad = rect.height() * 0.2
        return QtCore.QRectF(mute.right() + pad,
                             rect.top() + rect.height() * 0.32,
                             width, rect.height() * 0.36)

    def _volume_hit_rect(self):
        """A taller hit area around the volume slider."""

        rect = self._volume_slider_rect()
        if rect.isEmpty():
            return rect
        pad = rect.height() * 0.9
        return rect.adjusted(-pad, -pad, pad, pad)

    def _time_text_width(self):
        """Width available for the time label (0 when there is no room)."""

        rect = self._controls_rect()
        width = self._ui(90)
        # The label goes right of the last control
        anchor = self._play_button_rect().right()
        mute = self._mute_button_rect()
        if not mute.isEmpty():
            anchor = mute.right()
        volume = self._volume_slider_rect()
        if not volume.isEmpty():
            anchor = volume.right()
        pad = self._ui(10)
        free = rect.right() - anchor - pad
        if free < width * 0.85:
            return 0
        return min(width, free)

    def _time_rect(self):
        """The time label, right-aligned in the control bar."""

        rect = self._controls_rect()
        width = self._time_text_width()
        if not width:
            return QtCore.QRectF()
        pad = rect.height() * 0.3
        return QtCore.QRectF(rect.right() - width - pad * 0.5,
                             rect.top(), width, rect.height())

    def is_control_hit(self, scene_pos):
        """Whether the given scene position is on the player controls.

        The buttons and the volume slider always respond (they must not
        depend on the hover state), while the empty part of the bar only
        counts as a control while the bar is visible.
        """

        if not self._has_source():
            return False
        local = self.mapFromScene(scene_pos)
        if (self._play_button_rect().contains(local)
                or self._mute_button_rect().contains(local)
                or self._volume_hit_rect().contains(local)):
            return True
        return (self._controls_visible()
                and self._controls_rect().contains(local))

    def _scrub_to(self, x, pin=True):
        """Maps a local x coordinate to a video position and shows it."""

        duration = self._duration()
        if duration <= 0:
            return
        ratio = max(0.0, min(1.0, x / max(1, self._width)))
        self.seek_preview(ratio * (duration - 1), pin=pin)

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        super().hoverMoveEvent(event)
        pos = event.pos()
        self._hover_pos = pos
        if not self._has_source():
            return
        if self._controls_rect().contains(pos):
            self.set_cursor(QtGui.QCursor(Qt.CursorShape.PointingHandCursor))
            self._cursor_set = True
            self.update()
            return
        if getattr(self, '_cursor_set', False):
            self._cursor_set = False
            self.unset_cursor()
        # Only scrub with the pointer alone; while the item is being
        # dragged the scene is in an active (move) mode
        scene = self.scene()
        dragging = scene is not None and scene.active_mode is not None
        if (not self._playing
                and not dragging
                and self.bounding_rect_unselected().contains(pos)):
            # Hover scrubbing: the horizontal mouse position becomes the
            # frame the item keeps showing when the pointer leaves
            self._scrub_to(pos.x())
        self.update()

    def pin_preview(self):
        """Shows the frame at the remembered position again."""

        self._display_position = self._current_position
        self._seek_target = self._current_position
        if self._player is not None:
            self._flush_seek()
        self.update()

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self._hover_pos = None
        if not self._playing and not self._volume_dragging:
            # Keep the frame the pointer last rested on
            self.pin_preview()
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.is_control_hit(event.scenePos())):
            pos = event.pos()
            if self._play_button_rect().contains(pos):
                self.toggle_play()
            elif self._mute_button_rect().contains(pos):
                self.toggle_mute()
            elif self._volume_hit_rect().contains(pos):
                self._volume_dragging = True
                self._volume_from_x(pos.x())
            event.accept()
            return
        if (event.button() == Qt.MouseButton.LeftButton
                and not self._playing
                and self.bounding_rect_unselected().contains(event.pos())):
            # Clicking the video remembers that frame too (the click still
            # selects/moves the item as usual)
            self._scrub_to(event.pos().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._volume_dragging:
            self._volume_from_x(event.pos().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._volume_dragging:
            self._volume_dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.is_control_hit(event.scenePos()):
            self.mousePressEvent(event)
            return
        self.toggle_play()
        event.accept()

    # -- Rendering ---------------------------------------------------------

    def _paint_placeholder(self, painter, rect):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(40, 40, 40)))
        painter.drawRect(rect)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(220, 220, 220)))
        cx, cy = rect.center().x(), rect.center().y()
        s = min(rect.width(), rect.height()) * 0.2
        path = QtGui.QPainterPath()
        path.moveTo(cx - s / 2, cy - s / 2)
        path.lineTo(cx - s / 2, cy + s / 2)
        path.lineTo(cx + s / 2, cy)
        path.closeSubpath()
        painter.drawPath(path)
        if not self._has_source():
            painter.setPen(QtGui.QColor(230, 120, 120))
            font = painter.font()
            font.setPointSizeF(max(1.0, self._ui(10)))
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(0, rect.height() * 0.6, 0, 0),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                tr('Video source not found:\n{path}',
                   path=self.video_path or ''))

    def _paint_mute_icon(self, painter, rect):
        """Draws the speaker icon (crossed out when muted)."""

        s = rect.height() * 0.2
        cx, cy = rect.center().x(), rect.center().y()
        silent = self._muted or self._volume <= 0.001
        color = QtGui.QColor(145, 145, 145) if silent else QtGui.QColor(
            240, 240, 240)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        speaker = QtGui.QPolygonF([
            QtCore.QPointF(cx - s, cy - s * 0.45),
            QtCore.QPointF(cx - s * 0.3, cy - s * 0.45),
            QtCore.QPointF(cx + s * 0.25, cy - s),
            QtCore.QPointF(cx + s * 0.25, cy + s),
            QtCore.QPointF(cx - s * 0.3, cy + s * 0.45),
            QtCore.QPointF(cx - s, cy + s * 0.45),
        ])
        painter.drawPolygon(speaker)
        painter.setBrush(QtGui.QColor(255, 255, 255, 235))

        pen = QtGui.QPen(color)
        pen.setWidthF(max(1.0, rect.height() * 0.055))
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if silent:
            # Cross
            painter.drawLine(
                QtCore.QPointF(cx + s * 0.55, cy - s * 0.55),
                QtCore.QPointF(cx + s * 1.35, cy + s * 0.55))
            painter.drawLine(
                QtCore.QPointF(cx + s * 0.55, cy + s * 0.55),
                QtCore.QPointF(cx + s * 1.35, cy - s * 0.55))
        else:
            # Sound waves, one or two depending on the volume
            waves = 2 if self._volume > 0.55 else 1
            for k in range(waves):
                factor = 0.55 + k * 0.4
                arc = QtCore.QRectF(cx + s * 0.25 - s * factor,
                                    cy - s * factor,
                                    s * 2 * factor, s * 2 * factor)
                painter.drawArc(arc, -55 * 16, 110 * 16)

    def _paint_volume(self, painter):
        """Draws the volume slider."""

        rect = self._volume_slider_rect()
        if rect.isEmpty():
            return
        track_h = max(self._ui(3), 0.4)
        track = QtCore.QRectF(rect.left(),
                              rect.center().y() - track_h / 2,
                              rect.width(), track_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(255, 255, 255, 85))
        painter.drawRoundedRect(track, track_h / 2, track_h / 2)
        level = 0.0 if self._muted else self._volume
        if level > 0:
            filled = QtCore.QRectF(track)
            filled.setWidth(track.width() * level)
            painter.setBrush(QtGui.QColor(0, 140, 255))
            painter.drawRoundedRect(filled, track_h / 2, track_h / 2)
        knob_r = max(track_h * 1.5, rect.height() * 0.2)
        painter.setBrush(QtGui.QColor(255, 255, 255))
        painter.drawEllipse(
            QtCore.QPointF(track.left() + track.width() * level,
                           track.center().y()), knob_r, knob_r)

    def _paint_controls(self, painter):
        duration = self._duration()
        rect = self._controls_rect()
        radius = rect.height() * 0.25
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 160))
        painter.drawRoundedRect(rect, radius, radius)

        # Play / pause button
        button = self._play_button_rect()
        size = button.height() * 0.4
        cx, cy = button.center().x(), button.center().y()
        painter.setBrush(QtGui.QColor(240, 240, 240))
        if self._playing:
            bar_w = size * 0.35
            painter.drawRect(QtCore.QRectF(
                cx - size / 2, cy - size / 2, bar_w, size))
            painter.drawRect(QtCore.QRectF(
                cx + size / 2 - bar_w, cy - size / 2, bar_w, size))
        else:
            path = QtGui.QPainterPath()
            path.moveTo(cx - size * 0.4, cy - size / 2)
            path.lineTo(cx - size * 0.4, cy + size / 2)
            path.lineTo(cx + size * 0.6, cy)
            path.closeSubpath()
            painter.drawPath(path)

        # Mute button
        mute = self._mute_button_rect()
        if not mute.isEmpty():
            self._paint_mute_icon(painter, mute)

        # Volume slider
        self._paint_volume(painter)

        # Time label (the position is controlled by hovering/clicking the
        # video itself, so there is no seek bar)
        text_rect = self._time_rect()
        if not text_rect.isEmpty():
            painter.setPen(QtGui.QColor(240, 240, 240))
            font = painter.font()
            font.setPointSizeF(max(1.0, self._ui(9)))
            painter.setFont(font)
            text = (f'{_format_ms(self._display_position)} / '
                    f'{_format_ms(duration) if duration > 0 else "--:--"}')
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                text)

    def paint(self, painter, option, widget):
        rect = self.bounding_rect_unselected()
        if self._frame is not None and not self._frame.isNull():
            painter.drawImage(rect, self._frame)
        else:
            self._paint_placeholder(painter, rect)

        if (self._hovered and not self._playing and self._hover_pos
                and self._has_source()
                and not self._controls_rect().contains(self._hover_pos)):
            # Scrub playhead
            pen = QtGui.QPen(QtGui.QColor(255, 60, 60))
            pen.setCosmetic(True)
            pen.setWidth(2)
            painter.setPen(pen)
            x = max(0, min(self._width, self._hover_pos.x()))
            painter.drawLine(QtCore.QPointF(x, 0),
                             QtCore.QPointF(x, self._height))

        if self._controls_visible() and self._has_source():
            self._paint_controls(painter)
        self.paint_selectable(painter, option, widget)

    # -- Copy / clipboard ---------------------------------------------------

    def create_copy(self):
        item = BeeVideoItem(
            video_path=self.video_path,
            filename=self.filename,
            size=(self._width, self._height),
            duration=self.duration,
            preview=self._frame,
        )
        if getattr(self, 'video_bytes', None) is not None:
            item.video_bytes = self.video_bytes
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        item.setOpacity(self.opacity())
        if self.flip() == -1:
            item.do_flip()
        item._current_position = self._current_position
        item._display_position = self._current_position
        item._volume = self._volume
        item._muted = self._muted
        return item

    def copy_to_clipboard(self, clipboard):
        if self._frame is not None and not self._frame.isNull():
            clipboard.setPixmap(QtGui.QPixmap.fromImage(self._frame))
        elif self.has_source_file():
            clipboard.setUrls([QtCore.QUrl.fromLocalFile(self.video_path)])
        else:
            clipboard.setText(self.filename or 'video')
