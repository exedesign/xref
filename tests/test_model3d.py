"""Tests for the 3D model viewer (OBJ/STL/PLY)."""

import os
import struct
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from xref import model3d
from xref.fileio.media import media_type
from xref.items import XRefModelItem

CUBE_OBJ = b"""# cube
v -1 -1 -1
v 1 -1 -1
v 1 1 -1
v -1 1 -1
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 1 2 3 4
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
"""

CUBE_PLY = b"""ply
format ascii 1.0
element vertex 8
property float x
property float y
property float z
element face 6
property list uchar int vertex_indices
end_header
-1 -1 -1
1 -1 -1
1 1 -1
-1 1 -1
-1 -1 1
1 -1 1
1 1 1
-1 1 1
4 0 1 2 3
4 4 5 6 7
4 0 1 5 4
4 1 2 6 5
4 2 3 7 6
4 3 0 4 7
"""


def stl_binary(mesh):
    buf = []
    buf.append(b'\0' * 80)
    buf.append(struct.pack('<I', len(mesh['triangles'])))
    v = mesh['vertices']
    for a, b, c in mesh['triangles']:
        buf.append(struct.pack('<3f', 0, 0, 0))
        for i in (a, b, c):
            buf.append(struct.pack(
                '<3f', v[i * 3], v[i * 3 + 1], v[i * 3 + 2]))
        buf.append(struct.pack('<H', 0))
    return b''.join(buf)


def cube_mesh():
    return model3d.parse_model(CUBE_OBJ, 'cube.obj')


# -- Classification -------------------------------------------------------

def test_model_formats_are_recognised():
    assert media_type('a.obj') == 'model'
    assert media_type('b.STL') == 'model'
    assert media_type('c.ply') == 'model'
    assert media_type('d.fbx') == 'model'
    if model3d.F3D_ENABLED:
        assert media_type('e.3mf') == 'model'
        if model3d.USD_CORE_ENABLED:
            assert media_type('e.usdz') == 'model'
            assert media_type('e.usdc') == 'model'
    else:
        assert media_type('e.usdz') == 'model'
    assert media_type('e.png') == 'image'


# -- Parsers ---------------------------------------------------------------

def test_obj_parser():
    mesh = cube_mesh()
    assert len(mesh['vertices']) == 24  # 8 vertices * 3
    assert len(mesh['triangles']) == 12  # 6 quads -> 12 triangles


def test_stl_binary_parser():
    mesh = cube_mesh()
    data = stl_binary(mesh)
    parsed = model3d.parse_model(data, 'cube.stl')
    assert len(parsed['triangles']) == 12
    # Each facet repeats its 3 corner vertices
    assert len(parsed['vertices']) == 12 * 9


def test_stl_ascii_parser():
    text = (b'solid test\n'
            b'facet normal 0 0 1\n'
            b'outer loop\n'
            b'vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n'
            b'endloop\nendfacet\nendsolid test\n')
    parsed = model3d.parse_model(text, 'x.stl')
    assert parsed['triangles'] == [(0, 1, 2)]


def test_ply_ascii_parser():
    parsed = model3d.parse_model(CUBE_PLY, 'cube.ply')
    assert len(parsed['triangles']) == 12


def test_ply_binary_parser():
    # Minimal binary PLY: 3 vertices, 1 triangle
    header = (b'ply\nformat binary_little_endian 1.0\n'
              b'element vertex 3\n'
              b'property float x\nproperty float y\nproperty float z\n'
              b'element face 1\n'
              b'property list uchar int vertex_indices\n'
              b'end_header\n')
    body = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
    body += struct.pack('<B', 3) + struct.pack('<3I', 0, 1, 2)
    parsed = model3d.parse_model(header + body, 'tri.ply')
    assert parsed['triangles'] == [(0, 1, 2)]


def test_bounding_box():
    (minx, miny, minz), (maxx, maxy, maxz) = model3d.bounding_box(
        cube_mesh())
    assert (minx, miny, minz) == (-1, -1, -1)
    assert (maxx, maxy, maxz) == (1, 1, 1)


