"""Tests for per-scene window layouts."""

import base64

from xref.config import XRefSettings
from xref.widgets.settings import RememberSceneLayoutsWidget


def test_remember_layouts_is_off_by_default(view):
    view.settings.remove('View/remember_scene_layouts')
    assert view.settings.valueOrDefault('View/remember_scene_layouts') is False


def test_layout_sidecar_path(main_window):
    main_window.view.filename = r'C:\boards\project.xref'
    assert main_window.scene_layout_path() == \
        r'C:\boards\project.xref-layout'
    main_window.view.filename = None
    assert main_window.scene_layout_path() is None


def test_layout_saved_next_to_scene(main_window, tmp_path):
    XRefSettings().setValue('View/remember_scene_layouts', True)
    board = tmp_path / 'project.xref'
    board.write_bytes(b'x')
    main_window.view.filename = str(board)
    try:
        main_window.save_scene_layout()
        sidecar = tmp_path / 'project.xref-layout'
        assert sidecar.exists()
        stored = base64.b64decode(sidecar.read_bytes())
        assert stored  # a QByteArray geometry
    finally:
        XRefSettings().setValue('View/remember_scene_layouts', False)
        main_window.view.filename = None


def test_layout_not_saved_when_disabled(main_window, tmp_path):
    XRefSettings().setValue('View/remember_scene_layouts', False)
    board = tmp_path / 'project.xref'
    board.write_bytes(b'x')
    main_window.view.filename = str(board)
    main_window.save_scene_layout()
    assert not (tmp_path / 'project.xref-layout').exists()
    main_window.view.filename = None


def test_layout_restored_when_reopening(main_window, tmp_path):
    XRefSettings().setValue('View/remember_scene_layouts', True)
    board = tmp_path / 'project.xref'
    board.write_bytes(b'x')
    main_window.view.filename = str(board)
    main_window.setGeometry(111, 222, 640, 480)
    try:
        main_window.save_scene_layout()
        # Move the window somewhere else, then restore
        main_window.setGeometry(0, 0, 300, 200)
        assert main_window.restore_scene_layout()
        assert main_window.geometry().getRect() == (111, 222, 640, 480)
    finally:
        XRefSettings().setValue('View/remember_scene_layouts', False)
        main_window.view.filename = None


def test_restore_fails_without_sidecar(main_window, tmp_path):
    XRefSettings().setValue('View/remember_scene_layouts', True)
    board = tmp_path / 'nothing.xref'
    main_window.view.filename = str(board)
    try:
        assert main_window.restore_scene_layout() is False
    finally:
        XRefSettings().setValue('View/remember_scene_layouts', False)
        main_window.view.filename = None


def test_settings_widget_round_trip(settings, view):
    settings.setValue('View/remember_scene_layouts', True)
    widget = RememberSceneLayoutsWidget()
    assert widget.input.isChecked()
    widget.set_value(False)
    widget.on_value_changed(False)
    assert settings.valueOrDefault('View/remember_scene_layouts') is False
