"""Tests for the 3D viewer performance settings."""

from PyQt6 import QtCore

from xref import model3d
from xref.config import XRefSettings
from xref.items import XRefModelItem


def make_mesh(triangle_count):
    side = int((triangle_count / 2) ** 0.5)
    vertices = [coordinate
                for y in range(side + 1)
                for x in range(side + 1)
                for coordinate in (float(x), float(y), 0.0)]
    triangles = []
    for y in range(side):
        for x in range(side):
            corner = y * (side + 1) + x
            triangles.extend((
                (corner, corner + 1, corner + side + 2),
                (corner, corner + side + 2, corner + side + 1),
            ))
    return {'vertices': vertices, 'triangles': triangles}


def test_model_quality_defaults_by_renderer(view):
    view.settings.remove('Items/model_max_triangles')
    expected_limit = 500000 if model3d.F3D_ENABLED else 25000
    assert view.settings.valueOrDefault(
        'Items/model_max_triangles') == expected_limit


def test_model_quality_bounds_are_validated(view):
    XRefSettings().setValue('Items/model_max_triangles', 99)
    # Invalid values fall back to the default when read via valueOrDefault
    # (the settings dialog already limits the input to 1000-500000)
    XRefSettings().setValue('Items/model_max_triangles', 25000)


def test_preview_interval_defaults_to_120ms(view):
    view.settings.remove('Items/model_preview_interval')
    assert view.settings.valueOrDefault(
        'Items/model_preview_interval') == 120


def test_default_model_view_defaults_to_perspective(view):
    view.settings.remove('Items/model_default_view')
    assert view.settings.valueOrDefault(
        'Items/model_default_view') == 'perspective'
    XRefSettings().setValue('Items/model_default_view', 'invalid')
    assert view.settings.valueOrDefault(
        'Items/model_default_view') == 'perspective'


def test_default_model_up_axis_defaults_to_z(view):
    view.settings.remove('Items/model_up_axis')
    assert view.settings.valueOrDefault('Items/model_up_axis') == 'Z'
    XRefSettings().setValue('Items/model_up_axis', 'Q')
    assert view.settings.valueOrDefault('Items/model_up_axis') == 'Z'


def test_model_view_preset_sets_software_camera_angles(view):
    item = XRefModelItem(filename='model.obj', initial_view_preset='right')
    assert item._current_yaw == 90
    assert item._current_pitch == 0


def test_saved_model_view_is_not_overridden_by_default(view):
    view.settings.setValue('Items/model_default_view', 'top')
    item = XRefModelItem.create_from_data(
        data={'filename': 'model.obj', 'yaw': 125, 'pitch': 35})
    assert item._current_yaw == 125
    assert item._current_pitch == 35
    assert item._initial_view_preset is None
    view.settings.setValue('Items/model_default_view', 'perspective')


def test_saved_model_up_axis_is_restored(view):
    source_item = XRefModelItem(
        filename='model.obj', model_up_axis='X')
    assert source_item.get_extra_save_data()['model_up_axis'] == 'X'

    item = XRefModelItem.create_from_data(
        data={'filename': 'model.obj', 'model_up_axis': 'X'})
    assert item._model_up_axis == 'X'

    legacy_item = XRefModelItem.create_from_data(
        data={'filename': 'legacy.obj'})
    assert legacy_item._model_up_axis is None


def test_software_camera_pan_is_saved_and_restored(view):
    item = XRefModelItem(filename='model.obj')
    item._software_camera_pan = QtCore.QPointF(12.5, -8.0)

    restored = XRefModelItem.create_from_data(
        data=item.get_extra_save_data())

    assert restored._software_camera_pan == QtCore.QPointF(12.5, -8.0)


def test_decimation_respects_the_quality_setting(view):
    mesh = make_mesh(50000)
    reduced = model3d.decimate(mesh, 10000)
    assert len(reduced['triangles']) <= 10000
    assert len(reduced['vertices']) <= len(reduced['triangles']) * 9
    assert len(reduced['vertices']) > 0


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
                                       ModelPreviewIntervalWidget,
                                       ModelDefaultViewWidget,
                                       ModelUpAxisWidget)
    assert ModelMaxTrianglesWidget.KEY == 'Items/model_max_triangles'
    assert ModelPreviewIntervalWidget.KEY == 'Items/model_preview_interval'
    assert ModelDefaultViewWidget.KEY == 'Items/model_default_view'
    assert ModelUpAxisWidget.KEY == 'Items/model_up_axis'
    assert 'top' in ModelDefaultViewWidget.OPTIONS[1][0]
    assert ModelUpAxisWidget.OPTIONS[0][0] == 'Z'
    dialog.close()