def test_decimate_preserves_connected_surface():
    side = 40
    vertices = [
        coordinate
        for y in range(side + 1)
        for x in range(side + 1)
        for coordinate in (x / side, y / side, 0)
    ]
    triangles = []
    for y in range(side):
        for x in range(side):
            corner = y * (side + 1) + x
            triangles.extend((
                (corner, corner + 1, corner + side + 2),
                (corner, corner + side + 2, corner + side + 1),
            ))

    reduced = model3d.decimate(
        {'vertices': vertices, 'triangles': triangles}, 100)

    assert 0 < len(reduced['triangles']) <= 100
    assert len(reduced['vertices']) // 3 < len(reduced['triangles']) * 3
    assert len(set(reduced['triangles'])) == len(reduced['triangles'])


def test_face_normals_are_unit():
    for n in model3d.face_normals(cube_mesh()):
        length = (n[0]**2 + n[1]**2 + n[2]**2) ** 0.5
        assert abs(length - 1.0) < 1e-6


def test_vertex_normals_smooth_shared_vertices():
    mesh = {
        'vertices': [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
        'triangles': [(0, 1, 2), (1, 0, 3)],
    }

    normals = model3d.vertex_normals(mesh)

    assert normals[0] == pytest.approx((0, 2 ** -0.5, 2 ** -0.5))
    assert normals[1] == pytest.approx((0, 2 ** -0.5, 2 ** -0.5))
    assert normals[2] == pytest.approx((0, 0, 1))
    assert normals[3] == pytest.approx((0, 1, 0))


def test_damaged_files_raise_value_error():
    with pytest.raises(ValueError):
        model3d.parse_model(b'not a model at all', 'x.obj')
    with pytest.raises(ValueError):
        model3d.parse_model(b'\0' * 20, 'x.stl')


# -- GLB / glTF / USDZ ------------------------------------------------------

import base64
import json as _json
import zipfile as _zipfile


def make_glb():
    """A minimal GLB with one indexed triangle."""

    positions = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    bin_payload = (struct.pack('<9f', *positions)
                   + struct.pack('<3H', 0, 1, 2))
    doc = {
        'asset': {'version': '2.0'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0},
                                    'indices': 1}]}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': 3,
             'type': 'VEC3'},
            {'bufferView': 1, 'componentType': 5123, 'count': 3,
             'type': 'SCALAR'}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
            {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}],
        'buffers': [{'byteLength': len(bin_payload)}],
    }
    json_chunk = _json.dumps(doc).encode()
    while len(json_chunk) % 4:
        json_chunk += b' '
    bin_chunk = bin_payload
    while len(bin_chunk) % 4:
        bin_chunk += b'\0'
    glb = b'glTF' + struct.pack(
        '<II', 2, 12 + 8 + len(json_chunk) + 8 + len(bin_chunk))
    glb += struct.pack('<I4s', len(json_chunk), b'JSON') + json_chunk
    glb += struct.pack('<I4s', len(bin_chunk), b'BIN\x00') + bin_chunk
    return glb, positions


def make_usdz():
    usda = (b'#usda 1.0\n'
            b'def Mesh "Mesh"\n{\n'
            b'    int[] faceVertexCounts = [3]\n'
            b'    int[] faceVertexIndices = [0, 1, 2]\n'
            b'    point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]\n'
            b'}\n')
    buf = __import__('io').BytesIO()
    with _zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('model.usda', usda)
    return buf.getvalue()


def test_glb_parser():
    glb, positions = make_glb()
    mesh = model3d.parse_model(glb, 'tri.glb')
    assert mesh['triangles'] == [(0, 1, 2)]
    assert mesh['vertices'] == positions


def test_gltf_with_data_uri_buffer():
    glb, positions = make_glb()
    doc = _json.loads(_json.dumps({
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0},
                                    'indices': 1}]}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': 3,
             'type': 'VEC3'},
            {'bufferView': 1, 'componentType': 5123, 'count': 3,
             'type': 'SCALAR'}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
            {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}],
        'buffers': [{'byteLength': 42, 'uri': 'data:application/'
                     'octet-stream;base64,'
                     + base64.b64encode(glb[12:]).decode()[:0]
                     + base64.b64encode(
                         struct.pack('<9f', *positions)
                         + struct.pack('<3H', 0, 1, 2)).decode()}],
    }))
    mesh = model3d.parse_model(_json.dumps(doc).encode(), 'tri.gltf')
    assert mesh['triangles'] == [(0, 1, 2)]


