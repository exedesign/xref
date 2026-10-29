import os

from PyQt6 import QtGui

from xref.assets import XRefAssets


def test_singleton(view):
    assert XRefAssets() is XRefAssets()
    assert XRefAssets().logo is XRefAssets().logo


def test_has_logo(view):
    assert isinstance(XRefAssets().logo, QtGui.QIcon)


def test_logo_has_every_size(view):
    sizes = {s.width() for s in XRefAssets().logo.availableSizes()}
    for size in XRefAssets().ICON_SIZES:
        assert size in sizes


def test_logo_variants(view):
    assets = XRefAssets()
    assert not assets.logo_vertical.isNull()
    assert not assets.logo_horizontal.isNull()
    scaled = assets.logo_pixmap('logo-vertical.png', 180)
    assert scaled.width() == 180
    assert scaled.height() > 180


def test_window_and_packaging_icons_exist(view):
    assets = XRefAssets()
    for name in ('logo.ico', 'logo.icns', 'icon.svg'):
        path = assets.PATH.joinpath(name)
        assert path.is_file(), name
        assert os.path.getsize(str(path)) > 0
