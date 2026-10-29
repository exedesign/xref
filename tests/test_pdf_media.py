"""Tests for multi-page PDF items (page flipping like video scrubbing)."""

import os

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from xref import collab
from xref.fileio import SQLiteIO
from xref.fileio.media import is_pdf, media_type
from xref.items import XRefPdfItem, _probe_pdf
from xref.scene import XRefGraphicsScene

Mod = Qt.KeyboardModifier
Btn = Qt.MouseButton
PAGES = 6


@pytest.fixture
def pdf_file(tmp_path, qapp):
    """A PDF with six clearly labelled pages.

    A QApplication is needed before QPdfWriter can be used.
    """

    path = str(tmp_path / 'six-pages.pdf')
    writer = QtGui.QPdfWriter(path)
    writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4))
    painter = QtGui.QPainter(writer)
    for page in range(PAGES):
        if page:
            writer.newPage()
        font = painter.font()
        font.setPointSize(64)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(20, 20, 20))
        painter.drawText(120, 300, f'PAGE {page + 1}')
    painter.end()
    return path


@pytest.fixture
def pdf_item(pdf_file, qapp):
    probe = _probe_pdf(pdf_file)
    return XRefPdfItem(
        pdf_path=pdf_file,
        filename=os.path.basename(pdf_file),
        size=probe['size'],
        pages=probe['pages'],
        preview=probe['preview'])


def pump(app, condition=None, timeout=10.0):
    timer = QtCore.QElapsedTimer()
    timer.start()
    while timer.elapsed() < timeout * 1000:
        app.processEvents()
        QtCore.QThread.msleep(5)
        if condition is not None and condition():
            for _ in range(10):
                app.processEvents()
                QtCore.QThread.msleep(5)
            return True
    return condition() if condition is not None else False


def send_mouse(view, etype, scene_point, button=Btn.LeftButton,
               buttons=None, mods=Mod.NoModifier):
    if buttons is None:
        buttons = (Btn.NoButton
                   if etype == QtCore.QEvent.Type.MouseButtonRelease
                   else button)
    local = QtCore.QPointF(view.mapFromScene(scene_point))
    glob = QtCore.QPointF(view.viewport().mapToGlobal(local.toPoint()))
    event = QtGui.QMouseEvent(etype, local, glob, button, buttons, mods)
    QtWidgets.QApplication.sendEvent(view.viewport(), event)


# -- Detecting and probing ------------------------------------------------

def test_pdf_is_recognised_as_media(pdf_file):
    assert media_type(pdf_file) == 'pdf'
    assert is_pdf(pdf_file)
    assert is_pdf('https://example.com/document.pdf')
    assert not is_pdf('photo.png')


def test_probe_returns_pages_size_and_first_page(pdf_file):
    probe = _probe_pdf(pdf_file)
    assert probe['pages'] == PAGES
    assert probe['size'] is not None
    width, height = probe['size']
    assert width == XRefPdfItem.DISPLAY_WIDTH
    assert height > width  # A4 portrait
    assert probe['preview'] is not None
    assert not probe['preview'].isNull()


def test_item_shows_the_first_page_initially(pdf_item):
    assert pdf_item.pages == PAGES
    assert pdf_item.current_page == 0
    assert pdf_item._frame is not None


# -- Page flipping by hovering --------------------------------------------

def hovering_view(view, item):
    view.scene.addItem(item)
    item.setPos(50, 50)
    view.on_action_fit_scene()
    view.scene.clearSelection()
    view.scene.active_mode = None
    QtWidgets.QApplication.processEvents()
    return item


