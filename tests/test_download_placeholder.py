"""Tests for the asset download placeholder and web canvas parity."""

import base64

from PyQt6 import QtCore, QtGui

from xref import collab
from xref.config import XRefSettings
from xref.items import XRefPixmapItem


def make_item(view, size=(400, 300)):
    img = QtGui.QImage(60, 45, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(90, 90, 90))
    item = XRefPixmapItem(img, 'pic.png')
    item._width, item._height = size
    view.scene.addItem(item)
    return item


# -- Download placeholder --------------------------------------------------

def test_download_progress_round_trip(view):
    item = make_item(view)
    assert item.download_percent is None
    item.set_download_progress(0)
    assert item.download_percent == 0
    item.set_download_progress(150)  # clamped
    assert item.download_percent == 100
    item.set_download_progress(None)
    assert item.download_percent is None


def test_placeholder_painted_while_downloading(view, qapp):
    from PyQt6 import QtCore
    item = make_item(view)
    item.setPos(50, 50)
    item.set_download_progress(42)
    qapp.processEvents()
    image = QtGui.QImage(500, 400, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    view.setSceneRect(QtCore.QRectF(0, 0, 500, 400))
    view.render(painter, QtCore.QRectF(image.rect()),
                QtCore.QRect(0, 0, 500, 400))
    painter.end()
    found_blue = any(
        image.pixelColor(x, y).blue() > 150
        and image.pixelColor(x, y).blue() > image.pixelColor(x, y).red() + 40
        for x in range(60, 440, 4) for y in range(60, 340, 2))
    assert found_blue


def test_host_marks_pending_items_as_downloading(view, qapp):
    session = collab.CollabSession(view.scene, name='host')
    assert session.host(port=0, code='DLTEST')
    try:
        item = make_item(view)
        sha = 'abc123'
        session._pending_assets[sha] = [item]
        session._handle_asset(None, {'type': 'asset_begin', 'sha': sha,
                                     'size': 1000})
        assert item.download_percent == 0
        chunk = base64.b64encode(b'x' * 500).decode()
        session._handle_asset(None, {'type': 'asset_chunk', 'sha': sha,
                                     'data': chunk})
        assert 0 < item.download_percent < 100
        session._handle_asset(None, {'type': 'asset_end', 'sha': sha,
                                     'meta': {}})
        assert item.download_percent is None
    finally:
        # clear the partial buffer state
        session._asset_buffers.pop('abc123', None)
        session.leave()


# -- Web canvas parity --------------------------------------------------------

def test_snapshot_contains_canvas_settings(view, qapp):
    XRefSettings().setValue('View/grid_style', 'dots')
    XRefSettings().setValue('View/grid_spacing', 75)
    session = collab.CollabSession(view.scene, name='host')
    assert session.host(port=0, code='CANVTEST')
    try:
        snapshot = session.web_snapshot()
        canvas = snapshot.get('canvas')
        assert canvas and canvas['grid']['style'] == 'dots'
        assert canvas['grid']['spacing'] == 75
        assert canvas['colour'].startswith('#')
    finally:
        session.leave()
        XRefSettings().setValue('View/grid_style', 'none')


def test_web_client_has_grid_and_download_code():
    from xref.web_client import CLIENT_HTML
    assert 'asset_begin' in CLIENT_HTML
    assert 'asset_chunk' in CLIENT_HTML
    assert "boardCanvas.grid.style !== 'none'" in CLIENT_HTML
    assert "pct + '%'" in CLIENT_HTML  # download percentage label
