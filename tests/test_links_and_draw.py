import os.path

import pytest
from unittest.mock import patch

from PyQt6 import QtCore, QtGui

from xref import commands
from xref.items import XRefDrawItem, XRefPixmapItem, item_registry


@pytest.fixture
def imgfilename3x3():
    root = os.path.dirname(__file__)
    return os.path.join(root, 'assets', 'test3x3.png')


@pytest.fixture
def two_items(view, imgfilename3x3):
    img = QtGui.QImage(imgfilename3x3)
    item1 = XRefPixmapItem(img)
    item2 = XRefPixmapItem(img)
    view.scene.addItem(item1)
    view.scene.addItem(item2)
    item1.setPos(0, 0)
    item2.setPos(100, 100)
    item1.save_id = 1
    item2.save_id = 2
    return item1, item2


# -- Draw item ----------------------------------------------------------

def test_drawitem_in_registry():
    assert item_registry['draw'] == XRefDrawItem


def test_drawitem_add_point(view):
    item = XRefDrawItem()
    view.scene.addItem(item)
    item.add_point(QtCore.QPointF(10, 10))
    item.add_point(QtCore.QPointF(20, 20))
    assert item.path().elementCount() == 2
    rect = item.boundingRect()
    assert rect.contains(QtCore.QRectF(7, 7, 16, 16))


def test_drawitem_save_load_roundtrip(view):
    item = XRefDrawItem()
    item.add_point(QtCore.QPointF(10, 10))
    item.add_point(QtCore.QPointF(20, 20))
    data = item.get_extra_save_data()
    assert len(data['points']) == 2
    copy = XRefDrawItem.create_from_data(data=data)
    assert copy.path().elementCount() == 2
    assert copy.boundingRect() == item.boundingRect()


def test_drawitem_persistence(view, imgfilename3x3, tmp_path):
    img = QtGui.QImage(imgfilename3x3)
    item = XRefDrawItem()
    item.add_point(QtCore.QPointF(10, 10))
    item.add_point(QtCore.QPointF(20, 20))
    view.scene.addItem(item)
    path = str(tmp_path / 'test.bee')
    from xref.fileio import SQLiteIO
    io = SQLiteIO(path, view.scene, create_new=True)
    io.write()
    io._close_connection()
    scene2 = view.scene.__class__(view.undo_stack)
    io2 = SQLiteIO(path, scene2)
    io2.read()
    io2.scene.add_queued_items()
    io2._close_connection()
    draws = list(scene2.items_by_type('draw'))
    assert len(draws) == 1
    assert draws[0].path().elementCount() == 2


# -- Scene links ---------------------------------------------------------

def test_add_remove_link(view, two_items):
    item1, item2 = two_items
    assert view.scene.add_link(item1, item2)
    assert view.scene.links == [(item1, item2)]
    # Adding the same link again is a no-op
    assert not view.scene.add_link(item1, item2)
    # Adding a self-link is a no-op
    assert not view.scene.add_link(item1, item1)
    assert view.scene.remove_link(item1, item2)
    assert view.scene.links == []
    assert not view.scene.remove_link(item1, item2)


def test_linked_children_transitive(view, imgfilename3x3):
    img = QtGui.QImage(imgfilename3x3)
    a = XRefPixmapItem(img)
    b = XRefPixmapItem(img)
    c = XRefPixmapItem(img)
    for i, item in enumerate((a, b, c)):
        view.scene.addItem(item)
        item.setPos(i * 50, 0)
    view.scene.add_link(a, b)
    view.scene.add_link(b, c)
    assert view.scene.linked_children(a) == {b, c}
    # Links point from parent to child: children don't drag parents
    assert view.scene.linked_children(b) == {c}
    assert view.scene.linked_children(c) == set()


def test_links_persistence(view, two_items, tmp_path):
    item1, item2 = two_items
    view.scene.add_link(item1, item2)
    path = str(tmp_path / 'test.bee')
    from xref.fileio import SQLiteIO
    io = SQLiteIO(path, view.scene, create_new=True)
    io.write()
    io._close_connection()

    scene2 = view.scene.__class__(view.undo_stack)
    io2 = SQLiteIO(path, scene2)
    io2.read()
    io2.scene.add_queued_items()
    io2._close_connection()
    items = [i for i in scene2.items() if hasattr(i, 'save_id')]
    assert len(items) == 2
    assert len(scene2.links) == 1
    assert set(items) == {scene2.links[0][0], scene2.links[0][1]}


