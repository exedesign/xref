"""Tests for the toggleable media titles."""

from PyQt6 import QtCore, QtGui

from xref.items import XRefPixmapItem, XRefVideoItem


def make_image_item(view, filename='photo.png'):
    img = QtGui.QImage(200, 150, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor(120, 120, 120))
    item = XRefPixmapItem(img, filename)
    view.scene.addItem(item)
    item.setPos(100, 100)
    return item


def make_video_item(view):
    item = XRefVideoItem(filename='clip.mp4', size=(320, 240))
    view.scene.addItem(item)
    item.setPos(100, 100)
    return item


def rendered_label_visible(item):
    """Whether the title band would be painted for this item."""

    # paint_media_title returns early when titles are off; instead of
    # rendering, verify the settings gate + geometry directly
    from xref.config import XRefSettings
    return XRefSettings().valueOrDefault('Items/show_media_titles')


def test_titles_are_off_by_default(view):
    view.settings.remove('Items/show_media_titles')
    assert view.settings.valueOrDefault('Items/show_media_titles') is False


def test_setting_can_be_toggled(view):
    view.settings.setValue('Items/show_media_titles', True)
    assert view.settings.valueOrDefault('Items/show_media_titles') is True
    view.settings.setValue('Items/show_media_titles', False)
    assert view.settings.valueOrDefault('Items/show_media_titles') is False


def test_pixmap_paints_title_when_enabled(view, qapp):
    item = make_image_item(view, 'my_photo.png')
    view.settings.setValue('Items/show_media_titles', True)
    qapp.processEvents()
    image = QtGui.QImage(400, 300, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    item.paint(painter, None, None)
    painter.end()
    # The label band is under the image; sample it for non-black pixels
    # (the band and text are drawn over the black background)
    found_text = False
    for y in range(150, 190, 2):
        for x in range(0, 200, 3):
            c = image.pixelColor(x, y)
            if c.lightness() > 40:
                found_text = True
                break
        if found_text:
            break
    assert found_text


def test_pixmap_paints_no_title_when_disabled(view, qapp):
    item = make_image_item(view, 'my_photo.png')
    view.settings.setValue('Items/show_media_titles', False)
    qapp.processEvents()
    image = QtGui.QImage(400, 300, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    item.paint(painter, None, None)
    painter.end()
    # Below the image everything stays black
    for y in range(152, 190, 2):
        for x in range(0, 200, 3):
            assert image.pixelColor(x, y).lightness() <= 40


def test_video_and_pdf_have_the_title_hook(view):
    video = make_video_item(view)
    # The hook is present on all media classes via the mixin
    assert hasattr(video, 'paint_media_title')
    from xref.items import XRefPdfItem
    pdf = XRefPdfItem(filename='doc.pdf')
    view.scene.addItem(pdf)
    assert hasattr(pdf, 'paint_media_title')
