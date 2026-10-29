"""Tests for media distribution, host migration and autosave."""

import os

import pytest
from PyQt6 import QtCore, QtGui

from xref import collab
from xref.config import XRefSettings
from xref.items import XRefPixmapItem, XRefTextItem, XRefVideoItem
from xref.scene import XRefGraphicsScene

CODE = 'MEDIACODE42'


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


def items_of(scene, itype):
    return [i for i in scene.items() if getattr(i, 'TYPE', None) == itype]


def hq_image_file(tmp_path, size=(3200, 1400)):
    """An image bigger than the old 2400 px sharing limit."""

    image = QtGui.QImage(size[0], size[1],
                         QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor(30, 90, 160))
    painter = QtGui.QPainter(image)
    painter.setPen(QtGui.QColor(255, 220, 0))
    painter.drawText(40, 80, 'ORIGINAL RESOLUTION')
    painter.end()
    path = tmp_path / 'huge.png'
    image.save(str(path), 'PNG')
    return str(path)


@pytest.fixture
def videofilename():
    root = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(root, 'assets', 'test3x3.mp4'))


@pytest.fixture
def pair(view, qapp):
    scene_a = view.scene
    scene_b = XRefGraphicsScene(view.undo_stack)
    host = collab.CollabSession(scene_a, name='host')
    client = collab.CollabSession(scene_b, name='client')
    assert host.host(port=0, code=CODE)
    assert client.join(CODE, timeout_ms=5000), client.last_error
    assert pump(qapp, lambda: host.peer_count() == 1)
    yield host, client, scene_a, scene_b
    client.leave()
    host.leave()


# -- Media in its original form -------------------------------------------

def test_image_keeps_original_resolution(pair, qapp, tmp_path):
    """Sharing must not downscale (the old limit was 2400 px)."""

    host, client, scene_a, scene_b = pair
    path = hq_image_file(tmp_path)
    image = QtGui.QImage(path)
    item = XRefPixmapItem(image, path)
    scene_a.addItem(item)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b, 'pixmap')) == 1)

    remote = items_of(scene_b, 'pixmap')[0]
    assert remote.pixmap().width() == image.width()
    assert remote.pixmap().height() == image.height()
    # The original bytes arrive unchanged (no re-encoding)
    with open(path, 'rb') as f:
        original = f.read()
    assert remote.original_bytes == original
    assert collab._sha256(remote.original_bytes) == collab._sha256(original)


def test_large_media_is_streamed_in_chunks(pair, qapp, tmp_path,
                                           monkeypatch):
    """Files above the inline limit travel in chunks and are cached."""

    host, client, scene_a, scene_b = pair
    monkeypatch.setattr(collab, 'ASSET_INLINE_LIMIT', 4096)
    path = hq_image_file(tmp_path)
    assert os.path.getsize(path) > 4096

    item = XRefPixmapItem(QtGui.QImage(path), path)
    scene_a.addItem(item)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b, 'pixmap')) == 1)
    remote = items_of(scene_b, 'pixmap')[0]
    sha = collab._sha256(open(path, 'rb').read())
    assert pump(qapp, lambda: collab.find_cached_asset(sha) is not None)
    assert pump(qapp, lambda: remote.pixmap().width() == 3200)
    assert collab.find_cached_asset(sha) is not None


def test_video_is_transferred_and_playable(pair, qapp, videofilename):
    host, client, scene_a, scene_b = pair
    item = XRefVideoItem(video_path=videofilename, size=(32, 32),
                        duration=2000)
    scene_a.addItem(item)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b, 'video')) == 1)

    remote = items_of(scene_b, 'video')[0]
    assert pump(qapp, lambda: remote.has_source_file())
    # The peer plays its own cached copy, not the sender's path
    assert os.path.isfile(remote.video_path)
    assert os.path.normcase(remote.video_path) != os.path.normcase(
        os.path.abspath(videofilename))
    with open(videofilename, 'rb') as f:
        assert remote.video_to_bytes() == f.read()
    remote.release_player()
    item.release_player()


