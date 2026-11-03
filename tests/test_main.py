from unittest.mock import patch, MagicMock

from PyQt6 import QtCore, QtGui

from xref.__main__ import XRefMainWindow, main
from xref.assets import XRefAssets
from xref.view import XRefGraphicsView


@patch('PyQt6.QtWidgets.QWidget.show')
def test_xref_mainwindow_init(show_mock, qapp):
    window = XRefMainWindow(qapp)
    assert window.windowTitle() == 'XRef'
    assert XRefAssets().logo == XRefAssets().logo
    assert window.windowIcon()
    assert window.contentsMargins() == QtCore.QMargins(0, 0, 0, 0)
    assert isinstance(window.view, XRefGraphicsView)
    show_mock.assert_called()


@patch('xref.view.XRefGraphicsView.open_from_file')
def test_xrefapplication_fileopenevent(open_mock, qapp, main_window):
    event = MagicMock()
    event.type.return_value = QtCore.QEvent.Type.FileOpen
    event.file.return_value = 'test.bee'
    assert qapp.event(event) is True
    open_mock.assert_called_once_with('test.bee')


def test_mainwindow_moves_on_right_drag_from_child_widget(main_window, qapp):
    view = main_window.view
    right = QtCore.Qt.MouseButton.RightButton
    no_button = QtCore.Qt.MouseButton.NoButton
    no_modifier = QtCore.Qt.KeyboardModifier.NoModifier

    press = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(5, 5), QtCore.QPointF(5, 5),
        QtCore.QPointF(100, 100), right, right, no_modifier)
    assert qapp.sendEvent(view.viewport(), press)

    move = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        QtCore.QPointF(25, 20), QtCore.QPointF(25, 20),
        QtCore.QPointF(120, 115), no_button, right, no_modifier)
    with patch.object(main_window, 'move') as move_mock:
        assert qapp.sendEvent(view.viewport(), move)
        move_mock.assert_called_once_with(
            main_window.pos() + QtCore.QPoint(20, 15))

    release = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        QtCore.QPointF(25, 20), QtCore.QPointF(25, 20),
        QtCore.QPointF(120, 115), right, no_button, no_modifier)
    assert qapp.sendEvent(view.viewport(), release)


def test_mainwindow_suppresses_mouse_context_menu_after_right_drag(
        main_window):
    view = main_window.view
    right = QtCore.Qt.MouseButton.RightButton
    no_button = QtCore.Qt.MouseButton.NoButton
    no_modifier = QtCore.Qt.KeyboardModifier.NoModifier
    start = QtCore.QPoint(100, 100)
    release_pos = QtCore.QPoint(125, 115)
    press = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(5, 5), QtCore.QPointF(5, 5),
        QtCore.QPointF(start), right, right, no_modifier)
    view.begin_right_window_drag(press)
    move = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        QtCore.QPointF(30, 20), QtCore.QPointF(30, 20),
        QtCore.QPointF(release_pos), no_button, right, no_modifier)
    view.continue_right_window_drag(move)
    release = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        QtCore.QPointF(30, 20), QtCore.QPointF(30, 20),
        QtCore.QPointF(release_pos), right, no_button, no_modifier)
    view.end_right_window_drag(release)

    context_menu = QtGui.QContextMenuEvent(
        QtGui.QContextMenuEvent.Reason.Mouse,
        QtCore.QPoint(30, 20), release_pos)
    assert main_window.eventFilter(view.viewport(), context_menu) is True
    assert view._suppress_drag_context_menu_at is None


def test_alt_key_toggles_before_after_preview(main_window, qapp):
    view = main_window.view
    press = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Alt,
        QtCore.Qt.KeyboardModifier.AltModifier)
    release = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyRelease, QtCore.Qt.Key.Key_Alt,
        QtCore.Qt.KeyboardModifier.NoModifier)

    qapp.sendEvent(view.viewport(), press)
    assert view._before_after_active is True
    qapp.sendEvent(view.viewport(), release)
    assert view._before_after_active is False


@patch('xref.__main__.XRefApplication')
@patch('xref.__main__.CommandlineArgs')
@patch('xref.config.XRefSettings.on_startup')
def test_main(startup_mock, args_mock, app_mock, qapp):
    app_mock.return_value = qapp
    args_mock.return_value.filename = None
    args_mock.return_value.loglevel = 'WARN'
    args_mock.return_value.debug_raise_error = ''

    with patch.object(qapp, 'exec') as exec_mock:
        main()
        exec_mock.assert_called_once_with()

    args_mock.assert_called_once_with(with_check=True)
    startup_mock.assert_called()