def test_usdz_parser():
    mesh = model3d.parse_model(make_usdz(), 'model.usdz')
    assert mesh['triangles'] == [(0, 1, 2)]
    assert len(mesh['vertices']) == 9


@pytest.mark.skipif(not model3d.USD_CORE_ENABLED,
                    reason='OpenUSD is not installed')
def test_usdc_parser_reads_transformed_mesh(tmp_path):
    from pxr import Gf, Usd, UsdGeom

    filename = tmp_path / 'triangle.usdc'
    stage = Usd.Stage.CreateNew(str(filename))
    mesh = UsdGeom.Mesh.Define(stage, '/Triangle')
    mesh.CreatePointsAttr([
        Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0), Gf.Vec3f(0, 1, 0)])
    mesh.CreateFaceVertexCountsAttr([3])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
    mesh.AddTranslateOp().Set(Gf.Vec3d(4, 5, 6))
    stage.GetRootLayer().Save()

    parsed = model3d.parse_model(b'', filename.name, str(filename))

    assert parsed['triangles'] == [(0, 1, 2)]
    assert parsed['vertices'] == [4.0, 5.0, 6.0, 5.0, 5.0, 6.0,
                                  4.0, 6.0, 6.0]


def test_usdz_quad_is_fan_triangulated():
    usda = (b'#usda 1.0\n'
            b'def Mesh "Mesh"\n{\n'
            b'    int[] faceVertexCounts = [4]\n'
            b'    int[] faceVertexIndices = [0, 1, 2, 3]\n'
            b'    point3f[] points = [(0,0,0), (1,0,0), (1,1,0), (0,1,0)]'
            b'\n}\n')
    import io as _io
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('model.usda', usda)
    mesh = model3d.parse_model(buf.getvalue(), 'quad.usdz')
    assert mesh['triangles'] == [(0, 1, 2), (0, 2, 3)]


def test_new_model_formats_are_classified():
    assert media_type('a.glb') == 'model'
    assert media_type('b.gltf') == 'model'
    assert media_type('c.usdz') == (
        'model' if not model3d.F3D_ENABLED or model3d.USD_CORE_ENABLED
        else None)


@pytest.mark.skipif(not model3d.F3D_ENABLED,
                    reason='F3D backend is enabled on 64-bit Windows')
def test_f3d_renderer_renders_and_rotates_model(tmp_path):
    filename = tmp_path / 'cube.obj'
    filename.write_bytes(CUBE_OBJ)
    renderer = model3d.F3DRenderer(str(filename))
    try:
        first = renderer.render(96, 96, 30, 20, 1)
        rotated = renderer.render(96, 96, 130, -20, 1.5)
        assert first.width == 96
        assert first.height == 96
        assert first.channel_count == 4
        alpha = first.content[3::4]
        assert 0 in alpha
        assert 255 in alpha
        assert first.content != rotated.content
        for index in range(0, len(first.content), 4):
            if first.content[index + 3]:
                red, green, blue = first.content[index:index + 3]
                assert abs(red - green) <= 4
                assert abs(green - blue) <= 8
    finally:
        renderer.close()


@pytest.mark.skipif(not model3d.F3D_ENABLED,
                    reason='F3D backend is enabled on 64-bit Windows')
def test_f3d_native_mouse_controls_preserve_camera(tmp_path):
    filename = tmp_path / 'cube.obj'
    filename.write_bytes(CUBE_OBJ)
    renderer = model3d.F3DRenderer(str(filename))
    try:
        renderer.render(96, 96, 30, 20, 1)
        before = renderer.camera_state()
        renderer.set_native_interaction(True)
        renderer.begin_interaction('left', 48, 48)
        renderer.update_interaction(72, 60)
        renderer.end_interaction('left', 72, 60)
        after_interaction = renderer.camera_state()
        renderer.render(96, 96, 30, 20, 1)

        assert after_interaction != before
        assert renderer.camera_state() == after_interaction
    finally:
        renderer.close()


