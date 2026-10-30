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

"""XRef's native file format is using SQLite. Embedded files are
stored in an sqlar table so that they can be extracted using sqlite's
archive command line option.

For more info, see:

https://www.sqlite.org/appfileformat.html
https://www.sqlite.org/sqlar.html
"""

import json
import logging
import os
import pathlib
import shutil
import sqlite3
import tempfile

from PyQt6 import QtGui

from xref import constants
from xref.items import XRefPixmapItem, XRefErrorItem, XRefPdfItem, \
    XRefVideoItem, \
    XRefModelItem, \
    XRefDrawItem
from .errors import XRefFileIOError, IMG_LOADING_ERROR_MSG
from .schema import SCHEMA, USER_VERSION, MIGRATIONS, APPLICATION_ID


logger = logging.getLogger(__name__)


def is_bee_file(path):
    """Whether the file at the given path is an XRef board.

    Boards saved by older versions (and by BeeRef) still use ``.bee``
    and keep opening.
    """

    extension = os.path.splitext(path)[1].lstrip('.').lower()
    return (extension == constants.FILE_EXTENSION
            or extension in constants.LEGACY_FILE_EXTENSIONS)


def handle_sqlite_errors(func):
    def wrapper(self, *args, **kwargs):
        try:
            func(self, *args, **kwargs)
        except Exception as e:
            logger.exception(f'Error while reading/writing {self.filename}')
            try:
                # Try to roll back transaction if there is any
                if (hasattr(self, '_connection')
                        and self._connection.in_transaction):
                    self.ex('ROLLBACK')
                    logger.debug('Transaction rolled back')
            except sqlite3.Error:
                pass
            self._close_connection()
            if self.worker:
                self.worker.finished.emit(self.filename, [str(e)])
            else:
                raise XRefFileIOError(msg=str(e), filename=self.filename) from e

    return wrapper


