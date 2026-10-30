"""Tests for the Open Scene Location command."""

import os


def test_open_scene_location_opens_folder(view, tmp_path, monkeypatch):
    board = tmp_path / 'b.xref'
    board.write_bytes(b'x')
    opened = []
    monkeypatch.setattr(
        'PyQt6.QtGui.QDesktopServices.openUrl',
        lambda url: opened.append(url.toLocalFile()))
    view.filename = str(board)
    view.on_action_open_scene_location()
    assert opened and os.path.normpath(opened[0]) == os.path.normpath(
        str(tmp_path))
    view.filename = None


def test_open_scene_location_without_file(view):
    # Must not raise when no file is open
    view.filename = None
    view.on_action_open_scene_location()
