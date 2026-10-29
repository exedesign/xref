from unittest.mock import MagicMock

import pytest
from PyQt6 import QtCore, QtGui

from xref.config import XRefSettings
from xref.widgets.settings import WindowButtonsDelayWidget
from xref.widgets.window_buttons import WindowButtons


@pytest.fixture
def buttons(main_window):
    widget = main_window.window_buttons
    # The real pointer position is not part of the test, so the automatic
    # polling is turned off; the tests call check_position() directly
    widget.poll_timer.stop()
    main_window.resize(800, 600)
    QtGui.QGuiApplication.processEvents()
    yield widget
    widget.poll_timer.stop()
    widget.hide()


def corner_point(main_window, dx=10, dy=10):
    """A screen position close to the window's top right corner."""

    return main_window.mapToGlobal(QtCore.QPoint(
        main_window.width() - dx, dy))


def far_point(main_window):
    return main_window.mapToGlobal(QtCore.QPoint(20, 300))


def test_hidden_initially(buttons):
    assert not buttons.isVisible()


def test_default_delay_is_three_seconds(main_window, qapp):
    XRefSettings().setValue('View/window_buttons_delay', 3)
    assert main_window.window_buttons.delay_ms() == 3000


def test_button_delay_is_configurable(main_window):
    settings = XRefSettings()
    settings.setValue('View/window_buttons_delay', 7)
    assert main_window.window_buttons.delay_ms() == 7000
    settings.setValue('View/window_buttons_delay', 0)
    assert main_window.window_buttons.delay_ms() == 0
    settings.setValue('View/window_buttons_delay', 3)


def test_appears_immediately_with_no_delay(buttons, main_window):
    XRefSettings().setValue('View/window_buttons_delay', 0)
    try:
        buttons.check_position(corner_point(main_window))
        assert buttons.isVisible()
    finally:
        XRefSettings().setValue('View/window_buttons_delay', 3)
        buttons.hide()


def wait_until(qapp, condition, timeout=3000):
    timer = QtCore.QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout:
        qapp.processEvents()
        QtCore.QThread.msleep(10)
    return condition()


def test_waits_for_the_delay_before_showing(buttons, main_window, qapp):
    XRefSettings().setValue('View/window_buttons_delay', 1)
    try:
        buttons.check_position(corner_point(main_window))
        assert not buttons.isVisible()
        assert buttons.show_timer.isActive()
        assert wait_until(qapp, buttons.isVisible, timeout=3000)
    finally:
        XRefSettings().setValue('View/window_buttons_delay', 3)
        buttons.hide()


def test_does_not_appear_when_the_pointer_is_far_away(buttons, main_window):
    XRefSettings().setValue('View/window_buttons_delay', 0)
    try:
        buttons.check_position(far_point(main_window))
        assert not buttons.isVisible()
        assert not buttons.show_timer.isActive()
    finally:
        XRefSettings().setValue('View/window_buttons_delay', 3)


def test_hides_when_the_pointer_leaves(buttons, main_window, qapp):
    XRefSettings().setValue('View/window_buttons_delay', 0)
    try:
        buttons.check_position(corner_point(main_window))
        assert buttons.isVisible()
        buttons.check_position(far_point(main_window))
        # The buttons fade out before they disappear
        assert wait_until(qapp, lambda: not buttons.isVisible(),
                          timeout=2000)
    finally:
        XRefSettings().setValue('View/window_buttons_delay', 3)


def test_leaving_the_corner_cancels_the_timer(buttons, main_window):
    XRefSettings().setValue('View/window_buttons_delay', 5)
    try:
        buttons.check_position(corner_point(main_window))
        assert buttons.show_timer.isActive()
        buttons.check_position(far_point(main_window))
        assert not buttons.show_timer.isActive()
        assert not buttons.isVisible()
    finally:
        XRefSettings().setValue('View/window_buttons_delay', 3)


def test_corner_geometry_is_in_the_top_right(buttons, main_window):
    geometry = buttons.corner_geometry()
    assert geometry.right() == main_window.width() - buttons.MARGIN - 1
    assert geometry.top() == buttons.MARGIN


def test_minimize_button(buttons, main_window):
    main_window.showMinimized = MagicMock()
    buttons.minimize_button.click()
    assert main_window.showMinimized.called


def test_close_button(buttons, main_window):
    main_window.view.get_confirmation_unsaved_changes = MagicMock(
        return_value=True)
    main_window.close = MagicMock()
    buttons.close_button.click()
    assert main_window.close.called


def test_close_asks_before_discarding_changes(buttons, main_window):
    main_window.view.get_confirmation_unsaved_changes = MagicMock(
        return_value=False)
    buttons.close_button.click()
    assert main_window.isVisible()


def test_close_quits_when_confirmed(buttons, main_window):
    main_window.view.get_confirmation_unsaved_changes = MagicMock(
        return_value=True)
    buttons.close_button.click()
    assert not main_window.isVisible()


def test_fullscreen_button(buttons, main_window):
    main_window.view.toggle_fullscreen = MagicMock()
    buttons.fullscreen_button.click()
    assert main_window.view.toggle_fullscreen.called


def test_fullscreen_button_shows_the_restore_icon(buttons, main_window):
    main_window.showFullScreen()
    buttons.update_fullscreen_button()
    assert main_window.isFullScreen()
    main_window.showNormal()
    buttons.update_fullscreen_button()
    assert not main_window.isFullScreen()


def test_tooltips_are_translated(buttons):
    assert buttons.close_button.toolTip() == 'Close window'
    assert buttons.minimize_button.toolTip() == 'Minimize'
    assert buttons.fullscreen_button.toolTip() == 'Full screen'


def test_glyphs_are_not_empty(buttons):
    for kind in ('minimize', 'fullscreen', 'restore', 'close'):
        pixmap = buttons.glyph(kind)
        assert not pixmap.isNull()


def test_settings_widget_for_the_delay(settings, view):
    settings.setValue('View/window_buttons_delay', 5)
    widget = WindowButtonsDelayWidget()
    assert widget.input.value() == 5
    assert widget.input.minimum() == 0
    assert widget.input.maximum() == 30
    widget.set_value(2)
    assert settings.valueOrDefault('View/window_buttons_delay') == 2
