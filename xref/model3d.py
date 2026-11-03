#!/usr/bin/env python3

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

"""3D model loading and rendering backends.

Windows uses libf3d for GPU rendering and OpenUSD for USD formats that
the installed F3D build cannot read. Other platforms retain the built-in
software renderer.

"""

import logging
import math
import os
import os.path
import platform
import struct
import sys
import tempfile

logger = logging.getLogger(__name__)

F3D_ENABLED = (sys.platform == 'win32'
               and platform.machine().lower() in ('amd64', 'x86_64')
               and sys.version_info >= (3, 10)
               and sys.maxsize > 2**32)

if F3D_ENABLED:
    import f3d

try:
    from pxr import Tf, Usd, UsdGeom
except ImportError:
    Tf = None
    Usd = None
    UsdGeom = None

USD_CORE_ENABLED = Usd is not None
USD_EXTENSIONS = frozenset(('.usd', '.usda', '.usdc', '.usdz'))

_F3D_MODEL_FORMATS = frozenset((
    'abc', '3ds', '3mf', 'amf', 'drc', 'dae', 'dxf', 'off', 'x',
    'obj', 'stl', 'ply', 'fbx', 'glb', 'gltf', 'wrl', 'vrml',
    'vtkhdf', 'exo', 'ex2', 'e', 'g', 'nc', 'cdf', 'ncdf',
    'vtk', 'vtu', 'vtp', 'vti', 'vtr', 'vts', 'vtm',
    'igs', 'iges', 'stp', 'step', 'stpnc', 'p21', '210', 'brep',
    'xbf', 'fcstd', 'las', 'laz', 'bpf', 'csd', 'ptx', 'qi', 'sbet',
    'slpk', 'ifc', 'pts', 'pcd', 'splat', 'spz', 'gml', 'dcm',
    'mha', 'mhd', 'nrrd', 'nhdr', 'usd', 'usda', 'usdc', 'usdz',
))

if F3D_ENABLED:
    def _f3d_model_extensions():
        available = {
            extension.lower().lstrip('.')
            for reader in f3d.Engine.get_readers_info()
            for extension in reader.extensions
        }
        return tuple(sorted(
            f'.{extension}'
            for extension in available & _F3D_MODEL_FORMATS))

    F3D_MODEL_EXTENSIONS = _f3d_model_extensions()
    MODEL_EXTENSIONS = tuple(sorted(
        set(F3D_MODEL_EXTENSIONS)
        | (set(USD_EXTENSIONS) if USD_CORE_ENABLED else set())))
else:
    F3D_MODEL_EXTENSIONS = ()
    MODEL_EXTENSIONS = (
        '.obj', '.stl', '.ply', '.fbx', '.glb', '.gltf', '.usdz')


def parse_model(data, filename=None, source_path=None):
    """Parses raw model bytes into ``{'vertices', 'triangles'}``.

    ``vertices`` is a flat list of xyz floats; ``triangles`` a list of
    vertex index triples. Raises ``ValueError`` when the format is not
    recognised or the file is damaged.
    """

    ext = ''
    if filename:
        ext = '.' + filename.rsplit('.', 1)[-1].lower()
    if ext == '.obj' or (not ext and data.lstrip()[:1] in (b'#', b'v', b'f')):
        text = _decode(data)
        if _looks_like_stl_ascii(text):
            return _parse_stl_ascii(text)
        return _parse_obj(text)
    if ext == '.stl':
        return _parse_stl(data)
    if ext == '.ply':
        return _parse_ply(data)
    if ext in ('.glb', '.gltf'):
        return _parse_gltf(data, source_path)
    if ext in USD_EXTENSIONS:
        return _parse_usd(data, source_path, ext)
    if ext == '.fbx':
        return _parse_fbx(data)
    # Unknown extension: sniff the content
    if data[:5] == b'solid':
        return _parse_stl(data)
    if b'ply' in data[:64]:
        return _parse_ply(data)
    if data[:4] == b'glTF':
        return _parse_gltf(data)
    if data[:2] == b'PK':
        return _parse_usd(data, source_path, '.usdz')
    raise ValueError('Unsupported 3D format')


def convert_mesh_up_axis(mesh, source_axis, target_axis):
    """Rotate mesh coordinates from one positive up axis to another."""

    transforms = {
        ('X', 'X'): lambda x, y, z: (x, y, z),
        ('X', 'Y'): lambda x, y, z: (-y, x, z),
        ('X', 'Z'): lambda x, y, z: (-z, y, x),
        ('Y', 'X'): lambda x, y, z: (y, -x, z),
        ('Y', 'Y'): lambda x, y, z: (x, y, z),
        ('Y', 'Z'): lambda x, y, z: (x, -z, y),
        ('Z', 'X'): lambda x, y, z: (z, y, -x),
        ('Z', 'Y'): lambda x, y, z: (x, z, -y),
        ('Z', 'Z'): lambda x, y, z: (x, y, z),
    }
    try:
        transform = transforms[(source_axis, target_axis)]
    except KeyError:
        raise ValueError('Unsupported model up axis conversion: '
                         f'{source_axis} to {target_axis}') from None
    vertices = mesh['vertices']
    if source_axis == target_axis:
        return mesh
    aligned_vertices = []
    for index in range(0, len(vertices), 3):
        aligned_vertices.extend(transform(*vertices[index:index + 3]))
    return {
        'vertices': aligned_vertices,
        'triangles': mesh['triangles'],
    }


def align_mesh_up_axis(mesh, up_axis):
    """Rotate a mesh so its selected positive axis points along +Z."""

    return convert_mesh_up_axis(mesh, up_axis, 'Z')


