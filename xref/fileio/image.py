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

import logging
import os.path
import tempfile
from urllib.error import URLError
from urllib import parse, request

from PyQt6 import QtCore, QtGui

import exif
from lxml import etree
import plum


logger = logging.getLogger(__name__)


class ImagePreview:

    def __init__(self, image, source_size, source_bytes, source_format):
        self.image = image
        self.source_size = source_size
        self.source_bytes = source_bytes
        self.source_format = source_format


def _read_preview(reader, source_bytes, max_dimension):
    reader.setAutoTransform(True)
    reader_size = reader.size()
    source_size = QtCore.QSize(reader_size)
    transformation = reader.transformation()
    if (transformation
            & QtGui.QImageIOHandler.Transformation.TransformationRotate90):
        source_size.transpose()

    if (max_dimension and not source_size.isEmpty()
            and max(source_size.width(), source_size.height())
            > max_dimension):
        reader.setScaledSize(reader_size.scaled(
            max_dimension, max_dimension,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio))

    source_format = bytes(reader.format()).decode(
        'ascii', errors='ignore').lower()
    image = reader.read()
    if image.isNull():
        logger.info('Could not decode image preview: %s', reader.errorString())
        return ImagePreview(image, source_size, source_bytes, source_format)
    return ImagePreview(image, source_size, source_bytes, source_format)


def load_image_preview(path, max_dimension):
    """Decode a display-sized image while keeping its original bytes."""

    if isinstance(path, str):
        path = os.path.normpath(path)
        if path.startswith(('http://', 'https://')):
            url = path
            local_path = None
        else:
            url = None
            local_path = path
    elif path.isLocalFile():
        local_path = os.path.normpath(path.toLocalFile())
        url = None
    else:
        url = bytes(path.toEncoded()).decode()
        local_path = None

    if local_path is not None:
        try:
            with open(local_path, 'rb') as image_file:
                source_bytes = image_file.read()
        except OSError as error:
            logger.warning('Could not read image %s: %s',
                           local_path, error)
            return ImagePreview(
                QtGui.QImage(), QtCore.QSize(), b'', ''), local_path
        reader = QtGui.QImageReader(local_path)
        preview = _read_preview(reader, source_bytes, max_dimension)
        return preview, local_path

    domain = '.'.join(parse.urlparse(url).netloc.split('.')[-2:])
    if domain == 'pinterest.com':
        try:
            page_data = request.urlopen(url).read()
            root = etree.HTML(page_data)
            image_url = root.xpath('//img')[0].get('src')
            if image_url:
                url = image_url
        except (URLError, IndexError, AttributeError) as error:
            logger.warning('Could not resolve Pinterest image URL: %s',
                           error)
            return ImagePreview(QtGui.QImage(), QtCore.QSize(), b'', ''), url

    try:
        source_bytes = request.urlopen(url).read()
    except URLError as error:
        logger.warning('Could not download image %s: %s', url, error.reason)
        return ImagePreview(QtGui.QImage(), QtCore.QSize(), b'', ''), url

    buffer = QtCore.QBuffer()
    buffer.setData(source_bytes)
    buffer.open(QtCore.QIODevice.OpenModeFlag.ReadOnly)
    reader = QtGui.QImageReader(buffer)
    preview = _read_preview(reader, source_bytes, max_dimension)
    return preview, url


def preview_from_bytes(source_bytes, max_dimension):
    """Decode an embedded image into a display-sized preview."""

    buffer = QtCore.QBuffer()
    buffer.setData(source_bytes)
    buffer.open(QtCore.QIODevice.OpenModeFlag.ReadOnly)
    reader = QtGui.QImageReader(buffer)
    return _read_preview(reader, source_bytes, max_dimension)


def exif_rotated_image(path=None):
    """Returns a QImage that is transformed according to the source's
    orientation EXIF data.
    """

    img = QtGui.QImage(path)
    if img.isNull():
        return img

    with open(path, 'rb') as f:
        try:
            exifimg = exif.Image(f)
        except (plum.exceptions.UnpackError, NotImplementedError):
            logger.exception(f'Exif parser failed on image: {path}')
            return img

    try:
        if 'orientation' in exifimg.list_all():
            orientation = exifimg.orientation
        else:
            return img
    except (NotImplementedError, ValueError):
        logger.exception(f'Exif failed reading orientation of image: {path}')
        return img

    transform = QtGui.QTransform()

    if orientation == exif.Orientation.TOP_RIGHT:
        return img.mirrored(horizontal=True, vertical=False)
    if orientation == exif.Orientation.BOTTOM_RIGHT:
        transform.rotate(180)
        return img.transformed(transform)
    if orientation == exif.Orientation.BOTTOM_LEFT:
        return img.mirrored(horizontal=False, vertical=True)
    if orientation == exif.Orientation.LEFT_TOP:
        transform.rotate(90)
        return img.transformed(transform).mirrored(
            horizontal=True, vertical=False)
    if orientation == exif.Orientation.RIGHT_TOP:
        transform.rotate(90)
        return img.transformed(transform)
    if orientation == exif.Orientation.RIGHT_BOTTOM:
        transform.rotate(270)
        return img.transformed(transform).mirrored(
            horizontal=True, vertical=False)
    if orientation == exif.Orientation.LEFT_BOTTOM:
        transform.rotate(270)
        return img.transformed(transform)

    return img


def load_image(path):
    if isinstance(path, str):
        path = os.path.normpath(path)
        return (exif_rotated_image(path), path)
    if path.isLocalFile():
        path = os.path.normpath(path.toLocalFile())
        return (exif_rotated_image(path), path)

    url = bytes(path.toEncoded()).decode()
    domain = '.'.join(parse.urlparse(url).netloc.split(".")[-2:])
    img = exif_rotated_image()
    if domain == 'pinterest.com':
        try:
            page_data = request.urlopen(url).read()
            root = etree.HTML(page_data)
            url = root.xpath("//img")[0].get('src')
        except Exception as e:
            logger.debug(f'Pinterest image download failed: {e}')
    try:
        imgdata = request.urlopen(url).read()
    except URLError as e:
        logger.debug(f'Downloading image failed: {e.reason}')
    else:
        with tempfile.TemporaryDirectory() as tmp:
            fname = os.path.join(tmp, 'img')
            with open(fname, 'wb') as f:
                f.write(imgdata)
                logger.debug(f'Temporarily saved in: {fname}')
            img = exif_rotated_image(fname)
    return (img, url)
