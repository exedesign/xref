import json

import pytest
from PyQt6 import QtCore, QtWidgets

from xref import web_stream
from xref.items import XRefTextItem


@pytest.fixture
def stream_server(view, qapp):
    web_stream.init_gui_bridge()
    server = web_stream.BoardStreamServer(view)
    yield server
    server.stop()


class FakeChannel:
    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(json.loads(data))


def _web_coords(view, point):
    size = view.viewport().size()
    return point.x() / size.width(), point.y() / size.height()


def test_web_double_click_enters_edit_mode_and_backspace_edits_text(
        view, qapp, stream_server):
    channel = FakeChannel()
    item = XRefTextItem('Editable')
    view.scene.addItem(item)
    center = view.viewport().rect().center()
    item.setPos(view.mapToScene(center))
    point = view.mapFromScene(
        item.mapToScene(item.boundingRect().center()))
    x, y = _web_coords(view, point)

    stream_server._edit_text({'x': x, 'y': y}, channel)
    qapp.processEvents()

    assert item.edit_mode
    assert view.scene.edit_item is item
    assert channel.sent == [{'kind': 'text_edit', 'active': True}]

    stream_server.handler.handle({
        'kind': 'key', 'key': 'Backspace', '_guest': 'web-guest'})
    qapp.processEvents()
    assert item.toPlainText() == 'Editabl'


def test_web_double_click_only_edits_text_items(view, stream_server):
    channel = FakeChannel()
    empty_x, empty_y = _web_coords(view, QtCore.QPoint(0, 0))
    stream_server._edit_text({'x': empty_x, 'y': empty_y}, channel)

    other_item = QtWidgets.QGraphicsRectItem(
        QtCore.QRectF(0, 0, 100, 100))
    other_item.setPos(view.mapToScene(view.viewport().rect().center()))
    view.scene.addItem(other_item)
    point = view.mapFromScene(
        other_item.mapToScene(other_item.boundingRect().center()))
    x, y = _web_coords(view, point)
    stream_server._edit_text({'x': x, 'y': y}, channel)

    assert view.scene.edit_item is None
    assert channel.sent == [
        {'kind': 'text_edit', 'active': False},
        {'kind': 'text_edit', 'active': False},
    ]
