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


def test_title_shows_only_the_file_name_not_the_path(view, qapp):
    item = make_image_item(view, r'C:\Users\MGX\Desktop\my_photo.png')
    view.settings.setValue('Items/show_media_titles', True)
    qapp.processEvents()
    image = QtGui.QImage(400, 300, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    item.paint(painter, None, None)
    painter.end()
    # The short name fits into the band; a full path would be much wider.
    # Measure where drawn pixels end below the image
    last_x = 0
    for y in range(150, 190):
        for x in range(0, 400):
            if image.pixelColor(x, y).lightness() > 40:
                last_x = max(last_x, x)
    assert 10 < last_x < 150  # "my_photo.png" only, not the whole path


def test_video_paints_title_when_enabled(view, qapp):
    video = make_video_item(view)
    view.settings.setValue('Items/show_media_titles', True)
    qapp.processEvents()
    image = QtGui.QImage(400, 300, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    video.paint(painter, None, None)
    painter.end()
    # The band sits right below the 240px tall video
    found = any(image.pixelColor(x, y).lightness() > 40
                for y in range(242, 280) for x in range(0, 320, 2))
    assert found


def test_pdf_paints_title_when_enabled(view, qapp):
    from xref.items import XRefPdfItem
    pdf = XRefPdfItem(filename='doc.pdf')
    view.scene.addItem(pdf)
    view.settings.setValue('Items/show_media_titles', True)
    qapp.processEvents()
    image = QtGui.QImage(700, 950, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    pdf.paint(painter, None, None)
    painter.end()
    # The band sits right below the 900px tall PDF
    found = any(image.pixelColor(x, y).lightness() > 40
                for y in range(902, 945) for x in range(0, 640, 2))
    assert found


def test_titles_off_by_default_paint_nothing_for_video(view, qapp):
    video = make_video_item(view)
    view.settings.setValue('Items/show_media_titles', False)
    qapp.processEvents()
    image = QtGui.QImage(400, 300, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    video.paint(painter, None, None)
    painter.end()
    for y in range(242, 280, 2):
        for x in range(0, 320, 3):
            assert image.pixelColor(x, y).lightness() <= 40
