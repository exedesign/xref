"""Tests for the web upload placeholder (aspect ratio + progress)."""

import pytest
from PyQt6 import QtGui

from xref.items import XRefPixmapItem


@pytest.fixture
def stream_server(view, qapp, monkeypatch):
    from xref import web_stream
    server = web_stream.BoardStreamServer(view)
    web_stream.init_gui_bridge()
    # Keep the test hermetic: completing an upload would otherwise
    # run the real media-loading thread
    monkeypatch.setattr(server, '_inject_drop', lambda *a, **k: None)
    yield server
    server.stop()


class FakeChannel:
    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)


def test_upload_placeholder_matches_media_ratio(view, qapp, stream_server):
    ch = FakeChannel()
    stream_server._receive_file(ch, {
        'kind': 'file', 'id': 'up1', 'name': 'photo.png', 'size': 100000,
        'x': 0.5, 'y': 0.5, 'w': 300, 'h': 200})
    qapp.processEvents()

    state = stream_server._files['up1']
    placeholder = state.get('placeholder')
    assert placeholder is not None
    assert placeholder.scene() is view.scene
    rect = placeholder.boundingRect()
    assert abs(rect.width() / rect.height() - 1.5) < 0.05
    assert placeholder.download_percent == 0

    stream_server._binary_chunk(ch, b'up1|' + b'x' * 50000)
    qapp.processEvents()
    assert placeholder.download_percent == 50

    stream_server._receive_file(ch, {'kind': 'file', 'id': 'up1',
                                     'done': True, 'x': 0.5, 'y': 0.5})
    qapp.processEvents()
    assert placeholder.scene() is None


def test_upload_placeholder_square_for_unknown_size(
        view, qapp, stream_server):
    ch = FakeChannel()
    stream_server._receive_file(ch, {
        'kind': 'file', 'id': 'up2', 'name': 'blob.bin', 'size': 100,
        'x': 0.3, 'y': 0.3})
    qapp.processEvents()

    placeholder = stream_server._files['up2']['placeholder']
    rect = placeholder.boundingRect()
    assert abs(rect.width() - rect.height()) < 1

    stream_server._receive_file(ch, {'kind': 'file', 'id': 'up2',
                                     'done': True, 'x': 0.3, 'y': 0.3})
    qapp.processEvents()
    assert placeholder.scene() is None


def test_upload_placeholder_removed_on_write_error(
        view, qapp, stream_server, monkeypatch):
    ch = FakeChannel()
    stream_server._receive_file(ch, {
        'kind': 'file', 'id': 'up3', 'name': 'photo.png', 'size': 10,
        'x': 0.5, 'y': 0.5, 'w': 100, 'h': 50})
    qapp.processEvents()
    placeholder = stream_server._files['up3']['placeholder']
    assert placeholder is not None

    def fail_open(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr('builtins.open', fail_open)

    stream_server._receive_file(ch, {'kind': 'file', 'id': 'up3',
                                     'done': True, 'x': 0.5, 'y': 0.5})
    qapp.processEvents()
    assert placeholder.scene() is None
