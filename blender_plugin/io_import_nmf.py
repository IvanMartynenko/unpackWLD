bl_info = {
    "name": "Neo Model Format (NMF) Importer",
    "author": "Claude",
    "version": (1, 0, 0),
    "blender": (3, 3, 0),
    "location": "File > Import > Neo Model (.nmf)",
    "description": (
        "Import NMF (.nmf) scene files: node hierarchy, meshes (UV0/UV1/source UV, "
        "normals, per-triangle materials), materials & textures (incl. texture-atlas "
        "pages), node keyframe animation, joint orientation, vertex (shape-key) "
        "animation and collision meshes."
    ),
    "category": "Import-Export",
}

import struct
import os
import math
from dataclasses import dataclass, field
from collections import Counter

import bpy
import bmesh
from bpy.props import (
    StringProperty,
    BoolProperty,
    FloatProperty,
    CollectionProperty,
)
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Vector, Euler, Quaternion


# =============================================================================
# 1. Binary parser
#
# Reverse engineered from NMF_SPEC.MD and validated byte-for-byte (payload_size
# accounting) against real .nmf files. Two spots needed corrections relative to
# a literal reading of the spec text:
#
#   - The optional per-node `Animation` marker (ROOT/FRAM/JOIN): when the 4
#     marker bytes are not "ANIM", they are still part of the payload (a
#     "no animation" sentinel) and must be consumed, not rewound.
#   - MeshNode: after the `vertex_animations` chain, the terminating
#     non-"ANIM" 4 bytes are a *discarded* chain terminator - they are NOT
#     reused as `collision_vertex_count` (a literal reading of the spec's
#     wording here does not match real files).
# =============================================================================

MAGIC = b'NMF '
END_MARKER = b'END '


class NMFParseError(Exception):
    pass


def _read(f, n):
    d = f.read(n)
    if len(d) != n:
        raise NMFParseError(f"Unexpected EOF: wanted {n} bytes, got {len(d)}")
    return d


def _i32(f):
    return struct.unpack('<i', _read(f, 4))[0]


def _u32be(f):
    return struct.unpack('>I', _read(f, 4))[0]


def _f32(f):
    return struct.unpack('<f', _read(f, 4))[0]


def _vec2(f):
    return struct.unpack('<2f', _read(f, 8))


def _vec3(f):
    return struct.unpack('<3f', _read(f, 12))


def _mat4(f):
    return struct.unpack('<16f', _read(f, 64))


def _color4(f):
    return struct.unpack('<4f', _read(f, 16))


def _floats(f, n):
    if n == 0:
        return ()
    return struct.unpack(f'<{n}f', _read(f, 4 * n))


def _int32s(f, n):
    if n == 0:
        return ()
    return struct.unpack(f'<{n}i', _read(f, 4 * n))


def _uint16s(f, n):
    if n == 0:
        return ()
    return struct.unpack(f'<{n}H', _read(f, 2 * n))


def read_cstring(f):
    raw = bytearray()
    while True:
        b = f.read(1)
        if not b:
            raise NMFParseError("Unexpected EOF while reading string")
        if b == b'\x00':
            break
        raw += b
    total = len(raw) + 1
    pad = (-total) % 4
    if pad:
        _read(f, pad)
    return raw.decode('cp1252', errors='replace')


@dataclass
class Curve:
    times: tuple
    values: tuple


def _read_curve(f, key_count):
    times = _floats(f, key_count)
    values = _floats(f, key_count)
    return Curve(times, values)