def test_same_media_is_not_transferred_twice(pair, qapp, tmp_path,
                                             monkeypatch):
    host, client, scene_a, scene_b = pair
    monkeypatch.setattr(collab, 'ASSET_INLINE_LIMIT', 4096)
    path = hq_image_file(tmp_path)
    sent = []
    original = collab.CollabSession._send_asset_to

    def spy(self, sock, data, name, kind):
        sent.append(len(data))
        return original(self, sock, data, name, kind)

    monkeypatch.setattr(collab.CollabSession, '_send_asset_to', spy)
    for x in (0, 400):
        item = XRefPixmapItem(QtGui.QImage(path), path)
        scene_a.addItem(item)
        item.setPos(x, 0)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b, 'pixmap')) == 2)
    assert pump(qapp, lambda: all(
        i.pixmap().width() == 3200 for i in items_of(scene_b, 'pixmap')))
    # Both items share one cached asset: it was streamed only once
    assert len(sent) == 1


def test_crop_and_grayscale_are_shared_as_flags(pair, qapp, imgfilename3x3):
    host, client, scene_a, scene_b = pair
    item = XRefPixmapItem(QtGui.QImage(imgfilename3x3), imgfilename3x3)
    scene_a.addItem(item)
    item.grayscale = True
    item.crop = QtCore.QRectF(1, 1, 2, 2)
    host.sync()
    assert pump(qapp, lambda: len(items_of(scene_b, 'pixmap')) == 1)

    remote = items_of(scene_b, 'pixmap')[0]
    assert remote.grayscale is True
    assert remote.crop == QtCore.QRectF(1, 1, 2, 2)
    # The pixels themselves stay uncropped, so both sides can un-crop
    assert remote.pixmap().width() == 3


def test_late_peer_receives_original_media(view, qapp, tmp_path):
    path = hq_image_file(tmp_path)
    host = collab.CollabSession(view.scene, name='host')
    try:
        item = XRefPixmapItem(QtGui.QImage(path), path)
        view.scene.addItem(item)
        assert host.host(port=0, code=CODE)
        scene_b = XRefGraphicsScene(view.undo_stack)
        client = collab.CollabSession(scene_b, name='late')
        try:
            assert client.join(CODE, timeout_ms=6000)
            assert pump(qapp, lambda: len(items_of(scene_b, 'pixmap')) == 1)
            remote = items_of(scene_b, 'pixmap')[0]
            assert pump(qapp, lambda: remote.pixmap().width() == 3200)
        finally:
            client.leave()
    finally:
        host.leave()


# -- Host migration --------------------------------------------------------

def test_graceful_host_stop_ends_the_session(pair, qapp):
    host, client, scene_a, scene_b = pair
    host.leave()
    assert pump(qapp, lambda: client._session_ended)
    assert not client.is_active()
    # Nobody takes over a session that was ended on purpose
    qapp.processEvents()
    QtCore.QThread.msleep(1200)
    qapp.processEvents()
    assert not client.is_host


def test_successor_takes_over_when_host_disappears(view, qapp):
    scene_a = view.scene
    scene_b = XRefGraphicsScene(view.undo_stack)
    scene_c = XRefGraphicsScene(view.undo_stack)
    host = collab.CollabSession(scene_a, name='host')
    first = collab.CollabSession(scene_b, name='first')
    second = collab.CollabSession(scene_c, name='second')
    try:
        assert host.host(port=0, code=CODE)
        assert first.join(CODE, timeout_ms=5000), first.last_error
        assert second.join(CODE, timeout_ms=5000), second.last_error
        assert pump(qapp, lambda: host.peer_count() == 2)

        item = XRefTextItem('board content')
        scene_a.addItem(item)
        host.sync()
        assert pump(qapp, lambda: len(items_of(scene_b, 'text')) == 1)
        assert pump(qapp, lambda: len(items_of(scene_c, 'text')) == 1)

        # The host vanishes without announcing the end of the session
        host.leave(announce=False)
        assert pump(qapp, lambda: first.is_host, timeout=8)
        # The remaining peer finds the new host again
        assert pump(qapp, lambda: second.peer_count() == 1, timeout=10)
        # The board survived the migration
        assert len(items_of(scene_b, 'text')) == 1
        assert len(items_of(scene_c, 'text')) == 1
    finally:
        second.leave()
        first.leave()
        host.leave()


