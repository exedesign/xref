import os.path

import pytest

from PyQt6 import QtCore, QtGui, QtWidgets

from xref.items import XRefVideoItem, item_registry


@pytest.fixture
def videofilename():
    root = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(root, '..', 'assets', 'test3x3.mp4'))


@pytest.fixture
def videoitem(qapp, videofilename):
    item = XRefVideoItem(video_path=videofilename,
                        filename=videofilename,
                        size=(32, 32),
                        duration=2000)
    return item


def test_in_item_registry():
    assert item_registry['video'] == XRefVideoItem


def test_init(videoitem):
    assert videoitem.TYPE == 'video'
    assert videoitem.save_id is None
    assert videoitem.is_image is False
    assert videoitem.is_video is True
    assert videoitem.width == 32
    assert videoitem.height == 32
    assert videoitem.duration == 2000


def test_default_size_when_not_provided(qapp):
    item = XRefVideoItem()
    assert item.size == XRefVideoItem.DEFAULT_SIZE


def test_bounding_rect(videoitem):
    assert videoitem.boundingRect() == QtCore.QRectF(0, 0, 32, 32)


def test_set_video_size(videoitem):
    videoitem.set_video_size((100, 200))
    assert videoitem.size == (100, 200)
    assert videoitem.boundingRect() == QtCore.QRectF(0, 0, 100, 200)


def test_get_extra_save_data(videoitem):
    data = videoitem.get_extra_save_data()
    assert data['filename'] == videoitem.filename
    assert data['size'] == [32, 32]
    assert data['duration'] == 2000
    assert data['video_path'] == videoitem.video_path


def test_get_filename_for_export(videoitem):
    basename = os.path.splitext(os.path.basename(videoitem.filename))[0]
    assert videoitem.get_filename_for_export('mp4') == f'0000-{basename}.mp4'
    videoitem.save_id = 42
    assert videoitem.get_filename_for_export('mp4') == f'0042-{basename}.mp4'


def test_video_to_bytes(videofilename):
    item = XRefVideoItem(video_path=videofilename)
    data = item.video_to_bytes()
    assert data is not None
    assert len(data) > 12
    assert data[4:8] == b'ftyp'


def test_video_from_bytes(videoitem):
    data = b'fakevideo'
    videoitem.video_from_bytes(data)
    assert videoitem.video_bytes == data


def test_create_from_data():
    item = XRefVideoItem.create_from_data(
        item=XRefVideoItem(),
        data={
            'filename': 'test.mp4',
            'size': [64, 48],
            'duration': 5000,
            'opacity': 0.5,
        })
    assert item.filename == 'test.mp4'
    assert item.size == (64, 48)
    assert item.duration == 5000
    assert item.opacity() == 0.5


def test_create_from_data_preserves_video_bytes():
    base = XRefVideoItem()
    base.video_bytes = b'fakevideo'
    item = XRefVideoItem.create_from_data(
        item=base,
        data={'size': [10, 20], 'duration': 100})
    assert item.video_bytes == b'fakevideo'
    assert item.size == (10, 20)
    assert item.duration == 100


def test_create_copy(videoitem):
    videoitem.setPos(10, 20)
    copy = videoitem.create_copy()
    assert copy.filename == videoitem.filename
    assert copy.size == videoitem.size
    assert copy.pos() == videoitem.pos()
    assert copy.save_id is None


def test_paint_placeholder(videoitem, qapp):
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(videoitem)
    img = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_ARGB32)
    painter = QtGui.QPainter(img)
    scene.render(painter)
    painter.end()
    assert not img.isNull()


def test_contains(videoitem):
    assert videoitem.contains(QtCore.QPointF(10, 10))
    assert not videoitem.contains(QtCore.QPointF(100, 100))


def test_play_stops(videoitem, qapp):
    videoitem.play()
    assert videoitem._player is not None
    assert videoitem._playing is True
    # Give the player a moment to start
    QtCore.QCoreApplication.processEvents()
    videoitem.stop_playback()
    assert videoitem._playing is False


def test_scrub_maps_x_to_position(videoitem):
    from unittest.mock import patch
    with patch.object(videoitem, 'seek_preview') as seek:
        videoitem._scrub_to(16)
    seek.assert_called_once()
    assert seek.call_args[0][0] == pytest.approx(0.5 * 1999)


def test_hover_scrub_does_not_change_pinned_position(videoitem):
    from unittest.mock import patch
    videoitem._current_position = 300
    with patch.object(videoitem, '_ensure_player', return_value=False):
        videoitem._scrub_to(30)
    assert videoitem._current_position == 300


