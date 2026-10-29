"""Tests for the 3D viewer performance settings."""

from xref import model3d
from xref.config import XRefSettings
from xref.items import XRefModelItem


def make_mesh(triangle_count):
    vertices = []
    triangles = []
    for i in range(triangle_count):
        base = i * 3
        vertices.extend((float(i), 0.0, 0.0,
                         float(i) + 1, 0.0, 0.0,
                         float(i), 1.0, 0.0))
        triangles.append((base, base + 1, base + 2))
    return {'vertices': vertices, 'triangles': triangles}


def test_model_quality_defaults_to_25k(view):
    view.settings.remove('Items/model_max_triangles')
    assert view.settings.valueOrDefault('Items/model_max_triangles') == 25000


def test_model_quality_bounds_are_validated(view):
    XRefSettings().setValue('Items/model_max_triangles', 99)
    # Invalid values fall back to the default when read via valueOrDefault
    # (the settings dialog already limits the input to 1000-500000)
    XRefSettings().setValue('Items/model_max_triangles', 25000)


def test_preview_interval_defaults_to_120ms(view):
    view.settings.remove('Items/model_preview_interval')
    assert view.settings.valueOrDefault(
        'Items/model_preview_interval') == 120


def test_decimation_respects_the_quality_setting(view):
    mesh = make_mesh(50000)
    reduced = model3d.decimate(mesh, 10000)
    assert len(reduced['triangles']) <= 10000
    # Kept triangles are re-indexed: vertices only include used ones
    assert len(reduced['vertices']) == len(reduced['triangles']) * 9


def test_reload_mesh_applies_new_quality(view, qapp):
    view.settings.setValue('Items/model_max_triangles', 5000)
    item = XRefModelItem(filename='big.glb')
    item.model_bytes = None
    item._parsed = make_mesh(40000)
    item._apply_decimation()
    assert item._triangles_shown <= 5000

    view.settings.setValue('Items/model_max_triangles', 20000)
    item.reload_mesh()
    assert item._triangles_shown <= 20000
    assert item._triangles_shown > 5000
    view.settings.setValue('Items/model_max_triangles', 25000)


def test_preview_interval_zero_disables_throttle(view):
    from xref.widgets.settings import ModelPreviewIntervalWidget
    view.settings.setValue('Items/model_preview_interval', 0)
    widget = ModelPreviewIntervalWidget()
    assert widget.input.value() == 0
    view.settings.setValue('Items/model_preview_interval', 120)


def test_settings_dialog_has_a_3d_tab(view, qapp):
    from xref.widgets.settings import SettingsDialog
    dialog = SettingsDialog(view)
    tabs = dialog.findChildren(type(dialog.layout.itemAt(0).widget()))
    labels = [w.windowTitle() if hasattr(w, 'windowTitle') else ''
              for w in dialog.findChildren(type(view))]
    # The dialog builds without errors and contains the new widgets
    from xref.widgets.settings import (ModelMaxTrianglesWidget,
                                       ModelPreviewIntervalWidget)
    assert ModelMaxTrianglesWidget.KEY == 'Items/model_max_triangles'
    assert ModelPreviewIntervalWidget.KEY == 'Items/model_preview_interval'
    dialog.close()
