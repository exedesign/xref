"""Tests for code-based, encrypted board sharing."""

import time

import pytest
from PyQt6 import QtCore, QtGui

from xref import collab
from xref.items import XRefTextItem
from xref.scene import XRefGraphicsScene

CODE = 'TESTCODE42'


def pump(app, condition=None, timeout=8.0):
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


def items_of(scene, itype='text'):
    return [i for i in scene.items() if getattr(i, 'TYPE', None) == itype]


@pytest.fixture
def pair(view, qapp):
    """A host session on scene A and a joined session on scene B."""

    scene_a = view.scene
    scene_b = XRefGraphicsScene(view.undo_stack)
    host = collab.CollabSession(scene_a, name='host')
    client = collab.CollabSession(scene_b, name='client')
    code = host.host(port=0, code=CODE)
    assert code == collab.format_code(CODE)
    assert client.join(code, timeout_ms=5000), client.last_error
    assert pump(qapp, lambda: host.peer_count() == 1)
    yield host, client, scene_a, scene_b
    client.leave()
    host.leave()


# -- Codes and crypto ------------------------------------------------------

def test_generated_code_uses_the_alphabet():
    for _ in range(20):
        code = collab.generate_code()
        assert len(code) == collab.CODE_LENGTH
        assert all(ch in collab.CODE_ALPHABET for ch in code)


def test_normalize_code_accepts_typing_variants():
    assert collab.normalize_code('k7m4q-9pxe2') == 'K7M4Q9PXE2'
    assert collab.normalize_code(' K7M4Q 9PXE2 ') == 'K7M4Q9PXE2'
    # Look-alike characters are mapped to the alphabet
    assert collab.normalize_code('K7M4Q0PXE1') == 'K7M4QOPXEI'
    assert collab.normalize_code('') is None
    assert collab.normalize_code('---') is None


def test_format_code_groups_in_fives():
    assert collab.format_code('K7M4Q9PXE2') == 'K7M4Q-9PXE2'
    assert collab.format_code('abc') == 'ABC'


def test_keys_differ_per_code():
    first = collab.derive_keys('K7M4Q9PXE2')
    second = collab.derive_keys('K7M4Q9PXE3')
    assert first['enc'] != second['enc']
    assert first['mac'] != second['mac']
    assert collab.discovery_hash(first) != collab.discovery_hash(second)


def test_seal_roundtrip_and_tamper_detection():
    keys = collab.derive_keys(CODE)
    sealed = collab.seal(keys, {'type': 'snapshot', 'items': []})
    assert collab.unseal(keys, sealed) == {'type': 'snapshot', 'items': []}
    # Sealing twice gives different ciphertext (random nonce)
    assert collab.seal(keys, {'a': 1})['d'] != collab.seal(keys, {'a': 1})['d']

    tampered = dict(sealed)
    tampered['d'] = 'AAAA' + sealed['d'][4:]
    assert collab.unseal(keys, tampered) is None

    wrong = collab.derive_keys('WRONGCODE9')
    assert collab.unseal(wrong, sealed) is None

    broken = dict(sealed)
    del broken['m']
    assert collab.unseal(keys, broken) is None


def test_session_keys_are_bound_to_the_handshake():
    keys = collab.derive_keys(CODE)
    first = collab.derive_session_keys(keys, 'c-nonce', 's-nonce')
    second = collab.derive_session_keys(keys, 'c-nonce', 's-other')
    assert first['enc'] != second['enc']
    sealed = collab.seal(first, {'a': 1})
    # Frames from another handshake must not be accepted
    assert collab.unseal(second, sealed) is None


# -- Pairing ---------------------------------------------------------------

def test_share_and_join_by_code(pair, qapp):
    host, client, scene_a, scene_b = pair
    assert host.is_active() and client.is_active()
    assert host.peer_count() == 1
    assert client.session_code == collab.format_code(CODE)
    assert 'code' in host.status.lower()


def test_host_returns_a_code(view, qapp):
    host = collab.CollabSession(view.scene, name='host')
    try:
        code = host.host(port=0)
        assert code
        assert len(collab.normalize_code(code)) == collab.CODE_LENGTH
    finally:
        host.leave()


def test_join_with_wrong_code_is_refused(view, qapp):
    host = collab.CollabSession(view.scene, name='host')
    client = collab.CollabSession(XRefGraphicsScene(view.undo_stack),
                                  name='client')
    try:
        assert host.host(port=0, code=CODE)
        # Discovery only answers to the right code hash, so a wrong code
        # cannot even find the board
        assert client.join('WRONGCODE9', timeout_ms=1200) is False
        assert 'No board found' in client.last_error
        assert host.peer_count() == 0
        assert not client.is_active()
    finally:
        client.leave()
        host.leave()