class SQLiteIO:

    def __init__(self, filename, scene, create_new=False, readonly=False,
                 worker=None):
        self.scene = scene
        self.create_new = create_new
        self.filename = filename
        self.readonly = readonly
        self.worker = worker
        self.retry = False

    def __del__(self):
        self._close_connection()

    def _close_connection(self):
        if hasattr(self, '_connection'):
            self._connection.close()
            delattr(self, '_connection')
        if hasattr(self, '_cursor'):
            delattr(self, '_cursor')
        if hasattr(self, '_tmpdir'):
            self._tmpdir.cleanup()
            delattr(self, '_tmpdir')

    def _establish_connection(self):
        if (self.create_new
                and not self.readonly
                and os.path.exists(self.filename)):
            os.remove(self.filename)

        if self.create_new:
            self.scene.clear_save_ids()

        uri = pathlib.Path(self.filename).resolve().as_uri()
        if self.readonly:
            uri = f'{uri}?mode=rw'
        self._connection = sqlite3.connect(uri, uri=True)
        self._cursor = self.connection.cursor()
        if not self.create_new:
            try:
                self._migrate()
            except Exception:
                # Updating a file failed; try creating it from scratch instead
                logger.exception('Error migrating bee file')
                self.create_new = True
                self._establish_connection()

    def _migrate(self):
        """Migrate database if necessary."""

        version = self.fetchone('PRAGMA user_version')[0]
        logger.debug(f'Found bee file version: {version}')
        if version >= USER_VERSION:
            logger.debug('Version ok; no migrations necessary')
            return

        if self.readonly:
            try:
                # See whether file is writable so we can migrate it directly
                self.ex('PRAGMA application_id=%s' % APPLICATION_ID)
            except sqlite3.Error:
                logger.debug('File not writable; use temporary copy instead')
                self._connection.close()
                self._tmpdir = tempfile.TemporaryDirectory(
                    prefix=constants.APPNAME)
                tmpname = os.path.join(self._tmpdir.name, 'mig.bee')
                shutil.copyfile(self.filename, tmpname)
                self._connection = sqlite3.connect(tmpname)
                self._cursor = self.connection.cursor()

        self.ex('BEGIN TRANSACTION')
        for i in range(version, USER_VERSION):
            logger.debug(f'Migrating from version {i} to {i + 1}...')
            for migration in MIGRATIONS[i + 1]:
                self.ex(migration)
        self.write_meta()
        self.connection.commit()
        logger.debug('Migration finished')

    @property
    def connection(self):
        if not hasattr(self, '_connection'):
            self._establish_connection()
        return self._connection

    @property
    def cursor(self):
        if not hasattr(self, '_cursor'):
            self._establish_connection()
        return self._cursor

    def ex(self, *args, **kwargs):
        return self.cursor.execute(*args, **kwargs)

    def exmany(self, *args, **kwargs):
        return self.cursor.executemany(*args, **kwargs)

    def fetchone(self, *args, **kwargs):
        self.ex(*args, **kwargs)
        return self.cursor.fetchone()

    def fetchall(self, *args, **kwargs):
        self.ex(*args, **kwargs)
        return self.cursor.fetchall()

    def set_meta(self, key, value):
        """Stores a metadata value (e.g. the window layout) in the board."""

        self.ex(
            'INSERT INTO meta (key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (key, value))
        self.connection.commit()

    def get_meta(self, key):
        """Reads a metadata value from the board, or None."""

        row = self.fetchone('SELECT value FROM meta WHERE key=?', (key,))
        return row[0] if row else None

    def write_meta(self):
        self.ex('PRAGMA application_id=%s' % APPLICATION_ID)
        self.ex('PRAGMA user_version=%s' % USER_VERSION)
        self.ex('PRAGMA foreign_keys=ON')

    def create_schema_on_new(self):
        if self.create_new:
            self.write_meta()
            for schema in SCHEMA:
                self.ex(schema)

    @handle_sqlite_errors
    def read(self):
        rows = self.fetchall(
            'SELECT items.id, type, x, y, z, scale, rotation, flip, '
            'items.data, sqlar.data '
            'FROM sqlar JOIN items on sqlar.item_id = items.id')
        # Avoid OUTER JOIN for performance reasons; fetch items without
        # embedded data (text, draw) separately instead
        rows.extend(self.fetchall(
            'SELECT items.id, type, x, y, z, scale, rotation, flip, '
            ' items.data, null as data '
            'FROM items '
            'WHERE items.type IN ("text", "draw") '
            'OR (items.type IN ("video", "pdf", "model") '
            'AND items.id NOT IN '
            '(SELECT item_id FROM sqlar))'))
        if self.worker:
            self.worker.begin_processing.emit(len(rows))

        for i, row in enumerate(rows):
            data = {
                'save_id': row[0],
                'type': row[1],
                'x': row[2],
                'y': row[3],
                'z': row[4],
                'scale': row[5],
                'rotation': row[6],
                'flip': row[7],
                'data': json.loads(row[8]),
            }

            if data['type'] == 'pixmap':
                item = XRefPixmapItem(QtGui.QImage())
                item.pixmap_from_bytes(row[9])
                if item.pixmap().isNull():
                    item = data['data']['text'] = (
                        f'Image could not be loaded: {item.filename}\n'
                        + IMG_LOADING_ERROR_MSG)
                    data['type'] = XRefErrorItem.TYPE
                data['item'] = item

            if data['type'] == 'video':
                item = XRefVideoItem()
                if row[9] is not None:
                    item.video_from_bytes(row[9])
                data['item'] = item

            if data['type'] == 'pdf':
                item = XRefPdfItem()
                if row[9] is not None:
                    item.pdf_from_bytes(row[9])
                data['item'] = item

            if data['type'] == 'model':
                item = XRefModelItem()
                if row[9] is not None:
                    item.model_from_bytes(row[9])
                data['item'] = item

            if data['type'] == 'draw':
                item = XRefDrawItem.create_from_data(data=data['data'])
                data['item'] = item

            self.scene.add_item_later(data)

            if self.worker:
                logger.trace(f'Emit progress: {i}')
                self.worker.progress.emit(i)
                if self.worker.canceled:
                    self.worker.finished.emit('', [])
                    return
                # Give main thread time to process items:
                self.worker.msleep(10)
        # Links are restored after the items have been added to the scene
        self.add_queued_items()
        self.read_links()
        if self.worker:
            self.worker.finished.emit(self.filename, [])

    def add_queued_items(self):
        self.scene.add_queued_items()

    def read_links(self):
        """Restores node links between items from the links table."""

        try:
            if not self.fetchone(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='links'"):
                # Older bee files without the links table
                return
            rows = self.fetchall('SELECT source_id, target_id FROM links')
        except sqlite3.Error:
            return
        by_id = {item.save_id: item
                 for item in self.scene.items()
                 if hasattr(item, 'save_id') and item.save_id}
        for source_id, target_id in rows:
            source = by_id.get(source_id)
            target = by_id.get(target_id)
            if source is not None and target is not None:
                self.scene.add_link(source, target)
        logger.debug(f'Restored {len(rows)} links')

    @handle_sqlite_errors
    def write(self):
        if self.readonly:
            raise sqlite3.OperationalError(
                'Attempt to write to a readonly database')
        try:
            self.create_schema_on_new()
            self.write_data()
        except Exception:
            if self.retry:
                # Trying to recover failed
                raise
            else:
                self.retry = True
                # Try creating file from scratch and save again
                logger.exception(
                    f'Updating to existing file {self.filename} failed')
                self.create_new = True
                self._close_connection()
                self.write()

    def write_data(self):
        to_delete = {row[0] for row in self.fetchall('SELECT id from ITEMS')}
        # We don't want to touch existing items that are displayed as errors:
        keep = {item.original_save_id
                for item in self.scene.items_by_type(XRefErrorItem.TYPE)}
        logger.debug(f'Not saving error items: {keep}')
        to_delete = to_delete - keep

        to_save = list(self.scene.items_for_save())
        if self.worker:
            self.worker.begin_processing.emit(len(to_save))
        for i, item in enumerate(to_save):
            logger.debug(f'Saving {item} with id {item.save_id}')
            if item.save_id:
                self.update_item(item)
                to_delete.remove(item.save_id)
            else:
                self.insert_item(item)
            if self.worker:
                self.worker.progress.emit(i)
                if self.worker.canceled:
                    break
        self.delete_items(to_delete)
        self.write_links()
        self.connection.commit()
        self.ex('VACUUM')
        self.connection.commit()

    def _ensure_links_table(self):
        """Creates the links table if it doesn't exist yet (files
        written before links were supported)."""

        if not self.fetchone(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='links'"):
            self.ex(
                'CREATE TABLE links (id INTEGER PRIMARY KEY, '
                'source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, '
                'UNIQUE (source_id, target_id))')

    def write_links(self):
        """Saves node links between items to the links table."""

        self._ensure_links_table()
        self.ex('DELETE FROM links')
        rows = [(source.save_id, target.save_id)
                for source, target in self.scene.active_links()
                if getattr(source, 'save_id', None) is not None
                and getattr(target, 'save_id', None) is not None]
        self.exmany('INSERT INTO links (source_id, target_id) '
                    'VALUES (?, ?)', rows)
        if self.worker:
            self.worker.finished.emit(self.filename, [])

    def delete_items(self, to_delete):
        to_delete = [(pk,) for pk in to_delete]
        self.exmany('DELETE FROM items WHERE id=?', to_delete)
        self.exmany('DELETE FROM sqlar WHERE item_id=?', to_delete)
        self.connection.commit()

    def insert_item(self, item):
        self.ex(
            'INSERT INTO items (type, x, y, z, scale, rotation, flip, '
            'data) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (item.TYPE, item.pos().x(), item.pos().y(), item.zValue(),
             item.scale(), item.rotation(), item.flip(),
             json.dumps(item.get_extra_save_data())))
        item.save_id = self.cursor.lastrowid

        if hasattr(item, 'pixmap_to_bytes'):
            pixmap, imgformat = item.pixmap_to_bytes()
            name = item.get_filename_for_export(imgformat)
            self.ex(
                'INSERT INTO sqlar (item_id, name, mode, sz, data) '
                'VALUES (?, ?, ?, ?, ?)',
                (item.save_id, name, 0o644, len(pixmap), pixmap))

        if item.TYPE == 'pdf':
            # PDFs are embedded, so boards stay self-contained
            data = item.pdf_to_bytes()
            if data is not None:
                name = item.get_filename_for_export('pdf')
                self.ex(
                    'INSERT INTO sqlar (item_id, name, mode, sz, data) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (item.save_id, name, 0o644, len(data), data))

        if item.TYPE == 'model':
            # Models are embedded, so boards stay self-contained
            data = item.model_to_bytes()
            if data is not None:
                ext = (item.filename or 'model.obj').rsplit('.', 1)[-1]
                name = item.get_filename_for_export(ext)
                self.ex(
                    'INSERT INTO sqlar (item_id, name, mode, sz, data) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (item.save_id, name, 0o644, len(data), data))

        if item.TYPE == 'video':
            # Videos are played from their source location; only data
            # whose source file is gone (old bee files) stays embedded
            data = item.embedded_video_bytes()
            if data is not None:
                ext = item.get_video_extension().lstrip('.')
                name = item.get_filename_for_export(ext)
                self.ex(
                    'INSERT INTO sqlar (item_id, name, mode, sz, data) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (item.save_id, name, 0o644, len(data), data))
        self.connection.commit()

    def update_item(self, item):
        """Update item data.

        We only update the item data, not the pixmap data, as pixmap
        data never changes and is also time-consuming to save.
        """
        self.ex(
            'UPDATE items SET x=?, y=?, z=?, scale=?, rotation=?, flip=?, '
            'data=? '
            'WHERE id=?',
            (item.pos().x(), item.pos().y(), item.zValue(), item.scale(),
             item.rotation(), item.flip(),
             json.dumps(item.get_extra_save_data()),
             item.save_id))
        self.connection.commit()
