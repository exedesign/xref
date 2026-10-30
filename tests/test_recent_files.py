"""Tests for the recent files overview: thumbnails, pins, location."""

import os

import pytest
from PyQt6 import QtCore, QtGui

from xref.config import XRefSettings
from xref.fileio import thumbnails
from xref.items import XRefPixmapItem
from xref.scene import XRefGraphicsScene
from xref.widgets.welcome_overlay import RecentFilesModel, RecentFilesView


@pytest.fixture
def settings():
    return XRefSettings()


@pytest.fixture
def board(tmp_path, qapp):
    """A board with one embedded image."""

    from xref.fileio import SQLiteIO
    path = str(tmp_path / 'board.xref')
    scene = XRefGraphicsScene(QtGui.QUndoStack())
    img = QtGui.QImage(64, 48, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(200, 60, 60))
    scene.addItem(XRefPixmapItem(img, 'pic.png'))
    store = SQLiteIO(path, scene, create_new=True)
    store.write()
    store._close_connection()
    return path


# -- Thumbnails ---------------------------------------------------------------

def test_board_thumbnail_reads_first_image(board):
    image = thumbnails.board_thumbnail(board)
    assert not image.isNull()
    assert image.width() <= 96


def test_board_thumbnail_of_board_without_images(tmp_path):
    empty = str(tmp_path / 'empty.xref')
    open(empty, 'w').close()
    assert thumbnails.board_thumbnail(empty).isNull()


def test_board_thumbnail_of_missing_file():
    assert thumbnails.board_thumbnail(
        r'C:\nowhere\nothing.xref').isNull()


def test_board_mtime(board):
    assert thumbnails.board_mtime(board) > 0


# -- Pins ----------------------------------------------------------------------

def test_pin_toggle_round_trip(settings, board):
    assert not settings.is_pinned_recent_file(board)
    assert settings.toggle_pinned_recent_file(board) is True
    assert settings.is_pinned_recent_file(board)
    assert settings.toggle_pinned_recent_file(board) is False
    assert not settings.is_pinned_recent_file(board)


def test_pinned_files_survive_nonexistent_entries(settings, tmp_path):
    gone = str(tmp_path / 'gone.xref')
    settings.set_pinned_recent_files([gone])
    assert settings.get_pinned_recent_files() == []


# -- Count setting ---------------------------------------------------------------

def test_recent_files_limited_by_setting(settings, tmp_path):
    files = [str(tmp_path / f'b{i}.xref') for i in range(8)]
    for f in files:
        open(f, 'w').close()
    settings.beginWriteArray('RecentFiles')
    for i, f in enumerate(files):
        settings.setArrayIndex(i)
        settings.setValue('path', f)
    settings.endArray()
    settings.setValue('Save/recent_files_count', 3)
    assert len(settings.get_recent_files(existing_only=True)) == 3
    settings.setValue('Save/recent_files_count', 5)


def test_recent_files_count_widget(settings):
    from xref.widgets.settings import RecentFilesCountWidget
    settings.setValue('Save/recent_files_count', 7)
    widget = RecentFilesCountWidget()
    assert widget.input.value() == 7
    assert widget.input.minimum() == 0
    assert widget.input.maximum() == 20


# -- Model/view -------------------------------------------------------------------

def test_model_shows_thumbnail_and_pin(board, settings, view, qapp):
    settings.set_pinned_recent_files([board])
    model = RecentFilesModel([board], settings)
    model.refresh_metadata()
    index = model.createIndex(0, 0)
    deco = model.data(index, QtCore.Qt.ItemDataRole.DecorationRole)
    assert deco is not None and not deco.isNull()
    text = model.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
    assert 'board.xref' in text
    assert '\u2605' in text  # pinned marker
    settings.set_pinned_recent_files([])


def test_pin_reordering(settings, board, tmp_path, qapp):
    other = str(tmp_path / 'other.xref')
    open(other, 'w').close()
    settings.set_pinned_recent_files([board])
    try:
        view_instance = RecentFilesView(None, None)
        view_instance.update_files([other, board])
        # index 1 is the pinned board; unpinning it keeps 'other' first
        view_instance.toggle_pin(view_instance.model().createIndex(1, 0))
        assert view_instance.files[0].endswith('other.xref')
    finally:
        settings.set_pinned_recent_files([])

def test_open_scene_location_opens_folder(view, board, monkeypatch):
    opened = []
    monkeypatch.setattr(
        'PyQt6.QtGui.QDesktopServices.openUrl',
        lambda url: opened.append(url.toLocalFile()))
    view.filename = board
    view.on_action_open_scene_location()
    assert opened and os.path.normpath(opened[0]) == os.path.normpath(os.path.dirname(board))
    view.filename = None


def test_open_scene_location_without_file(view):
    # Must not raise when no file is open
    view.filename = None
    view.on_action_open_scene_location()