def make_event(kind, scene_pos,
               button=QtCore.Qt.MouseButton.LeftButton,
               buttons=QtCore.Qt.MouseButton.LeftButton,
               mods=QtCore.Qt.KeyboardModifier.NoModifier):
    # Real scene mouse events are QGraphicsSceneMouseEvent, which this Qt
    # binding does not expose in a constructible form. A QMouseEvent with a
    # shimmed scenePos() is structurally equivalent for the Python-level
    # scene code, and Qt accepts QMouseEvent where a scene event is expected.
    ev = QtGui.QMouseEvent(
        kind, scene_pos, scene_pos, scene_pos, button, buttons, mods)
    ev.scenePos = lambda: scene_pos
    return ev


def test_link_creation_via_shift_drag(view, two_items):
    item1, item2 = two_items
    pos1 = item1.pos() + item1.boundingRect().center()
    pos2 = item2.pos() + item2.boundingRect().center()

    view.scene.mousePressEvent(make_event(
        QtCore.QEvent.Type.MouseButtonPress, pos1,
        mods=QtCore.Qt.KeyboardModifier.ShiftModifier))
    assert view.scene.active_mode == view.scene.LINK_MODE

    view.scene.mouseReleaseEvent(make_event(
        QtCore.QEvent.Type.MouseButtonRelease, pos2,
        buttons=QtCore.Qt.MouseButton.NoButton,
        mods=QtCore.Qt.KeyboardModifier.ShiftModifier))
    assert view.scene.links == [(item1, item2)]

    # Releasing the Shift+drag on empty space removes all links of the
    # source item
    view.scene.mousePressEvent(make_event(
        QtCore.QEvent.Type.MouseButtonPress, pos1,
        mods=QtCore.Qt.KeyboardModifier.ShiftModifier))
    view.scene.mouseReleaseEvent(make_event(
        QtCore.QEvent.Type.MouseButtonRelease,
        pos1 + QtCore.QPointF(200, 200),
        buttons=QtCore.Qt.MouseButton.NoButton,
        mods=QtCore.Qt.KeyboardModifier.ShiftModifier))
    assert view.scene.links == []


def test_ctrl_drag_selects_linked_group(view, two_items):
    item1, item2 = two_items
    view.scene.add_link(item1, item2)
    pos1 = item1.pos() + item1.boundingRect().center()

    view.scene.mousePressEvent(make_event(
        QtCore.QEvent.Type.MouseButtonPress, pos1,
        mods=QtCore.Qt.KeyboardModifier.ControlModifier))
    assert item1.isSelected()
    assert item2.isSelected()


def test_draw_mode_toggle(view):
    assert not view.scene.draw_mode
    view.scene.enter_draw_mode()
    assert view.scene.draw_mode
    view.scene.exit_draw_mode()
    assert not view.scene.draw_mode


def test_draw_mode_draws_stroke(view):
    view.scene.enter_draw_mode()
    view.scene.mousePressEvent(make_event(
        QtCore.QEvent.Type.MouseButtonPress, QtCore.QPointF(10, 10)))
    assert view.scene.active_mode == view.scene.DRAW_MODE

    view.scene.mouseMoveEvent(make_event(
        QtCore.QEvent.Type.MouseMove, QtCore.QPointF(20, 20),
        button=QtCore.Qt.MouseButton.NoButton,
        buttons=QtCore.Qt.MouseButton.NoButton))

    view.scene.mouseReleaseEvent(make_event(
        QtCore.QEvent.Type.MouseButtonRelease, QtCore.QPointF(20, 20),
        buttons=QtCore.Qt.MouseButton.NoButton))

    strokes = list(view.scene.items_by_type('draw'))
    assert len(strokes) == 1
    assert strokes[0].path().elementCount() >= 2
