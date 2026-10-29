"""Tests for the pen shape tools, duplicate and arrange randomly."""

from PyQt6 import QtCore, QtGui, QtWidgets

from xref import commands
from xref.items import XRefDrawItem, XRefPixmapItem


def add_stroke(scene, points):
    item = XRefDrawItem()
    for p in points:
        item.add_point(QtCore.QPointF(*p))
    scene.addItem(item)
    return item


def add_image(view, x, y):
    img = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(200, 50, 50))
    item = XRefPixmapItem(img)
    view.scene.addItem(item)
    item.setPos(x, y)
    return item


# -- Shape items ----------------------------------------------------------

def test_rect_shape_builds_a_rectangle(qapp):
    item = XRefDrawItem(shape='rect')
    item.set_shape_points(QtCore.QPointF(0, 0), QtCore.QPointF(100, 50))
    rect = item.path().boundingRect()
    assert 95 <= rect.width() <= 105
    assert 45 <= rect.height() <= 55


def test_ellipse_shape_builds_an_ellipse(qapp):
    item = XRefDrawItem(shape='ellipse')
    item.set_shape_points(QtCore.QPointF(0, 0), QtCore.QPointF(100, 100))
    rect = item.path().boundingRect()
    assert 95 <= rect.width() <= 105
    assert 95 <= rect.height() <= 105


def test_shift_constrains_to_a_square(qapp):
    item = XRefDrawItem(shape='rect')
    item._constrain_active = True
    item.set_shape_points(QtCore.QPointF(0, 0), QtCore.QPointF(100, 30))
    rect = item.path().boundingRect()
    assert abs(rect.width() - rect.height()) < 1


def test_shapes_survive_save_and_load(qapp):
    item = XRefDrawItem(shape='ellipse', stroke_color=(10, 20, 30))
    item.set_shape_points(QtCore.QPointF(5, 5), QtCore.QPointF(105, 155))
    data = item.get_extra_save_data()
    assert data['shape'] == 'ellipse'
    restored = XRefDrawItem.create_from_data(data=data)
    assert restored._shape == 'ellipse'
    rect = restored.path().boundingRect()
    assert 95 <= rect.width() <= 110
    assert 145 <= rect.height() <= 160


def test_freehand_still_works_without_shape_marker(qapp):
    item = XRefDrawItem()
    for p in ((0, 0), (10, 10), (20, 5)):
        item.add_point(QtCore.QPointF(*p))
    data = item.get_extra_save_data()
    assert 'shape' not in data
    restored = XRefDrawItem.create_from_data(data=data)
    assert restored._shape == XRefDrawItem.SHAPE_FREEHAND
    assert len(restored.points) == 3


def test_shape_create_copy(qapp):
    item = XRefDrawItem(shape='line')
    item.set_shape_points(QtCore.QPointF(0, 0), QtCore.QPointF(80, 40))
    copy = item.create_copy()
    assert copy._shape == 'line'
    assert copy.path().boundingRect() == item.path().boundingRect()


# -- Pen tool selection ---------------------------------------------------

def test_pen_tool_selection_changes_the_scene_tool(view):
    view.on_action_pen_tool_rect(True)
    assert view.scene.draw_shape == 'rect'
    # Picking a tool does not enable pen mode on its own
    assert not view.scene.draw_mode
    view.on_action_pen_tool_ellipse(True)
    assert view.scene.draw_shape == 'ellipse'
    view.on_action_pen_tool_freehand(True)
    assert view.scene.draw_shape == 'freehand'
    # But the shape is used when pen mode is on
    view.on_action_pen_tool_line(True)
    view.on_action_toggle_draw(True)
    assert view.scene.draw_mode
    assert view.scene.draw_shape == 'line'
    view.on_action_toggle_draw(False)


def test_drawing_a_shape_with_the_scene(view):
    scene = view.scene
    scene.draw_shape = 'rect'
    scene.enter_draw_mode()
    scene.draw_start(QtCore.QPointF(10, 10))
    scene.draw_move(QtCore.QPointF(110, 60))
    scene.finish_draw_stroke()
    shapes = [i for i in scene.items() if isinstance(i, XRefDrawItem)]
    assert len(shapes) == 1
    assert shapes[0]._shape == 'rect'
    rect = shapes[0].path().boundingRect()
    assert 95 <= rect.width() <= 105


# -- Duplicate ------------------------------------------------------------

def test_duplicate_copies_selection_with_offset(view):
    item = add_image(view, 100, 100)
    item.setSelected(True)
    before = len(view.scene.items())
    view.on_action_duplicate()
    assert len(view.scene.items()) == before + 1
    images = [i for i in view.scene.items()
              if isinstance(i, XRefPixmapItem)]
    assert len(images) == 2
    # The copy is offset from the original
    positions = sorted(
        (round(i.pos().x()), round(i.pos().y())) for i in images)
    assert positions[1] != positions[0]


def test_duplicate_is_undoable(view):
    item = add_image(view, 100, 100)
    item.setSelected(True)
    before = len(view.scene.items())
    view.on_action_duplicate()
    assert len(view.scene.items()) == before + 1
    view.undo_stack.undo()
    assert len(view.scene.items()) == before


def test_duplicate_requires_a_selection(view):
    before = len(view.scene.items())
    view.on_action_duplicate()
    assert len(view.scene.items()) == before


# -- Arrange randomly -----------------------------------------------------

def test_arrange_randomly_moves_items(view):
    items = [add_image(view, 100 + i * 200, 100) for i in range(4)]
    for item in items:
        item.setSelected(True)
    before = [(i.pos().x(), i.pos().y()) for i in items]
    view.on_action_arrange_randomly()
    after = [(i.pos().x(), i.pos().y()) for i in items]
    assert after != before


def test_arrange_randomly_is_undoable(view):
    items = [add_image(view, 100 + i * 200, 100) for i in range(4)]
    for item in items:
        item.setSelected(True)
    before = [(i.pos().x(), i.pos().y()) for i in items]
    view.on_action_arrange_randomly()
    view.undo_stack.undo()
    after = [(i.pos().x(), i.pos().y()) for i in items]
    for b, a in zip(before, after):
        assert abs(b[0] - a[0]) < 1
        assert abs(b[1] - a[1]) < 1
