"""End-to-end interaction tests that send real Qt input events through
the view's viewport (like a user would), instead of calling scene
handlers directly."""

import os.path

import pytest
from unittest.mock import patch

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from xref.items import XRefDrawItem, XRefPixmapItem, XRefVideoItem


Mod = Qt.KeyboardModifier
Btn = Qt.MouseButton


@pytest.fixture
def shown_view(view, qapp):
    view.parent.resize(800, 600)
    view.parent.show()
    view.setTransform(QtGui.QTransform())
    qapp.processEvents()
    return view


def add_image(view, x, y, size=100):
    img = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(200, 50, 50))
    item = XRefPixmapItem(img)
    view.scene.addItem(item)
    item.setPos(x, y)
    return item


def empty_spot(view):
    """A scene position inside the visible viewport (so that dragging
    there doesn't trigger the drag-out-of-the-window export)."""

    rect = view.viewport().rect()
    return view.mapToScene(QtCore.QPoint(rect.width() - 30,
                                       rect.height() - 30))
def vpos(view, scene_point):
    return QtCore.QPointF(view.mapFromScene(scene_point))


def send_mouse(view, etype, scene_point, button=Btn.LeftButton,
               buttons=None, mods=Mod.NoModifier):
    local = vpos(view, scene_point)
    glob = QtCore.QPointF(view.viewport().mapToGlobal(local.toPoint()))
    if buttons is None:
        buttons = (Btn.NoButton
                   if etype == QtCore.QEvent.Type.MouseButtonRelease
                   else button)
    event = QtGui.QMouseEvent(etype, local, glob, button, buttons, mods)
    QtWidgets.QApplication.sendEvent(view.viewport(), event)


def drag(view, start, end, mods=Mod.NoModifier, steps=5):
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseButtonPress, start, mods=mods)
    for i in range(1, steps + 1):
        p = start + (end - start) * (i / steps)
        send_mouse(view, T.MouseMove, p, button=Btn.NoButton,
                   buttons=Btn.LeftButton, mods=mods)
    send_mouse(view, T.MouseButtonRelease, end, mods=mods)


def send_key(widget, etype, key, mods=Mod.NoModifier):
    event = QtGui.QKeyEvent(etype, key, mods)
    QtWidgets.QApplication.sendEvent(widget, event)


# -- Links --------------------------------------------------------------