def test_join_is_refused_when_the_host_declines(view, qapp):
    host = collab.CollabSession(view.scene, name='host')
    client = collab.CollabSession(XRefGraphicsScene(view.undo_stack),
                                  name='client')
    try:
        host.approval_callback = lambda name, address: False
        host.host(port=0, code=CODE)
        assert client.join(collab.format_code(CODE), timeout_ms=3000) is False
        assert 'declined' in client.last_error
        assert host.peer_count() == 0
    finally:
        client.leave()
        host.leave()


def test_approval_callback_receives_the_peer_name(view, qapp):
    seen = []

    def approve(name, address):
        seen.append((name, address))
        return True

    host = collab.CollabSession(view.scene, name='host')
    client = collab.CollabSession(XRefGraphicsScene(view.undo_stack),
                                  name='alice')
    try:
        host.approval_callback = approve
        host.host(port=0, code=CODE)
        assert client.join(CODE, timeout_ms=3000)
        assert pump(qapp, lambda: bool(seen))
        assert seen[0][0] == 'alice'
    finally:
        client.leave()
        host.leave()


def test_failed_attempts_are_limited(view, qapp):
    host = collab.CollabSession(view.scene, name='host')
    try:
        host.host(port=0, code=CODE)
        for _ in range(collab.MAX_FAILED_ATTEMPTS):
            host._record_failure('10.0.0.9')
        assert host._is_locked_out('10.0.0.9')
        assert not host._is_locked_out('10.0.0.10')
    finally:
        host.leave()


def test_poll_timeouts_are_not_reported_as_errors(pair, qapp):
    """waitForReadyRead() emits SocketTimeoutError; that must not end up
    as a connection error (and must not raise)."""

    host, client, scene_a, scene_b = pair
    SocketError = collab.QtNetwork.QAbstractSocket.SocketError
    client.last_error = ''
    client._on_client_error(SocketError.SocketTimeoutError)
    assert client.last_error == ''
    assert client.is_active()


# -- Sync ------------------------------------------------------------------

def test_item_added_on_host_appears_on_client(pair, qapp):
    host, client, scene_a, scene_b = pair
    item = XRefTextItem('hello from host')
    scene_a.addItem(item)
    item.setPos(120, 80)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b)) == 1)
    remote = items_of(scene_b)[0]
    assert remote.toPlainText() == 'hello from host'
    assert remote.pos() == QtCore.QPointF(120, 80)


def test_item_added_on_client_appears_on_host(pair, qapp):
    host, client, scene_a, scene_b = pair
    item = XRefTextItem('from client')
    scene_b.addItem(item)
    client.sync()
    assert pump(qapp, lambda: len(items_of(scene_a)) == 1)
    assert items_of(scene_a)[0].toPlainText() == 'from client'


def test_moving_an_item_syncs(pair, qapp):
    host, client, scene_a, scene_b = pair
    item = XRefTextItem('move me')
    scene_a.addItem(item)
    item.setPos(10, 10)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b)) == 1)

    item.setPos(300, 250)
    host.sync()
    assert pump(qapp, lambda: items_of(scene_b)[0].pos().x() == 300)


def test_removing_an_item_syncs(pair, qapp):
    host, client, scene_a, scene_b = pair
    item = XRefTextItem('bye')
    scene_a.addItem(item)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b)) == 1)

    scene_a.removeItem(item)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b)) == 0)


def test_links_sync(pair, qapp):
    host, client, scene_a, scene_b = pair
    a = XRefTextItem('parent')
    b = XRefTextItem('child')
    for item in (a, b):
        scene_a.addItem(item)
    a.setPos(0, 0)
    b.setPos(200, 0)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b)) == 2)

    scene_a.add_link(a, b)
    host.sync()
    assert pump(qapp, lambda: len(scene_b.active_links()) == 1)


def test_text_edit_syncs(pair, qapp):
    host, client, scene_a, scene_b = pair
    item = XRefTextItem('first')
    scene_a.addItem(item)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b)) == 1)

    item.setPlainText('second')
    host.sync()
    assert pump(qapp, lambda: items_of(scene_b)[0].toPlainText() == 'second')


