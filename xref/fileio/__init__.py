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

from PyQt6 import QtCore

from xref import commands
from xref.config import XRefSettings
from xref.fileio.errors import XRefFileIOError
from xref.fileio.image import load_image_preview
from xref.fileio.media import load_media
from xref.fileio.sql import SQLiteIO, is_bee_file
from xref.items import XRefPixmapItem, XRefVideoItem


__all__ = [
    'is_bee_file',
    'load_bee',
    'save_bee',
    'load_images',
    'load_media_items',
    'ThreadedLoader',
    'XRefFileIOError',
]

logger = logging.getLogger(__name__)


def load_bee(filename, scene, worker=None):
    """Load XRef native file."""
    logger.info(f'Loading from file {filename}...')
    io = SQLiteIO(filename, scene, readonly=True, worker=worker)
    return io.read()


def save_bee(filename, scene, create_new=False, worker=None):
    """Save XRef native file."""
    logger.info(f'Saving to file {filename}...')
    logger.debug(f'Create new: {create_new}')
    io = SQLiteIO(filename, scene, create_new, worker=worker)
    io.write()
    logger.info('End save')


def load_images(filenames, pos, scene, worker):
    """Add images to existing scene."""

    errors = []
    items = []
    worker.begin_processing.emit(len(filenames))
    for i, filename in enumerate(filenames):
        logger.info(f'Loading image from file {filename}')
        preview, filename = load_image_preview(
            filename, XRefSettings().valueOrDefault(
                'Items/image_preview_max_dimension'))
        worker.progress.emit(i)
        if preview.image.isNull():
            logger.info(f'Could not load file {filename}')
            errors.append(filename)
            continue

        item = XRefPixmapItem(
            preview.image, filename,
            source_image_bytes=preview.source_bytes,
            source_image_size=preview.source_size,
            source_image_format=preview.source_format)
        item.set_pos_center(pos)
        scene.add_item_later({'item': item, 'type': 'pixmap'}, selected=True)
        items.append(item)
        if worker.canceled:
            break
        # Give main thread time to process items:
        worker.msleep(10)

    scene.undo_stack.push(
        commands.InsertItems(scene, items, ignore_first_redo=True))
    worker.finished.emit('', errors)


def load_media_items(filenames, pos, scene, worker):
    """Add images and videos to the existing scene.

    Files are classified by their media type; files that can't be
    loaded are reported as errors.
    """

    import os.path

    from xref.items import XRefModelItem, XRefPdfItem, _probe_pdf, _probe_video

    errors = []
    items = []
    settings = XRefSettings()
    image_preview_max_dimension = settings.valueOrDefault(
        'Items/image_preview_max_dimension')
    model_default_view = settings.valueOrDefault(
        'Items/model_default_view')
    model_up_axis = settings.valueOrDefault('Items/model_up_axis')
    worker.begin_processing.emit(len(filenames))
    for i, filename in enumerate(filenames):
        logger.info(f'Loading media from file {filename}')
        result = load_media(filename, image_preview_max_dimension)
        worker.progress.emit(i)
        if result is None:
            logger.info(f'Could not load file {filename}')
            errors.append(filename)
            continue

        mtype, data, resolved = result
        if mtype == 'image':
            item = XRefPixmapItem(
                data.image, resolved,
                source_image_bytes=data.source_bytes,
                source_image_size=data.source_size,
                source_image_format=data.source_format)
            itype = 'pixmap'
        elif mtype == 'pdf':
            probe = _probe_pdf(data)
            item = XRefPdfItem(
                pdf_path=data,
                filename=os.path.basename(resolved),
                size=probe['size'],
                pages=probe['pages'],
                preview=probe['preview'],
            )
            itype = 'pdf'
        elif mtype == 'model':
            item = XRefModelItem(
                model_path=data,
                filename=os.path.basename(resolved),
                initial_view_preset=model_default_view,
                model_up_axis=model_up_axis,
            )
            itype = 'model'
        else:
            probe = _probe_video(data)
            item = XRefVideoItem(
                video_path=data,
                filename=os.path.basename(resolved),
                size=probe['size'],
                duration=probe['duration'],
                preview=probe['preview'],
            )
            itype = 'video'
        item.set_pos_center(pos)
        scene.add_item_later({'item': item, 'type': itype}, selected=True)
        items.append(item)
        if worker.canceled:
            break
        # Give main thread time to process items:
        worker.msleep(10)

    scene.undo_stack.push(
        commands.InsertItems(scene, items, ignore_first_redo=True))
    worker.finished.emit('', errors)


class ThreadedIO(QtCore.QThread):
    """Dedicated thread for loading and saving."""

    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str, list)
    begin_processing = QtCore.pyqtSignal(int)
    user_input_required = QtCore.pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.kwargs['worker'] = self
        self.canceled = False

    def run(self):
        self.func(*self.args, **self.kwargs)

    def on_canceled(self):
        self.canceled = True
