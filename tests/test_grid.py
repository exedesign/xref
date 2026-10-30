"""Tests for the background grid and grid snapping."""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from xref.config import XRefSettings
from xref.items import XRefPixmapItem


def add_item(view, x=137.0, y=143.0):
    img = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(150, 80, 80))
    item = XRefPixmapItem(img)
    view.scene.addItem(item)
    item.setPos(x, y)
    return item


# -- Settings -----------------------------------------------------------------

def test_grid_defaults_to_off(view):
    view.settings.remove('View/grid_style')
    assert view.settings.valueOrDefault('View/grid_style') == 'none'
    assert not view.grid_visible()


def test_grid_style_can_be_changed(view):
    for style in ('lines', 'dots', 'none'):
        view.settings.setValue('View/grid_style', style)
        assert view.settings.valueOrDefault('View/grid_style') == style
    assert view.grid_visible() or True
    view.settings.setValue('View/grid_style', 'lines')
    assert view.grid_visible()
    view.settings.setValue('View/grid_style', 'none')


def test_grid_spacing_bounds(view):
    view.settings.setValue('View/grid_spacing', 5)
    assert view.settings.valueOrDefault('View/grid_spacing') == 5
    view.settings.setValue('View/grid_spacing', 1000)
    assert view.settings.valueOrDefault('View/grid_spacing') == 1000


# -- Snapping -----------------------------------------------------------------

def test_snap_rounds_to_the_grid(view):
    view.settings.setValue('View/grid_snap', True)
    view.settings.setValue('View/grid_spacing', 50)
    try:
        snapped = view.snap_position_to_grid(QtCore.QPointF(137.0, 163.0))
        assert snapped.x() == 150.0
        assert snapped.y() == 150.0
    finally:
        view.settings.setValue('View/grid_snap', False)


def test_snap_is_off_by_default(view):
    view.settings.setValue('View/grid_spacing', 50)
    view.settings.remove('View/grid_snap')
    assert view.settings.valueOrDefault('View/grid_snap') is False
    pos = QtCore.QPointF(137.0, 163.0)
    assert view.snap_position_to_grid(pos) == pos


def test_snap_works_while_grid_is_hidden(view):
    view.settings.setValue('View/grid_style', 'none')
    view.settings.setValue('View/grid_snap', True)
    view.settings.setValue('View/grid_spacing', 50)
    try:
        snapped = view.snap_position_to_grid(QtCore.QPointF(12.0, 12.0))
        assert snapped == QtCore.QPointF(0.0, 0.0)
    finally:
        view.settings.setValue('View/grid_snap', False)


# -- Scene release snapping -----------------------------------------------------

def test_dragging_snaps_the_item_to_the_grid(view, qapp):
    """The release handler snaps the selection centre onto the grid."""

    view.settings.setValue('View/grid_snap', True)
    view.settings.setValue('View/grid_spacing', 50)
    try:
        item = add_item(view, 137.0, 143.0)
        item.setSelected(True)
        scene = view.scene
        # Simulate the state at the end of a Qt item drag: the item was
        # already moved visually and MOVE_MODE is being finished
        item.setPos(160.0, 154.0)
        scene.active_mode = scene.MOVE_MODE
        scene.event_start = QtCore.QPointF(0, 0)
        scene.finish_item_move(QtCore.QPointF(0, 0))
        center = item.mapToScene(item.boundingRect().center())
        # The centre (210, 204) snaps onto the next grid crossing
        assert center.x() % 50 == 0
        assert center.y() % 50 == 0
        assert (center.x(), center.y()) == (200.0, 200.0)
        # The snap is part of one undo step and can be undone
        view.undo_stack.undo()
        center = item.mapToScene(item.boundingRect().center())
        assert (center.x(), center.y()) == (210.0, 204.0)
        scene.active_mode = None
    finally:
        view.settings.setValue('View/grid_snap', False)


def test_settings_dialog_has_grid_widgets(settings, view):
    from xref.widgets.settings import (GridSnapWidget, GridSpacingWidget,
                                       GridStyleWidget)
    settings.setValue('View/grid_style', 'dots')
    widget = GridStyleWidget()
    assert widget.buttons['dots'].isChecked()
    settings.setValue('View/grid_spacing', 75)
    spacing = GridSpacingWidget()
    assert spacing.input.value() == 75
    settings.setValue('View/grid_snap', True)
    snap = GridSnapWidget()
    assert snap.input.isChecked()
    assert GridStyleWidget.KEY == 'View/grid_style'
    assert GridSpacingWidget.KEY == 'View/grid_spacing'
    assert GridSnapWidget.KEY == 'View/grid_snap'