def test_late_peer_receives_the_existing_board(view, qapp):
    scene_a = view.scene
    host = collab.CollabSession(scene_a, name='host')
    try:
        item = XRefTextItem('already here')
        scene_a.addItem(item)
        item.setPos(50, 60)
        assert host.host(port=0, code=CODE)
        scene_b = XRefGraphicsScene(view.undo_stack)
        client = collab.CollabSession(scene_b, name='late')
        try:
            assert client.join(CODE, timeout_ms=5000)
            assert pump(qapp, lambda: len(items_of(scene_b)) == 1)
            assert items_of(scene_b)[0].toPlainText() == 'already here'
            assert items_of(scene_b)[0].pos() == QtCore.QPointF(50, 60)
        finally:
            client.leave()
    finally:
        host.leave()


def test_join_returns_only_after_the_board_is_there(view, qapp):
    """The board of a host that was already edited must be there when
    join() returns (no half-set-up session)."""

    scene_a = view.scene
    host = collab.CollabSession(scene_a, name='host')
    try:
        code = host.host(port=0, code=CODE)
        item = XRefTextItem('made after hosting')
        scene_a.addItem(item)
        item.setPos(10, 10)
        host.sync()

        scene_b = XRefGraphicsScene(view.undo_stack)
        client = collab.CollabSession(scene_b, name='client')
        try:
            assert client.join(code, timeout_ms=5000)
            # Immediately after joining, without pumping the event loop
            texts = [i.toPlainText() for i in items_of(scene_b)]
            assert texts == ['made after hosting']
        finally:
            client.leave()
    finally:
        host.leave()


def test_client_does_not_sync_before_the_board_arrives(view, qapp):
    scene_a = view.scene
    host = collab.CollabSession(scene_a, name='host')
    try:
        code = host.host(port=0, code=CODE)
        client = collab.CollabSession(XRefGraphicsScene(view.undo_stack),
                                      name='client')
        try:
            assert client.join(code, timeout_ms=5000)
            assert client._got_snapshot
            assert client._timer.isActive()
        finally:
            client.leave()
    finally:
        host.leave()


def test_leaving_stops_updates(pair, qapp):
    host, client, scene_a, scene_b = pair
    client.leave()
    assert not client.is_active()
    item = XRefTextItem('after leave')
    scene_a.addItem(item)
    host.sync()
    time.sleep(0.2)
    qapp.processEvents()
    assert items_of(scene_b) == []


def test_pixmap_is_transferred(pair, qapp):
    from xref.items import XRefPixmapItem
    host, client, scene_a, scene_b = pair
    image = QtGui.QImage(64, 48, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(10, 200, 120))
    item = XRefPixmapItem(image, 'pic.png')
    scene_a.addItem(item)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b, 'pixmap')) == 1)
    remote = items_of(scene_b, 'pixmap')[0]
    assert remote.pixmap().width() == 64
    assert remote.pixmap().height() == 48


# -- Privacy ---------------------------------------------------------------

def test_board_data_is_never_sent_in_plaintext(pair, qapp, monkeypatch):
    host, client, scene_a, scene_b = pair
    captured = []
    original = collab.CollabSession._write

    def spy(sock, message):
        captured.append(repr(message).encode('utf-8'))
        return original(sock, message)

    monkeypatch.setattr(collab.CollabSession, '_write', staticmethod(spy))
    item = XRefTextItem('TOPSECRET-PAYLOAD')
    scene_a.addItem(item)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b)) == 1)

    wire = b''.join(captured)
    assert wire, 'nothing was captured'
    assert b'TOPSECRET-PAYLOAD' not in wire
    assert b'snapshot' not in wire
    # Sanity check: the item really did travel
    assert items_of(scene_b)[0].toPlainText() == 'TOPSECRET-PAYLOAD'


def test_handshake_does_not_contain_the_code(view, qapp, monkeypatch):
    captured = []
    original = collab.CollabSession._write

    def spy(sock, message):
        captured.append(repr(message).encode('utf-8'))
        return original(sock, message)

    monkeypatch.setattr(collab.CollabSession, '_write', staticmethod(spy))
    host = collab.CollabSession(view.scene, name='host')
    client = collab.CollabSession(XRefGraphicsScene(view.undo_stack),
                                  name='client')
    try:
        host.host(port=0, code='SECRETCODE')
        assert client.join('SECRETCODE', timeout_ms=3000)
        wire = b''.join(captured).upper()
        assert b'SECRETCODE' not in wire
        assert b'SECRET' not in wire
    finally:
        client.leave()
        host.leave()
