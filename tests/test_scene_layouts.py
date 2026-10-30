"""Tests for per-scene window layouts."""

from xref.config import XRefSettings
from xref.widgets.settings import RememberSceneLayoutsWidget


def test_remember_layouts_is_off_by_default(view):
    view.settings.remove('View/remember_scene_layouts')
    assert view.settings.valueOrDefault('View/remember_scene_layouts') is False


def make_board(tmp_path, name='project.xref'):
    """A minimal board file with the current schema."""

    from xref.fileio import SQLiteIO
    from xref.scene import XRefGraphicsScene
    from PyQt6 import QtGui
    path = str(tmp_path / name)
    scene = XRefGraphicsScene(QtGui.QUndoStack())
    store = SQLiteIO(path, scene, create_new=True)
    store.write()
    store._close_connection()
    return path


def test_layout_stored_inside_the_board(main_window, tmp_path):
    XRefSettings().setValue('View/remember_scene_layouts', True)
    path = make_board(tmp_path)
    main_window.view.filename = path
    try:
        main_window.setGeometry(111, 222, 640, 480)
        main_window.save_scene_layout()
        # No sidecar file is created
        assert not (tmp_path / 'project.xref-layout').exists()
        from xref.fileio import SQLiteIO
        store = SQLiteIO(path, main_window.view.scene, readonly=True)
        geom = store.get_meta('window_geometry')
        store._close_connection()
        assert geom
    finally:
        XRefSettings().setValue('View/remember_scene_layouts', False)
        main_window.view.filename = None


def test_layout_not_saved_when_disabled(main_window, tmp_path):
    XRefSettings().setValue('View/remember_scene_layouts', False)
    path = make_board(tmp_path)
    main_window.view.filename = path
    main_window.save_scene_layout()
    from xref.fileio import SQLiteIO
    store = SQLiteIO(path, main_window.view.scene, readonly=True)
    geom = store.get_meta('window_geometry')
    store._close_connection()
    assert geom is None
    main_window.view.filename = None


def test_layout_restored_when_reopening(main_window, tmp_path):
    XRefSettings().setValue('View/remember_scene_layouts', True)
    path = make_board(tmp_path)
    main_window.view.filename = path
    try:
        main_window.setGeometry(111, 222, 640, 480)
        main_window.save_scene_layout()
        main_window.setGeometry(0, 0, 300, 200)
        assert main_window.restore_scene_layout()
        assert main_window.geometry().getRect() == (111, 222, 640, 480)
    finally:
        XRefSettings().setValue('View/remember_scene_layouts', False)
        main_window.view.filename = None


def test_restore_fails_without_stored_layout(main_window, tmp_path):
    XRefSettings().setValue('View/remember_scene_layouts', True)
    path = make_board(tmp_path)
    main_window.view.filename = path
    try:
        assert main_window.restore_scene_layout() is False
    finally:
        XRefSettings().setValue('View/remember_scene_layouts', False)
        main_window.view.filename = None


def test_migration_4_creates_the_meta_table(tmp_path):
    """The v4 migration adds the meta table to existing boards."""

    import sqlite3
    path = str(tmp_path / 'old.xref')
    con = sqlite3.connect(path)
    con.execute('PRAGMA user_version=3')
    con.execute('PRAGMA application_id=2060242126')
    con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, type TEXT,'
                ' x REAL, y REAL, z REAL, scale REAL, rotation REAL,'
                ' flip INTEGER, data JSON)')
    con.execute('CREATE TABLE sqlar (name TEXT PRIMARY KEY,'
                ' item_id INTEGER NOT NULL UNIQUE, mode INT, mtime INT,'
                ' sz INT, data BLOB)')
    con.execute('CREATE TABLE links (id INTEGER PRIMARY KEY,'
                ' source_id INTEGER NOT NULL, target_id INTEGER NOT NULL)')
    con.commit()
    con.close()

    from xref.fileio import SQLiteIO
    from xref.scene import XRefGraphicsScene
    from PyQt6 import QtGui
    scene = XRefGraphicsScene(QtGui.QUndoStack())
    store = SQLiteIO(path, scene)
    # Migrations run on open; then meta can be used
    store.set_meta('window_geometry', b'test')
    store._close_connection()

    con = sqlite3.connect(path)
    version = con.execute('PRAGMA user_version').fetchone()[0]
    keys = [r[0] for r in con.execute('SELECT key FROM meta')]
    con.close()
    assert version >= 4
    assert keys == ['window_geometry']


def test_settings_widget_round_trip(settings, view):
    settings.setValue('View/remember_scene_layouts', True)
    widget = RememberSceneLayoutsWidget()
    assert widget.input.isChecked()
    widget.set_value(False)
    widget.on_value_changed(False)
    assert settings.valueOrDefault('View/remember_scene_layouts') is False