def test_saved_position_is_restored():
    item = XRefVideoItem.create_from_data(
        item=XRefVideoItem(), data={'duration': 5000, 'position': 1234})
    assert item._current_position == 1234
    assert item.get_extra_save_data()['position'] == 1234


def test_embedded_bytes_only_without_source(videoitem):
    videoitem.video_bytes = b'data'
    assert videoitem.embedded_video_bytes() is None
    videoitem.video_path = 'does/not/exist.mp4'
    assert videoitem.embedded_video_bytes() == b'data'
def test_controls_layout_play_mute_volume(qapp):
    videoitem = XRefVideoItem(size=(400, 300))
    play = videoitem._play_button_rect()
    mute = videoitem._mute_button_rect()
    volume = videoitem._volume_slider_rect()
    time = videoitem._time_rect()
    # Mute sits directly right of play/pause
    assert mute.left() == pytest.approx(play.right())
    assert mute.width() == pytest.approx(play.width())
    # Volume follows the mute button, the time label sits at the right end
    assert volume.left() > mute.right()
    assert time.right() <= videoitem._controls_rect().right()
    assert all(not r.isEmpty() for r in (play, mute, volume, time))


def test_controls_have_no_seek_bar(qapp):
    """The position is controlled by hovering/clicking the video, so the
    control bar has no seek bar."""

    item = XRefVideoItem(size=(400, 300))
    assert not hasattr(item, '_seek_bar_rect')
    assert not hasattr(item, '_seek_from_bar')


def test_controls_layout_hides_volume_on_small_items(qapp):
    item = XRefVideoItem(size=(90, 80))
    assert not item._mute_button_rect().isEmpty()
    assert item._volume_slider_rect().isEmpty()


def test_volume_and_mute_state(videoitem):
    assert videoitem.volume == 1.0
    assert videoitem.is_muted is False
    videoitem.set_volume(0.25)
    assert videoitem.volume == pytest.approx(0.25)
    videoitem.toggle_mute()
    assert videoitem.is_muted is True
    videoitem.toggle_mute()
    assert videoitem.is_muted is False


def test_turning_volume_up_unmutes(videoitem):
    videoitem.set_volume(0.5)
    videoitem.toggle_mute()
    assert videoitem.is_muted
    videoitem.set_volume(0.8)
    assert not videoitem.is_muted
    assert videoitem.volume == pytest.approx(0.8)


def test_mute_with_zero_volume_restores_level(videoitem):
    videoitem.set_volume(0.0)
    videoitem.toggle_mute()
    assert videoitem.volume == 1.0
    assert not videoitem.is_muted


def test_volume_is_clamped(videoitem):
    videoitem.set_volume(2.5)
    assert videoitem.volume == 1.0
    videoitem.set_volume(-1)
    assert videoitem.volume == 0.0


def test_audio_state_is_applied(videoitem):
    from unittest.mock import MagicMock
    videoitem._audio = MagicMock()
    videoitem.set_volume(0.5)
    videoitem._audio.setVolume.assert_called_with(0.5)
    videoitem._audio.setMuted.assert_called_with(False)
    videoitem.toggle_mute()
    videoitem._audio.setMuted.assert_called_with(True)
    videoitem._audio.setVolume.assert_called_with(0.0)


def test_volume_and_mute_are_saved(videoitem):
    videoitem.set_volume(0.3)
    videoitem.toggle_mute()
    data = videoitem.get_extra_save_data()
    assert data['volume'] == pytest.approx(0.3)
    assert data['muted'] is True
    restored = XRefVideoItem.create_from_data(item=XRefVideoItem(), data=data)
    assert restored.volume == pytest.approx(0.3)
    assert restored.is_muted is True


def test_create_from_data_defaults_for_older_files():
    item = XRefVideoItem.create_from_data(
        item=XRefVideoItem(), data={'duration': 1000})
    assert item.volume == 1.0
    assert item.is_muted is False

def test_time_label_sits_right_of_the_controls(qapp):
    item = XRefVideoItem(size=(400, 300))
    time = item._time_rect()
    volume = item._volume_slider_rect()
    assert not time.isEmpty()
    assert time.left() > volume.right()
    assert time.right() <= item._controls_rect().right()
    # No seek bar between them anymore
    assert item._time_text_width() > 0


def test_time_label_hidden_on_narrow_items(qapp):
    item = XRefVideoItem(size=(160, 100))
    assert item._time_rect().isEmpty()