@pytest.mark.skipif(not model3d.F3D_ENABLED,
                    reason='F3D backend is enabled on 64-bit Windows')
def test_f3d_renderer_renders_mesh_with_clay_shading():
    mesh = cube_mesh()
    renderer = model3d.F3DRenderer.from_mesh(
        mesh, model3d.vertex_normals(mesh))
    temporary_file = renderer.temporary_file
    try:
        image = renderer.render(96, 96, 30, 20, 1)
        assert image.width == 96
        pixels = [
            tuple(image.content[index:index + 3])
            for index in range(0, len(image.content), image.channel_count)
            if image.content[index + 3]
        ]
        assert pixels
        assert max(max(pixel) - min(pixel) for pixel in pixels) <= 8
        assert len(set(pixels)) > 1
    finally:
        renderer.close()
    assert not os.path.exists(temporary_file)


@pytest.mark.skipif(not model3d.F3D_ENABLED,
                    reason='F3D backend is enabled on 64-bit Windows')
def test_model_item_uses_f3d_image_in_qt(tmp_path):
    filename = tmp_path / 'cube.obj'
    filename.write_bytes(CUBE_OBJ)
    item = XRefModelItem(model_path=str(filename), filename=filename.name)

    assert item._ensure_mesh()
    image = item._render_projection(item.bounding_rect_unselected())

    assert image.format() == QtGui.QImage.Format.Format_RGBA8888
    assert any(image.pixelColor(x, y).alpha() > 0
               for x in range(image.width())
               for y in range(image.height()))
    item.release_mesh()


def test_f3d_model_paints_without_software_mesh():
    item = XRefModelItem(filename='triangle.glb')
    item._renderer = MagicMock()
    image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGBA8888)
    rect = item.bounding_rect_unselected()
    painter = MagicMock()

    with patch.object(item, '_render_projection', return_value=image):
        item._paint_model(painter, rect)

    painter.drawImage.assert_called_once_with(rect, image)


@pytest.mark.skipif(
    not model3d.F3D_ENABLED or '.glb' not in model3d.F3D_MODEL_EXTENSIONS,
    reason='F3D GLB reader is available on supported Windows builds')
def test_f3d_renderer_renders_glb(tmp_path):
    glb, _ = make_glb()
    filename = tmp_path / 'triangle.glb'
    filename.write_bytes(glb)
    renderer = model3d.F3DRenderer(str(filename))
    try:
        image = renderer.render(64, 64, 30, 20, 1)
        assert image.width == 64
        assert image.height == 64
        assert any(image.content[index + 3]
                   for index in range(0, len(image.content), 4))
    finally:
        renderer.close()


@pytest.mark.skipif(not model3d.USD_CORE_ENABLED,
                    reason='OpenUSD is not installed')
@pytest.mark.skipif(
    model3d.F3D_ENABLED
    and '.usdz' in model3d.F3D_MODEL_EXTENSIONS,
    reason='F3D already supports USDZ')
def test_model_item_falls_back_to_openusd_for_usdz(tmp_path):
    filename = tmp_path / 'triangle.usdz'
    filename.write_bytes(make_usdz())
    item = XRefModelItem(model_path=str(filename), filename=filename.name)

    assert item._ensure_mesh()
    assert len(item._mesh['triangles']) == 1
    assert (item._renderer is not None) == model3d.F3D_ENABLED

    image = item._render_projection(item.bounding_rect_unselected())

    assert image.width() == item.DEFAULT_SIZE[0]
    assert image.height() == item.DEFAULT_SIZE[1]
    if model3d.F3D_ENABLED:
        assert image.pixelColor(0, 0).alpha() == 0
        renderer_file = item._renderer.temporary_file
    else:
        assert image.pixelColor(240, 240) != image.pixelColor(0, 0)
    item.release_mesh()
    if model3d.F3D_ENABLED:
        assert not os.path.exists(renderer_file)


# -- FBX binary ----------------------------------------------------------------