def test_shift_drag_creates_parent_child_link(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    drag(view, QtCore.QPointF(50, 50), QtCore.QPointF(350, 50),
         mods=Mod.ShiftModifier)
    assert view.scene.links == [(parent, child)]
    # Nothing got moved by the link gesture
    assert parent.pos() == QtCore.QPointF(0, 0)
    assert child.pos() == QtCore.QPointF(300, 0)


def test_shift_drag_on_empty_space_removes_links(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    view.scene.add_link(parent, child)
    drag(view, QtCore.QPointF(50, 50), empty_spot(view),
         mods=Mod.ShiftModifier)
    assert view.scene.links == []


def test_links_are_rendered(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    view.scene.add_link(parent, child)
    img = QtGui.QImage(view.viewport().size(),
                       QtGui.QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    painter = QtGui.QPainter(img)
    view.render(painter)
    painter.end()
    # Pixel between both items is link-coloured (blue-ish)
    color = img.pixelColor(vpos(view, QtCore.QPointF(200, 50)).toPoint())
    assert color.blue() > 150 and color.red() < 100


# -- Ctrl+drag group move ---------------------------------------------------

def test_ctrl_drag_parent_moves_children(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    grandchild = add_image(view, 300, 200)
    other = add_image(view, -300, 0)
    view.scene.add_link(parent, child)
    view.scene.add_link(child, grandchild)

    drag(view, QtCore.QPointF(50, 50), QtCore.QPointF(90, 110),
         mods=Mod.ControlModifier)

    assert parent.pos() == QtCore.QPointF(40, 60)
    assert child.pos() == QtCore.QPointF(340, 60)
    assert grandchild.pos() == QtCore.QPointF(340, 260)
    assert other.pos() == QtCore.QPointF(-300, 0)
    assert {parent, child, grandchild} == set(
        view.scene.selectedItems(user_only=True))

    # Single undo step
    view.undo_stack.undo()
    assert parent.pos() == QtCore.QPointF(0, 0)
    assert child.pos() == QtCore.QPointF(300, 0)
    assert grandchild.pos() == QtCore.QPointF(300, 200)


def test_ctrl_drag_child_does_not_move_parent(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    view.scene.add_link(parent, child)
    drag(view, QtCore.QPointF(350, 50), QtCore.QPointF(370, 50),
         mods=Mod.ControlModifier)
    assert child.pos() == QtCore.QPointF(320, 0)
    assert parent.pos() == QtCore.QPointF(0, 0)


def test_plain_drag_moves_only_item(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    view.scene.add_link(parent, child)
    parent.setSelected(True)
    drag(view, QtCore.QPointF(50, 50), QtCore.QPointF(70, 50))
    assert parent.pos() == QtCore.QPointF(20, 0)
    assert child.pos() == QtCore.QPointF(300, 0)


# -- Pen mode ---------------------------------------------------------------

def test_alt_double_tap_toggles_pen_mode(shown_view):
    view = shown_view
    add_image(view, 0, 0)
    T = QtCore.QEvent.Type
    target = view.viewport()
    for _ in range(2):
        send_key(target, T.KeyPress, Qt.Key.Key_Alt, Mod.AltModifier)
        send_key(target, T.KeyRelease, Qt.Key.Key_Alt)
    assert view.scene.draw_mode
    for _ in range(2):
        send_key(target, T.KeyPress, Qt.Key.Key_Alt, Mod.AltModifier)
        send_key(target, T.KeyRelease, Qt.Key.Key_Alt)
    assert not view.scene.draw_mode


def test_alt_single_tap_or_alt_drag_does_not_toggle(shown_view):
    view = shown_view
    add_image(view, 0, 0)
    T = QtCore.QEvent.Type
    target = view.viewport()
    send_key(target, T.KeyPress, Qt.Key.Key_Alt, Mod.AltModifier)
    send_key(target, T.KeyRelease, Qt.Key.Key_Alt)
    assert not view.scene.draw_mode
    # Alt used as modifier (Alt+drag pans) must not count as a tap
    send_key(target, T.KeyPress, Qt.Key.Key_Alt, Mod.AltModifier)
    send_mouse(view, T.MouseButtonPress, QtCore.QPointF(500, 500),
               mods=Mod.AltModifier)
    send_mouse(view, T.MouseButtonRelease, QtCore.QPointF(500, 500),
               mods=Mod.AltModifier)
    send_key(target, T.KeyRelease, Qt.Key.Key_Alt)
    assert not view.scene.draw_mode


def test_pen_draws_only_stroke_without_trail(shown_view):
    view = shown_view
    image = add_image(view, 0, 0, size=300)
    view.on_action_toggle_draw(True)
    T = QtCore.QEvent.Type
    points = [QtCore.QPointF(20, 20), QtCore.QPointF(150, 20),
              QtCore.QPointF(150, 150)]
    send_mouse(view, T.MouseButtonPress, points[0])
    for p in points[1:]:
        send_mouse(view, T.MouseMove, p, button=Btn.NoButton,
                   buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease, points[-1])

    strokes = list(view.scene.items_by_type('draw'))
    assert len(strokes) == 1
    # The underlying image wasn't moved or selected while drawing
    assert image.pos() == QtCore.QPointF(0, 0)
    assert not image.isSelected()
    assert view.scene.draw_mode  # still drawing

    # Render and check that the "inside" of the L-shape (which a filled
    # path would cover) shows the untouched image colour
    img = QtGui.QImage(view.viewport().size(),
                       QtGui.QImage.Format.Format_ARGB32)
    painter = QtGui.QPainter(img)
    view.render(painter)
    painter.end()
    inside = img.pixelColor(vpos(view, QtCore.QPointF(110, 60)).toPoint())
    assert (inside.red(), inside.green(), inside.blue()) == (200, 50, 50)
    on_line = img.pixelColor(vpos(view, QtCore.QPointF(80, 20)).toPoint())
    # The stroke is drawn in the pen colour (default: warm orange)
    assert on_line != inside
    assert on_line.red() > 200

    view.undo_stack.undo()
    assert list(view.scene.items_by_type('draw')) == []


def test_escape_leaves_pen_mode(shown_view):
    view = shown_view
    view.on_action_toggle_draw(True)
    send_key(view, QtCore.QEvent.Type.KeyPress, Qt.Key.Key_Escape)
    assert not view.scene.draw_mode


# -- Video ------------------------------------------------------------------

@pytest.fixture
def videofilename():
    root = os.path.dirname(__file__)
    return os.path.join(root, 'assets', 'test3x3.mp4')


def wait_until(qapp, condition, timeout=3000):
    timer = QtCore.QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout:
        qapp.processEvents()
        QtCore.QThread.msleep(5)
    return condition()


def make_video(view, videofilename, qapp):
    from xref.items import _probe_video
    probe = _probe_video(videofilename)
    item = XRefVideoItem(video_path=videofilename, size=(200, 200),
                        duration=probe['duration'],
                        preview=probe['preview'])
    view.scene.addItem(item)
    item.setPos(0, 0)
    return item, probe


def test_video_probe_gives_first_frame(videofilename, qapp):
    from xref.items import _probe_video
    probe = _probe_video(videofilename)
    assert probe['duration'] == 2000
    assert probe['size'] == (32, 32)
    assert probe['preview'] is not None and not probe['preview'].isNull()


def test_video_is_saved_by_reference(shown_view, videofilename, qapp,
                                     tmp_path):
    from xref.fileio import SQLiteIO
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    item.set_position(1200)
    path = str(tmp_path / 'test.bee')
    io = SQLiteIO(path, view.scene, create_new=True)
    io.write()
    assert io.fetchone('SELECT COUNT(*) FROM sqlar')[0] == 0
    io._close_connection()

    scene2 = view.scene.__class__(view.undo_stack)
    io2 = SQLiteIO(path, scene2)
    io2.read()
    io2._close_connection()
    videos = list(scene2.items_by_type('video'))
    assert len(videos) == 1
    assert videos[0].video_path == videofilename
    assert videos[0]._current_position == 1200
    for video in videos:
        video.release_player()


def test_video_hover_scrub_is_remembered(shown_view, videofilename, qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    assert wait_until(qapp, lambda: item._player is not None)

    # Moving over the right part of the video scrubs to the end
    send_mouse(view, T.MouseMove, QtCore.QPointF(10, 50),
               button=Btn.NoButton, buttons=Btn.NoButton)
    send_mouse(view, T.MouseMove, QtCore.QPointF(190, 50),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert item._hovered
    assert item._display_position > 1500
    # The frame under the pointer is remembered, not just previewed
    assert item._current_position > 1500
    assert wait_until(qapp, lambda: item._player.position() > 1000)

    # Leaving keeps that frame
    send_mouse(view, T.MouseMove, QtCore.QPointF(500, 500),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert not item._hovered
    assert item._display_position == item._current_position
    assert item._display_position > 1500
    # and it is persisted
    assert item.get_extra_save_data()['position'] > 1500
    item.release_player()


def test_video_click_remembers_frame(shown_view, videofilename, qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    assert wait_until(qapp, lambda: item._player is not None)
    # Clicking a quarter into the video remembers that frame
    click = QtCore.QPointF(50, 50)
    send_mouse(view, T.MouseButtonPress, click)
    send_mouse(view, T.MouseButtonRelease, click)
    qapp.processEvents()
    assert 300 <= item._current_position <= 700
    assert item._current_position == item._display_position
    item.release_player()


def test_video_single_click_locks_the_frame_and_the_next_click_browses(
        shown_view, videofilename, qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    assert wait_until(qapp, lambda: item._player is not None)

    middle = QtCore.QPointF(100, 100)
    send_mouse(view, T.MouseButtonPress, middle)
    send_mouse(view, T.MouseButtonRelease, middle)
    qapp.processEvents()
    assert item.is_frame_locked()
    locked = item._current_position
    assert 800 <= locked <= 1200

    # While locked, hovering no longer scrubs through the video
    send_mouse(view, T.MouseMove, QtCore.QPointF(190, 100),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert item._current_position == locked
    assert item._display_position == locked

    # A second single click resumes browsing at the pointer position
    # (not at the very edge, where the item's flip handle sits)
    end = QtCore.QPointF(160, 100)
    send_mouse(view, T.MouseButtonPress, end)
    send_mouse(view, T.MouseButtonRelease, end)
    qapp.processEvents()
    assert not item.is_frame_locked()
    assert item._current_position > 1500
    item.release_player()


def test_video_drag_does_not_lock_the_frame(shown_view, videofilename, qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    assert wait_until(qapp, lambda: item._player is not None)
    start = QtCore.QPointF(100, 100)
    send_mouse(view, T.MouseButtonPress, start)
    send_mouse(view, T.MouseMove, start + QtCore.QPointF(150, 120),
               buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease, start + QtCore.QPointF(150, 120))
    qapp.processEvents()
    assert not item.is_frame_locked()
    item.release_player()


def test_video_remembered_position_survives_reload(shown_view, videofilename,
                                                   qapp, tmp_path):
    from xref.fileio import SQLiteIO
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    item.set_position(1700)
    item.release_player()

    path = str(tmp_path / 'video.bee')
    io = SQLiteIO(path, view.scene, create_new=True)
    io.write()
    io._close_connection()

    scene2 = view.scene.__class__(view.undo_stack)
    io2 = SQLiteIO(path, scene2)
    io2.read()
    io2._close_connection()
    videos = list(scene2.items_by_type('video'))
    assert len(videos) == 1
    assert videos[0]._current_position == 1700
    assert videos[0]._display_position == 1700
    for video in videos:
        video.release_player()


def test_video_controls_play_pause_and_seek(shown_view, videofilename,
                                            qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseMove, QtCore.QPointF(100, 100),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert item._controls_visible()

    play_center = item.mapToScene(item._play_button_rect().center())
    send_mouse(view, T.MouseButtonPress, play_center)
    send_mouse(view, T.MouseButtonRelease, play_center)
    assert item.is_playing
    assert item.pos() == QtCore.QPointF(0, 0)

    send_mouse(view, T.MouseButtonPress, play_center)
    send_mouse(view, T.MouseButtonRelease, play_center)
    assert not item.is_playing

    # Clicking the video body pins the position there (no seek bar)
    seek_point = item.mapToScene(QtCore.QPointF(100, 100))
    send_mouse(view, T.MouseButtonPress, seek_point)
    send_mouse(view, T.MouseButtonRelease, seek_point)
    assert 800 <= item._current_position <= 1200
    assert item.pos() == QtCore.QPointF(0, 0)

    # Pinned position survives leaving the item
    send_mouse(view, T.MouseMove, QtCore.QPointF(600, 500),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert 800 <= item._display_position <= 1200
    item.release_player()

# -- Node linking: shift-drag, menu action --------------------------------

def test_drag_from_link_port_creates_link(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    # Shift+drag from the parent to the child creates the link
    start = parent.pos() + parent.boundingRect().center()
    drag(view, start, QtCore.QPointF(350, 50),
         mods=Qt.KeyboardModifier.ShiftModifier)
    assert view.scene.links == [(parent, child)]
    assert parent.pos() == QtCore.QPointF(0, 0)
    assert child.pos() == QtCore.QPointF(300, 0)


def test_link_action_links_two_selected_items(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    view.scene.clearSelection()
    parent.setSelected(True)
    child.setSelected(True)
    view.on_action_link_items()
    assert view.scene.links == [(parent, child)]


def test_link_does_not_toggle_off_when_repeated(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    start = parent.pos() + parent.boundingRect().center()
    drag(view, start, QtCore.QPointF(350, 50),
         mods=Qt.KeyboardModifier.ShiftModifier)
    assert len(view.scene.links) == 1
    drag(view, start, QtCore.QPointF(350, 50),
         mods=Qt.KeyboardModifier.ShiftModifier)
    assert len(view.scene.links) == 1


def test_unlink_action_removes_links(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 300, 0)
    view.scene.add_link(parent, child)
    parent.setSelected(True)
    view.on_action_unlink_items()
    assert view.scene.links == []


def test_link_cycle_is_refused(shown_view):
    view = shown_view
    a = add_image(view, 0, 0)
    b = add_image(view, 300, 0)
    view.scene.add_link(a, b)
    assert not view.scene.add_link(b, a)
    assert view.scene.links == [(a, b)]


# -- Pen: brush size, colour, smoothing ------------------------------------

def test_pen_uses_configured_colour_and_width(shown_view):
    view = shown_view
    add_image(view, 0, 0, size=300)
    view.scene.set_pen_color(QtGui.QColor(20, 220, 90))
    view.scene.set_pen_width(18)
    view.on_action_toggle_draw(True)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseButtonPress, QtCore.QPointF(20, 20))
    send_mouse(view, T.MouseMove, QtCore.QPointF(120, 20),
               button=Btn.NoButton, buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease, QtCore.QPointF(120, 20))
    stroke = list(view.scene.items_by_type('draw'))[0]
    assert stroke.stroke_color == QtGui.QColor(20, 220, 90)
    # Brush size is stored in item units (constant on screen)
    assert stroke.stroke_width == pytest.approx(18, rel=0.05)


def test_pen_stroke_is_smoothed(shown_view):
    view = shown_view
    add_image(view, 0, 0, size=300)
    view.on_action_toggle_draw(True)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseButtonPress, QtCore.QPointF(20, 20))
    for i in range(1, 30):
        send_mouse(view, T.MouseMove,
                   QtCore.QPointF(20 + i * 5, 20 + (i % 3)),
                   button=Btn.NoButton, buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease, QtCore.QPointF(170, 22))
    stroke = list(view.scene.items_by_type('draw'))[0]
    # Raw points are all kept, but the rendered path uses curves
    assert len(stroke.points) == 30
    path = stroke.path()
    curves = sum(1 for i in range(path.elementCount())
                 if path.elementAt(i).isCurveTo())
    assert curves > 10


def test_pen_width_actions_change_selected_stroke(shown_view):
    view = shown_view
    view.on_action_toggle_draw(True)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseButtonPress, QtCore.QPointF(20, 20))
    send_mouse(view, T.MouseMove, QtCore.QPointF(120, 20),
               button=Btn.NoButton, buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease, QtCore.QPointF(120, 20))
    stroke = list(view.scene.items_by_type('draw'))[0]
    view.on_action_toggle_draw(False)

    stroke.setSelected(True)
    view.on_action_pen_width_huge()
    assert stroke.stroke_width == pytest.approx(30, rel=0.05)
    view.undo_stack.undo()
    assert stroke.stroke_width < 20

    stroke.setSelected(True)
    view.scene.set_pen_color(QtGui.QColor(250, 10, 10))
    assert stroke.stroke_color == QtGui.QColor(250, 10, 10)
    view.undo_stack.undo()
    assert stroke.stroke_color != QtGui.QColor(250, 10, 10)


def test_draw_item_survives_save_load(shown_view, tmp_path):
    from xref.fileio import SQLiteIO
    view = shown_view
    view.scene.set_pen_color(QtGui.QColor(11, 22, 33))
    view.scene.set_pen_width(14)
    view.on_action_toggle_draw(True)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseButtonPress, QtCore.QPointF(20, 20))
    send_mouse(view, T.MouseMove, QtCore.QPointF(120, 90),
               button=Btn.NoButton, buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease, QtCore.QPointF(120, 90))
    view.on_action_toggle_draw(False)

    path = str(tmp_path / 'draw.bee')
    io = SQLiteIO(path, view.scene, create_new=True)
    io.write()
    io._close_connection()
    scene2 = view.scene.__class__(view.undo_stack)
    io2 = SQLiteIO(path, scene2)
    io2.read()
    io2._close_connection()
    strokes = list(scene2.items_by_type('draw'))
    assert len(strokes) == 1
    assert strokes[0].stroke_color == QtGui.QColor(11, 22, 33)
    assert strokes[0].stroke_width == pytest.approx(14, rel=0.05)
    assert len(strokes[0].points) == 2


# -- Video: pinned preview robustness --------------------------------------

def test_video_ignores_stale_frames_after_pinning(shown_view, videofilename,
                                                  qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    item._current_position = 300
    item._display_position = 300
    item.pin_preview()
    assert item._expected_position == 300

    stale = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_ARGB32)
    stale.fill(QtGui.QColor(0, 255, 0))
    fresh = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_ARGB32)
    fresh.fill(QtGui.QColor(255, 0, 0))

    def frame_for(ms):
        from PyQt6.QtMultimedia import QVideoFrame
        frame = QVideoFrame(stale)
        frame.setStartTime(int(ms * 1000))
        return frame

    item._frame = fresh
    item._on_frame_changed(frame_for(1800))   # stale scrub frame
    assert item._frame is fresh
    item._on_frame_changed(frame_for(305))    # the pinned frame
    assert item._frame is not fresh
    item.release_player()


def test_video_frame_survives_hover_cycles(shown_view, videofilename, qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    assert wait_until(qapp, lambda: item._player is not None)

    remembered = []
    for _ in range(3):
        send_mouse(view, T.MouseMove, QtCore.QPointF(120, 100),
                   button=Btn.NoButton, buttons=Btn.NoButton)
        send_mouse(view, T.MouseMove, QtCore.QPointF(600, 500),
                   button=Btn.NoButton, buttons=Btn.NoButton)
        qapp.processEvents()
        # The frame last touched by the pointer is kept between visits
        assert item._display_position == item._current_position
        remembered.append(item._current_position)
    assert len(set(remembered)) == 1
    assert remembered[0] > 0

    # Playing and pausing pins to the paused frame
    item.play()
    qapp.processEvents()
    item.pause()
    qapp.processEvents()
    assert item._current_position == item._display_position
    item.release_player()


def test_link_port_follows_nearest_edge(shown_view):
    view = shown_view
    item = add_image(view, 100, 100, size=200)
    # Pointer left of the item -> port on the left edge
    left = view.scene.link_port_pos(
        item, QtCore.QPointF(0, 200))
    assert left.x() < item.sceneBoundingRect().left()
    assert left.y() == pytest.approx(item.sceneBoundingRect().center().y(),
                                     abs=1)
    # Pointer above the item -> port on the top edge
    top = view.scene.link_port_pos(item, QtCore.QPointF(200, 0))
    assert top.y() < item.sceneBoundingRect().top()
    assert top.x() == pytest.approx(item.sceneBoundingRect().center().x(),
                                    abs=1)
    # Pointer right of the item -> port on the right edge
    right = view.scene.link_port_pos(item, QtCore.QPointF(900, 200))
    assert right.x() > item.sceneBoundingRect().right()

# -- Disconnecting links ---------------------------------------------------

def link_midpoint(view, source, target):
    line = view.scene.link_line(source, target)
    path, _ = view.scene._link_path(line)
    return path.pointAtPercent(0.5)


def test_clicking_a_link_selects_it(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 320, 200)
    view.scene.add_link(parent, child)
    mid = link_midpoint(view, parent, child)
    send_mouse(view, QtCore.QEvent.Type.MouseButtonPress, mid)
    send_mouse(view, QtCore.QEvent.Type.MouseButtonRelease, mid)
    assert view.scene.selected_link == (parent, child)
    # The items themselves are not selected
    assert not parent.isSelected()
    assert not child.isSelected()


def test_delete_removes_selected_link_only(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 320, 200)
    other = add_image(view, 0, 320)
    view.scene.add_link(parent, child)
    view.scene.add_link(parent, other)
    mid = link_midpoint(view, parent, child)
    send_mouse(view, QtCore.QEvent.Type.MouseButtonPress, mid)
    send_mouse(view, QtCore.QEvent.Type.MouseButtonRelease, mid)
    view.on_action_delete_items()
    assert view.scene.links == [(parent, other)]
    # Items are untouched
    assert parent.scene() is view.scene
    assert child.scene() is view.scene
    assert view.scene.selected_link is None


def test_clicking_empty_space_clears_link_selection(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 320, 200)
    view.scene.add_link(parent, child)
    mid = link_midpoint(view, parent, child)
    send_mouse(view, QtCore.QEvent.Type.MouseButtonPress, mid)
    send_mouse(view, QtCore.QEvent.Type.MouseButtonRelease, mid)
    assert view.scene.selected_link is not None
    empty = QtCore.QPointF(700, 550)
    send_mouse(view, QtCore.QEvent.Type.MouseButtonPress, empty)
    send_mouse(view, QtCore.QEvent.Type.MouseButtonRelease, empty)
    assert view.scene.selected_link is None
    assert view.scene.links == [(parent, child)]


def test_escape_clears_link_selection(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 320, 200)
    view.scene.add_link(parent, child)
    view.scene.select_link((parent, child))
    send_key(view, QtCore.QEvent.Type.KeyPress, Qt.Key.Key_Escape)
    assert view.scene.selected_link is None


def test_port_drag_to_empty_space_disconnects(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 320, 0)
    view.scene.add_link(parent, child)
    start = parent.pos() + parent.boundingRect().center()
    drag(view, start, empty_spot(view),
         mods=Qt.KeyboardModifier.ShiftModifier)
    assert view.scene.links == []


def test_links_cannot_be_clicked_while_drawing(shown_view):
    view = shown_view
    parent = add_image(view, 0, 0)
    child = add_image(view, 320, 200)
    view.scene.add_link(parent, child)
    view.on_action_toggle_draw(True)
    mid = link_midpoint(view, parent, child)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseButtonPress, mid)
    send_mouse(view, T.MouseMove, mid + QtCore.QPointF(30, 30),
               button=Btn.NoButton, buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease, mid + QtCore.QPointF(30, 30))
    # In pen mode the click draws instead of selecting the link
    assert view.scene.selected_link is None
    assert len(list(view.scene.items_by_type('draw'))) == 1
    assert view.scene.links == [(parent, child)]

# -- Repaint correctness / dragging media out of the window ---------------

def send_mouse_view(view, etype, view_pos, button=Btn.LeftButton,
                    buttons=None, mods=Mod.NoModifier):
    """Sends a mouse event at a *viewport* position (may be outside)."""
    if buttons is None:
        buttons = (Btn.NoButton
                   if etype == QtCore.QEvent.Type.MouseButtonRelease
                   else button)
    glob = QtCore.QPointF(view.viewport().mapToGlobal(view_pos.toPoint()))
    event = QtGui.QMouseEvent(etype, view_pos, glob, button, buttons, mods)
    QtWidgets.QApplication.sendEvent(view.viewport(), event)


def test_viewport_mode_switches_with_links(shown_view):
    """Links are painted in the foreground; while they exist the view must
    repaint fully, otherwise moving items leaves trails."""
    view = shown_view
    ViewMode = QtWidgets.QGraphicsView.ViewportUpdateMode
    a = add_image(view, 0, 0)
    b = add_image(view, 300, 0)
    assert view.viewportUpdateMode() == ViewMode.BoundingRectViewportUpdate

    view.scene.add_link(a, b)
    assert view.viewportUpdateMode() == ViewMode.FullViewportUpdate

    view.scene.remove_link(a, b)
    assert view.viewportUpdateMode() == ViewMode.BoundingRectViewportUpdate


def test_move_with_links_repaints_whole_viewport(shown_view):
    """A moving linked item must invalidate the previous link curve."""
    view = shown_view
    ViewMode = QtWidgets.QGraphicsView.ViewportUpdateMode
    a = add_image(view, 0, 0)
    b = add_image(view, 300, 0)
    view.scene.add_link(a, b)
    assert view.viewportUpdateMode() == ViewMode.FullViewportUpdate
    # Moving is a normal item move; the mode stays full while linked
    a.setSelected(True)
    view.on_selection_changed()
    drag(view, QtCore.QPointF(50, 50), QtCore.QPointF(150, 200))
    assert view.viewportUpdateMode() == ViewMode.FullViewportUpdate
    assert a.pos() == QtCore.QPointF(100, 150)


def test_build_export_mime_data_image_with_file(view, imgfilename3x3, tmp_path):
    import shutil
    target = tmp_path / 'pic.png'
    shutil.copyfile(imgfilename3x3, target)
    item = add_image(view, 0, 0)
    item.filename = str(target)
    mime = view.build_export_mime_data([item])
    assert mime is not None
    assert [u.toLocalFile() for u in mime.urls()] == [str(target).replace(
        '\\', '/')]


def test_build_export_mime_data_image_without_file(view):
    item = add_image(view, 0, 0)
    item.filename = None
    mime = view.build_export_mime_data([item])
    assert mime is not None
    assert mime.hasImage()
    assert mime.urls() == []


def test_build_export_mime_data_text(view):
    from xref.items import XRefTextItem
    item = XRefTextItem('hello export')
    view.scene.addItem(item)
    mime = view.build_export_mime_data([item])
    assert mime is not None
    assert mime.text() == 'hello export'
    assert mime.urls() == []


def test_build_export_mime_data_video(view, videofilename):
    item = XRefVideoItem(video_path=videofilename, size=(32, 32))
    view.scene.addItem(item)
    try:
        mime = view.build_export_mime_data([item])
        assert mime is not None
        assert [u.toLocalFile() for u in mime.urls()] == [
            videofilename.replace('\\', '/')]
    finally:
        item.release_player()


def test_build_export_mime_data_drawing_is_ignored(view):
    from xref.items import XRefDrawItem
    item = XRefDrawItem()
    item.add_point(QtCore.QPointF(0, 0))
    view.scene.addItem(item)
    assert view.build_export_mime_data([item]) is None


def test_drag_outside_viewport_starts_export(shown_view):
    view = shown_view
    item = add_image(view, 100, 100)
    item.setSelected(True)
    view.on_selection_changed()
    T = QtCore.QEvent.Type
    # Press on the item itself (scene coordinates)
    start = item.scenePos() + item.boundingRect().center()
    with patch.object(view, '_start_export_drag') as start_drag:
        send_mouse(view, T.MouseButtonPress, start)
        # Moving inside the viewport must not export
        send_mouse_view(view, T.MouseMove, QtCore.QPointF(60, 60),
                        button=Btn.NoButton, buttons=Btn.LeftButton)
        assert not start_drag.called
        # Leaving the viewport does
        send_mouse_view(view, T.MouseMove, QtCore.QPointF(-40, 200),
                        button=Btn.NoButton, buttons=Btn.LeftButton)
    assert start_drag.called


def test_drag_outside_keeps_item_in_place(shown_view):
    view = shown_view
    item = add_image(view, 100, 100)
    item.setSelected(True)
    view.on_selection_changed()
    with patch('xref.view.QtGui.QDrag') as drag_cls:
        view._drag_export_items = [item]
        view._drag_export_positions = [QtCore.QPointF(100, 100)]
        # As if the in-scene drag already moved the item
        item.setPos(400, 400)
        view._start_export_drag()
    # Dragging out copies, so the original stays where it was
    assert item.pos() == QtCore.QPointF(100, 100)
    mime = drag_cls.return_value.setMimeData.call_args[0][0]
    assert mime is not None
    assert drag_cls.return_value.exec.called

def test_video_mute_button_toggles(shown_view, videofilename, qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseMove, QtCore.QPointF(100, 100),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert item._controls_visible()
    mute = item.mapToScene(item._mute_button_rect().center())
    assert not item.is_muted
    send_mouse(view, T.MouseButtonPress, mute)
    send_mouse(view, T.MouseButtonRelease, mute)
    assert item.is_muted
    send_mouse(view, T.MouseButtonPress, mute)
    send_mouse(view, T.MouseButtonRelease, mute)
    assert not item.is_muted
    # Clicking a control doesn't move the item
    assert item.pos() == QtCore.QPointF(0, 0)
    item.release_player()


def test_video_volume_slider_click_and_drag(shown_view, videofilename, qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseMove, QtCore.QPointF(100, 100),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    bar = item._volume_slider_rect()
    y = bar.center().y()

    quarter = item.mapToScene(
        QtCore.QPointF(bar.left() + bar.width() * 0.25, y))
    send_mouse(view, T.MouseButtonPress, quarter)
    send_mouse(view, T.MouseButtonRelease, quarter)
    assert 0.15 <= item.volume <= 0.35

    # Drag to the far right -> full volume
    send_mouse(view, T.MouseButtonPress, quarter)
    send_mouse(view, T.MouseMove,
               item.mapToScene(QtCore.QPointF(bar.right() - 1, y)),
               button=Btn.NoButton, buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease,
               item.mapToScene(QtCore.QPointF(bar.right() - 1, y)))
    assert item.volume == pytest.approx(1.0, abs=0.05)
    assert not item.is_muted
    assert item.pos() == QtCore.QPointF(0, 0)
    item.release_player()


def test_video_mute_does_not_disturb_seek(shown_view, videofilename, qapp):
    view = shown_view
    item, _ = make_video(view, videofilename, qapp)
    T = QtCore.QEvent.Type
    send_mouse(view, T.MouseMove, QtCore.QPointF(100, 100),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    before = item._current_position
    mute = item.mapToScene(item._mute_button_rect().center())
    send_mouse(view, T.MouseButtonPress, mute)
    send_mouse(view, T.MouseButtonRelease, mute)
    assert item._current_position == before
    item.release_player()