def test_migrated_host_can_still_sync(pair, qapp):
    host, client, scene_a, scene_b = pair
    host.leave(announce=False)
    assert pump(qapp, lambda: client.is_host, timeout=8)

    item = XRefTextItem('after migration')
    scene_b.addItem(item)
    client.sync()

    # A newcomer can join the new host and gets the board
    scene_c = XRefGraphicsScene(None)
    newcomer = collab.CollabSession(scene_c, name='newcomer')
    try:
        assert newcomer.join(CODE, timeout_ms=5000), newcomer.last_error
        assert pump(qapp, lambda: len(items_of(scene_c, 'text')) == 1)
    finally:
        newcomer.leave()


# -- Autosave --------------------------------------------------------------

@pytest.fixture
def autosave_settings(qapp):
    settings = XRefSettings()
    old = {key: settings.value(key) for key in
           ('Save/autosave', 'Save/autosave_interval')}
    yield settings
    for key, value in old.items():
        if value is None:
            settings.remove(key)
        else:
            settings.setValue(key, value)


def test_autosave_is_disabled_by_default(view, autosave_settings):
    assert autosave_settings.valueOrDefault('Save/autosave') is False
    assert view.autosave_enabled() is False
    assert view.on_autosave_tick() is False


def test_autosave_writes_the_file(view, tmp_path, autosave_settings,
                                 monkeypatch):
    autosave_settings.setValue('Save/autosave', True)
    view.filename = str(tmp_path / 'auto.bee')
    view.undo_stack.push(__import__('xref.commands', fromlist=['x'])
                         .InsertItems(view.scene, [XRefTextItem('dirty')]))
    saved = []
    monkeypatch.setattr(view, 'do_save',
                        lambda *a, **kw: saved.append((a, kw)))
    assert view.on_autosave_tick(force=True) is True
    assert saved and saved[0][0][0] == view.filename
    assert saved[0][1]['quiet'] is True


def test_autosave_needs_a_filename(view, autosave_settings, monkeypatch):
    autosave_settings.setValue('Save/autosave', True)
    view.filename = None
    monkeypatch.setattr(view, 'do_save',
                        lambda *a, **kw: pytest.fail('must not save'))
    assert view.on_autosave_tick(force=True) is False


def test_autosave_skips_clean_boards(view, tmp_path, autosave_settings,
                                     monkeypatch):
    autosave_settings.setValue('Save/autosave', True)
    view.filename = str(tmp_path / 'clean.bee')
    view.undo_stack.setClean()
    monkeypatch.setattr(view, 'do_save',
                        lambda *a, **kw: pytest.fail('must not save'))
    assert view.on_autosave_tick(force=True) is False


def test_autosave_interval_setting_is_validated(autosave_settings):
    autosave_settings.setValue('Save/autosave_interval', 5)
    assert autosave_settings.valueOrDefault('Save/autosave_interval') == 5
    autosave_settings.setValue('Save/autosave_interval', 999)
    # Out of range values fall back to the default
    assert autosave_settings.valueOrDefault('Save/autosave_interval') == 2


def test_quiet_save_does_not_show_dialogs(view, monkeypatch):
    from unittest.mock import MagicMock
    warning = MagicMock()
    monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', warning)
    view._saving_quietly = True
    view.on_saving_finished('/tmp/x.bee', ['error'])
    warning.assert_not_called()


from PyQt6 import QtWidgets  # noqa: E402  (used by the test above)
