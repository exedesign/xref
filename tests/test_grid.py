"""Tests for the PureRef style reference grid."""

from unittest.mock import MagicMock

import pytest
from PyQt6 import QtCore, QtGui

from xref.config import XRefSettings
from xref.items import XRefPixmapItem
from xref.widgets.settings import (
    GridSnapWidget, GridSpacingWidget, GridStyleWidget)


def make_item(view, x=0, y=0):
    image = QtGui.QImage(40, 30, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(120, 160, 200))
    item = XRefPixmapItem(image, 'grid.png')
    view.scene.addItem(item)
    item.setPos(x, y)
    return item


# -- Settings ---------------------------------------------------------------

def test_grid_defaults_to_off(view):
    view.settings.remove('View/grid_style')
    assert view.grid_style() == 'off'


def test_grid_style_can_be_changed(view):
    for style in ('dots', 'squares', 'off'):
        view.settings.setValue('View/grid_style', style)
        assert view.grid_style() == style


def test_grid_style_falls_back_on_invalid_values(view):
    view.settings.setValue('View/grid_style', 'triangles')
    assert view.grid_style() == 'off'


def test_grid_spacing_defaults_and_bounds(view):
    view.settings.remove('View/grid_spacing')
    assert view.grid_spacing() == 100

    view.settings.setValue('View/grid_spacing', 250)
    assert view.grid_spacing() == 250

    # Values outside the range fall back through valueOrDefault
    XRefSettings().setValue('View/grid_spacing', 5)
    assert view.grid_spacing() == 100


def test_snap_is_off_by_default(view):
    view.settings.remove('View/grid_snap')
    assert view.grid_snap_enabled() is False


def test_snap_point_rounds_to_the_grid(view):
    view.settings.setValue('View/grid_style', 'dots')
    view.settings.setValue('View/grid_spacing', 50)
    view.settings.setValue('View/grid_snap', True)

    snapped = view.snap_point(QtCore.QPointF(112.0, 38.0))

    assert snapped.x() == 100
    assert snapped.y() == 50


def test_snap_point_is_a_noop_when_disabled(view):
    view.settings.setValue('View/grid_spacing', 50)
    view.settings.setValue('View/grid_snap', False)

    point = QtCore.QPointF(112.0, 38.0)

    assert view.snap_point(point) is point


# -- Drawing ----------------------------------------------------------------

def painted(view, width=200, height=200):
    """Renders the view background into an image for inspection."""

    image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    view.drawBackground(painter, QtCore.QRectF(0, 0, width, height))
    painter.end()
    return image


def test_no_grid_is_painted_when_off(view):
    view.settings.setValue('View/grid_style', 'off')
    view.set_canvas_color(QtGui.QColor(0, 0, 0))

    image = painted(view)

    colors = {image.pixelColor(x, y).name() for x in range(0, 200, 7)
              for y in range(0, 200, 7)}
    assert colors == {'#000000'}


def test_dot_grid_paints_dots(view):
    view.settings.setValue('View/grid_style', 'dots')
    view.settings.setValue('View/grid_spacing', 50)
    view.set_canvas_color(QtGui.QColor(0, 0, 0))

    image = painted(view)

    colors = {image.pixelColor(x, y).name() for x in range(200)
              for y in range(200)}
    # The dots are a light tint over the black canvas
    assert len(colors) > 1
    assert '#000000' in colors


def test_square_grid_paints_lines(view):
    view.settings.setValue('View/grid_style', 'squares')
    view.settings.setValue('View/grid_spacing', 50)
    view.set_canvas_color(QtGui.QColor(0, 0, 0))

    image = painted(view)

    # A grid line sits on the first grid column, not between two of them
    assert image.pixelColor(50, 10) != image.pixelColor(20, 10)


def test_grid_is_skipped_when_too_dense(view):
    """Zooming far out must not paint a solid rectangle of grid colour."""

    view.settings.setValue('View/grid_style', 'dots')
    view.settings.setValue('View/grid_spacing', 10)
    view.set_canvas_color(QtGui.QColor(0, 0, 0))
    view.scale(0.05, 0.05)
    try:
        image = painted(view, 120, 120)
        # Plenty of untouched canvas is left between the dots
        assert image.pixelColor(3, 3).name() == '#000000'
    finally:
        view.resetTransform()


# -- Snapping ---------------------------------------------------------------

def test_dragging_snaps_the_item_to_the_grid(view):
    view.settings.setValue('View/grid_style', 'dots')
    view.settings.setValue('View/grid_spacing', 50)
    view.settings.setValue('View/grid_snap', True)
    item = make_item(view)

    # Simulate the interactive drag: the item is the mouse grabber
    view.scene.mouseGrabberItem = MagicMock(return_value=item)
    item.setPos(112.0, 38.0)

    assert item.pos().x() == 100
    assert item.pos().y() == 50


def test_programmatic_moves_do_not_snap(view):
    """Loading, arranging and undo keep their exact positions."""

    view.settings.setValue('View/grid_spacing', 50)
    view.settings.setValue('View/grid_snap', True)
    item = make_item(view)

    view.scene.mouseGrabberItem = MagicMock(return_value=None)
    item.setPos(112.0, 38.0)

    assert item.pos().x() == pytest.approx(112.0)
    assert item.pos().y() == pytest.approx(38.0)


def test_snapping_is_ignored_when_disabled(view):
    view.settings.setValue('View/grid_spacing', 50)
    view.settings.setValue('View/grid_snap', False)
    item = make_item(view)

    view.scene.mouseGrabberItem = MagicMock(return_value=item)
    item.setPos(112.0, 38.0)

    assert item.pos().x() == pytest.approx(112.0)


def test_transient_items_never_snap_to_the_grid():
    from xref.selection import RubberbandItem, MultiSelectItem

    assert RubberbandItem.SNAP_TO_GRID is False
    assert MultiSelectItem.SNAP_TO_GRID is False


# -- Settings dialog --------------------------------------------------------

def test_settings_dialog_has_grid_widgets(view):
    from xref.widgets.settings import SettingsDialog
    dialog = SettingsDialog(view)
    try:
        assert dialog.findChildren(GridStyleWidget)
        assert dialog.findChildren(GridSpacingWidget)
        assert dialog.findChildren(GridSnapWidget)
        assert GridStyleWidget.KEY == 'View/grid_style'
        assert GridSpacingWidget.KEY == 'View/grid_spacing'
        assert GridSnapWidget.KEY == 'View/grid_snap'
        values = [option[0] for option in GridStyleWidget.OPTIONS]
        assert values == ['off', 'dots', 'squares']
    finally:
        dialog.close()
        dialog.deleteLater()


def test_grid_spacing_widget_bounds():
    assert GridSpacingWidget.MIN == 10
    assert GridSpacingWidget.MAX == 500
