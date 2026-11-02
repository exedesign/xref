"""Tests for the window corner radius setting."""

from PyQt6 import QtCore

from xref.config import XRefSettings


def test_corner_radius_setting_defaults(main_window, qapp):
    XRefSettings().setValue('View/window_corner_radius', 8)
    assert XRefSettings().valueOrDefault('View/window_corner_radius') == 8


def test_corner_radius_bounds(main_window):
    XRefSettings().setValue('View/window_corner_radius', 0)
    assert XRefSettings().valueOrDefault('View/window_corner_radius') == 0
    XRefSettings().setValue('View/window_corner_radius', 32)
    assert XRefSettings().valueOrDefault('View/window_corner_radius') == 32
    XRefSettings().setValue('View/window_corner_radius', 8)


def test_mask_clips_corners_when_rounded(main_window, qapp):
    win = main_window
    win.resize(600, 400)
    win.view.apply_window_flags(frameless=True)
    win.show()
    qapp.processEvents()

    XRefSettings().setValue('View/window_corner_radius', 8)
    win.apply_corner_shape()
    qapp.processEvents()

    assert win.rounded_corners_on()
    mask = win.mask()
    # Corners are clipped away, the rest of the window stays visible
    assert not mask.contains(QtCore.QPoint(1, 1))
    assert not mask.contains(QtCore.QPoint(
        win.width() - 1, win.height() - 1))
    assert mask.contains(QtCore.QPoint(win.width() // 2,
                                       win.height() // 2))
    assert mask.contains(QtCore.QPoint(win.width() // 2, 1))


def test_mask_gone_with_zero_radius(main_window, qapp):
    win = main_window
    win.view.apply_window_flags(frameless=True)
    win.show()
    qapp.processEvents()

    XRefSettings().setValue('View/window_corner_radius', 0)
    win.apply_corner_shape()
    qapp.processEvents()
    assert not win.rounded_corners_on()
    # After clearMask() the region is empty, which means "no clipping":
    # the system mask is gone and corners are square
    assert win.mask().isEmpty()

    XRefSettings().setValue('View/window_corner_radius', 8)
    win.apply_corner_shape()
    qapp.processEvents()


def test_settings_dialog_has_corner_widget():
    from xref.widgets.settings import WindowCornerRadiusWidget
    assert WindowCornerRadiusWidget.KEY == 'View/window_corner_radius'
    assert WindowCornerRadiusWidget.MIN == 0
    assert WindowCornerRadiusWidget.MAX == 32
