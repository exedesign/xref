from unittest.mock import patch

from PyQt6 import QtCore, QtWidgets

from xref.view import XRefGraphicsView
from xref.widgets.welcome_overlay import WelcomeOverlay


def test_welcome_overlay_when_no_recent_files(qapp):
    parent = QtWidgets.QMainWindow()
    view = XRefGraphicsView(qapp, parent)
    overlay = WelcomeOverlay(view)
    overlay.show()
    # The canvas shows no recent files list; they live in the menu
    assert not hasattr(overlay, 'files_widget')


def test_welcome_overlay_shows_the_logo(qapp):
    parent = QtWidgets.QMainWindow()
    view = XRefGraphicsView(qapp, parent)
    overlay = WelcomeOverlay(view)
    assert not overlay.logo.pixmap().isNull()
    assert overlay.layout.indexOf(overlay.center_widget) > 0


def test_welcome_overlay_has_no_recent_files_widget(qapp):
    parent = QtWidgets.QMainWindow()
    view = XRefGraphicsView(qapp, parent)
    overlay = WelcomeOverlay(view)
    overlay.show()
    # No files widget exists on the canvas; recent files live in the menu
    assert not hasattr(overlay, 'files_widget')
    assert not hasattr(overlay, 'files_view')


@patch('PyQt6.QtWidgets.QGraphicsView.mousePressEvent')
def test_mouse_press_when_move_window_active(mouse_event_mock, qapp):
    parent = QtWidgets.QMainWindow()
    view = XRefGraphicsView(qapp, parent)
    overlay = WelcomeOverlay(view)
    from unittest.mock import MagicMock
    event = MagicMock()
    event.button.return_value = QtCore.Qt.MouseButton.LeftButton
    event.pos.return_value = QtCore.QPointF(200.0, 150.0)
    overlay.movewin_active = True
    overlay.mousePressEvent(event)
    assert overlay.movewin_active is False
    mouse_event_mock.assert_not_called()