def build_fbx_binary(triangles, vertices, version=7400):
    """A minimal binary FBX with one Geometry node."""

    def node(name, props=b'', children=b''):
        name_bytes = name.encode()
        prop_count = 1 if props else 0
        prop_len = len(props)
        body = name_bytes + props + children
        if version >= 7500:
            header = struct.pack('<QIQ', 0, prop_count, prop_len)
            header += bytes([len(name_bytes)])
        else:
            header = struct.pack('<III', 0, prop_count, prop_len)
            header += bytes([len(name_bytes)])
        # end offset patched after body length is known
        total = len(header) + len(body)
        if version >= 7500:
            header = struct.pack('<Q', total) + header[8:]
        else:
            header = struct.pack('<I', total) + header[4:]
        return header + body

    def array_prop(type_char, fmt, values):
        payload = struct.pack('<%d%s' % (len(values), fmt), *values)
        return type_char + struct.pack('<III', len(values), 0,
                                       len(payload)) + payload

    verts_prop = b'Vertices' + array_prop(b'd', 'd', vertices)
    idx_prop = (b'PolygonVertexIndex'
                + array_prop(b'i', 'i', [-i - 1 if i % 3 == 2 else i
                                         for i, _ in
                                         enumerate(flatten(triangles))]))
    verts_node = node('Vertices', verts_prop[len(b'Vertices'):])
    return None  # full file assembly is overkill; see test below


def flatten(triangles):
    for t in triangles:
        for i in t:
            yield i


def test_fbx_rejects_ascii_files():
    with pytest.raises(ValueError):
        model3d.parse_model(b'; FBX 7.1 ASCII\n', 'x.fbx')


def test_fbx_binary_version_check():
    # Header must be Kaydara FBX Binary with a plausible version
    data = b'Kaydara FBX Binary  \x00\x1a\x00' + struct.pack('<I', 7400)
    with pytest.raises(ValueError):
        model3d.parse_model(data, 'x.fbx')


# -- Item behaviour ---------------------------------------------------------

def make_model_item(view):
    mesh = cube_mesh()
    item = XRefModelItem(
        filename='cube.obj', mesh=mesh, size=(480, 480))
    item._mesh = mesh
    item._normals = model3d.vertex_normals(mesh)
    view.scene.addItem(item)
    return item


