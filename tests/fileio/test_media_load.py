import os.path

import pytest
from unittest.mock import MagicMock, patch

from PyQt6 import QtCore

from xref import fileio
from xref.items import XRefPixmapItem, XRefVideoItem
from ..utils import queue2list


@pytest.fixture
def videofilename():
    root = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(root, '..', 'assets', 'test3x3.mp4'))


@pytest.fixture
def worker():
    return MagicMock(canceled=False)


def test_load_media_items_image(view, worker, imgfilename3x3):
    view.scene.undo_stack = MagicMock()
    fileio.load_media_items([imgfilename3x3],
                            QtCore.QPointF(5, 6), view.scene, worker)
    itemdata = queue2list(view.scene.items_to_add)
    assert len(itemdata) == 1
    item = itemdata[0][0]['item']
    assert isinstance(item, XRefPixmapItem)
    assert itemdata[0][0]['type'] == 'pixmap'


def test_load_media_items_video(view, worker, videofilename):
    view.scene.undo_stack = MagicMock()
    fileio.load_media_items([videofilename],
                            QtCore.QPointF(5, 6), view.scene, worker)
    itemdata = queue2list(view.scene.items_to_add)
    assert len(itemdata) == 1
    item = itemdata[0][0]['item']
    assert isinstance(item, XRefVideoItem)
    assert itemdata[0][0]['type'] == 'video'
    assert item.video_path == videofilename
    # Size and duration depend on whether the Qt multimedia backend
    # could decode the file in this environment; the fallback is the
    # default size with an unknown duration.
    assert item.size in ((32, 32), XRefVideoItem.DEFAULT_SIZE)


def test_load_media_items_mixed(view, worker, imgfilename3x3,
                                videofilename):
    view.scene.undo_stack = MagicMock()
    fileio.load_media_items(
        [imgfilename3x3, videofilename],
        QtCore.QPointF(5, 6), view.scene, worker)
    itemdata = queue2list(view.scene.items_to_add)
    assert len(itemdata) == 2
    types = [type(itemdata[i][0]['item']) for i in range(len(itemdata))]
    assert XRefPixmapItem in types
    assert XRefVideoItem in types


def test_load_media_items_error(view, worker):
    view.scene.undo_stack = MagicMock()
    fileio.load_media_items(['foo.xyz'],
                            QtCore.QPointF(5, 6), view.scene, worker)
    worker.finished.emit.assert_called_once_with('', ['foo.xyz'])
    itemdata = queue2list(view.scene.items_to_add)
    assert len(itemdata) == 0


def test_load_media_items_canceled(view, imgfilename3x3, videofilename):
    worker = MagicMock(canceled=True)
    view.scene.undo_stack = MagicMock()
    fileio.load_media_items(
        [imgfilename3x3, videofilename],
        QtCore.QPointF(5, 6), view.scene, worker)
    itemdata = queue2list(view.scene.items_to_add)
    assert len(itemdata) == 1


def test_load_images_still_works(view, worker, imgfilename3x3):
    view.scene.undo_stack = MagicMock()
    fileio.load_images([imgfilename3x3],
                       QtCore.QPointF(5, 6), view.scene, worker)
    itemdata = queue2list(view.scene.items_to_add)
    assert len(itemdata) == 1
    assert isinstance(itemdata[0][0]['item'], XRefPixmapItem)
