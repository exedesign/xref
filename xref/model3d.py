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

"""Parsers and a small software renderer for simple 3D model formats.

Supported formats (parsed without any external dependency):

* OBJ  - vertices + faces (triangles and polygons, fan triangulated)
* STL  - binary and ASCII (triangles + normals)
* PLY  - ASCII and binary little endian (triangles and quads)

FBX is only loaded if the optional ``pyassimp``/``assimp`` wrapper is
installed; FBX is a closed format and not parsed here.
"""

import logging
import os.path
import struct

logger = logging.getLogger(__name__)

MODEL_EXTENSIONS = ('.obj', '.stl', '.ply', '.fbx', '.glb', '.gltf', '.usdz')


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
    if ext == '.usdz':
        return _parse_usdz(data)
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
        return _parse_usdz(data)
    raise ValueError('Unsupported 3D format')


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

def _parse_usdz(data):
    """Parses USDZ archives (a zip containing USDA/USDC payloads).

    USDA (ASCII) meshes are parsed natively: ``point3f[] points`` arrays
    plus ``faceVertexIndices``/``faceVertexCounts``. USDC (binary crate)
    payloads fall back to the optional pyassimp package.
    """

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

    # No ASCII payload: USDC needs the assimp library; give a clear hint
    raise ValueError(
        'This USDZ file stores its mesh as binary USDC, which needs the '
        'assimp library. Convert it to OBJ/GLB, or install assimp.')


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
    """Reduces the triangle count by keeping every n-th triangle.

    The kept triangles are re-indexed onto only the vertices they use, so
    the projection and shading loops scale with the kept triangles, not
    with the size of the original mesh. The overall silhouette stays the
    same, which is enough for a reference board.
    """

    triangles = mesh['triangles']
    if len(triangles) <= max_triangles:
        return mesh
    step = len(triangles) / float(max_triangles)
    kept = []
    index = 0.0
    while int(index) < len(triangles):
        kept.append(triangles[int(index)])
        index += step
    vertices = mesh['vertices']
    remap = {}
    new_vertices = []
    new_triangles = []
    for a, b, c in kept:
        corner = []
        for old in (a, b, c):
            new = remap.get(old)
            if new is None:
                new = len(new_vertices) // 3
                remap[old] = new
                new_vertices.extend(
                    (vertices[old * 3], vertices[old * 3 + 1],
                     vertices[old * 3 + 2]))
            corner.append(new)
        new_triangles.append(tuple(corner))
    return {'vertices': new_vertices, 'triangles': new_triangles}




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
