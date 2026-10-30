"""Tests for the public web tunnel and browser drag & drop."""

import base64

import pytest
from PyQt6 import QtCore, QtGui

from xref import collab
from xref.items import XRefPixmapItem


def make_png_bytes(color=(200, 80, 80)):
    from PyQt6 import QtCore
    img = QtGui.QImage(40, 30, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(*color))
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, 'PNG')
    return bytes(buf.data())


def web_drop_state(filename='dropped.png'):
    """The state a browser sends when a file is dropped onto the canvas."""

    data = make_png_bytes()
    return {
        'type': 'pixmap',
        'x': 120.0, 'y': 80.0,
        'filename': filename,
        'size': [400, 300],
        'asset': {
            'inline': base64.b64encode(data).decode(),
            'meta': {'mime': 'image/png', 'name': filename,
                     'kind': 'image'},
        },
    }


# -- Browser drop -> host item ------------------------------------------------

def test_browser_drop_creates_an_image_on_the_host(view, qapp):
    item = collab.create_item_from_state(web_drop_state())
    assert item is not None
    assert item.filename == 'dropped.png'
    assert item.pixmap().width() == 40


def test_browser_drop_op_flows_through_apply(view, qapp):
    session = collab.CollabSession(view.scene, name='host')
    assert session.host(port=0, code='DROPTEST')
    try:
        state = web_drop_state()
        session.apply_web_message(
            {'type': 'ops', 'ops': [{'op': 'add', 'id': 'webdrop1',
                                    'item': state}]})
        images = [i for i in view.scene.items()
                  if getattr(i, 'filename', '') == 'dropped.png']
        assert len(images) == 1
        assert images[0].pixmap().width() == 40
    finally:
        session.leave()


# -- Tunnel ---------------------------------------------------------------------

def test_tunnel_regex_matches_localhost_run_urls():
    from xref.tunnel import TUNNEL_URL_RE
    line = '6ca028dc157d14.lhr.life tunneled, https://6ca028dc157d14.lhr.life'
    match = TUNNEL_URL_RE.search(line)
    assert match and match.group(1) == 'https://6ca028dc157d14.lhr.life'


def test_tunnel_starts_ssh_with_127_forward(monkeypatch):
    from xref import tunnel

    started = {}

    class FakeProcess:
        def __init__(self, lines):
            self.stdout = iter(line.encode() for line in lines)

        def terminate(self):
            started['terminated'] = True

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kwargs):
        started['forward'] = cmd[2]
        return FakeProcess([
            'welcome to localhost.run',
            'https://1234abcd.lhr.life tunneled with tls termination',
        ])

    monkeypatch.setattr(tunnel.subprocess, 'Popen', fake_popen)
    t = tunnel.SshTunnel(54321)
    url = t.start(timeout=5)
    assert url == 'https://1234abcd.lhr.life'
    # localhost resolves to IPv6 on Windows; the forward must use 127.0.0.1
    assert started['forward'] == '80:127.0.0.1:54321'


def test_tunnel_stop_without_start():
    from xref.tunnel import SshTunnel
    SshTunnel(1234).stop()  # must not raise


# -- Public link ------------------------------------------------------------------

def test_public_link_requires_tunnel(view):
    session = collab.CollabSession(view.scene, name='host')
    assert session.public_web_link() is None
    session.web_tunnel = None
    assert session.public_web_link() is None