def test_hover_flips_pages_and_remembers_the_last_one(view, pdf_item,
                                                      qapp):
    item = hovering_view(view, pdf_item)
    T = QtCore.QEvent.Type
    mid_y = 50 + item.size()[1] / 2

    send_mouse(view, T.MouseMove, QtCore.QPointF(60, mid_y),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert item.current_page == 0

    half = QtCore.QPointF(50 + item.size()[0] * 0.55, mid_y)
    send_mouse(view, T.MouseMove, half, button=Btn.NoButton,
               buttons=Btn.NoButton)
    qapp.processEvents()
    middle = item.current_page
    assert 2 <= middle <= 3

    end = QtCore.QPointF(50 + item.size()[0] * 0.95, mid_y)
    send_mouse(view, T.MouseMove, end, button=Btn.NoButton,
               buttons=Btn.NoButton)
    qapp.processEvents()
    assert item.current_page == PAGES - 1

    # Leaving the item keeps the page the pointer rested on
    send_mouse(view, T.MouseMove, QtCore.QPointF(900, 700),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert item.current_page == PAGES - 1
    assert item._display_page == PAGES - 1


def test_single_click_locks_the_page_and_the_next_click_browses(
        view, pdf_item, qapp):
    item = hovering_view(view, pdf_item)
    T = QtCore.QEvent.Type
    mid_y = 50 + item.size()[1] / 2
    middle = QtCore.QPointF(50 + item.size()[0] * 0.5, mid_y)

    send_mouse(view, T.MouseButtonPress, middle)
    send_mouse(view, T.MouseButtonRelease, middle)
    qapp.processEvents()
    assert item.is_frame_locked()
    locked = item.current_page
    assert 2 <= locked <= 3

    # While locked, hovering no longer flips through the pages
    send_mouse(view, T.MouseMove,
               QtCore.QPointF(50 + item.size()[0] * 0.95, mid_y),
               button=Btn.NoButton, buttons=Btn.NoButton)
    qapp.processEvents()
    assert item.current_page == locked
    assert item._display_page == locked

    # A second single click resumes browsing at the pointer position
    end = QtCore.QPointF(50 + item.size()[0] * 0.95, mid_y)
    send_mouse(view, T.MouseButtonPress, end)
    send_mouse(view, T.MouseButtonRelease, end)
    qapp.processEvents()
    assert not item.is_frame_locked()
    assert item.current_page == PAGES - 1


def test_dragging_a_pdf_does_not_lock_it(view, pdf_item, qapp):
    item = hovering_view(view, pdf_item)
    T = QtCore.QEvent.Type
    start = QtCore.QPointF(50 + item.size()[0] * 0.5,
                           50 + item.size()[1] * 0.5)
    send_mouse(view, T.MouseButtonPress, start)
    send_mouse(view, T.MouseMove, start + QtCore.QPointF(120, 90),
               buttons=Btn.LeftButton)
    send_mouse(view, T.MouseButtonRelease, start + QtCore.QPointF(120, 90))
    qapp.processEvents()
    assert not item.is_frame_locked()


def test_page_can_be_set_directly_and_is_clamped(pdf_item):
    pdf_item.set_page(3)
    assert pdf_item.current_page == 3
    pdf_item.set_page(999)
    assert pdf_item.current_page == PAGES - 1
    pdf_item.set_page(-5)
    assert pdf_item.current_page == 0


def test_page_is_saved_and_restored(pdf_item, tmp_path, view):
    pdf_item.set_page(4)
    scene = view.scene
    scene.addItem(pdf_item)

    board = str(tmp_path / 'pages.xref')
    store = SQLiteIO(board, scene, create_new=True)
    store.write()
    store._close_connection()

    scene2 = XRefGraphicsScene(None)
    store2 = SQLiteIO(board, scene2)
    store2.read()
    store2._close_connection()
    restored = [i for i in scene2.items()
                if getattr(i, 'TYPE', None) == 'pdf']
    assert len(restored) == 1
    assert restored[0].pages == PAGES
    assert restored[0].current_page == 4
    # The PDF itself is embedded, so the board is self-contained
    assert restored[0].pdf_to_bytes()


def test_inserting_a_pdf_file_creates_a_page_item(view, pdf_file, qapp):
    view.do_insert_images([pdf_file])
    assert pump(qapp, lambda: len([
        i for i in view.scene.items()
        if getattr(i, 'TYPE', None) == 'pdf']) == 1)
    item = [i for i in view.scene.items()
            if getattr(i, 'TYPE', None) == 'pdf'][0]
    assert item.pages == PAGES
    assert item.filename.endswith('.pdf')
    assert item._frame is not None


# -- Sharing ---------------------------------------------------------------

def test_pdf_is_shared_with_original_bytes(view, pdf_item, qapp):
    scene_a = view.scene
    scene_b = XRefGraphicsScene(view.undo_stack)
    host = collab.CollabSession(scene_a, name='host')
    client = collab.CollabSession(scene_b, name='client')
    try:
        assert host.host(port=0, code='PDFCODE123')
        assert client.join('PDFCODE123', timeout_ms=5000), client.last_error
        pdf_item.set_page(2)
        scene_a.addItem(pdf_item)
        host.sync()

        def arrived():
            pdfs = [i for i in scene_b.items()
                    if getattr(i, 'TYPE', None) == 'pdf']
            return bool(pdfs) and pdfs[0].pages == PAGES

        assert pump(qapp, arrived)
        remote = [i for i in scene_b.items()
                  if getattr(i, 'TYPE', None) == 'pdf'][0]
        # Page and bytes travel with the board
        assert remote.current_page == 2
        with open(pdf_item.pdf_path, 'rb') as f:
            assert remote.pdf_to_bytes() == f.read()
    finally:
        client.leave()
        host.leave()
