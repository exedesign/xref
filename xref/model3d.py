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
import struct

logger = logging.getLogger(__name__)

MODEL_EXTENSIONS = ('.obj', '.stl', '.ply', '.fbx')


def parse_model(data, filename=None):
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
    if ext == '.fbx':
        return _parse_fbx(data)
    # Unknown extension: sniff the content
    if data[:5] == b'solid':
        return _parse_stl(data)
    if b'ply' in data[:64]:
        return _parse_ply(data)
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


# -- FBX (optional via pyassimp) ----------------------------------------------

def _parse_fbx(data):
    try:
        import pyassimp  # noqa: F401 - optional dependency
    except ImportError:
        raise ValueError(
            'FBX support needs the optional pyassimp package')
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix='.fbx', delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        with pyassimp.load(path) as scene:
            vertices = []
            triangles = []
            for mesh in scene.meshes:
                base = len(vertices) // 3
                verts = mesh.vertices
                for i in range(len(verts)):
                    vertices.append(float(verts[i][0]))
                    vertices.append(float(verts[i][1]))
                    vertices.append(float(verts[i][2]))
                faces = mesh.faces
                for face in faces:
                    count = len(face)
                    for i in range(1, count - 1):
                        triangles.append(
                            (face[0] + base, face[i] + base,
                             face[i + 1] + base))
        return {'vertices': vertices, 'triangles': triangles}
    finally:
        os.unlink(path)


# -- Geometry helpers ----------------------------------------------------------

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
