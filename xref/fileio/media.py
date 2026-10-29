# This file is part of XRef.
#
# XRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# XRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with XRef.  If not, see <https://www.gnu.org/licenses/>.

"""Classifying and loading media files (images and videos)."""

import logging
import mimetypes
import os.path
import posixpath
import tempfile
from urllib import parse, request

from PyQt6 import QtCore

from .image import load_image

logger = logging.getLogger(__name__)

# The video file extensions supported for loading. This is used both for
# classifying files as videos and for the insert-video file dialog.
VIDEO_EXTENSIONS = (
    '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.ogv', '.flv',
    '.wmv', '.mpg', '.mpeg',
)

# Multi-page documents
PDF_EXTENSIONS = ('.pdf',)

# Simple 3D models, rendered in software (see xref/model3d.py)
MODEL3D_EXTENSIONS = ('.obj', '.stl', '.ply', '.fbx')

# mimetypes doesn't recognise some extensions on all platforms; make
# sure we classify them correctly
mimetypes.add_type('image/webp', '.webp')
mimetypes.add_type('video/mp4', '.m4v')
mimetypes.add_type('video/x-flv', '.flv')
mimetypes.add_type('video/mpeg', '.mpg')
mimetypes.add_type('video/mpeg', '.mpeg')
mimetypes.add_type('application/pdf', '.pdf')

# Temp dirs for downloaded media, kept alive until process exit (as they
# are needed while the media items are in use)
_temp_dirs = []


def guess_mime_type(path):
    """Guesses the MIME type for the given file name or URL.

    :param str | QtCore.QUrl path: File name or URL
    :rtype: str | None
    :return: the MIME type, or None if it couldn't be determined
    """

    if isinstance(path, QtCore.QUrl):
        path = bytes(path.toEncoded()).decode()
    return mimetypes.guess_type(str(path))[0]


def _has_video_extension(path):
    if isinstance(path, QtCore.QUrl):
        ext = posixpath.splitext(path.path())[1].lower()
    else:
        ext = posixpath.splitext(str(path))[1].lower()
    return ext in VIDEO_EXTENSIONS


def _has_pdf_extension(path):
    if isinstance(path, QtCore.QUrl):
        ext = posixpath.splitext(path.path())[1].lower()
    else:
        ext = posixpath.splitext(str(path))[1].lower()
    return ext in PDF_EXTENSIONS


def _has_model_extension(path):
    if isinstance(path, QtCore.QUrl):
        path = path.toString()
    ext = os.path.splitext(path)[1].lower()
    return ext in MODEL3D_EXTENSIONS


def media_type(path):
    """Classify a file name or URL by media type.

    :param str | QtCore.QUrl path: File name or URL
    :rtype: str | None
    :return: 'image', 'video' or None
    """

    mime = guess_mime_type(path)
    if _has_pdf_extension(path) or mime == 'application/pdf':
        return 'pdf'    if _has_model_extension(path):
        return 'model'

    if mime and mime.startswith('image/'):
        return 'image'
    if mime and (mime.startswith('video/') or _has_video_extension(path)):
        return 'video'
    return None


def is_pdf(path):
    """Returns True if the given file name or URL refers to a PDF."""

    return media_type(path) == 'pdf'


def is_video(path):
    """Returns True if the given file name or URL refers to a video.

    :param str | QtCore.QUrl path: File name or URL
    :rtype: bool
    """

    return media_type(path) == 'video'


def download_url(url):
    """Downloads the file at the given URL to a temporary directory.

    :param str url: The URL to download
    :rtype: str | None
    :return: the temporary file name, or None on failure
    """

    try:
        data = request.urlopen(url).read()
    except Exception as e:
        logger.debug(f'Downloading {url} failed: {e}')
        return None
    ext = posixpath.splitext(parse.urlparse(url).path)[1]
    if not ext:
        ext = '.media'
    tmp = tempfile.TemporaryDirectory(prefix='xref_')
    path = os.path.join(tmp.name, f'media{ext}')
    with open(path, 'wb') as f:
        f.write(data)
    # Keep the temp dir alive for as long as the media item is in use
    _temp_dirs.append((tmp, path))
    logger.debug(f'Downloaded {url} to {path}')
    return path


def _resolve_path_or_url(path):
    """Normalise a path/URL to a local file name, or extract a URL.

    :rtype: tuple
    :return: (local_path, url) — exactly one of them is None
    """

    if isinstance(path, QtCore.QUrl):
        if path.isLocalFile():
            return os.path.normpath(path.toLocalFile()), None
        return None, bytes(path.toEncoded()).decode()

    path = str(path)
    if parse.urlparse(path).scheme in ('http', 'https'):
        return None, path
    return os.path.normpath(path), None


def load_model(path):
    """Downloads or resolves a 3D model file to a local path."""

    if isinstance(path, QtCore.QUrl):
        if path.isLocalFile():
            return path.toLocalFile()
        url = str(path.toString())
    else:
        url = path
    if url.startswith('http://') or url.startswith('https://'):
        return download_url(url)
    return url if os.path.isfile(url) else None


def load_video(path):
    """Resolve a video file or URL to a local file name.

    :param str | QtCore.QUrl path: File name or URL
    :rtype: str | None
    :return: the local file name, or None if it's not a video or
        downloading failed
    """

    local, url = _resolve_path_or_url(path)
    if url:
        if not is_video(url):
            logger.info(f'Not a video URL: {url}')
            return None
        local = download_url(url)
        if not local:
            return None

    if not is_video(local):
        logger.info(f'Not a video: {local}')
        return None

    return local


def load_pdf(path):
    """Resolve a PDF file or URL to a local file name."""

    local, url = _resolve_path_or_url(path)
    if url:
        if not is_pdf(url):
            logger.info(f'Not a PDF URL: {url}')
            return None
        local = download_url(url)
    if not local or not is_pdf(local):
        logger.info(f'Not a PDF: {local}')
        return None
    return local


def load_media(path):
    """Load any supported media file or URL (image or video).

    :param str | QtCore.QUrl path: File name or URL
    :rtype: tuple | None
    :return: ('image', image, resolved_path) or
             ('video', path, filename) or None on failure
    """

    mt = media_type(path)

    if mt == 'pdf':
        local = load_pdf(path)
        if not local:
            return None
        return ('pdf', local, os.path.basename(local))

    if mt == 'model':
        local = load_model(path)
        if not local:
            return None
        return ('model', local, local)

    if mt == 'video':
        local = load_video(path)
        if not local:
            return None
        return ('video', local, os.path.basename(local))

    if mt == 'image':
        img, resolved = load_image(path)
        if img.isNull():
            logger.info(f'Could not load {path} as image')
            return None
        return ('image', img, resolved)

    # Unknown type: try PDF, then image, then video
    local = load_pdf(path)
    if local:
        return ('pdf', local, os.path.basename(local))
    img, resolved = load_image(path)
    if not img.isNull():
        return ('image', img, resolved)
    local = load_video(path)
    if local:
        return ('video', local, os.path.basename(local))
    logger.info(f'Could not load {path} as PDF, image or video')
    return None
