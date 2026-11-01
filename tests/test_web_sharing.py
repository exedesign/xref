"""Tests for the web sharing bridge (host side, real WebSocket)."""

import asyncio
import json
import urllib.request

import pytest
from PyQt6 import QtGui

from xref.items import XRefPixmapItem

aiohttp = pytest.importorskip('aiohttp')

from xref import collab  # noqa: E402


@pytest.fixture
def host_session(view, qapp):
    img = QtGui.QImage(80, 60, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(100, 150, 220))
    view.scene.addItem(XRefPixmapItem(img, 'blue.png'))
    session = collab.CollabSession(view.scene, name='host')
    assert session.host(port=0, code='WEBTEST1')
    yield session
    session.stop_web_sharing()
    session.leave()


def test_web_link_is_created(host_session):
    link = host_session.start_web_sharing()
    assert link and link.startswith('http://')
    assert '#CODE' in link
    assert host_session.web_link() == link


def test_web_sharing_requires_an_active_session(view):
    session = collab.CollabSession(view.scene, name='host')
    assert session.start_web_sharing() is None


def test_web_page_is_served(host_session):
    link = host_session.start_web_sharing()
    page = urllib.request.urlopen(link.split('#')[0]).read().decode()
    # The WebRTC mirror page is served when aiortc is available,
    # otherwise the ops-based board page
    assert ('XRef Mirror' in page and 'RTCPeerConnection' in page) \
        or ('XRef web board' in page and 'WebSocket' in page)


def test_snapshot_reaches_a_browser_client(host_session, qapp):
    link = host_session.start_web_sharing()
    if getattr(host_session, 'stream_server', None):
        pytest.skip('WebRTC mirror active; ops WS not served')

    async def client():
        base = link.split('#')[0]
        code = link.split('#CODE')[1]
        connector = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(
                trust_env=False, connector=connector) as http:
            async with http.ws_connect(
                    base.replace('http', 'ws') + 'ws?code=' + code) as ws:
                msg = await ws.receive(timeout=5)
                return json.loads(msg.data)

    snapshot = asyncio.run(client())
    assert snapshot['type'] == 'snapshot'
    assert len(snapshot['items']) == 1


def test_wrong_code_is_rejected(host_session):
    link = host_session.start_web_sharing()
    if getattr(host_session, 'stream_server', None):
        pytest.skip('WebRTC mirror active; ops WS not served')

    async def client():
        base = link.split('#')[0]
        connector = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(
                trust_env=False, connector=connector) as http:
            async with http.ws_connect(
                    base.replace('http', 'ws')
                    + 'ws?code=WRONGCODE') as ws:
                msg = await ws.receive(timeout=5)
                return json.loads(msg.data)

    answer = asyncio.run(client())
    assert answer['type'] == 'error'


def test_browser_ops_reach_the_host(host_session, qapp):
    link = host_session.start_web_sharing()
    if getattr(host_session, 'stream_server', None):
        pytest.skip('WebRTC mirror active; ops WS not served')

    async def client():
        base = link.split('#')[0]
        code = link.split('#CODE')[1]
        connector = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(
                trust_env=False, connector=connector) as http:
            async with http.ws_connect(
                    base.replace('http', 'ws') + 'ws?code=' + code) as ws:
                msg = await ws.receive(timeout=5)
                snapshot = json.loads(msg.data)
                item_id = snapshot['items'][0]['id']
                await ws.send_json({'type': 'ops', 'ops': [
                    {'op': 'update', 'id': item_id,
                     'item': {'x': 500.0, 'y': 400.0}}]})
                await asyncio.sleep(0.5)

    asyncio.run(client())
    qapp.processEvents()
    item = [i for i in host_session.scene.items()
            if getattr(i, 'filename', '') == 'blue.png'][0]
    assert abs(item.pos().x() - 500) < 1
    assert abs(item.pos().y() - 400) < 1