ANIM_CHANNELS_NODE = ('tx', 'ty', 'tz', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz')


@dataclass
class Animation:
    interpolation: int
    curves: dict


def _read_animation(f):
    interpolation = _i32(f)
    key_counts = _int32s(f, 9)
    curves = {}
    for name, kc in zip(ANIM_CHANNELS_NODE, key_counts):
        if kc > 0:
            curves[name] = _read_curve(f, kc)
    return Animation(interpolation, curves)


def _maybe_read_animation(f, payload_end):
    if payload_end - f.tell() < 4:
        return None
    marker = _read(f, 4)
    if marker == b'ANIM':
        return _read_animation(f)
    return None  # sentinel bytes already consumed


@dataclass
class TransformPayload:
    local_matrix: tuple
    translation: tuple
    scale: tuple
    rotation: tuple
    rotate_pivot_translate: tuple
    rotate_pivot: tuple
    scale_pivot_translate: tuple
    scale_pivot: tuple
    shear: tuple
    animation: object


def _read_transform_payload(f, payload_end):
    local_matrix = _mat4(f)
    translation = _vec3(f)
    scale = _vec3(f)
    rotation = _vec3(f)
    rotate_pivot_translate = _vec3(f)
    rotate_pivot = _vec3(f)
    scale_pivot_translate = _vec3(f)
    scale_pivot = _vec3(f)
    shear = _vec3(f)
    animation = _maybe_read_animation(f, payload_end)
    return TransformPayload(local_matrix, translation, scale, rotation,
                             rotate_pivot_translate, rotate_pivot,
                             scale_pivot_translate, scale_pivot, shear, animation)


@dataclass
class JointPayload:
    local_matrix: tuple
    translation: tuple
    scale: tuple
    rotation: tuple
    joint_orient_matrix: tuple
    rotation_limit_min: tuple
    rotation_limit_max: tuple
    animation: object


def _read_joint_payload(f, payload_end):
    local_matrix = _mat4(f)
    translation = _vec3(f)
    scale = _vec3(f)
    rotation = _vec3(f)
    joint_orient_matrix = _mat4(f)
    rotation_limit_min = _vec3(f)
    rotation_limit_max = _vec3(f)
    animation = _maybe_read_animation(f, payload_end)
    return JointPayload(local_matrix, translation, scale, rotation,
                         joint_orient_matrix, rotation_limit_min, rotation_limit_max, animation)


@dataclass
class TextureReference:
    kind: str  # 'TXPG', 'TEXT', or 'NONE'
    name: str
    page: int
    index_on_page: int
    atlas_rect: tuple


def _read_texture_reference(f):
    kind_bytes = _read(f, 4)
    if kind_bytes == b'TXPG':
        name = read_cstring(f)
        page = _i32(f)
        index_on_page = _i32(f)
        atlas_rect = _int32s(f, 4)
        return TextureReference('TXPG', name, page, index_on_page, atlas_rect)
    elif kind_bytes == b'TEXT':
        name = read_cstring(f)
        return TextureReference('TEXT', name, -1, -1, None)
    else:
        return TextureReference('NONE', '', -1, -1, None)


@dataclass
class Material:
    name: str
    blend_mode: int
    vertex_offset: int
    vertex_count: int
    index_offset: int
    index_count: int
    uv_flip_u: int
    uv_flip_v: int
    uv_rotation: int
    uv_scale_u: float
    uv_scale_v: float
    diffuse: tuple
    ambient: tuple
    specular: tuple
    emissive: tuple
    specular_power: float
    texture: object


def _read_material(f):
    marker = _read(f, 4)
    if marker != b'MTRL':
        raise NMFParseError(f"Expected MTRL marker, got {marker!r}")
    name = read_cstring(f)
    blend_mode = _i32(f)
    vertex_offset = _i32(f)
    vertex_count = _i32(f)
    index_offset = _i32(f)
    index_count = _i32(f)
    uv_flip_u = _i32(f)
    uv_flip_v = _i32(f)
    uv_rotation = _i32(f)
    uv_scale_u = _f32(f)
    uv_scale_v = _f32(f)
    diffuse = _color4(f)
    ambient = _color4(f)
    specular = _color4(f)
    emissive = _color4(f)
    specular_power = _f32(f)
    texture = _read_texture_reference(f)
    return Material(name, blend_mode, vertex_offset, vertex_count, index_offset, index_count,
                     uv_flip_u, uv_flip_v, uv_rotation, uv_scale_u, uv_scale_v,
                     diffuse, ambient, specular, emissive, specular_power, texture)


ANIM_CHANNELS_VERTEX = ('x', 'y', 'z')


@dataclass
class VertexAnimationClip:
    interpolation: int
    vertex_indices: tuple
    rest_position: tuple
    delta_curves: dict


def _read_vertex_animation_clip(f):
    interpolation = _i32(f)
    vertex_count = _i32(f)
    vertex_indices = _int32s(f, vertex_count)
    rest_position = _vec3(f)
    key_counts = _int32s(f, 3)
    curves = {}
    for name, kc in zip(ANIM_CHANNELS_VERTEX, key_counts):
        if kc > 0:
            curves[name] = _read_curve(f, kc)
    return VertexAnimationClip(interpolation, vertex_indices, rest_position, curves)


@dataclass
class Vertex:
    position: tuple
    normal: tuple
    uv0: tuple
    uv1: tuple


@dataclass
class MeshPayload:
    vertices: list
    source_uv: list
    indices: tuple
    backface_culling: int
    complex_: int
    inside: int
    smooth: int
    light_flare: int
    materials: list
    vertex_animation_clips: list
    collision_vertices: tuple
    collision_indices: tuple


def _read_mesh_payload(f, payload_end):
    triangle_count = _i32(f)
    vertex_count = _i32(f)
    vertices = []
    for _ in range(vertex_count):
        position = _vec3(f)
        normal = _vec3(f)
        uv0 = _vec2(f)
        uv1 = _vec2(f)
        vertices.append(Vertex(position, normal, uv0, uv1))
    source_uv = [_vec2(f) for _ in range(vertex_count)]
    index_count = _i32(f)
    indices = _uint16s(f, index_count)
    if index_count % 2 == 1:
        _read(f, 2)  # alignment pad
    backface_culling = _i32(f)
    complex_ = _i32(f)
    inside = _i32(f)
    smooth = _i32(f)
    light_flare = _i32(f)
    material_count = _i32(f)
    materials = [_read_material(f) for _ in range(material_count)]

    vertex_animation_clips = []
    while payload_end - f.tell() >= 4:
        marker = _read(f, 4)
        if marker == b'ANIM':
            vertex_animation_clips.append(_read_vertex_animation_clip(f))
        else:
            break  # discarded chain terminator

    collision_vertex_count = _i32(f)
    collision_vertices = tuple(_vec3(f) for _ in range(collision_vertex_count)) if collision_vertex_count > 0 else ()
    collision_index_count = _i32(f)
    collision_indices = _int32s(f, collision_index_count) if collision_index_count > 0 else ()

    return MeshPayload(vertices, source_uv, indices, backface_culling, complex_, inside,
                        smooth, light_flare, materials, vertex_animation_clips,
                        collision_vertices, collision_indices), triangle_count


@dataclass
class LocatorPayload:
    pass


@dataclass
class Node:
    type: str
    version: int
    parent: int
    name: str
    payload: object
    triangle_count: int = 0  # MESH only


@dataclass
class NMFFile:
    nodes: list


def parse_nmf(f):
    magic = _read(f, 4)
    if magic != MAGIC:
        raise NMFParseError(f"Not an NMF file (bad magic {magic!r})")
    _i32(f)  # reserved
    nodes = []
    while True:
        tag = _read(f, 4)
        if tag == END_MARKER:
            _i32(f)  # reserved
            break
        if tag not in (b'ROOT', b'LOCA', b'FRAM', b'JOIN', b'MESH'):
            raise NMFParseError(f"Unknown node type {tag!r} at offset {f.tell() - 4}")
        payload_size = _u32be(f)
        hdr_end = f.tell()
        version = _i32(f)
        parent = _i32(f)
        name = read_cstring(f)
        payload_end = hdr_end + payload_size
        node_type = tag.decode('ascii')
        triangle_count = 0
        payload = None
        try:
            if node_type in ('ROOT', 'FRAM'):
                payload = _read_transform_payload(f, payload_end)
            elif node_type == 'JOIN':
                payload = _read_joint_payload(f, payload_end)
            elif node_type == 'LOCA':
                payload = LocatorPayload()
            elif node_type == 'MESH':
                payload, triangle_count = _read_mesh_payload(f, payload_end)
        except NMFParseError as e:
            print(f"NMF import: warning - failed to parse node {len(nodes)} "
                  f"({node_type} '{name}'): {e}")
            payload = None
        nodes.append(Node(node_type, version, parent, name, payload, triangle_count))
        # Resync regardless of parse success/failure - payload_size is authoritative.
        f.seek(payload_end)
    return NMFFile(nodes)


# =============================================================================
# 2. Matrix / curve math helpers
#
# NMF matrices are row-major and used in a row-vector convention (v' = v @ M,
# matrices composed left-to-right in the order they are applied), matching
# Maya/D3D. Validated empirically: for a non-animated node, the upper-left 3x3
# of `local_matrix` equals Diag(scale) @ Rx(rx) @ Ry(ry) @ Rz(rz) (X applied
# first) using row-vector rotation matrices, and translation sits in the last
# row. Transposing such a matrix once converts it losslessly into Blender's
# column-vector convention (v' = M @ v); after transposing, the same rotation
# field values can be fed directly into mathutils.Euler(..., 'XYZ').
# =============================================================================

def nmf_mat_to_blender(vals16):
    rows = [vals16[0:4], vals16[4:8], vals16[8:12], vals16[12:16]]
    return Matrix(rows).transposed()


def _is_zero_vec(v, eps=1e-6):
    return abs(v[0]) < eps and abs(v[1]) < eps and abs(v[2]) < eps


_IDENTITY16 = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def _is_identity_mat16(vals16, eps=1e-5):
    return all(abs(a - b) < eps for a, b in zip(vals16, _IDENTITY16))


def euler_to_mat(rx, ry, rz):
    return Euler((rx, ry, rz), 'XYZ').to_matrix().to_4x4()


def shear_to_mat(shear):
    shxy, shxz, shyz = shear
    m = Matrix.Identity(4)
    m[0][1] = shxy
    m[0][2] = shxz
    m[1][2] = shyz
    return m


def build_pivot_matrix(t, r, s, rotate_pivot, rotate_pivot_translate,
                        scale_pivot, scale_pivot_translate, shear):
    """Full Maya-style TRS+pivot+shear formula, transposed into Blender's
    column-vector convention. Reduces to Translation(t) @ Euler(r) @ Diag(s)
    when all pivots/shear are zero."""
    T = Matrix.Translation(t)
    Rpt = Matrix.Translation(rotate_pivot_translate)
    Rp = Matrix.Translation(rotate_pivot)
    RpInv = Matrix.Translation(-Vector(rotate_pivot))
    R = euler_to_mat(*r)
    Spt = Matrix.Translation(scale_pivot_translate)
    Sp = Matrix.Translation(scale_pivot)
    SpInv = Matrix.Translation(-Vector(scale_pivot))
    Sh = shear_to_mat(shear)
    S = Matrix.Diagonal((s[0], s[1], s[2], 1.0))
    return T @ Rpt @ Rp @ R @ RpInv @ Spt @ Sp @ Sh @ S @ SpInv


def eval_curve_at(curve, t, interpolation):
    times, values = curve.times, curve.values
    n = len(times)
    if n == 0:
        return None
    if n == 1 or t <= times[0]:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    for i in range(n - 1):
        t0, t1 = times[i], times[i + 1]
        if t0 <= t <= t1:
            v0, v1 = values[i], values[i + 1]
            f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            if interpolation == 1:
                f = 0.5 - 0.5 * math.cos(f * math.pi)
            return v0 + (v1 - v0) * f
    return values[-1]


def eval_channel(curve, static_val, t, interpolation):
    if curve is None or len(curve.times) == 0:
        return static_val
    return eval_curve_at(curve, t, interpolation)


def union_times(curves_dict):
    times = set()
    for c in curves_dict.values():
        times.update(c.times)
    return sorted(times) if times else [0.0]


def make_quat_continuous(quat, prev_quat):
    """A quaternion and its negation represent the same rotation, but keyframing
    whichever one a fresh decompose()/to_quaternion() happens to produce at each
    sample - independently, with no memory of the previous sample - can flip
    sign between consecutive keyframes. Blender then interpolates "the long way
    round" between them, which looks like a sudden broken snap/spin on
    playback. Flip back to match the previous sample's hemisphere so the curve
    stays continuous."""
    if prev_quat is not None and prev_quat.dot(quat) < 0:
        return -quat
    return quat


def _iter_action_fcurves(anim):
    """Yield an id_data's current action's fcurves, across Blender API versions.

    Blender <4.4: Action.fcurves is a flat collection.
    Blender >=4.4 ("layered" Actions): fcurves live under
    action.layers[*].strips[*].channelbag(slot).fcurves instead, and the flat
    Action.fcurves accessor may not exist at all (removed in later releases).
    """
    action = anim.action
    if hasattr(action, "fcurves"):
        yield from action.fcurves
        return
    slot = getattr(anim, "action_slot", None)
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            get_channelbag = getattr(strip, "channelbag", None)
            if get_channelbag is None:
                continue
            channelbag = None
            try:
                channelbag = get_channelbag(slot) if slot is not None else None
            except TypeError:
                channelbag = None
            if channelbag is None:
                continue
            yield from channelbag.fcurves


def _apply_interpolation(fc, mode):
    for kp in fc.keyframe_points:
        if mode == 'SINE':
            kp.interpolation = 'SINE'
            kp.easing = 'EASE_IN_OUT'
        else:
            kp.interpolation = 'LINEAR'


def set_fcurve_interpolation(obj_or_id_data, data_path, index, mode):
    anim = obj_or_id_data.animation_data
    if not anim or not anim.action:
        return
    for fc in _iter_action_fcurves(anim):
        if fc.data_path == data_path and fc.array_index == index:
            _apply_interpolation(fc, mode)
            return


def set_all_fcurves_interpolation(obj, mode):
    anim = obj.animation_data
    if not anim or not anim.action:
        return
    for fc in _iter_action_fcurves(anim):
        _apply_interpolation(fc, mode)


def keyframe_axis_prop(obj, prop, index, curve, static_val, fps, interp_mode):
    if curve is None or len(curve.times) == 0:
        getattr(obj, prop)[index] = static_val
        return
    for t, v in zip(curve.times, curve.values):
        getattr(obj, prop)[index] = v
        obj.keyframe_insert(data_path=prop, index=index, frame=t * fps)
    set_fcurve_interpolation(obj, prop, index, interp_mode)


# =============================================================================
# 3. Scene construction
# =============================================================================

@dataclass
class ImportOptions:
    global_scale: float
    fps: float
    import_animation: bool
    import_vertex_animation: bool
    import_collision: bool
    texture_dir: str
    mirror_x: bool = True
    double_sided: bool = False


def apply_transform_node(obj, payload, opts):
    has_anim = opts.import_animation and payload.animation is not None
    if not has_anim:
        obj.matrix_basis = nmf_mat_to_blender(payload.local_matrix)
        return

    curves = payload.animation.curves
    interp_flag = payload.animation.interpolation
    interp = 'SINE' if interp_flag == 1 else 'LINEAR'
    pivots_zero = (_is_zero_vec(payload.rotate_pivot) and
                   _is_zero_vec(payload.rotate_pivot_translate) and
                   _is_zero_vec(payload.scale_pivot) and
                   _is_zero_vec(payload.scale_pivot_translate) and
                   _is_zero_vec(payload.shear))

    if pivots_zero:
        obj.rotation_mode = 'XYZ'
        for i, key in enumerate(('tx', 'ty', 'tz')):
            keyframe_axis_prop(obj, 'location', i, curves.get(key), payload.translation[i], opts.fps, interp)
        for i, key in enumerate(('rx', 'ry', 'rz')):
            keyframe_axis_prop(obj, 'rotation_euler', i, curves.get(key), payload.rotation[i], opts.fps, interp)
        for i, key in enumerate(('sx', 'sy', 'sz')):
            keyframe_axis_prop(obj, 'scale', i, curves.get(key), payload.scale[i], opts.fps, interp)
    else:
        obj.rotation_mode = 'QUATERNION'
        prev_quat = None
        for t in union_times(curves):
            tx = eval_channel(curves.get('tx'), payload.translation[0], t, interp_flag)
            ty = eval_channel(curves.get('ty'), payload.translation[1], t, interp_flag)
            tz = eval_channel(curves.get('tz'), payload.translation[2], t, interp_flag)
            rx = eval_channel(curves.get('rx'), payload.rotation[0], t, interp_flag)
            ry = eval_channel(curves.get('ry'), payload.rotation[1], t, interp_flag)
            rz = eval_channel(curves.get('rz'), payload.rotation[2], t, interp_flag)
            sx = eval_channel(curves.get('sx'), payload.scale[0], t, interp_flag)
            sy = eval_channel(curves.get('sy'), payload.scale[1], t, interp_flag)
            sz = eval_channel(curves.get('sz'), payload.scale[2], t, interp_flag)
            M = build_pivot_matrix((tx, ty, tz), (rx, ry, rz), (sx, sy, sz),
                                    payload.rotate_pivot, payload.rotate_pivot_translate,
                                    payload.scale_pivot, payload.scale_pivot_translate, payload.shear)
            loc, quat, scale = M.decompose()
            quat = make_quat_continuous(quat, prev_quat)
            prev_quat = quat
            frame = t * opts.fps
            obj.location = loc
            obj.keyframe_insert('location', frame=frame)
            obj.rotation_quaternion = quat
            obj.keyframe_insert('rotation_quaternion', frame=frame)
            obj.scale = scale
            obj.keyframe_insert('scale', frame=frame)
        set_all_fcurves_interpolation(obj, 'LINEAR')


def build_fram_pivot_chain(node, payload, opts, coll):
    """Expand an animated FRAM node into an explicit Maya-style pivot rig instead
    of approximating it on a single object:

        {name}                       - animated translation
          .rotatePivotTranslate      - static
            .rotatePivot             - static offset + animated rotation
              .scalePivotTranslate   - static (undoes rotatePivot, via matrix_parent_inverse)
                .scalePivot          - static offset + animated scale (+ shear, if any)

    This mirrors Maya's TRS+pivot formula (see build_pivot_matrix) term-for-term
    using real, individually named/editable empties instead of a single sampled
    object - one node per static pivot field (rotate_pivot_translate, rotate_pivot,
    scale_pivot_translate, scale_pivot, shear). Rotation is co-located with
    rotatePivot and scale with scalePivot, exactly like a hand-built pivot rig
    (create an empty at the pivot, parent the content to it, animate the empty).

    The two pivot "undo" terms required by Maya's formula (RotatePivot^-1 and
    ScalePivot^-1) don't get their own visible nodes: the first is folded into
    scalePivotTranslate's matrix_parent_inverse, the second is returned as
    child_correction for the caller to apply to this node's own NMF children.

    Returns (outer_obj, inner_obj, child_correction):
      outer_obj - what this node's own NMF parent attaches to.
      inner_obj - what this node's NMF children attach to.
      child_correction - Matrix to set as those children's matrix_parent_inverse,
      or None if scale_pivot is zero (no correction needed).
    """
    name = node.name or 'FRAM'
    curves = payload.animation.curves
    interp_flag = payload.animation.interpolation
    interp = 'SINE' if interp_flag == 1 else 'LINEAR'

    def new_empty(nm, size=0.06):
        o = bpy.data.objects.new(nm, None)
        o.empty_display_type = 'PLAIN_AXES'
        o.empty_display_size = size
        coll.objects.link(o)
        o["nmf_type"] = "FRAM_PIVOT"
        return o

    main = new_empty(name, size=0.1)
    main["nmf_type"] = "FRAM"
    main.rotation_mode = 'XYZ'
    for i, key in enumerate(('tx', 'ty', 'tz')):
        keyframe_axis_prop(main, 'location', i, curves.get(key), payload.translation[i], opts.fps, interp)

    rpt = new_empty(f"{name}.rotatePivotTranslate")
    rpt.parent = main
    rpt.location = payload.rotate_pivot_translate

    rp = new_empty(f"{name}.rotatePivot")
    rp.parent = rpt
    rp.location = payload.rotate_pivot
    rp.rotation_mode = 'XYZ'
    for i, key in enumerate(('rx', 'ry', 'rz')):
        keyframe_axis_prop(rp, 'rotation_euler', i, curves.get(key), payload.rotation[i], opts.fps, interp)

    spt = new_empty(f"{name}.scalePivotTranslate")
    spt.parent = rp
    if not _is_zero_vec(payload.rotate_pivot):
        spt.matrix_parent_inverse = Matrix.Translation(-Vector(payload.rotate_pivot))
    spt.location = payload.scale_pivot_translate

    sp = new_empty(f"{name}.scalePivot")
    sp.parent = spt

    if _is_zero_vec(payload.shear):
        sp.location = payload.scale_pivot
        sp.rotation_mode = 'XYZ'
        for i, key in enumerate(('sx', 'sy', 'sz')):
            keyframe_axis_prop(sp, 'scale', i, curves.get(key), payload.scale[i], opts.fps, interp)
    else:
        # Rare case: shear can't be expressed as a plain loc/rot/scale channel, so
        # this last segment (scale_pivot -> shear -> scale) is baked by sampling.
        sp.rotation_mode = 'QUATERNION'
        Sp_b = Matrix.Translation(payload.scale_pivot)
        Sh_b = shear_to_mat(payload.shear)
        scale_curves = {k: curves[k] for k in ('sx', 'sy', 'sz') if k in curves}
        prev_quat = None
        for t in union_times(scale_curves):
            sx = eval_channel(curves.get('sx'), payload.scale[0], t, interp_flag)
            sy = eval_channel(curves.get('sy'), payload.scale[1], t, interp_flag)
            sz = eval_channel(curves.get('sz'), payload.scale[2], t, interp_flag)
            M = Sp_b @ Sh_b @ Matrix.Diagonal((sx, sy, sz, 1.0))
            loc, quat, scale = M.decompose()
            quat = make_quat_continuous(quat, prev_quat)
            prev_quat = quat
            frame = t * opts.fps
            sp.location = loc
            sp.keyframe_insert('location', frame=frame)
            sp.rotation_quaternion = quat
            sp.keyframe_insert('rotation_quaternion', frame=frame)
            sp.scale = scale
            sp.keyframe_insert('scale', frame=frame)
        set_all_fcurves_interpolation(sp, 'LINEAR')

    child_correction = None
    if not _is_zero_vec(payload.scale_pivot):
        child_correction = Matrix.Translation(-Vector(payload.scale_pivot))

    return main, sp, child_correction


def compute_static_joint_matrix(payload):
    """Non-animated JOIN local matrix.

    `joint_orient_matrix` is deliberately NOT applied here. It reads like it
    should be (per a literal reading of the spec's JointNode remarks), and an
    earlier version of this function did apply it - but the engine's own
    joint_orient-composition code only ever runs while sampling keyframed
    rotation curves; a non-animated joint's `local_matrix` already has its
    complete rest transform baked in by the exporter, and joint_orient is
    simply never consulted for it. Applying it here anyway double-counts a
    rotation that's already inside `local_matrix`, which for this format's
    typical ~90 degree joint_orient values means every non-animated joint in
    a chain comes out rotated ~90 degrees from where it belongs - and since
    joints chain, that compounds into the rest of that branch collapsing
    into the wrong place entirely."""
    return nmf_mat_to_blender(payload.local_matrix)


def apply_joint_node(obj, payload, opts):
    obj["nmf_rotation_limit_min"] = tuple(payload.rotation_limit_min)
    obj["nmf_rotation_limit_max"] = tuple(payload.rotation_limit_max)

    jo_identity = _is_identity_mat16(payload.joint_orient_matrix)
    jo_mat = nmf_mat_to_blender(payload.joint_orient_matrix)

    has_anim = opts.import_animation and payload.animation is not None

    if not has_anim:
        obj.matrix_basis = compute_static_joint_matrix(payload)
        return

    curves = payload.animation.curves
    interp_flag = payload.animation.interpolation
    interp = 'SINE' if interp_flag == 1 else 'LINEAR'

    if jo_identity:
        obj.rotation_mode = 'XYZ'
        for i, key in enumerate(('tx', 'ty', 'tz')):
            keyframe_axis_prop(obj, 'location', i, curves.get(key), payload.translation[i], opts.fps, interp)
        for i, key in enumerate(('rx', 'ry', 'rz')):
            keyframe_axis_prop(obj, 'rotation_euler', i, curves.get(key), payload.rotation[i], opts.fps, interp)
        for i, key in enumerate(('sx', 'sy', 'sz')):
            keyframe_axis_prop(obj, 'scale', i, curves.get(key), payload.scale[i], opts.fps, interp)
    else:
        obj.rotation_mode = 'QUATERNION'
        jo3 = jo_mat.to_3x3()
        prev_quat = None
        for t in union_times(curves):
            tx = eval_channel(curves.get('tx'), payload.translation[0], t, interp_flag)
            ty = eval_channel(curves.get('ty'), payload.translation[1], t, interp_flag)
            tz = eval_channel(curves.get('tz'), payload.translation[2], t, interp_flag)
            rx = eval_channel(curves.get('rx'), payload.rotation[0], t, interp_flag)
            ry = eval_channel(curves.get('ry'), payload.rotation[1], t, interp_flag)
            rz = eval_channel(curves.get('rz'), payload.rotation[2], t, interp_flag)
            sx = eval_channel(curves.get('sx'), payload.scale[0], t, interp_flag)
            sy = eval_channel(curves.get('sy'), payload.scale[1], t, interp_flag)
            sz = eval_channel(curves.get('sz'), payload.scale[2], t, interp_flag)
            R3 = euler_to_mat(rx, ry, rz).to_3x3()
            quat = (jo3 @ R3).to_quaternion()
            quat = make_quat_continuous(quat, prev_quat)
            prev_quat = quat
            frame = t * opts.fps
            obj.location = (tx, ty, tz)
            obj.keyframe_insert('location', frame=frame)
            obj.rotation_quaternion = quat
            obj.keyframe_insert('rotation_quaternion', frame=frame)
            obj.scale = (sx, sy, sz)
            obj.keyframe_insert('scale', frame=frame)
        set_all_fcurves_interpolation(obj, 'LINEAR')


def get_principled(mat):
    for n in mat.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None


def _set_input(bsdf, names, value):
    for name in names:
        if name in bsdf.inputs:
            bsdf.inputs[name].default_value = value
            return


def _decode_dds_uncompressed_16bit(path):
    """Decodes an uncompressed 16-bit DDS (RGB555 or ARGB1555) directly,
    bypassing Blender's own DDS reader entirely.

    Every file in texture_pages (349/349 sampled) is this exact format:
    fourcc all-zero (uncompressed), 16 bits/pixel, R=0x7C00 G=0x03E0
    B=0x001F, with A either absent or 0x8000 - not DXT/BC-compressed, and
    not a bit depth/channel layout Blender's DDS support is guaranteed to
    handle consistently across builds. Decoding it by hand here removes
    that dependency for the common case; returns None (falls back to
    bpy.data.images.load) for anything that doesn't match this exact
    layout, e.g. a compressed DDS this format doesn't otherwise use.

    Row order: DDS stores row 0 as the texture's top row, and this format's
    own UVs are authored the same way (V=0 = top - confirmed against a
    reference converter for this same engine, which has to flip V because
    *its* pipeline goes through PNG, whose row 0 is also always "top", but
    only after the target format's consumer separately assumes V=0 is
    "bottom"). Blender's own image.pixels convention indexes row 0 as V=0
    too, so writing DDS rows here in file order - no vertical flip - lines
    up with this format's V=0-is-top UVs used as-is (see build_mesh_object,
    which does not flip V either).
    """
    with open(path, 'rb') as f:
        magic = f.read(4)
        if magic != b'DDS ':
            return None
        header = f.read(124)
        if len(header) < 124:
            return None
        flags, height, width, pitch, depth, mipmaps = struct.unpack('<6I', header[4:28])
        pf = header[72:104]
        pf_flags, fourcc, rgbbitcount, rmask, gmask, bmask, amask = struct.unpack('<I4s5I', pf[4:32])
        if (fourcc != b'\x00\x00\x00\x00' or rgbbitcount != 16 or
                rmask != 0x7C00 or gmask != 0x03E0 or bmask != 0x001F):
            return None
        if width <= 0 or height <= 0:
            return None
        has_alpha = amask == 0x8000
        raw = f.read(width * height * 2)
        if len(raw) < width * height * 2:
            return None

    pixels = [0.0] * (width * height * 4)
    for i in range(width * height):
        v = raw[2 * i] | (raw[2 * i + 1] << 8)
        o = i * 4
        pixels[o] = ((v >> 10) & 0x1F) / 31.0
        pixels[o + 1] = ((v >> 5) & 0x1F) / 31.0
        pixels[o + 2] = (v & 0x1F) / 31.0
        pixels[o + 3] = 1.0 if (not has_alpha or (v & 0x8000)) else 0.0
    return width, height, pixels


def _load_dds_as_blender_image(path):
    decoded = None
    try:
        decoded = _decode_dds_uncompressed_16bit(path)
    except Exception as e:
        print(f"NMF import: custom DDS decode failed for '{path}': {e}")
    if decoded is not None:
        width, height, pixels = decoded
        img = bpy.data.images.new(os.path.basename(path), width, height, alpha=True)
        img.pixels.foreach_set(pixels)
        img.update()
        img.pack()
        return img
    # Not the uncompressed 16-bit layout this decodes (e.g. DXT/BC-compressed) -
    # fall back to Blender's own DDS reader, whatever this build supports.
    return bpy.data.images.load(path, check_existing=True)


def load_texture_image(tex, texture_dir, nmf_dir, cache):
    if tex.kind == 'TXPG':
        key = ('page', tex.page)
        candidates = [f"{tex.page}.dds"]
        search_dirs = [texture_dir] if texture_dir else []
        search_dirs += [os.path.join(nmf_dir, 'texture_pages'), nmf_dir]
    elif tex.kind == 'TEXT':
        key = ('name', tex.name)
        base = os.path.basename(tex.name.replace('\\', '/'))
        stem = os.path.splitext(base)[0]
        candidates = [base, stem + '.dds', stem + '.png', stem + '.tga', stem + '.jpg']
        search_dirs = [texture_dir] if texture_dir else []
        search_dirs += [nmf_dir, os.path.join(nmf_dir, 'texture_pages')]
    else:
        return None

    if key in cache:
        return cache[key]

    found = None
    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        for fn in candidates:
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                found = p
                break
        if found:
            break

    img = None
    if found:
        try:
            if found.lower().endswith('.dds'):
                img = _load_dds_as_blender_image(found)
            else:
                img = bpy.data.images.load(found, check_existing=True)
        except Exception as e:
            print(f"NMF import: failed to load texture '{found}': {e}")
    cache[key] = img
    return img


def build_material(nmf_mat, mesh_name, index, opts, nmf_dir, material_cache, image_cache):
    cache_key = (nmf_mat.name, nmf_mat.blend_mode, nmf_mat.texture.kind,
                 nmf_mat.texture.name, nmf_mat.texture.page, nmf_mat.diffuse,
                 nmf_mat.specular_power)
    if cache_key in material_cache:
        return material_cache[cache_key]

    name = nmf_mat.name or f"{mesh_name}_mat{index}"
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = get_principled(mat)

    diffuse = nmf_mat.diffuse
    if bsdf:
        _set_input(bsdf, ("Base Color",), (diffuse[0], diffuse[1], diffuse[2], 1.0))
        _set_input(bsdf, ("Alpha",), diffuse[3])
        roughness = 1.0 - min(max(nmf_mat.specular_power / 128.0, 0.0), 1.0)
        _set_input(bsdf, ("Roughness",), roughness)
        emissive = nmf_mat.emissive
        if any(c > 0.0 for c in emissive[:3]):
            _set_input(bsdf, ("Emission Color", "Emission"), (emissive[0], emissive[1], emissive[2], 1.0))
            _set_input(bsdf, ("Emission Strength",), 1.0)

    if nmf_mat.blend_mode != 0:
        if hasattr(mat, "blend_method"):
            mat.blend_method = 'BLEND'
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = 'HASHED'
        if hasattr(mat, "show_transparent_back"):
            mat.show_transparent_back = False

    mat["nmf_blend_mode"] = nmf_mat.blend_mode
    mat["nmf_ambient"] = nmf_mat.ambient
    mat["nmf_specular"] = nmf_mat.specular
    mat["nmf_emissive"] = nmf_mat.emissive
    mat["nmf_specular_power"] = nmf_mat.specular_power
    mat["nmf_uv_flip_u"] = nmf_mat.uv_flip_u
    mat["nmf_uv_flip_v"] = nmf_mat.uv_flip_v
    mat["nmf_uv_rotation"] = nmf_mat.uv_rotation
    mat["nmf_uv_scale"] = (nmf_mat.uv_scale_u, nmf_mat.uv_scale_v)
    mat["nmf_texture_kind"] = nmf_mat.texture.kind

    if nmf_mat.texture.kind in ('TXPG', 'TEXT'):
        mat["nmf_texture_name"] = nmf_mat.texture.name
        if nmf_mat.texture.kind == 'TXPG':
            mat["nmf_texture_page"] = nmf_mat.texture.page
            mat["nmf_texture_index_on_page"] = nmf_mat.texture.index_on_page
            mat["nmf_texture_atlas_rect"] = nmf_mat.texture.atlas_rect
        img = load_texture_image(nmf_mat.texture, opts.texture_dir, nmf_dir, image_cache)
        if img and bsdf:
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            tex_node = nodes.new('ShaderNodeTexImage')
            tex_node.image = img
            tex_node.location = (bsdf.location.x - 700, bsdf.location.y)
            uv_node = nodes.new('ShaderNodeUVMap')
            uv_node.uv_map = "UV0"
            uv_node.location = (tex_node.location.x - 300, tex_node.location.y)
            links.new(uv_node.outputs['UV'], tex_node.inputs['Vector'])

            # The engine renders diffuse_color * texture, not the texture alone -
            # some materials deliberately use a flat white/grey texture and rely
            # entirely on `diffuse` for their actual color; wiring the texture
            # straight to Base Color silently drops that tint. Skipped when
            # diffuse is ~white, where the multiply would be a no-op.
            diffuse_rgb = (diffuse[0], diffuse[1], diffuse[2])
            if min(diffuse_rgb) < 0.999:
                tint_node = nodes.new('ShaderNodeVectorMath')
                tint_node.operation = 'MULTIPLY'
                tint_node.inputs[1].default_value = diffuse_rgb
                tint_node.location = (tex_node.location.x + 300, tex_node.location.y - 200)
                links.new(tex_node.outputs['Color'], tint_node.inputs[0])
                links.new(tint_node.outputs['Vector'], bsdf.inputs['Base Color'])
            else:
                links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
            if nmf_mat.blend_mode != 0:
                links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])

    material_cache[cache_key] = mat
    return mat