def _decode(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin-1')


def _looks_like_stl_ascii(text):
    first = text.lstrip()[:60].lower()
    return first.startswith('solid') and 'facet' in text[:4000].lower()


# -- OBJ ----------------------------------------------------------------------

def _parse_obj(text):
    vertices = []
    triangles = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('v '):
            parts = line.split()
            try:
                vertices.extend(
                    (float(parts[1]), float(parts[2]), float(parts[3])))
            except (IndexError, ValueError):
                continue
        elif line.startswith('f '):
            indices = []
            for token in line.split()[1:]:
                # Formats like "1/2/3", "1//3", "1"
                index = token.split('/')[0]
                try:
                    index = int(index)
                except ValueError:
                    continue
                if index < 0:
                    index = len(vertices) // 3 + index
                else:
                    index -= 1
                indices.append(index)
            for i in range(1, len(indices) - 1):
                triangles.append((indices[0], indices[i], indices[i + 1]))
    if not triangles:
        raise ValueError('OBJ file has no faces')
    return {'vertices': vertices, 'triangles': triangles}


# -- STL ----------------------------------------------------------------------

def _parse_stl(data):
    if data[:5] == b'solid' and b'facet' in data[:4000]:
        return _parse_stl_ascii(_decode(data))
    return _parse_stl_binary(data)


def _parse_stl_ascii(text):
    vertices = []
    triangles = []
    current = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('vertex'):
            try:
                values = [float(v) for v in line.split()[1:4]]
            except (IndexError, ValueError):
                continue
            current.append(len(vertices) // 3)
            vertices.extend(values)
            if len(current) == 3:
                triangles.append(tuple(current))
                current = []
    if not triangles:
        raise ValueError('ASCII STL file has no facets')
    return {'vertices': vertices, 'triangles': triangles}


def _parse_stl_binary(data):
    # 80 byte header, uint32 count, then 50 bytes per facet
    if len(data) < 84:
        raise ValueError('STL file too short')
    count = struct.unpack_from('<I', data, 80)[0]
    if len(data) < 84 + count * 50:
        raise ValueError('STL file truncated')
    vertices = []
    triangles = []
    offset = 84
    for _ in range(count):
        for corner in range(3):
            x, y, z = struct.unpack_from('<3f', data, offset + 12 + corner * 12)
            vertices.extend((x, y, z))
        triangles.append((
            len(vertices) // 3 - 3, len(vertices) // 3 - 2,
            len(vertices) // 3 - 1))
        offset += 50
    return {'vertices': vertices, 'triangles': triangles}


# -- PLY ----------------------------------------------------------------------

def _parse_ply(data):
    if not data.startswith(b'ply'):
        raise ValueError('Not a PLY file')
    header_end = data.find(b'end_header')
    if header_end < 0:
        raise ValueError('PLY header not terminated')
    header = _decode(data[:header_end])
    binary = 'binary_little_endian' in header
    body = data[header_end + len(b'end_header'):]
    while body[:1] in (b'\n', b'\r'):
        body = body[1:]

    vertex_count = 0
    face_count = 0
    has_normals = False
    has_colors = False
    property_count = 0
    current_element = None
    for line in header.splitlines():
        line = line.strip()
        if line.startswith('element vertex'):
            current_element = 'vertex'
            vertex_count = int(line.split()[-1])
        elif line.startswith('element face'):
            current_element = 'face'
            face_count = int(line.split()[-1])
        elif line.startswith('property') and current_element == 'vertex':
            property_count += 1
            parts = line.split()
            if len(parts) > 2 and 'normal' in parts[2]:
                has_normals = True
            elif 'red' in parts[-1] or 'green' in parts[-1]:
                has_colors = True

    vertices = []
    triangles = []
    if not binary:
        values = body.split()
        pos = 0
        for _ in range(vertex_count):
            for axis in range(3):
                vertices.append(float(values[pos + axis]))
            pos += property_count
        for _ in range(face_count):
            count = int(values[pos])
            pos += 1
            indices = [int(values[pos + i]) for i in range(count)]
            pos += count
            for i in range(1, count - 1):
                triangles.append((indices[0], indices[i], indices[i + 1]))
    else:
        # Only float x/y/z are read; other properties are skipped based on
        # the declared types
        sizes = {'float': 4, 'float32': 4, 'double': 8, 'float64': 8,
                 'uchar': 1, 'uint8': 1, 'char': 1, 'int8': 1,
                 'ushort': 2, 'uint16': 2, 'short': 2, 'int16': 2,
                 'uint': 4, 'int': 4, 'uint32': 4, 'int32': 4}
        props = []
        vertex_props = []
        face_props = []
        element = None
        for line in header.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] == 'element':
                element = parts[1]
            elif parts[0] == 'property' and len(parts) >= 3:
                if parts[1] == 'list':
                    entry = ('list', sizes.get(parts[2], 1),
                             sizes.get(parts[3], 4))
                else:
                    entry = ('scalar', sizes.get(parts[1], 4))
                props.append(entry)
                if element == 'vertex':
                    vertex_props.append(entry)
                elif element == 'face':
                    face_props.append(entry)
        # The first three float scalars are x/y/z; other properties
        # (normals, colors, ...) advance the offset by their size.
        # Face records use their own (list) properties.
        floats_seen = 0
        offset = 0
        for _ in range(vertex_count):
            floats_seen = 0
            for prop in vertex_props:
                if prop[0] == 'scalar' and prop[1] == 4:
                    value = struct.unpack_from('<f', body, offset)[0]
                    if floats_seen < 3:
                        vertices.append(value)
                    floats_seen += 1
                    offset += 4
                else:
                    offset += prop[1]
        for _ in range(face_count):
            for prop in face_props:
                if prop[0] != 'list':
                    offset += prop[1]
                    continue
                # The count type can be uchar/ushort/uint; use the
                # declared size for reading and advancing
                count_size = prop[1]
                fmt = {1: '<B', 2: '<H'}.get(count_size, '<I')
                count = struct.unpack_from(fmt, body, offset)[0]
                offset += count_size
                indices = struct.unpack_from(
                    '<%dI' % count, body, offset)
                offset += 4 * count
                for i in range(1, count - 1):
                    triangles.append((indices[0], indices[i], indices[i + 1]))
                break
    if not triangles:
        raise ValueError('PLY file has no faces')
    return {'vertices': vertices, 'triangles': triangles,
            'has_normals': has_normals, 'has_colors': has_colors}


# -- glTF / GLB --------------------------------------------------------------

COMPONENT_SIZE = {'SCALAR': 4, 'VEC2': 8, 'VEC3': 12, 'VEC4': 16}


def _parse_gltf(data, source_path=None):
    """Parses binary glTF (.glb) and .gltf files.

    Only the POSITION attribute and the index accessor are needed; the
    meshes' vertices and triangles are rebuilt from the embedded buffers
    (data URIs and the GLB BIN chunk). glTF files that reference external
    .bin files can't work without their siblings and raise an error.
    """

    import base64
    import json

    if data[:4] == b'glTF':
        if len(data) < 20:
            raise ValueError('GLB file too short')
        json_text = None
        bin_data = None
        offset = 12
        while offset + 8 <= len(data):
            length, chunk_type = struct.unpack_from('<I4s', data, offset)
            offset += 8
            chunk = data[offset:offset + length]
            offset += length
            if chunk_type == b'JSON':
                json_text = _decode(chunk.rstrip(b'\x00 \t\r\n'))
            elif chunk_type == b'BIN\x00':
                bin_data = chunk
        if json_text is None:
            raise ValueError('GLB file has no JSON chunk')
    else:
        json_text = _decode(data)
        bin_data = None

    try:
        doc = json.loads(json_text)
    except ValueError:
        raise ValueError('glTF JSON is damaged')

    buffers = []
    for buffer in doc.get('buffers', []):
        uri = buffer.get('uri', '')
        if uri.startswith('data:'):
            header, _, payload = uri.partition(',')
            if 'base64' in header:
                buffers.append(base64.b64decode(payload))
            else:
                buffers.append(base64.b64decode(payload + '==='))
        elif bin_data is not None:
            buffers.append(bin_data[:buffer.get('byteLength',
                                                len(bin_data))])
        elif source_path:
            sibling = os.path.join(
                os.path.dirname(source_path), uri.lstrip('./'))
            if os.path.isfile(sibling):
                with open(sibling, 'rb') as f:
                    buffers.append(f.read())
            else:
                buffers.append(None)
        else:
            buffers.append(None)

    def accessor(index):
        acc = doc['accessors'][index]
        view = doc['bufferViews'][acc['bufferView']]
        buffer = buffers[view.get('buffer', 0)] if buffers else None
        if buffer is None:
            raise ValueError('glTF file uses external buffers')
        start = acc.get('byteOffset', 0) + view.get('byteOffset', 0)
        return buffer, start, acc

    vertices = []
    triangles = []
    for mesh in doc.get('meshes', []):
        for prim in mesh.get('primitives', []):
            attributes = prim.get('attributes', {})
            if 'POSITION' not in attributes:
                continue
            base = len(vertices) // 3
            buffer, start, acc = accessor(attributes['POSITION'])
            count = acc.get('count', 0)
            comp_type = acc.get('componentType', 5126)
            if comp_type == 5126:
                values = struct.unpack_from(
                    '<%df' % (count * 3), buffer, start)
            elif comp_type == 5123:
                values = struct.unpack_from(
                    '<%dH' % (count * 3), buffer, start)
            elif comp_type == 5125:
                values = struct.unpack_from(
                    '<%dI' % (count * 3), buffer, start)
            else:
                raise ValueError('Unsupported glTF position type')
            vertices.extend(float(v) for v in values)
            index_ref = prim.get('indices')
            if index_ref is None:
                for i in range(1, count - 1):
                    triangles.append((base, base + i, base + i + 1))
            else:
                ibuffer, istart, iacc = accessor(index_ref)
                icount = iacc.get('count', 0)
                fmt = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H',
                       5125: 'I'}.get(iacc.get('componentType', 5123))
                if not fmt:
                    raise ValueError('Unsupported glTF index type')
                indices = struct.unpack_from(
                    '<%d%s' % (icount, fmt), ibuffer, istart)
                for i in range(0, icount - 2, 3):
                    triangles.append((indices[i] + base,
                                      indices[i + 1] + base,
                                      indices[i + 2] + base))
    if not triangles:
        raise ValueError('glTF file has no triangles')
    return {'vertices': vertices, 'triangles': triangles}


# -- USDZ ----------------------------------------------------------------------

def _parse_usd(data, source_path, extension):
    """Parses USD stages, including binary USDZ packages."""

    if USD_CORE_ENABLED:
        return _parse_usd_stage(data, source_path, extension)
    if extension == '.usdz':
        return _parse_usdz_ascii(data)
    if data.startswith(b'#usda'):
        return _parse_usda(_decode(data))
    raise ValueError(
        'Binary USD models require the usd-core package.')


def _parse_usd_stage(data, source_path, extension):
    stage_path = source_path
    temporary_path = None
    if not stage_path:
        temp = tempfile.NamedTemporaryFile(
            suffix=extension, prefix='xref_usd_', delete=False)
        with temp:
            temp.write(data)
        stage_path = temporary_path = temp.name

    try:
        stage = Usd.Stage.Open(stage_path)
        if stage is None:
            raise ValueError('Could not open USD model')

        vertices = []
        triangles = []
        transform_cache = UsdGeom.XformCache()
        for prim in Usd.PrimRange.Stage(stage):
            if not prim.IsA(UsdGeom.Mesh):
                continue
            mesh = UsdGeom.Mesh(prim)
            points = mesh.GetPointsAttr().Get()
            counts = mesh.GetFaceVertexCountsAttr().Get()
            indices = mesh.GetFaceVertexIndicesAttr().Get()
            if points is None or counts is None or indices is None:
                continue

            base = len(vertices) // 3
            transform = transform_cache.GetLocalToWorldTransform(prim)
            for point in points:
                world_point = transform.Transform(point)
                vertices.extend((
                    float(world_point[0]),
                    float(world_point[1]),
                    float(world_point[2])))

            position = 0
            for face_count in counts:
                face_count = int(face_count)
                if face_count >= 3 and position + face_count <= len(indices):
                    first = int(indices[position]) + base
                    for offset in range(1, face_count - 1):
                        triangles.append((
                            first,
                            int(indices[position + offset]) + base,
                            int(indices[position + offset + 1]) + base))
                position += face_count

        if not triangles:
            raise ValueError('USD model contains no mesh faces')
        return {'vertices': vertices, 'triangles': triangles}
    except Tf.ErrorException as error:
        raise ValueError(f'Could not read USD model: {error}') from error
    finally:
        if temporary_path:
            os.unlink(temporary_path)


def _parse_usdz_ascii(data):
    """Parses USDA mesh data from a USDZ archive."""

    import io as _io
    import re
    import zipfile

    try:
        archive = zipfile.ZipFile(_io.BytesIO(data))
    except Exception:
        raise ValueError('USDZ file is not a valid zip archive')
    names = archive.namelist()
    usda = next((n for n in names if n.endswith('.usda')), None)
    if usda is not None:
        return _parse_usda(_decode(archive.read(usda)))

    raise ValueError(
        'This USDZ file stores binary USDC data; install usd-core to load it.')


def _parse_usda(text):
    """Parses the mesh subset of a USDA (ASCII USD) file."""

    import re

    vertices = []
    triangles = []

    for match in re.finditer(
            r'point3f\[\]\s+points\s*=\s*\[(.*?)\]', text, re.S):
        for point in re.finditer(
                r'\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,'
                r'\s*([-\d.eE+]+)\s*\)', match.group(1)):
            vertices.extend((float(point.group(1)), float(point.group(2)),
                             float(point.group(3))))

    counts = []
    count_match = re.search(
        r'int\[\]\s+faceVertexCounts\s*=\s*\[(.*?)\]', text, re.S)
    if count_match:
        counts = [int(v) for v in
                  re.findall(r'-?\d+', count_match.group(1))]

    for match in re.finditer(
            r'int\[\]\s+faceVertexIndices\s*=\s*\[(.*?)\]', text,
            re.S):
        indices = [int(v) for v in re.findall(r'-?\d+', match.group(1))]
        face_counts = counts if counts else [3] * (len(indices) // 3)
        pos = 0
        for count in face_counts:
            if count >= 3 and pos + count <= len(indices):
                for i in range(1, count - 1):
                    triangles.append((indices[pos], indices[pos + i],
                                      indices[pos + i + 1]))
            pos += count

    if not triangles:
        raise ValueError('USDZ archive has no mesh data')
    return {'vertices': vertices, 'triangles': triangles}


# -- FBX (binary) ---------------------------------------------------------------

def _parse_fbx(data):
    """Parses binary FBX 7.x files (Kaydara FBX Binary header).

    The node records are walked recursively until the Geometry nodes;
    ``Vertices`` (doubles) and ``PolygonVertexIndex`` (int32, last index
    of each polygon XOR-encoded as -i-1) are turned into vertices and
    fan-triangulated triangles. ASCII FBX files are not supported.
    """

    if data[:20] != b'Kaydara FBX Binary  ':
        raise ValueError('ASCII FBX files are not supported; '
                         'export as binary FBX, OBJ or GLB instead')
    if len(data) < 27:
        raise ValueError('FBX file too short')
    version = struct.unpack_from('<I', data, 23)[0]
    wide = version >= 7500  # 64-bit offsets in newer files

    vertices = []
    triangles = []

    def walk(offset, end, depth=0, in_geometry=False):
        while offset < end:
            if offset + (25 if wide else 13) > end:
                break
            if wide:
                # FBX 7.5+: u64 end, u32 prop_count, u64 prop_list_len,
                # u8 name_len
                node_end = struct.unpack_from('<Q', data, offset)[0]
                prop_count = struct.unpack_from('<I', data, offset + 8)[0]
                prop_len = struct.unpack_from('<Q', data, offset + 16)[0]
                name_len = data[offset + 24]
                pos = offset + 25
            else:
                node_end, prop_count, prop_len = struct.unpack_from(
                    '<III', data, offset)
                name_len = data[offset + 12]
                pos = offset + 13
            if node_end <= offset or node_end > len(data):
                break
            name = data[pos:pos + name_len]
            pos += name_len
            # Skip the properties; we only need nested Geometry nodes
            child_start = pos + prop_len
            if name == b'Geometry':
                parse_geometry(child_start, node_end)
            elif prop_count == 0 and child_start < node_end:
                # Geometry nodes sit at various nesting levels; keep
                # walking until one is found
                walk(child_start, node_end, depth + 1)
            offset = node_end

    def read_properties(offset, count):
        """Reads property records starting at offset."""

        values = []
        for _ in range(count):
            if offset >= len(data):
                break
            type_code = data[offset:offset + 1]
            offset += 1
            if type_code in (b'Y',):
                values.append(struct.unpack_from('<h', data, offset)[0])
                offset += 2
            elif type_code in (b'C', b'B'):
                values.append(bool(data[offset]))
                offset += 1
            elif type_code in (b'I',):
                values.append(struct.unpack_from('<i', data, offset)[0])
                offset += 4
            elif type_code in (b'F',):
                values.append(struct.unpack_from('<f', data, offset)[0])
                offset += 4
            elif type_code in (b'D',):
                values.append(struct.unpack_from('<d', data, offset)[0])
                offset += 8
            elif type_code in (b'L',):
                values.append(struct.unpack_from('<q', data, offset)[0])
                offset += 8
            elif type_code in (b'f', b'd', b'l', b'i', b'b'):
                # arrays: length, encoding, compressed length, payload
                array_len, encoding, comp_len = struct.unpack_from(
                    '<III', data, offset)
                offset += 12
                payload = data[offset:offset + comp_len]
                offset += comp_len
                fmt = {b'f': 'f', b'd': 'd', b'l': 'q', b'i': 'i',
                       b'b': 'B'}[type_code]
                if encoding == 1:
                    import zlib
                    payload = zlib.decompress(payload)
                size = {b'f': 4, b'd': 8, b'l': 8, b'i': 4, b'b': 1}[
                    type_code]
                if len(payload) >= array_len * size:
                    values.append(struct.unpack_from(
                        '<%d%s' % (array_len, fmt), payload, 0))
            elif type_code in (b'S',):
                length = struct.unpack_from('<I', data, offset)[0]
                offset += 4
                values.append(data[offset:offset + length])
                offset += length
            else:
                break
        return values, offset

    def parse_geometry(offset, end):
        geo_vertices = None
        geo_indices = None
        while offset < end:
            if offset + (25 if wide else 13) > end:
                break
            if wide:
                node_end = struct.unpack_from('<Q', data, offset)[0]
                prop_count = struct.unpack_from('<I', data, offset + 8)[0]
                prop_len = struct.unpack_from('<Q', data, offset + 16)[0]
                name_len = data[offset + 24]
                pos = offset + 25
            else:
                node_end, prop_count, prop_len = struct.unpack_from(
                    '<III', data, offset)
                name_len = data[offset + 12]
                pos = offset + 13
            if node_end <= offset or node_end > len(data):
                break
            name = data[pos:pos + name_len]
            pos += name_len
            props_start = pos
            if name == b'Vertices' and prop_count == 1:
                values, _ = read_properties(props_start, 1)
                if values and isinstance(values[0], tuple):
                    geo_vertices = list(values[0])
            elif name == b'PolygonVertexIndex' and prop_count == 1:
                values, _ = read_properties(props_start, 1)
                if values and isinstance(values[0], tuple):
                    geo_indices = list(values[0])
            offset = node_end
        if not geo_vertices or not geo_indices:
            return
        base = len(vertices) // 3
        vertices.extend(float(v) for v in geo_vertices)
        polygon = []
        for index in geo_indices:
            if index < 0:
                # FBX encodes the last index of a polygon as -i - 1
                polygon.append(-index - 1)
                if len(polygon) >= 3:
                    for i in range(1, len(polygon) - 1):
                        triangles.append(
                            (polygon[0] + base, polygon[i] + base,
                             polygon[i + 1] + base))
                polygon = []
            else:
                polygon.append(index)

    walk(27, len(data))
    if not triangles:
        raise ValueError('FBX file has no mesh data')
    return {'vertices': vertices, 'triangles': triangles}


# -- Geometry helpers ----------------------------------------------------------

#: Models above this many triangles are reduced before rendering, so even
#: multi-million-triangle exports stay responsive in the software renderer
MAX_TRIANGLES = 25000


def decimate(mesh, max_triangles=MAX_TRIANGLES):
    """Reduces mesh detail by clustering nearby vertices without holes."""

    triangles = mesh['triangles']
    if len(triangles) <= max_triangles:
        return mesh
    vertices = mesh['vertices']
    if max_triangles < 1:
        raise ValueError('max_triangles must be positive')

    minimum, maximum = bounding_box(mesh)
    spans = tuple(maximum[i] - minimum[i] for i in range(3))
    largest_span = max(spans) or 1.0
    resolution = max(2, int((max_triangles / (2 * 3.14159)) ** 0.5))

    while True:
        axis_counts = tuple(
            (max(2, int(resolution * spans[i] / largest_span))
             if spans[i] else 1)
            for i in range(3))
        sums = {}
        counts = {}
        vertex_cells = []
        for index in range(len(vertices) // 3):
            point = vertices[index * 3:index * 3 + 3]
            cell = tuple(
                min(axis_counts[axis] - 1, max(
                    0, int((point[axis] - minimum[axis])
                           / spans[axis] * axis_counts[axis])))
                if spans[axis] else 0
                for axis in range(3))
            vertex_cells.append(cell)
            total = sums.get(cell)
            if total is None:
                sums[cell] = list(point)
                counts[cell] = 1
            else:
                total[0] += point[0]
                total[1] += point[1]
                total[2] += point[2]
                counts[cell] += 1

        cluster_positions = {
            cell: tuple(value / counts[cell] for value in position)
            for cell, position in sums.items()
        }
        cluster_indices = {}
        new_vertices = []
        new_triangles = []
        seen_triangles = set()
        for a, b, c in triangles:
            cells = (vertex_cells[a], vertex_cells[b], vertex_cells[c])
            if cells[0] == cells[1] or cells[1] == cells[2] \
                    or cells[2] == cells[0]:
                continue
            canonical = tuple(sorted(cells))
            if canonical in seen_triangles:
                continue
            seen_triangles.add(canonical)
            face = []
            for cell in cells:
                index = cluster_indices.get(cell)
                if index is None:
                    index = len(new_vertices) // 3
                    cluster_indices[cell] = index
                    new_vertices.extend(cluster_positions[cell])
                face.append(index)
            new_triangles.append(tuple(face))

        if len(new_triangles) <= max_triangles or resolution <= 2:
            return {'vertices': new_vertices, 'triangles': new_triangles}
        resolution = max(2, int(resolution * 0.8))




def bounding_box(mesh):
    """The (min, max) xyz corners of the mesh."""

    v = mesh['vertices']
    if not v:
        return (0, 0, 0), (0, 0, 0)
    xs = v[0::3]
    ys = v[1::3]
    zs = v[2::3]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def face_normals(mesh):
    """One normal per triangle."""

    v = mesh['vertices']
    normals = []
    for a, b, c in mesh['triangles']:
        ax, ay, az = v[a * 3], v[a * 3 + 1], v[a * 3 + 2]
        bx, by, bz = v[b * 3], v[b * 3 + 1], v[b * 3 + 2]
        cx, cy, cz = v[c * 3], v[c * 3 + 1], v[c * 3 + 2]
        ux, uy, uz = bx - ax, by - ay, bz - az
        wx, wy, wz = cx - ax, cy - ay, cz - az
        nx = uy * wz - uz * wy
        ny = uz * wx - ux * wz
        nz = ux * wy - uy * wx
        length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        normals.append((nx / length, ny / length, nz / length))
    return normals


def vertex_normals(mesh):
    """Area-weighted smooth normals for meshes with shared vertices."""

    vertices = mesh['vertices']
    normals = [[0.0, 0.0, 0.0] for _ in range(len(vertices) // 3)]
    for a, b, c in mesh['triangles']:
        ax, ay, az = vertices[a * 3:a * 3 + 3]
        bx, by, bz = vertices[b * 3:b * 3 + 3]
        cx, cy, cz = vertices[c * 3:c * 3 + 3]
        ux, uy, uz = bx - ax, by - ay, bz - az
        wx, wy, wz = cx - ax, cy - ay, cz - az
        face = (uy * wz - uz * wy,
                uz * wx - ux * wz,
                ux * wy - uy * wx)
        for index in (a, b, c):
            normal = normals[index]
            normal[0] += face[0]
            normal[1] += face[1]
            normal[2] += face[2]

    result = []
    for nx, ny, nz in normals:
        length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        result.append((nx / length, ny / length, nz / length))
    return result


def _write_mesh_obj(mesh, normals):
    """Writes indexed geometry for F3D's native GPU renderer."""

    temp = tempfile.NamedTemporaryFile(
        mode='w', encoding='ascii', suffix='.obj', prefix='xref_mesh_',
        delete=False, newline='\n')
    try:
        vertices = mesh['vertices']
        for index in range(0, len(vertices), 3):
            temp.write('v {:.9g} {:.9g} {:.9g}\n'.format(
                vertices[index], vertices[index + 1], vertices[index + 2]))
        for nx, ny, nz in normals:
            temp.write('vn {:.9g} {:.9g} {:.9g}\n'.format(nx, ny, nz))
        for a, b, c in mesh['triangles']:
            temp.write('f {0}//{0} {1}//{1} {2}//{2}\n'.format(
                a + 1, b + 1, c + 1))
        return temp.name
    except Exception:
        temp.close()
        os.unlink(temp.name)
        raise
    finally:
        if not temp.closed:
            temp.close()


if F3D_ENABLED:
    class F3DRenderer:
        """Render a model with a persistent offscreen libf3d engine."""

        def __init__(self, filename, temporary_file=None,
                     camera_state=None, initial_view_preset=None,
                     up_axis=None):
            f3d.Log.set_verbose_level(f3d.Log.QUIET)
            engine = f3d.Engine.create(True)
            options = {
                'ui.axis': False,
                'ui.fps': False,
                'ui.filename': False,
                'ui.metadata': False,
                'ui.console': False,
                'ui.cheatsheet': False,
                'render.grid.enable': False,
                'render.background.skybox': 'disabled',
                'render.background.color': [0.0, 0.0, 0.0],
                'render.light.intensity': 3.0,
                'render.effect.ambient_occlusion': True,
                'render.effect.antialiasing.mode': 'fxaa',
                'model.coloring': 'scivis',
                'model.material.roughness': 1.0,
            }
            if up_axis is not None:
                up_directions = {
                    'X': [1.0, 0.0, 0.0],
                    'Y': [0.0, 1.0, 0.0],
                    'Z': [0.0, 0.0, 1.0],
                }
                if up_axis not in up_directions:
                    raise ValueError(f'Unsupported model up axis: {up_axis}')
                options['scene.up_direction'] = up_directions[up_axis]
            engine.options.update(options)
            if engine.scene.supports(filename) != f3d.SUPPORTED:
                raise ValueError(f'Unsupported 3D model format: {filename}')
            engine.scene.add(filename)
            engine.window.camera.reset_to_bounds()
            self.engine = engine
            self.temporary_file = temporary_file
            self._camera_state = camera_state
            self._initial_view_preset = initial_view_preset
            self._up_axis = up_axis
            self._rendered_view = None
            self._native_interaction = False
            self._orbit_delta_theta = 0.0
            self._orbit_delta_phi = 0.0
            self._pan_offset = [0.0, 0.0, 0.0]

        @classmethod
        def from_mesh(cls, mesh, normals, camera_state=None,
                      initial_view_preset=None, up_axis=None):
            filename = _write_mesh_obj(mesh, normals)
            try:
                return cls(filename, temporary_file=filename,
                           camera_state=camera_state,
                           initial_view_preset=initial_view_preset,
                           up_axis=up_axis)
            except Exception:
                os.unlink(filename)
                raise

        def render(self, width, height, yaw, pitch, zoom):
            self.engine.window.size = (width, height)
            view = (float(yaw), float(pitch), float(zoom))
            if (self._rendered_view is None
                    or (not self._native_interaction
                        and view != self._rendered_view)):
                camera = self.engine.window.camera
                camera.reset_to_bounds()
                if self._initial_view_preset:
                    self.set_view_preset(self._initial_view_preset)
                    self._initial_view_preset = None
                else:
                    camera.azimuth(yaw)
                    camera.elevation(pitch)
                camera.zoom(zoom)
                self._rendered_view = view
                if self._camera_state is not None:
                    self.set_camera_state(self._camera_state)
                    self._camera_state = None
            return self.engine.window.render_to_image(True)

        def set_native_interaction(self, active):
            self._native_interaction = bool(active)

        def camera_state(self):
            state = self.engine.window.camera.state
            return {
                'position': list(state.position),
                'focal_point': list(state.focal_point),
                'view_up': list(state.view_up),
                'view_angle': state.view_angle,
            }

        def set_camera_state(self, values):
            state = self.engine.window.camera.state
            state.position = tuple(values['position'])
            state.focal_point = tuple(values['focal_point'])
            state.view_up = tuple(values['view_up'])
            state.view_angle = float(values['view_angle'])
            self.engine.window.camera.state = state

        def set_axis_view(self, axis, positive=True):
            axes = {
                'x': (1.0, 0.0, 0.0),
                'y': (0.0, 1.0, 0.0),
                'z': (0.0, 0.0, 1.0),
            }
            if axis not in axes:
                raise ValueError(f'Unsupported camera axis: {axis}')
            state = self.engine.window.camera.state
            focal_point = tuple(state.focal_point)
            direction = axes[axis]
            if not positive:
                direction = tuple(-value for value in direction)
            distance = math.sqrt(sum(
                (state.position[index] - focal_point[index]) ** 2
                for index in range(3)))
            if distance <= 0:
                raise ValueError('Camera position and focal point coincide')
            up_axes = {
                'X': (1.0, 0.0, 0.0),
                'Y': (0.0, 1.0, 0.0),
                'Z': (0.0, 0.0, 1.0),
            }
            up_axis = up_axes.get(self._up_axis, (0.0, 0.0, 1.0))
            if axis == (self._up_axis or 'Z').lower():
                view_up = {
                    'X': (0.0, 1.0, 0.0),
                    'Y': (0.0, 0.0, 1.0),
                    'Z': (0.0, 1.0, 0.0),
                }[self._up_axis or 'Z']
            else:
                view_up = up_axis
            state.position = tuple(
                focal_point[index] + direction[index] * distance
                for index in range(3))
            state.view_up = view_up
            self.engine.window.camera.state = state
            return self.camera_state()

        def pan(self, delta_x, delta_y, viewport_height):
            translation = self._pan_translation(
                delta_x, delta_y, viewport_height)
            if translation is None:
                return self.camera_state()
            state = self.engine.window.camera.state
            state.position = tuple(
                state.position[index] + translation[index]
                for index in range(3))
            state.focal_point = tuple(
                state.focal_point[index] + translation[index]
                for index in range(3))
            self.engine.window.camera.state = state
            return self.camera_state()

        def _pan_translation(self, delta_x, delta_y, viewport_height):
            if viewport_height <= 0:
                return None
            state = self.engine.window.camera.state
            position = tuple(state.position)
            focal_point = tuple(state.focal_point)
            forward = tuple(focal_point[index] - position[index]
                            for index in range(3))
            distance = math.sqrt(sum(value * value for value in forward))
            if distance <= 0:
                return None
            forward = tuple(value / distance for value in forward)
            view_up = tuple(state.view_up)
            right = (
                forward[1] * view_up[2] - forward[2] * view_up[1],
                forward[2] * view_up[0] - forward[0] * view_up[2],
                forward[0] * view_up[1] - forward[1] * view_up[0],
            )
            right_length = math.sqrt(sum(value * value for value in right))
            if right_length <= 0:
                return None
            right = tuple(value / right_length for value in right)
            camera_up = (
                right[1] * forward[2] - right[2] * forward[1],
                right[2] * forward[0] - right[0] * forward[2],
                right[0] * forward[1] - right[1] * forward[0],
            )
            scale = (2 * distance
                     * math.tan(math.radians(float(state.view_angle)) / 2)
                     / viewport_height)
            return tuple(
                -delta_x * scale * right[index]
                + delta_y * scale * camera_up[index]
                for index in range(3))

        def queue_pan(self, delta_x, delta_y, viewport_height):
            translation = self._pan_translation(
                delta_x, delta_y, viewport_height)
            if translation is not None:
                self._pan_offset = [
                    self._pan_offset[index] + translation[index]
                    for index in range(3)]
            return self.camera_state()

        def orbit(self, previous, current, viewport_width, viewport_height):
            """Accumulate OrbitControls-style rotation for damped updates."""

            if viewport_width <= 0 or viewport_height <= 0:
                return self.camera_state()
            delta_x = float(current[0]) - float(previous[0])
            delta_y = float(current[1]) - float(previous[1])
            self._orbit_delta_theta -= (
                2 * math.pi * delta_x / viewport_height)
            self._orbit_delta_phi -= (
                2 * math.pi * delta_y / viewport_height)
            return self.camera_state()

        def advance_controls(self, damping_factor=0.05):
            """Advance camera motion using OrbitControls' damping factor."""

            damping_factor = min(1.0, max(0.0, float(damping_factor)))
            theta = self._orbit_delta_theta * damping_factor
            phi = self._orbit_delta_phi * damping_factor
            translation = tuple(
                value * damping_factor for value in self._pan_offset)
            moved = (abs(theta) > 1e-12 or abs(phi) > 1e-12
                     or any(abs(value) > 1e-12 for value in translation))
            if moved:
                self._apply_orbit(theta, phi)
                state = self.engine.window.camera.state
                state.position = tuple(
                    state.position[index] + translation[index]
                    for index in range(3))
                state.focal_point = tuple(
                    state.focal_point[index] + translation[index]
                    for index in range(3))
                self.engine.window.camera.state = state

            decay = 1.0 - damping_factor
            self._orbit_delta_theta *= decay
            self._orbit_delta_phi *= decay
            self._pan_offset = [
                value * decay for value in self._pan_offset]
            pending = (
                abs(self._orbit_delta_theta) > 1e-5
                or abs(self._orbit_delta_phi) > 1e-5
                or any(abs(value) > 1e-5 for value in self._pan_offset))
            if not pending:
                self.cancel_pending_controls()
            return self.camera_state(), pending

        def _apply_orbit(self, theta_delta, phi_delta):
            state = self.engine.window.camera.state
            axis = {'X': 0, 'Y': 1, 'Z': 2}.get(
                self._up_axis or 'Z', 2)
            up = tuple(1.0 if index == axis else 0.0
                       for index in range(3))
            forward = {
                0: (0.0, 0.0, 1.0),
                1: (0.0, 0.0, 1.0),
                2: (0.0, -1.0, 0.0),
            }[axis]
            right = (
                up[1] * forward[2] - up[2] * forward[1],
                up[2] * forward[0] - up[0] * forward[2],
                up[0] * forward[1] - up[1] * forward[0],
            )
            offset = tuple(
                state.position[index] - state.focal_point[index]
                for index in range(3))
            distance = math.sqrt(sum(value * value for value in offset))
            if distance <= 1e-10:
                return
            theta = math.atan2(
                sum(offset[i] * right[i] for i in range(3)),
                sum(offset[i] * forward[i] for i in range(3)))
            phi = math.acos(min(1.0, max(
                -1.0, sum(offset[i] * up[i] for i in range(3))
                / distance)))
            theta += theta_delta
            phi = min(math.pi - 1e-6, max(1e-6, phi + phi_delta))
            sin_phi = math.sin(phi)
            offset = tuple(distance * (
                right[i] * sin_phi * math.sin(theta)
                + up[i] * math.cos(phi)
                + forward[i] * sin_phi * math.cos(theta))
                for i in range(3))
            state.position = tuple(
                state.focal_point[i] + offset[i] for i in range(3))
            view_forward = tuple(-value / distance for value in offset)
            camera_right = (
                view_forward[1] * up[2] - view_forward[2] * up[1],
                view_forward[2] * up[0] - view_forward[0] * up[2],
                view_forward[0] * up[1] - view_forward[1] * up[0],
            )
            right_length = math.sqrt(sum(
                value * value for value in camera_right))
            camera_right = tuple(
                value / right_length for value in camera_right)
            state.view_up = (
                camera_right[1] * view_forward[2]
                - camera_right[2] * view_forward[1],
                camera_right[2] * view_forward[0]
                - camera_right[0] * view_forward[2],
                camera_right[0] * view_forward[1]
                - camera_right[1] * view_forward[0],
            )
            self.engine.window.camera.state = state

        def cancel_pending_controls(self):
            self._orbit_delta_theta = 0.0
            self._orbit_delta_phi = 0.0
            self._pan_offset = [0.0, 0.0, 0.0]

        def dolly(self, distance_factor):
            state = self.engine.window.camera.state
            focal_point = tuple(state.focal_point)
            offset = tuple(
                state.position[index] - focal_point[index]
                for index in range(3))
            distance = math.sqrt(sum(value * value for value in offset))
            if distance <= 1e-10:
                return self.camera_state()
            factor = max(1e-4, float(distance_factor))
            new_distance = max(1e-4, distance * factor)
            state.position = tuple(
                focal_point[index] + offset[index] * new_distance
                / distance for index in range(3))
            self.engine.window.camera.state = state
            return self.camera_state()

        def set_view_preset(self, preset):
            top_axis = (self._up_axis or 'Z').lower()
            side_axis = {'X': 'y', 'Y': 'x', 'Z': 'x'}[
                self._up_axis or 'Z']
            views = {
                'top': (top_axis, True),
                'right': (side_axis, True),
                'left': (side_axis, False),
                'bottom': (top_axis, False),
            }
            if preset not in views:
                raise ValueError(f'Unsupported camera view preset: {preset}')
            return self.set_axis_view(*views[preset])

        def begin_interaction(self, button, x, y):
            interactor = self.engine.interactor
            buttons = {
                'left': interactor.MouseButton.LEFT,
                'middle': interactor.MouseButton.MIDDLE,
                'right': interactor.MouseButton.RIGHT,
            }
            interactor.trigger_mouse_position(x, y)
            interactor.trigger_mouse_button(
                interactor.InputAction.PRESS, buttons[button])

        def update_interaction(self, x, y):
            self.engine.interactor.trigger_mouse_position(x, y)

        def end_interaction(self, button, x, y):
            interactor = self.engine.interactor
            buttons = {
                'left': interactor.MouseButton.LEFT,
                'middle': interactor.MouseButton.MIDDLE,
                'right': interactor.MouseButton.RIGHT,
            }
            interactor.trigger_mouse_position(x, y)
            interactor.trigger_mouse_button(
                interactor.InputAction.RELEASE, buttons[button])
            return self.camera_state()

        def scroll_interaction(self, direction, x, y):
            factors = {'forward': 0.95, 'backward': 1 / 0.95}
            if direction not in factors:
                raise ValueError(f'Unsupported scroll direction: {direction}')
            return self.dolly(factors[direction])

        def close(self):
            self.engine = None
            if self.temporary_file is not None:
                try:
                    os.unlink(self.temporary_file)
                except FileNotFoundError:
                    pass
                self.temporary_file = None
