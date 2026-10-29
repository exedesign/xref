from PyQt6 import QtGui

from xref.assets import XRefAssets


def test_singleton(view):
    assert XRefAssets() is XRefAssets()
    assert XRefAssets().logo is XRefAssets().logo


def test_has_logo(view):
    assert isinstance(XRefAssets().logo, QtGui.QIcon)