def build_collision_object(node, payload, mesh_obj, coll):
    cverts = payload.collision_vertices
    cidx = payload.collision_indices
    tri_count = len(cidx) // 3
    faces = [(cidx[3 * i], cidx[3 * i + 1], cidx[3 * i + 2]) for i in range(tri_count)]
    cmesh = bpy.data.meshes.new(f"{node.name}_collision")
    cmesh.from_pydata(list(cverts), [], faces)
    cmesh.update(calc_edges=True)
    cobj = bpy.data.objects.new(f"{node.name}_collision", cmesh)
    coll.objects.link(cobj)
    cobj.parent = mesh_obj
    cobj.display_type = 'WIRE'
    cobj.hide_render = True
    cobj["nmf_collision"] = True
    return cobj


def build_vertex_animation(obj, payload, opts):
    verts = payload.vertices
    basis_positions = [v.position for v in verts]
    obj.shape_key_add(name="Basis", from_mix=False)
    fps = opts.fps

    for ci, clip in enumerate(payload.vertex_animation_clips):
        curves = clip.delta_curves
        times = union_times(curves) if curves else [0.0]
        interp_flag = clip.interpolation
        interp_mode = 'SINE' if interp_flag == 1 else 'LINEAR'
        rest = clip.rest_position

        sk_frames = []
        for t in times:
            dx = eval_channel(curves.get('x'), 0.0, t, interp_flag)
            dy = eval_channel(curves.get('y'), 0.0, t, interp_flag)
            dz = eval_channel(curves.get('z'), 0.0, t, interp_flag)
            sk = obj.shape_key_add(name=f"nmf_clip{ci}_t{t:.4f}", from_mix=False)
            sk.interpolation = 'KEY_LINEAR'
            coords = list(basis_positions)
            new_pos = (rest[0] + dx, rest[1] + dy, rest[2] + dz)
            for vi in clip.vertex_indices:
                coords[vi] = new_pos
            flat = [c for p in coords for c in p]
            sk.data.foreach_set('co', flat)
            sk_frames.append((sk, t * fps))

        for idx, (sk, frame) in enumerate(sk_frames):
            prev_frame = sk_frames[idx - 1][1] if idx > 0 else None
            next_frame = sk_frames[idx + 1][1] if idx < len(sk_frames) - 1 else None
            if prev_frame is not None:
                sk.value = 0.0
                sk.keyframe_insert('value', frame=prev_frame)
            sk.value = 1.0
            sk.keyframe_insert('value', frame=frame)
            if next_frame is not None:
                sk.value = 0.0
                sk.keyframe_insert('value', frame=next_frame)
            set_fcurve_interpolation(obj.data.shape_keys,
                                      f'key_blocks["{sk.name}"].value', 0, interp_mode)


