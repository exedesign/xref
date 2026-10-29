import pytest

from PyQt6 import QtCore, QtGui

from beeref.fileio.media import (
    VIDEO_EXTENSIONS,
    guess_mime_type,
    is_video,
    media_type,
)


def test_guess_mime_type_webp():
    assert guess_mime_type('foo.webp') == 'image/webp'


def test_guess_mime_type_mp4():
    assert guess_mime_type('foo.mp4') == 'video/mp4'


def test_guess_mime_type_m4v():
    assert guess_mime_type('foo.m4v') == 'video/mp4'


def test_media_type_image():
    assert media_type('foo.png') == 'image'


def test_media_type_webp():
    assert media_type('foo.webp') == 'image'


def test_media_type_video():
    assert media_type('foo.mp4') == 'video'
    assert media_type('foo.mkv') == 'video'


def test_media_type_unknown():
    assert media_type('foo.xyz') is None


def test_media_type_qurl(qapp):
    assert media_type(QtCore.QUrl.fromLocalFile('D:/foo.mp4')) == 'video'
    assert media_type(QtCore.QUrl.fromLocalFile('D:/foo.webp')) == 'image'


def test_is_video():
    assert is_video('foo.mp4')
    assert not is_video('foo.png')
    assert not is_video('foo.xyz')


def test_video_extensions_tuple():
    assert '.mp4' in VIDEO_EXTENSIONS
    assert '.webm' in VIDEO_EXTENSIONS