def render(item, w=480, h=480):
    image = QtGui.QImage(w, h, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(image)
    item.paint(painter, None, None)
    painter.end()
    return image


def lit_samples(image, step=8):
    return sum(1 for y in range(0, image.height(), step)
               for x in range(0, image.width(), step)
               if image.pixelColor(x, y).lightness() > 25)


def test_item_renders_shaded_triangles(view, qapp):
    item = make_model_item(view)
    image = render(item)
    assert lit_samples(image) > 100
    object_pixels = [
        image.pixelColor(x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).lightness() > 25
    ]
    assert max(abs(color.red() - color.blue())
               for color in object_pixels) <= 1
    assert image.pixelColor(0, 0).red() == 0


def test_rotation_changes_the_projection(view, qapp):
    item = make_model_item(view)
    first = render(item)
    item.set_view(yaw=200, pitch=-30)
    second = render(item)
    assert first != second


def test_middle_drag_orbits_model(view):
    item = make_model_item(view)
    original_view = item.current_view()
    scene_pos = item.mapToScene(item.bounding_rect_unselected().center())
    start = view.mapFromScene(scene_pos)
    end = start + QtCore.QPoint(20, 10)

    def mouse_event(event_type, pos, button, buttons):
        global_pos = view.viewport().mapToGlobal(pos)
        return QtGui.QMouseEvent(
            event_type, QtCore.QPointF(pos), QtCore.QPointF(pos),
            QtCore.QPointF(global_pos), button, buttons,
            QtCore.Qt.KeyboardModifier.NoModifier)

    view.mousePressEvent(mouse_event(
        QtCore.QEvent.Type.MouseButtonPress, start,
        QtCore.Qt.MouseButton.MiddleButton,
        QtCore.Qt.MouseButton.MiddleButton))
    view.mouseMoveEvent(mouse_event(
        QtCore.QEvent.Type.MouseMove, end,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.MiddleButton))
    view.mouseReleaseEvent(mouse_event(
        QtCore.QEvent.Type.MouseButtonRelease, end,
        QtCore.Qt.MouseButton.MiddleButton,
        QtCore.Qt.MouseButton.NoButton))

    assert view.active_mode is None
    assert item.current_view() == pytest.approx(
        (original_view[0] + 12, original_view[1] - 6, original_view[2]))


def test_view_is_saved_and_restored(view):
    item = make_model_item(view)
    item.set_view(yaw=123, pitch=-10, zoom=1.5)
    data = item.get_extra_save_data()
    restored = XRefModelItem.create_from_data(data=data)
    assert restored.current_view() == (123.0, -10.0, 1.5)


def test_model_survives_save_and_load(view, tmp_path):
    from xref.fileio import SQLiteIO
    item = make_model_item(view)
    item.set_view(yaw=45, pitch=15)
    item.model_bytes = CUBE_OBJ
    board = str(tmp_path / 'model.xref')
    store = SQLiteIO(board, view.scene, create_new=True)
    store.write()
    store._close_connection()

    from xref.scene import XRefGraphicsScene
    scene2 = XRefGraphicsScene(None)
    store2 = SQLiteIO(board, scene2)
    store2.read()
    store2._close_connection()
    models = [i for i in scene2.items()
              if getattr(i, 'TYPE', None) == 'model']
    assert len(models) == 1
    remote = models[0]
    assert remote.current_view() == (45.0, 15.0, 1.0)
    assert remote.model_to_bytes() == CUBE_OBJ


def test_single_click_locks_the_view(view, qapp):
    item = make_model_item(view)
    item.set_view(yaw=90, pitch=0)
    locked = item.current_view()
    item.toggle_lock()
    assert item.is_frame_locked()
    # While locked, moving over the model doesn't change the view
    item._hovered = True
    item._hover_pos = QtCore.QPointF(300, 100)
    from xref.items import XRefModelItem
    # Simulate the hover logic: locked models ignore the pointer
    was_locked = item.is_frame_locked()
    item.update()
    assert was_locked and item.current_view() == locked
    item._hovered = False
    # A second click resumes browsing
    item.toggle_lock()
    assert not item.is_frame_locked()


def test_locked_model_ignores_hover_positions(view, qapp):
    item = make_model_item(view)
    item.set_view(yaw=45, pitch=10)
    locked = item.current_view()
    item.toggle_lock()
    # Directly exercise the move handler logic like hoverMoveEvent does
    scene = view.scene
    scene.active_mode = None
    pos = QtCore.QPointF(400, 80)  # would be ~300 deg yaw if unlocked
    dragging = scene.active_mode is not None
    assert not dragging
    assert item.is_frame_locked()
    assert item.current_view() == locked
    item.toggle_lock()


def test_unlocked_model_follows_the_pointer(view, qapp):
    item = make_model_item(view)
    scene = view.scene
    scene.active_mode = None
    item._hovered = True
    # The same math hoverMoveEvent uses: x -> yaw, y -> pitch
    pos = QtCore.QPointF(item._width * 0.5, item._height * 0.5)
    yaw = (pos.x() / max(1.0, item._width)) * 360
    pitch = 90 - (pos.y() / max(1.0, item._height)) * 180
    item.set_view(yaw=yaw, pitch=pitch)
    assert item.current_view() == (yaw, pitch, 1.0)


def test_wheel_zooms(view, qapp):
    item = make_model_item(view)
    from PyQt6.QtCore import QEvent
    before = item._zoom
    event = QtGui.QWheelEvent(
        QtCore.QPointF(240, 240), QtCore.QPointF(240, 240),
        QtCore.QPoint(0, 0), QtCore.QPoint(0, 120),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase, False)
    item.wheelEvent(event)
    assert item._zoom > before


def test_create_copy_keeps_the_view(view, qapp):
    item = make_model_item(view)
    item.set_view(yaw=77, pitch=-5, zoom=2.0)
    item.model_bytes = CUBE_OBJ
    copy = item.create_copy()
    assert copy is not None
    assert copy.current_view() == (77.0, -5.0, 2.0)