def fix_winding_if_needed(mesh, verts):
    flip_votes = 0
    total = 0
    for poly in mesh.polygons:
        fn = poly.normal
        file_n = Vector((0.0, 0.0, 0.0))
        for vi in poly.vertices:
            file_n += Vector(verts[vi].normal)
        if file_n.length_squared > 1e-12:
            file_n.normalize()
            if fn.dot(file_n) < 0:
                flip_votes += 1
            total += 1
    if total > 0 and flip_votes / total > 0.5:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)


def build_mesh_object(node, payload, coll, opts, nmf_dir, material_cache, image_cache):
    verts = payload.vertices
    tri_count = node.triangle_count
    idx = payload.indices
    n_faces = min(tri_count, len(idx) // 3)

    # Materials partition both `vertices` and `indices` into contiguous
    # per-material blocks (index_offset/index_count, vertex_offset/
    # vertex_count) - but the index *values themselves* inside a block are
    # local to that material's own vertex_offset, not absolute into the
    # full `vertices` array. Confirmed against a real asset
    # (Auto_Schrott_1801's windshield-glass material, vertex_offset=178):
    # its raw index values are 0-7, which only form a sane, compact
    # triangle fan once vertex_offset is added back (178-185); read as
    # absolute indices instead, they silently point at unrelated vertices
    # elsewhere on the mesh (there: the car body) while still carrying the
    # glass material - the windshield renders in the wrong place using the
    # wrong geometry entirely. A material with vertex_offset 0 (the common
    # case, especially any single-material mesh) is unaffected either way.
    face_mat_index = [0] * n_faces
    for mi, m in enumerate(payload.materials):
        start = m.index_offset // 3
        end = (m.index_offset + m.index_count) // 3
        for fi in range(max(start, 0), min(end, n_faces)):
            face_mat_index[fi] = mi

    faces = []
    for fi in range(n_faces):
        vofs = payload.materials[face_mat_index[fi]].vertex_offset if payload.materials else 0
        a, b, c = idx[3 * fi], idx[3 * fi + 1], idx[3 * fi + 2]
        faces.append((a + vofs, b + vofs, c + vofs))

    mesh = bpy.data.meshes.new(node.name or "mesh")
    mesh.from_pydata([v.position for v in verts], [], faces)
    mesh.update(calc_edges=True)

    fix_winding_if_needed(mesh, verts)

    uv0 = mesh.uv_layers.new(name="UV0")
    uv1 = mesh.uv_layers.new(name="UV1")
    src_uv = mesh.uv_layers.new(name="SourceUV")
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            vi = mesh.loops[li].vertex_index
            uv0.data[li].uv = verts[vi].uv0
            uv1.data[li].uv = verts[vi].uv1
            src_uv.data[li].uv = payload.source_uv[vi]

    try:
        if hasattr(mesh, "use_auto_smooth"):
            mesh.use_auto_smooth = True
        mesh.normals_split_custom_set_from_vertices([v.normal for v in verts])
    except Exception as e:
        print(f"NMF import: could not set custom normals on '{node.name}': {e}")

    smooth_flag = bool(payload.smooth)
    mesh.polygons.foreach_set('use_smooth', [smooth_flag] * len(mesh.polygons))

    for i, m in enumerate(payload.materials):
        mat = build_material(m, node.name, i, opts, nmf_dir, material_cache, image_cache)
        mat.use_backface_culling = False if opts.double_sided else bool(not payload.backface_culling)
        mesh.materials.append(mat)

    mesh.polygons.foreach_set('material_index', face_mat_index)

    obj = bpy.data.objects.new(node.name or "mesh", mesh)
    coll.objects.link(obj)
    obj["nmf_backface_culling"] = bool(payload.backface_culling)
    obj["nmf_complex"] = bool(payload.complex_)
    obj["nmf_inside"] = bool(payload.inside)
    obj["nmf_smooth"] = bool(payload.smooth)
    obj["nmf_light_flare"] = bool(payload.light_flare)

    if opts.import_collision and len(payload.collision_vertices) > 0:
        build_collision_object(node, payload, obj, coll)

    if opts.import_vertex_animation and payload.vertex_animation_clips:
        build_vertex_animation(obj, payload, opts)

    return obj


def node_has_animation(node, opts):
    return (node.payload is not None and opts.import_animation and
            node.payload.animation is not None)


def classify_and_collapse(nmf, opts):
    """Decide which nodes get a real Blender object, and recursively fold
    non-animated FRAM/JOIN nodes into whichever real descendant sits below them
    (mesh, locator, or the next animated FRAM/JOIN) instead of creating an empty
    for each of them.

    A FRAM/JOIN node is only collapsible when its payload parsed successfully
    and it has no animation to import - anything we failed to parse still gets
    a real (identity-transform) object, so data is never silently dropped.

    Returns:
      is_real: list[bool], one per node.
      effective: {real_node_index: (real_parent_index_or_None, accumulated_matrix)}
        accumulated_matrix is the product of every skipped ancestor's own local
        matrix, to be combined into that node's matrix_parent_inverse.
    """
    n = len(nmf.nodes)
    is_real = [True] * n
    static_mat = {}

    for i, node in enumerate(nmf.nodes):
        if node.type not in ('FRAM', 'JOIN'):
            continue
        if node.payload is None or node_has_animation(node, opts):
            continue
        is_real[i] = False
        if node.type == 'FRAM':
            static_mat[i] = nmf_mat_to_blender(node.payload.local_matrix)
        else:
            static_mat[i] = compute_static_joint_matrix(node.payload)

    cache = {}

    def resolve(i):
        if i in cache:
            return cache[i]
        node = nmf.nodes[i]
        if node.parent == 0:
            result = (None, Matrix.Identity(4))
        else:
            p_idx = node.parent - 1
            if is_real[p_idx]:
                result = (p_idx, Matrix.Identity(4))
            else:
                grand_idx, grand_accum = resolve(p_idx)
                result = (grand_idx, grand_accum @ static_mat[p_idx])
        cache[i] = result
        return result

    effective = {i: resolve(i) for i in range(n) if is_real[i]}
    return is_real, effective


def import_nmf_file(context, filepath, opts):
    with open(filepath, 'rb') as f:
        nmf = parse_nmf(f)

    base = os.path.splitext(os.path.basename(filepath))[0]
    coll = bpy.data.collections.new(base)
    context.scene.collection.children.link(coll)
    nmf_dir = os.path.dirname(filepath)

    material_cache = {}
    image_cache = {}
    objs = [None] * len(nmf.nodes)
    # For most nodes outer/inner are the same object. An animated FRAM node
    # expanded into a pivot chain (build_fram_pivot_chain) has a different
    # object at each end: outer_objs[i] is what node i's own effective NMF
    # parent attaches to, objs[i] is what node i's NMF children attach to.
    outer_objs = [None] * len(nmf.nodes)
    child_corrections = {}

    # Non-animated FRAM/JOIN nodes don't get an object at all: their static
    # local matrix is folded into whichever real descendant sits below them.
    is_real, effective = classify_and_collapse(nmf, opts)

    for i, node in enumerate(nmf.nodes):
        if not is_real[i]:
            continue
        obj = None
        if node.type in ('ROOT', 'FRAM'):
            has_anim = node_has_animation(node, opts)
            if node.type == 'FRAM' and has_anim:
                outer, inner, correction = build_fram_pivot_chain(node, node.payload, opts, coll)
                obj = inner
                outer_objs[i] = outer
                if correction is not None:
                    child_corrections[i] = correction
            else:
                obj = bpy.data.objects.new(node.name or node.type, None)
                obj.empty_display_type = 'PLAIN_AXES'
                obj.empty_display_size = 0.1
                coll.objects.link(obj)
                if node.payload is not None:
                    apply_transform_node(obj, node.payload, opts)
        elif node.type == 'LOCA':
            obj = bpy.data.objects.new(node.name or 'LOCA', None)
            obj.empty_display_type = 'PLAIN_AXES'
            obj.empty_display_size = 0.05
            coll.objects.link(obj)
        elif node.type == 'JOIN':
            obj = bpy.data.objects.new(node.name or 'JOIN', None)
            obj.empty_display_type = 'ARROWS'
            obj.empty_display_size = 0.1
            coll.objects.link(obj)
            if node.payload is not None:
                apply_joint_node(obj, node.payload, opts)
        elif node.type == 'MESH':
            if node.payload is not None:
                obj = build_mesh_object(node, node.payload, coll, opts, nmf_dir,
                                         material_cache, image_cache)

        if obj is not None:
            obj["nmf_type"] = node.type
        objs[i] = obj
        if outer_objs[i] is None:
            outer_objs[i] = obj

    identity4 = Matrix.Identity(4)
    for i, node in enumerate(nmf.nodes):
        if not is_real[i]:
            continue
        obj = outer_objs[i]
        if obj is None or node.type == 'ROOT':
            continue
        real_parent_idx, accum = effective[i]
        if real_parent_idx is None or objs[real_parent_idx] is None:
            continue
        obj.parent = objs[real_parent_idx]
        correction = child_corrections.get(real_parent_idx, identity4)
        mpi = correction @ accum
        if mpi != identity4:
            obj.matrix_parent_inverse = mpi

    needs_wrapper = opts.mirror_x or abs(opts.global_scale - 1.0) > 1e-9
    if needs_wrapper:
        # NMF's engine is DirectX-based (left-handed) and Y-up; Blender is
        # right-handed and Z-up. ROOT's own local_matrix only encodes this
        # particular asset's own placement in that Y-up scene - it is NOT by
        # itself a full conversion to Blender's convention. A single Y<->Z
        # axis swap on top of it (composed once here, cascading through the
        # whole hierarchy via ordinary parenting) fixes both problems at
        # once: without it, models come out both mirrored *and* lying on
        # their side (their tall axis ends up along Y instead of Z). This is
        # a plain axis permutation (not a diagonal scale), so it needs an
        # explicit matrix_basis rather than a .scale assignment.
        y_up_to_z_up = Matrix((
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )) if opts.mirror_x else Matrix.Identity(4)
        wrap_root = bpy.data.objects.new(f"{base}_import", None)
        wrap_root.empty_display_size = 0.01
        wrap_root.matrix_basis = y_up_to_z_up @ Matrix.Diagonal(
            (opts.global_scale, opts.global_scale, opts.global_scale, 1.0))
        coll.objects.link(wrap_root)
        for i, node in enumerate(nmf.nodes):
            if node.parent == 0 and outer_objs[i] is not None:
                outer_objs[i].parent = wrap_root

    type_counts = Counter(n.type for n in nmf.nodes)
    return type_counts


# =============================================================================
# 4. Operator / registration
# =============================================================================

class ImportNMF(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.nmf"
    bl_label = "Import NMF"
    bl_description = "Import a Neo Model Format (.nmf) scene"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".nmf"
    filter_glob: StringProperty(default="*.nmf", options={'HIDDEN'})

    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    global_scale: FloatProperty(
        name="Scale", default=1.0, min=0.0001, max=10000.0,
        description="Uniform scale applied to imported root object(s)")
    mirror_x: BoolProperty(
        name="Fix Coordinate System",
        default=True,
        description="NMF's engine is left-handed (DirectX-style) and Y-up; Blender "
                    "is right-handed and Z-up. Without this, imported models come "
                    "out both mirrored along X and lying on their side")
    use_scene_fps: BoolProperty(
        name="Use Scene FPS", default=True,
        description="Convert animation time (seconds) to frames using the scene's frame rate")
    fps: FloatProperty(
        name="FPS", default=30.0, min=1.0, max=1000.0,
        description="Frames per second used instead of the scene FPS")
    import_animation: BoolProperty(name="Node Animation", default=True)
    import_vertex_animation: BoolProperty(name="Vertex Animation (Shape Keys)", default=True)
    import_collision: BoolProperty(name="Collision Meshes", default=False)
    double_sided: BoolProperty(
        name="Double-Sided Materials",
        default=False,
        description="Show every material from both sides, overriding each mesh's own "
                    "backface_culling flag from the file")
    texture_dir: StringProperty(
        name="Texture Folder", subtype='DIR_PATH', default="",
        description="Folder to search for textures / texture_pages. "
                    "Leave empty to auto-detect next to the .nmf file")

    def invoke(self, context, event):
        # ImportHelper.invoke() unconditionally opens the file browser - fine
        # for File > Import (no path chosen yet), but wrong for a drag-and-
        # drop: the FileHandler already set filepath/files from the dropped
        # file(s) before invoke() runs, so re-opening the browser on top of
        # that is redundant and not what "drop a file" should feel like.
        # Show a small options popup instead when a path is already known,
        # and only fall back to the full browser when it isn't.
        if self.filepath or self.files:
            return context.window_manager.invoke_props_dialog(self, width=400)
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        if self.files:
            paths = [os.path.join(self.directory, f.name) for f in self.files]
        else:
            paths = [self.filepath]

        opts = ImportOptions(
            global_scale=self.global_scale,
            fps=(context.scene.render.fps if self.use_scene_fps else self.fps),
            import_animation=self.import_animation,
            import_vertex_animation=self.import_vertex_animation,
            import_collision=self.import_collision,
            texture_dir=self.texture_dir,
            mirror_x=self.mirror_x,
            double_sided=self.double_sided,
        )

        imported = 0
        for p in paths:
            if not p.lower().endswith('.nmf'):
                continue
            try:
                import_nmf_file(context, p, opts)
                imported += 1
            except Exception as e:
                self.report({'ERROR'}, f"Failed to import {os.path.basename(p)}: {e}")
                import traceback
                traceback.print_exc()

        if imported:
            self.report({'INFO'}, f"Imported {imported} NMF file(s)")
            return {'FINISHED'}
        return {'CANCELLED'}

    def draw(self, context):
        layout = self.layout
        if self.files:
            names = ", ".join(f.name for f in self.files)
        elif self.filepath:
            names = os.path.basename(self.filepath)
        else:
            names = None
        if names:
            layout.label(text=names, icon='FILE_3D')
        layout.prop(self, "global_scale")
        layout.prop(self, "mirror_x")

        box = layout.box()
        box.label(text="Animation")
        box.prop(self, "import_animation")
        row = box.row()
        row.prop(self, "use_scene_fps")
        sub = box.row()
        sub.enabled = not self.use_scene_fps
        sub.prop(self, "fps")
        box.prop(self, "import_vertex_animation")

        box2 = layout.box()
        box2.label(text="Meshes")
        box2.prop(self, "import_collision")
        box2.prop(self, "double_sided")
        box2.prop(self, "texture_dir")


def menu_func_import(self, context):
    self.layout.operator(ImportNMF.bl_idname, text="Neo Model (.nmf)")


classes = (ImportNMF,)

# Drag-and-drop support (bpy.types.FileHandler): dropping a .nmf file into the
# 3D viewport runs ImportNMF directly, no File > Import needed. FileHandler
# itself was only added in Blender 4.1 - this addon otherwise supports back to
# 3.3 (see bl_info), so the class is defined conditionally: on older Blender,
# bpy.types.FileHandler doesn't exist at all, and subclassing it would raise
# at *module load time* (class statements evaluate their bases immediately),
# breaking the whole addon rather than just this one feature.
if hasattr(bpy.types, "FileHandler"):
    class NMF_FH_import(bpy.types.FileHandler):
        bl_idname = "NMF_FH_import"
        bl_label = "Neo Model (.nmf)"
        bl_import_operator = ImportNMF.bl_idname
        bl_file_extensions = ".nmf"

        @classmethod
        def poll_drop(cls, context):
            return context.area is not None and context.area.type == 'VIEW_3D'

    classes = classes + (NMF_FH_import,)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for c in classes:
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
