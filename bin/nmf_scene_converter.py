#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

"""
Der Clou! 2 (The Sting! / Ва-Банк!) NMF scene conversion - Stage 1, shared.

`NmfSceneConverter` turns the flat, `parent_id`-linked list of raw NMF nodes
(as parsed by `common.Nmf`) into a flat list of "processed" plain dicts
describing transforms/geometry/materials in target-format-agnostic terms -
translation/rotation(Euler XYZ degrees)/scaling, per-axis animation curves,
pivot-chain expansion for animated FRAM nodes, mesh geometry/UV/normals,
material/texture resolution. It has no knowledge of FBX, glTF, or any other
specific output format - see its own class docstring below.

This module used to live inline in `nmf_to_fbx.py`; it was extracted here,
verbatim (no functional changes), once `nmf_to_gltf.py` needed the exact
same Stage 1 logic. Both `nmf_to_fbx.py` (Stage 2/3: FBX object graph +
binary writer) and `nmf_to_gltf.py` (Stage 2/3: glTF JSON graph + GLB
writer) import from here.

For the full historical debugging narrative behind this module's design
(a long chain of gotchas - Maya-style pivot decomposition, rotation-wrap
handling, transform folding for shear, per-axis rotation-node splitting to
dodge Euler-branch ambiguity in FBX importers, etc.) see `nmf_to_fbx.py`'s
own module docstring, which originated it - most of that history is about
*why* this module's logic looks the way it does, and is not duplicated
here to avoid drifting out of sync between the two files.

License: MIT License
"""

import sys, os
import json
import math
from dataclasses import dataclass, field
from struct import pack, unpack, error as struct_error

# Stage-1 debug logging ("[pivot]"/"[wire]"/"[texture]" traces) - separate
# from nmf_to_fbx.py's/nmf_to_gltf.py's own Stage 2/3 DEBUG flag; each
# entry point's main() sets both when --debug is passed.
DEBUG = False


def debug_output(data):
    if DEBUG:
        print(data, file=sys.stderr)


FPS = 24.0
RAD2DEG = 180.0 / math.pi

# Reused wherever an explicit "no transform" 4x4 is needed (transform
# folding, mesh vertex baking).
_IDENTITY4 = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

# mtrl.rotate is a 0-3 enum (quarter turns), mapped to FBX Texture
# "Rotation" degrees.
_UV_ROTATION_DEGREES = {0: 0.0, 1: -90.0, 2: -180.0, 3: -270.0}


@dataclass
class TransformFold:
    """Result of `NmfSceneConverter._compute_transform_folds`: which
    FRAM/JOIN node indices should become an identity pass-through Model, and
    which mesh node indices need their vertices/normals pre-multiplied by an
    accumulated ancestor matrix before being written out."""

    fold_as_identity: set = field(default_factory=set)
    mesh_bake_matrix: dict = field(default_factory=dict)


# =============================================================================
# Stage 1: NmfSceneConverter - raw NMF nodes -> processed node list.
# No FBX knowledge: the output is a flat list of plain dicts describing
# transforms/geometry/materials in DCC-agnostic terms.
# =============================================================================


class NmfSceneConverter:
    """Converts the flat, parent_id-linked list of raw NMF nodes (as parsed
    by `common.Nmf`) into a flat list of "processed" plain dicts consumed by
    `FbxSceneAssembler`. Holds the (mutable) id generator and texture
    resolution config as instance state so per-node conversion methods
    don't need to thread them through every call; the matrix/vector math and
    static-transform-folding helpers below need no instance state at all and
    are plain `@staticmethod`s."""

    _manifest_cache = {}

    def __init__(self, uid_gen, textures_dir, page_manifest=None):
        self.uid_gen = uid_gen
        self.textures_dir = textures_dir
        self.page_manifest = page_manifest or {}

    # -- geometry / matrix math (static, stateless) -----------------------

    @staticmethod
    def _normalize(v):
        l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        if l == 0.0:
            return (0.0, 0.0, 0.0)
        return (v[0] / l, v[1] / l, v[2] / l)

    @staticmethod
    def _cross(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    @staticmethod
    def _sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    @staticmethod
    def _dot(a, b):
        return (a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2])

    @staticmethod
    def _len3(v):
        return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    @staticmethod
    def _extract_3x3(m4):
        if not m4:
            return None
        a = [c for row in m4 for c in row]
        return [[a[0], a[1], a[2]], [a[4], a[5], a[6]], [a[8], a[9], a[10]]]

    @staticmethod
    def _matrix_rowmajor_to_euler_xyz_standard(m):
        """Extracts XYZ Euler angles (degrees) from a pure rotation matrix.
        Used for JOIN's `rotation_matrix` (its baked "joint orient"); shares
        its extraction convention with `_decompose_directx_row_major` below
        by design, so a joint's PreRotation and an equivalent non-animated
        node's decomposed rotation agree."""
        if m is None:
            return [0.0, 0.0, 0.0]
        m00, m01, m02 = m[0]
        m10, m11, m12 = m[1]
        m20, m21, m22 = m[2]
        r00, r01, r02 = m00, m10, m20
        r10, r11, r12 = m01, m11, m21
        r20, r21, r22 = m02, m12, m22
        if abs(r20) < 0.999999:
            y = math.asin(-r20)
            x = math.atan2(r21, r22)
            z = math.atan2(r10, r00)
        else:
            y = math.asin(-r20)
            x = math.atan2(-r12, r11)
            z = 0.0
        return [x * RAD2DEG, y * RAD2DEG, z * RAD2DEG]

    @staticmethod
    def _dx_to_blender_matrix(dx_m):
        """Transposes a DirectX row-major 4x4 into the row/column convention
        the rest of this file's matrix math (and FBX/Blender) uses. This is
        a pure row-vector-to-column-vector convention change, not an axis
        remap - the DirectX-Y-up to Blender-Z-up swap happens separately,
        once, in `_convert_root_node`."""
        if not dx_m:
            return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        return [[dx_m[j][i] for j in range(4)] for i in range(4)]

    @staticmethod
    def _mat_mul(a, b):
        res = [[0.0] * 4 for _ in range(4)]
        for i in range(4):
            for j in range(4):
                res[i][j] = (
                    a[i][0] * b[0][j]
                    + a[i][1] * b[1][j]
                    + a[i][2] * b[2][j]
                    + a[i][3] * b[3][j]
                )
        return res

    @staticmethod
    def _decompose_directx_row_major(m):
        """Decomposes a 4x4 (already run through `_dx_to_blender_matrix`)
        into (translation, scale, XYZ-Euler-rotation, in radians). Only
        valid for matrices that are a pure Scale*Rotation (no shear) - see
        `_compute_transform_folds`, which exists specifically to avoid
        calling this on matrices that aren't."""
        tx, ty, tz = m[0][3], m[1][3], m[2][3]
        r0 = [m[0][0], m[1][0], m[2][0]]
        r1 = [m[0][1], m[1][1], m[2][1]]
        r2 = [m[0][2], m[1][2], m[2][2]]
        sx = NmfSceneConverter._len3(r0)
        sy = NmfSceneConverter._len3(r1)
        sz = NmfSceneConverter._len3(r2)
        det = (
            r0[0] * (r1[1] * r2[2] - r1[2] * r2[1])
            - r0[1] * (r1[0] * r2[2] - r1[2] * r2[0])
            + r0[2] * (r1[0] * r2[1] - r1[1] * r2[0])
        )
        if det < 0:
            sz = -sz
        sx = sx if sx != 0 else 1.0
        sy = sy if sy != 0 else 1.0
        sz = sz if sz != 0 else 1.0
        r00, r10, r20 = r0[0] / sx, r0[1] / sx, r0[2] / sx
        r01, r11, r21 = r1[0] / sy, r1[1] / sy, r1[2] / sy
        r02, r12, r22 = r2[0] / sz, r2[1] / sz, r2[2] / sz
        ry_gate = (
            math.asin(-r20) if abs(r20) <= 1.0 else math.asin(-1.0 if r20 > 0 else 1.0)
        )
        if abs(math.cos(ry_gate)) > 1e-6:
            ry = math.asin(-r20)
            rx = math.atan2(r21, r22)
            rz = math.atan2(r10, r00)
        else:
            ry = math.asin(-1.0 if r20 > 0 else 1.0)
            rx = math.atan2(-r12, r11)
            rz = 0.0
        return ((tx, ty, tz), (sx, sy, sz), (rx, ry, rz))

    @staticmethod
    def _transform_point(m, p):
        x, y, z = p
        return [
            m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
        ]

    @staticmethod
    def _transform_vector(m, v):
        """Like `_transform_point` but for a displacement, not a position -
        m's upper-left 3x3 only, no translation column. Used for MESH_ANIM
        per-axis unit deltas (gotcha #25) when a mesh's transform got baked
        into its vertices via `_bake_matrix_into_vertices`."""
        x, y, z = v
        return [
            m[0][0] * x + m[0][1] * y + m[0][2] * z,
            m[1][0] * x + m[1][1] * y + m[1][2] * z,
            m[2][0] * x + m[2][1] * y + m[2][2] * z,
        ]

    @staticmethod
    def _normal_transform_3x3(m):
        """Inverse-transpose of m's upper-left 3x3, for transforming normals
        under a matrix that may contain shear/non-uniform scale/reflection -
        where transforming a normal by the same matrix as positions would
        stop it being perpendicular to the surface. inverse-transpose(A)
        equals cofactor(A)/det(A), so this needs no separate transpose
        step."""

        def minor(r0, r1, c0, c1):
            return m[r0][c0] * m[r1][c1] - m[r0][c1] * m[r1][c0]

        c00 = minor(1, 2, 1, 2)
        c01 = -minor(1, 2, 0, 2)
        c02 = minor(1, 2, 0, 1)
        c10 = -minor(0, 2, 1, 2)
        c11 = minor(0, 2, 0, 2)
        c12 = -minor(0, 2, 0, 1)
        c20 = minor(0, 1, 1, 2)
        c21 = -minor(0, 1, 0, 2)
        c22 = minor(0, 1, 0, 1)
        det = m[0][0] * c00 + m[0][1] * c01 + m[0][2] * c02
        if abs(det) < 1e-12:
            return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        inv_det = 1.0 / det
        return [
            [c00 * inv_det, c01 * inv_det, c02 * inv_det],
            [c10 * inv_det, c11 * inv_det, c12 * inv_det],
            [c20 * inv_det, c21 * inv_det, c22 * inv_det],
        ]

    @staticmethod
    def _transform_normal(m3, n):
        x, y, z = n
        return [
            m3[0][0] * x + m3[0][1] * y + m3[0][2] * z,
            m3[1][0] * x + m3[1][1] * y + m3[1][2] * z,
            m3[2][0] * x + m3[2][1] * y + m3[2][2] * z,
        ]

    @staticmethod
    def _is_mesh_right_handed(ibuf, vbuf):
        """Votes, triangle by triangle, whether the mesh's authored normals
        (vbuf columns 3-5) agree with the geometric winding of `ibuf` - used
        to decide whether to flip winding once per mesh. Must be called
        exactly once, before per-material vertex index shifting (see gotcha
        #9 in the module docstring) - checking again afterwards can flip
        winding back."""
        pos = [[r[0], r[1], r[2]] for r in vbuf]
        nrm = [[r[3], r[4], r[5]] for r in vbuf] if len(vbuf[0]) > 5 else []
        if not nrm:
            return True
        pos_cnt = 0
        neg_cnt = 0
        for i0, i1, i2 in ibuf:
            p0, p1, p2 = pos[i0], pos[i1], pos[i2]
            n_geom = NmfSceneConverter._normalize(
                NmfSceneConverter._cross(
                    NmfSceneConverter._sub(p1, p0), NmfSceneConverter._sub(p2, p0)
                )
            )
            n_avg = NmfSceneConverter._normalize(
                [
                    nrm[i0][0] + nrm[i1][0] + nrm[i2][0],
                    nrm[i0][1] + nrm[i1][1] + nrm[i2][1],
                    nrm[i0][2] + nrm[i1][2] + nrm[i2][2],
                ]
            )
            s = NmfSceneConverter._dot(n_geom, n_avg)
            if s >= 0:
                pos_cnt += 1
            else:
                neg_cnt += 1
        return pos_cnt >= neg_cnt

    @staticmethod
    def _make_polygon_vertex_index_from_tris(ibuf):
        out = []
        for a, b, c in ibuf:
            out.append(a)
            out.append(b)
            out.append(-(c + 1))
        return out

    @staticmethod
    def _pvi_vertex(pvi_val: int) -> int:
        return -pvi_val - 1 if pvi_val < 0 else pvi_val

    @staticmethod
    def _build_fbx_edges_from_pvi(pvi):
        edges_positions = []
        seen = set()
        poly_start = 0
        i = 0
        n = len(pvi)
        while i < n:
            if pvi[i] < 0:
                poly_end = i
                for j in range(poly_start, poly_end + 1):
                    v_a = NmfSceneConverter._pvi_vertex(pvi[j])
                    v_b = (
                        NmfSceneConverter._pvi_vertex(pvi[j + 1])
                        if j < poly_end
                        else NmfSceneConverter._pvi_vertex(pvi[poly_start])
                    )
                    key = (v_a, v_b) if v_a < v_b else (v_b, v_a)
                    if key not in seen:
                        seen.add(key)
                        edges_positions.append(j)
                poly_start = i + 1
            i += 1
        return edges_positions

    @staticmethod
    def _build_fbx_normals_flat(verts, ibuf):
        """Per-face-vertex (flat/"Direct") normals, computed from geometry -
        NOT from the mesh's authored vbuf normals. This matters when a
        matrix has been baked into vertex positions (see
        `_compute_transform_folds`): since these are recomputed from the
        (already-transformed) positions, they come out correct with no
        separate normal-matrix step needed."""
        normals = []
        normals_w = []
        for a, b, c in ibuf:
            v0 = verts[a]
            v1 = verts[b]
            v2 = verts[c]
            e1 = NmfSceneConverter._sub(v1, v0)
            e2 = NmfSceneConverter._sub(v2, v0)
            n = NmfSceneConverter._normalize(NmfSceneConverter._cross(e1, e2))
            for _ in range(3):
                normals.extend(n)
                normals_w.append(1.0)
        return normals, normals_w

    @staticmethod
    def _build_fbx_uv_layer(vbuf, ibuf):
        uv_direct = []
        for t in vbuf:
            u = float(t[6]) if len(t) > 6 else 0.0
            # Baked as DirectX-style V (0 = top of the page, increasing
            # downward). FBX/OpenGL-style consumers (Blender's importer
            # included) read V as 0 = bottom, increasing upward, so without
            # this flip the sampled rect lands mirrored vertically around
            # v=0.5 - see gotcha #2 in the module docstring.
            v = 1.0 - float(t[7]) if len(t) > 7 else 0.0
            uv_direct.append(u)
            uv_direct.append(v)
        uv_index = []
        for a, b, c in ibuf:
            uv_index.extend([int(a), int(b), int(c)])
        return uv_direct, uv_index

    _FULL_TURN_EPSILON_DEG = 2.0

    @staticmethod
    def _unwrap_degrees(vals):
        """Removes spurious +/-360 jumps from a sequence of per-axis Euler
        keyframe angles (degrees) so consecutive keys always differ by at
        most 180 - the "short way" - instead of whatever raw value the
        exporter happened to store. Each source axis is an independent
        angle sequence (no shared quaternion), so a real short rotation
        through the 180 boundary (e.g. 170 -> -170, an actual 20 step) is
        otherwise stored as a literal 340 jump, which FBX/Blender then
        interpolates the long way around, snapping the limb through a
        near-full spin.

        Gotcha #13: a continuously-spinning part (fan/propeller/radar dish/
        rotating light cone) is commonly authored as just 2 keyframes, 0 ->
        360 (one full loop, meant to play on repeat), and that raw 360 delta
        looks identical to this function's whole reason for existing - a
        spurious wraparound - EXCEPT that collapsing a spurious wraparound
        is supposed to land on a small residual angle (that's the actual
        real motion), whereas collapsing a genuine whole turn lands on ~0,
        silently erasing all visible rotation. Distinguish the two by that
        residual: only apply the shortest-path correction when it leaves a
        non-trivial angle - if the correction would collapse a clearly
        non-zero raw delta down to ~0, it's a whole number of real turns,
        not storage wraparound, so the raw delta is kept as-is."""
        if not vals:
            return vals
        out = [vals[0]]
        for v in vals[1:]:
            prev = out[-1]
            delta = v - prev
            corrected = delta - 360.0 * round(delta / 360.0)
            if (
                abs(corrected) < NmfSceneConverter._FULL_TURN_EPSILON_DEG
                and abs(delta) >= NmfSceneConverter._FULL_TURN_EPSILON_DEG
            ):
                out.append(prev + delta)
            else:
                out.append(prev + corrected)
        return out

    _MAX_ROTATION_SEGMENT_DEG = 179.0

    @staticmethod
    def _subdivide_wide_rotation_segments(frames, vals):
        """Inserts intermediate keyframes into any consecutive pair whose
        value delta is large (>= ~180 degrees) - this always includes the
        exact 0 -> 360 full-loop case from gotcha #13's `_unwrap_degrees`
        fix, which now leaves that delta intact instead of collapsing it to
        ~0.

        That fix alone turned out not to be enough: a keyframe pair whose
        start and end angle describe the SAME final orientation (0 and 360
        are the same pose) plays no visible motion in at least one real FBX
        consumer, regardless of what the literal stored degree values are -
        it evaluates the animation by the pose at each key, not the raw
        number, and sees nothing to interpolate between. A genuinely
        distinct intermediate pose (e.g. 180, halfway through a 0->360
        turn) can't be collapsed away the same way, so this splits any wide
        segment into several wide-as-safe pieces instead of just two
        endpoints."""
        if len(frames) < 2:
            return frames, vals
        out_frames = [frames[0]]
        out_vals = [vals[0]]
        for i in range(1, len(frames)):
            f0, f1 = frames[i - 1], frames[i]
            v0, v1 = vals[i - 1], vals[i]
            delta = v1 - v0
            steps = max(
                1,
                math.ceil(abs(delta) / NmfSceneConverter._MAX_ROTATION_SEGMENT_DEG),
            )
            for s in range(1, steps + 1):
                t = s / steps
                out_frames.append(f0 + (f1 - f0) * t)
                out_vals.append(v0 + delta * t)
        return out_frames, out_vals

    _ROTATION_WRAP_LIMIT_DEG = 179.9
    _ROTATION_WRAP_STEP_FRAMES = 0.001

    @staticmethod
    def _wrap_rotation_into_range(frames, vals):
        """Gotcha #19: even after gotcha #13's fix, a literal continuous
        curve (0 -> 120 -> 240 -> 360, say) still visibly breaks in
        Blender, root-caused by direct experiment (editing the
        intermediate JSON and re-testing, not inspection): Blender's FBX
        importer normalizes each keyframe's Euler value into (-180, 180]
        INDEPENDENTLY, with no awareness of neighbouring keys - so 240 and
        360 silently become -120 and -0 on import - and then interpolates
        between the now-displaced numbers with no shortest-path
        correction, which visibly reverses direction right where a value
        got wrapped.

        The fix has to make every stored value already fit in that range,
        since Blender will re-derive its own wrapped copy no matter what
        we send otherwise. Whenever the (already continuous, already
        small-step - see `_subdivide_wide_rotation_segments`) curve would
        cross +-180, this inserts the exact crossing point followed
        immediately (`_ROTATION_WRAP_STEP_FRAMES` later - a thousandth of
        a frame, i.e. a fraction of a millisecond) by its wrapped
        equivalent on the other side: the same true angle, ~360 degrees
        apart numerically. Both keys use the same cubic-auto
        interpolation as everything else - no new FBX interpolation mode
        needed - relying on the gap being far too small for any real
        playback (which only ever samples whole/half frames) to land
        inside it and see the reversed sweep between them."""
        if len(vals) < 2:
            return frames, vals
        limit = NmfSceneConverter._ROTATION_WRAP_LIMIT_DEG
        step = NmfSceneConverter._ROTATION_WRAP_STEP_FRAMES

        out_vals = [vals[0]]
        offset = 0.0
        while out_vals[0] > limit:
            offset -= 360.0
            out_vals[0] += -360.0
        while out_vals[0] < -limit:
            offset += 360.0
            out_vals[0] += 360.0
        out_frames = [frames[0]]

        for i in range(1, len(frames)):
            f0, f1 = frames[i - 1], frames[i]
            v0 = out_vals[-1]
            v1 = vals[i] + offset
            if v1 > limit:
                frac = 0.0 if v1 == v0 else (limit - v0) / (v1 - v0)
                cross_frame = f0 + (f1 - f0) * frac
                out_frames.append(cross_frame)
                out_vals.append(limit)
                out_frames.append(cross_frame + step)
                out_vals.append(-limit)
                offset -= 360.0
                v1 -= 360.0
            elif v1 < -limit:
                frac = 0.0 if v1 == v0 else (-limit - v0) / (v1 - v0)
                cross_frame = f0 + (f1 - f0) * frac
                out_frames.append(cross_frame)
                out_vals.append(-limit)
                out_frames.append(cross_frame + step)
                out_vals.append(limit)
                offset += 360.0
                v1 += 360.0
            out_frames.append(f1)
            out_vals.append(v1)
        return out_frames, out_vals

    @staticmethod
    def _uv_rotation_degrees(rotate_enum):
        return _UV_ROTATION_DEGREES.get(int(rotate_enum), 0.0)

    # -- static-transform folding (gotcha #8) ------------------------------

    @staticmethod
    def _compute_transform_folds(nodes):
        """A static (non-animated) FRAM/JOIN whose matrix contains even a
        small amount of shear (non-orthogonal basis vectors) can't be
        represented by FBX's plain Translation/Rotation/Scale Model
        transform. Decomposing it that way isn't just imprecise - close to
        a gimbal-lock angle (Y near +-90) the Euler extraction amplifies
        that shear into a wildly wrong rotation/scale and visibly distorts
        everything under it (found on polySurface49/polySurfaceShape69's
        shin, and again on group87, whose own shear is tiny but its Y
        rotation sits at ~-85.7 degrees).

        Fix: fold the whole chain of static FRAM/JOIN nodes - however it
        branches - down into identity, accumulating their matrices, until
        each branch reaches either a mesh (bake the accumulated matrix into
        its vertices/normals - geometry represents shear exactly, no
        decomposition needed) or an animated node (stop; animation
        keyframes need a clean local space, so a static ancestor's matrix is
        only ever folded past nodes whose entire subtree is itself fully
        static)."""
        children_of = {}
        for n in nodes:
            children_of.setdefault(n.get("parent"), []).append(n)
        by_index = {n["index"]: n for n in nodes}

        static_memo = {}

        def is_fully_static(idx):
            if idx in static_memo:
                return static_memo[idx]
            n = by_index[idx]
            if n["type"] == "ROOT":
                ok = False
            elif n["type"] in ("FRAM", "JOIN") and n["payload"].get("animation"):
                ok = False
            else:
                ok = all(is_fully_static(c["index"]) for c in children_of.get(idx, []))
            static_memo[idx] = ok
            return ok

        fold_as_identity = set()
        mesh_bake_matrix = {}
        incoming_matrix_for = {}
        for n in nodes:
            idx = n["index"]
            incoming = incoming_matrix_for.get(n.get("parent"), _IDENTITY4)
            if (
                n["type"] in ("FRAM", "JOIN")
                and not n["payload"].get("animation")
                and is_fully_static(idx)
            ):
                own_matrix = NmfSceneConverter._dx_to_blender_matrix(
                    n["payload"]["local_matrix"]
                )
                incoming_matrix_for[idx] = NmfSceneConverter._mat_mul(incoming, own_matrix)
                fold_as_identity.add(idx)
            else:
                incoming_matrix_for[idx] = _IDENTITY4
                if n["type"] == "MESH":
                    mesh_bake_matrix[idx] = incoming

        return TransformFold(
            fold_as_identity=fold_as_identity, mesh_bake_matrix=mesh_bake_matrix
        )

    @staticmethod
    def _bake_matrix_into_vertices(raw_vbuf, matrix):
        """Applies `matrix` to each vertex's position and (via the correct
        inverse-transpose rule) normal - see `_compute_transform_folds`."""
        normal_m3 = NmfSceneConverter._normal_transform_3x3(matrix)
        return [
            [
                *NmfSceneConverter._transform_point(matrix, v[0:3]),
                *NmfSceneConverter._transform_normal(normal_m3, v[3:6]),
                *v[6:],
            ]
            for v in raw_vbuf
        ]

    @staticmethod
    def _assign_polygon_materials(raw_ibuf, materials_in):
        """Maps each triangle to its material index and shifts that
        triangle's vertex indices by the material's own base-vertex offset.
        The NMF format stores each material's face range against its own
        locally-based vertex block when a mesh is split across several
        materials: `vertex_offset`/`index_offset`/`index_count` (see
        NMF_SPEC.md's Material) - `vertex_count` isn't needed here (it's
        implied by the next material's `vertex_offset`, or the mesh's own
        `vertex_count` for the last one). Mutates `raw_ibuf` in place."""
        poly_mat_indices = [0] * len(raw_ibuf)
        for mat_idx, m in enumerate(materials_in):
            if "vertex_offset" not in m:
                continue
            min_vertex = m["vertex_offset"]
            start_index = m.get("index_offset", 0)
            num_indices = m.get("index_count", 0)
            start_face = start_index // 3
            num_faces = num_indices // 3
            for f_idx in range(start_face, start_face + num_faces):
                if f_idx < len(raw_ibuf):
                    poly_mat_indices[f_idx] = mat_idx
                    raw_ibuf[f_idx][0] += min_vertex
                    raw_ibuf[f_idx][1] += min_vertex
                    raw_ibuf[f_idx][2] += min_vertex
        return poly_mat_indices

    @staticmethod
    def _mark_fram_parents_with_mesh_children(result):
        """A FRAM's FBX Model subtype is "Mesh" instead of "Null" when it
        hosts a mesh child - flagged here once all nodes are converted."""
        id_to_node = {n["id"]: n for n in result}
        for node in result:
            if node["node_type"] == "mesh":
                parent_node = id_to_node.get(node["parent_id"])
                if parent_node and parent_node["node_type"] == "fram":
                    parent_node["mesh"] = True

    # -- texture page resolution --------------------------------------------
    #
    # The pages are not cropped/re-encoded: the user supplies the raw
    # per-page textures directly as "textures/{page_id}.png" (1.png,
    # 2.png, ...), and we just point the FBX material at the right file.
    # The mesh's own baked UV already targets the correct spot on that
    # full page directly (gotcha #3) - no per-material sub-rect
    # placement, scaling, or on-disk cache involved.

    @staticmethod
    def _read_png_dimensions(path):
        with open(path, "rb") as f:
            header = f.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise ValueError(f"not a valid PNG: {path}")
        width, height = unpack(">II", header[16:24])
        return width, height

    @staticmethod
    def _find_texture_pages_json(start_dir):
        d = os.path.abspath(start_dir)
        for _ in range(8):
            candidate = os.path.join(d, "texture_pages.json")
            if os.path.exists(candidate):
                return candidate
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        return None

    @staticmethod
    def find_textures_dir(start_dir):
        """Searches upward from start_dir for a directory named "textures".
        In the real unpacked layout, .nmf files live several levels below
        a single shared top-level "textures" folder (e.g.
        VaBank_unpack/models/Characters/Hero_2782.nmf vs.
        VaBank_unpack/textures/) - same upward-search shape as
        `_find_texture_pages_json`/`load_texture_page_manifest` below, for
        the same reason."""
        d = os.path.abspath(start_dir)
        for _ in range(8):
            candidate = os.path.join(d, "textures")
            if os.path.isdir(candidate):
                return candidate
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        return None

    @classmethod
    def load_texture_page_manifest(cls, start_dir):
        """Returns {page_id: [texture_entry, ...]} parsed from
        texture_pages.json, searched upward from start_dir. Empty dict
        (with a warning) if not found - callers then fall back to each
        MTRL's own (likely-wrong) box.

        The MTRL's own x0,y0,x2,y2 describe the sub-texture's bounds within
        its OWN original source file (e.g. "rucksack.TIF") - that's why
        every material tends to show a "full image" box like
        (0,0)-(256,256), regardless of where it actually ended up on the
        shared page. The real on-page placement lives in the .wld's own
        texture-page manifest (produced by wld_unpacker.py), where each
        page lists its textures in the same order as
        "index_on_page" - that entry's "box" is the real
        (x0,y0,x2,y2) on the shared atlas page. We no longer need it for
        placement (gotcha #3), but it's kept as a diagnostic cross-check -
        see `_resolve_material_texture`."""
        start_dir = os.path.abspath(start_dir)
        if start_dir in cls._manifest_cache:
            return cls._manifest_cache[start_dir]

        manifest = {}
        path = cls._find_texture_pages_json(start_dir)
        if path:
            with open(path, "r", encoding="utf-8") as f:
                pages = json.load(f)
            for page in pages:
                manifest[page["id"]] = page.get("textures", [])
            debug_output(f"[texture] loaded page manifest {path} ({len(manifest)} pages)")
        else:
            debug_output(
                f"[texture] no texture_pages.json found above {start_dir} - "
                f"falling back to each MTRL's own box, which is usually just "
                f"the full source-file bounds, not the real on-page rect"
            )
        cls._manifest_cache[start_dir] = manifest
        return manifest

    def _resolve_material_texture(
        self, page_id, index_on_page, tex_name, x0, y0, x2, y2, mesh_uv_bounds=None
    ):
        """Locates the source page PNG for a material.

        Verified against Hero_2782 (every one of its 36 materials): the
        mesh's own baked UV (vbuf columns 6/7) is already an absolute
        coordinate on the FULL shared page - it lands exactly inside the
        manifest's "box" for that (page, index_on_page) with no flip and no
        rescale needed (gotcha #3). So we just reference the whole page
        directly and let the baked UV do the placement; we do NOT derive
        any offset/scale from box/source_box here.

        The manifest lookup and mesh_uv_bounds below are kept purely as
        diagnostics: they log the page's own claimed rect and the rect the
        mesh's actual UV resolves to (in that same page's pixels), so a
        mismatch (e.g. a page.png that doesn't match the build this NMF
        was baked against) is visible in the console without extra
        tooling.

        Returns None if the page file is missing - the material then falls
        back to its flat color."""
        path = os.path.join(self.textures_dir, f"{page_id}.png")
        if not os.path.exists(path):
            debug_output(f"[texture] '{tex_name}' page {page_id}: NOT FOUND at {path}")
            return None

        try:
            atlas_w, atlas_h = self._read_png_dimensions(path)
        except (OSError, ValueError, struct_error) as e:
            debug_output(f"[texture] '{tex_name}' page {page_id}: cannot read {path} ({e})")
            return None

        obtained = ""
        if mesh_uv_bounds is not None:
            umin, vmin, umax, vmax = mesh_uv_bounds
            obtained = (
                f", obtained coords (from mesh UV) "
                f"({umin * atlas_w:.1f},{vmin * atlas_h:.1f})-"
                f"({umax * atlas_w:.1f},{vmax * atlas_h:.1f})"
            )

        page_textures = self.page_manifest.get(page_id)
        if page_textures is not None and 0 <= index_on_page < len(page_textures):
            box = page_textures[index_on_page].get("box")
            if box:
                debug_output(
                    f"[texture] '{tex_name}' page {page_id}: found {path} "
                    f"({atlas_w}x{atlas_h}), MTRL rect ({x0},{y0})-({x2},{y2}), "
                    f"manifest on-page rect ({box['x0']},{box['y0']})-"
                    f"({box['x2']},{box['y2']}){obtained}"
                )
                return {"path": path}

        debug_output(
            f"[texture] '{tex_name}' page {page_id}: found {path} "
            f"({atlas_w}x{atlas_h}), MTRL rect ({x0},{y0})-({x2},{y2}) "
            f"[no manifest entry]{obtained}"
        )
        return {"path": path}

    # -- animation curves -------------------------------------------------

    # Confirmed via GHIDRA_FINDINGS.md: when a node's `ANIM`/`MESH_ANIM` block has
    # `interpolation` set, the engine remaps the linear fraction `t` between two
    # keyframes through a cosine ease-in-out before mixing values - the exact
    # constants read out of `VaBank.exe`'s `.rdata` (0x553c28=pi, 0x5592f8=pi/2,
    # 0x5560b0=1.0, 0x559340=2.0; formula `(sin(t*pi - pi/2) + 1) / 2`) simplify
    # to `(1 - cos(pi*t)) / 2`. Checked against the full asset set: this is not a
    # rare edge case - 77% of `ANIM` blocks (999/1304) and 51% of `MESH_ANIM`
    # clips (335/651) have it set. Neither FBX's nor glTF's animation-curve
    # formats have a native "cosine ease between exactly these two keys" curve
    # type, so this is reproduced the same way `_subdivide_wide_rotation_segments`
    # already handles a different curve-shape problem: bake extra, densely-eased
    # intermediate keyframes along each real segment, and let the target format's
    # own plain linear/STEP playback connect them.
    _EASE_SAMPLES_PER_SEGMENT = 8

    @staticmethod
    def _ease_cosine(t):
        return (1.0 - math.cos(math.pi * t)) / 2.0

    @staticmethod
    def _apply_ease_supersampling(frames, values, eased):
        """No-op unless `eased` (the node/clip's `interpolation` flag) is set, or
        there are fewer than 2 keys to ease between. Otherwise inserts
        `_EASE_SAMPLES_PER_SEGMENT` extra points between every pair of adjacent
        real keyframes: `frames` gets evenly-spaced times (same as an unsegmented
        linear resample would), but each point's `values` entry is mixed using
        `_ease_cosine(t)` instead of `t` itself - baking the true eased curve
        shape into a dense-enough sequence of straight-line segments that a
        downstream linear player reproduces it closely, without needing a
        native "eased" curve type in the target format."""
        if not eased or len(frames) < 2:
            return frames, values
        n = NmfSceneConverter._EASE_SAMPLES_PER_SEGMENT
        out_frames = [frames[0]]
        out_values = [values[0]]
        for i in range(1, len(frames)):
            f0, f1 = frames[i - 1], frames[i]
            v0, v1 = values[i - 1], values[i]
            for s in range(1, n + 1):
                t = s / n
                out_frames.append(f0 + (f1 - f0) * t)
                out_values.append(v0 + (v1 - v0) * NmfSceneConverter._ease_cosine(t))
        return out_frames, out_values

    @staticmethod
    def _animation_build_tracks_by_axis(unpacked):
        """Builds per-axis Translation/Rotation/Scale keyframe tracks from
        a node's raw `unpacked["animation"]` block - see gotcha #18 for why
        every axis that ends up here is padded to at least 2 keyframes, even
        ones that were never actually animated. Used by FRAM (and LOCA);
        JOIN uses the deliberately simpler
        `_animation_build_tracks_by_axis_join` instead - see gotcha #27."""
        raw_values = unpacked.get("animation") or {}
        eased = bool(raw_values.get("interpolation"))
        axes = ("x", "y", "z")
        static_defaults = {
            "translation": list(unpacked.get("translation", [0.0, 0.0, 0.0])),
            "rotation": [r * RAD2DEG for r in unpacked.get("rotation", [0.0, 0.0, 0.0])],
            "scale": list(unpacked.get("scale", [1.0, 1.0, 1.0])),
        }

        # Pass 1: build every axis that has any real keyframe data at all,
        # however many keys - gaps get backfilled in pass 2.
        per_track = {}
        for track in ("translation", "rotation", "scale"):
            anim = raw_values.get(track)
            if not anim:
                continue
            times = anim.get("times") or {}
            values = anim.get("values") or {}
            track_hash = {}
            for ax in axes:
                tlist = times.get(ax)
                vlist = values.get(ax)
                if not tlist or not vlist:
                    continue
                frames = [float(t) * FPS for t in tlist]
                vals = [float(v) for v in vlist]
                wrapped = False
                if track == "rotation":
                    vals = [v * RAD2DEG for v in vals]
                    vals = NmfSceneConverter._unwrap_degrees(vals)
                    frames, vals = NmfSceneConverter._apply_ease_supersampling(
                        frames, vals, eased
                    )
                    frames, vals = (
                        NmfSceneConverter._subdivide_wide_rotation_segments(
                            frames, vals
                        )
                    )
                    pre_wrap_len = len(frames)
                    frames, vals = NmfSceneConverter._wrap_rotation_into_range(
                        frames, vals
                    )
                    wrapped = len(frames) > pre_wrap_len
                else:
                    frames, vals = NmfSceneConverter._apply_ease_supersampling(
                        frames, vals, eased
                    )
                track_hash[ax] = {"frames": frames, "values": vals, "linear": wrapped}
            if track_hash:
                per_track[track] = track_hash

        if not per_track:
            return {}

        # Gotcha #18: Blender's FBX importer silently drops an entire
        # AnimCurveNode unless its "d|X" channel specifically has >= 2
        # keyframes - confirmed by direct experiment (moving the only real
        # keys from d|Z to d|X made the animation appear; d|Z and d|Y with
        # no d|X curve at all showed nothing; a 1-key d|X curve also showed
        # nothing; a 2-key constant d|X curve worked). So every axis of
        # every track built above is padded to >= 2 keys here: a shared
        # time span is taken from whichever real (>= 2 key) axis exists
        # anywhere on this node (falling back to a synthetic 1-second span
        # if nothing on the node has 2+ keys at all - e.g. an all-1-key
        # "scale" track with no animated rotation/translation to borrow a
        # span from), and any axis with 0 or 1 keys is expanded to that
        # span at a constant value - its own single keyframe's value if it
        # had one, otherwise the node's static Lcl default for that axis.
        span_frames = [
            f
            for track_hash in per_track.values()
            for curve in track_hash.values()
            if len(curve["frames"]) >= 2
            for f in (curve["frames"][0], curve["frames"][-1])
        ]
        if span_frames:
            t0, t1 = min(span_frames), max(span_frames)
            if t0 == t1:
                t1 = t0 + FPS
        else:
            t0 = next(
                curve["frames"][0]
                for track_hash in per_track.values()
                for curve in track_hash.values()
            )
            t1 = t0 + FPS

        for track, track_hash in per_track.items():
            for ax_idx, ax in enumerate(axes):
                curve = track_hash.get(ax)
                if curve is not None and len(curve["frames"]) >= 2:
                    continue
                value = curve["values"][0] if curve else static_defaults[track][ax_idx]
                track_hash[ax] = {"frames": [t0, t1], "values": [value, value]}
                DEBUG and debug_output(
                    f"[curve-pad] track={track} axis={ax}: padded to 2 keys "
                    f"(frames=[{t0},{t1}], value={value})"
                )

        # Gotcha #21: a node with a genuinely multi-axis rotation (e.g.
        # X/Y/Z all animated together, not just one axis wrapping through
        # +-180) needs consistent interpolation across all 3 axes of that
        # *same* rotation - mixing gotcha #19's LINEAR (on whichever axis
        # crossed +-180) with CUBIC (on the others, untouched by wrap)
        # reportedly produced not just a wrong-direction spin but an
        # unpredictable tumble involving axes that shouldn't have been
        # moving much at all. If any axis of this node's rotation went
        # through the wrap, every axis of that same rotation is forced to
        # LINEAR too, even ones that never crossed +-180 on their own.
        rotation_hash = per_track.get("rotation")
        if rotation_hash and any(c.get("linear") for c in rotation_hash.values()):
            for curve in rotation_hash.values():
                curve["linear"] = True

            # Gotcha #22: root-caused by direct experiment (dumping the
            # actual imported F-curve keyframes from Blender's Python
            # console) - gotcha #21's interpolation-consistency fix wasn't
            # enough either. When a node's rotation axes don't all share
            # the same keyframe *times* (Z gets extra points from the wrap
            # above; X/Y don't), Blender's importer resamples the missing
            # axes onto the union of times itself - by round-tripping
            # through a rotation matrix/quaternion and re-decomposing back
            # to XYZ Euler - and its re-decomposition isn't continuity-
            # aware against the *other* keyframes already on that curve:
            # confirmed exactly by the numbers - at our wrap-crossing
            # frame, Blender's own resampled X/Y/Z came back as
            # (rx+180, 180-ry, rz+180), the mathematically-equivalent
            # "flipped" Euler branch, while the original endpoint keys
            # stayed on the direct branch. Both branches encode the same
            # rotation individually, but interpolating from a direct-
            # branch key to a flipped-branch one traces a completely wrong
            # path. Fix: give Blender nothing to resample - every rotation
            # axis of this node is forced onto the exact same set of
            # keyframe times (the union of all of them), each axis
            # filling any new point via plain linear interpolation of its
            # own already-correct curve.
            all_times = sorted(
                {t for curve in rotation_hash.values() for t in curve["frames"]}
            )
            merged_times = [all_times[0]]
            for t in all_times[1:]:
                if t - merged_times[-1] > 1e-4:
                    merged_times.append(t)

            for curve in rotation_hash.values():
                if curve["frames"] == merged_times:
                    continue
                curve["values"] = [
                    NmfSceneConverter._interp_linear(
                        curve["frames"], curve["values"], t
                    )
                    for t in merged_times
                ]
                curve["frames"] = list(merged_times)

        return per_track

    @staticmethod
    def _interp_linear(frames, values, t):
        if t <= frames[0]:
            return values[0]
        if t >= frames[-1]:
            return values[-1]
        for i in range(1, len(frames)):
            if t <= frames[i]:
                f0, f1 = frames[i - 1], frames[i]
                v0, v1 = values[i - 1], values[i]
                frac = 0.0 if f1 == f0 else (t - f0) / (f1 - f0)
                return v0 + (v1 - v0) * frac
        return values[-1]

    @staticmethod
    def _unwrap_degrees_unconditional(vals):
        """The original gotcha #6 form of `_unwrap_degrees`, before gotcha
        #13 added its "leave clearly-non-wraparound whole turns alone"
        exception. Always takes the shortest path between consecutive
        keys, unconditionally. Used only by
        `_animation_build_tracks_by_axis_join` - see gotcha #27's
        write-up for why JOIN needs this exact older behaviour instead of
        the shared, gotcha-#13-refined `_unwrap_degrees`."""
        if not vals:
            return vals
        out = [vals[0]]
        for v in vals[1:]:
            prev = out[-1]
            delta = v - prev
            delta -= 360.0 * round(delta / 360.0)
            out.append(prev + delta)
        return out

    @staticmethod
    def _animation_build_tracks_by_axis_join(unpacked):
        """Gotcha #27: JOIN's own, deliberately primitive counterpart to
        `_animation_build_tracks_by_axis` - ported verbatim (module-scope
        `FPS`/`RAD2DEG` aside) from this converter's very first working
        version, from before gotchas #12-26 (pivot-chain splitting, the
        rotation wrap/subdivide pipeline, per-axis rotation-node splitting,
        MESH_ANIM) existed at all: only unwrap runs on rotation (no
        `_subdivide_wide_rotation_segments`, no
        `_wrap_rotation_into_range`), and - unlike the FRAM/LOCA path -
        axes are NOT padded to >= 2 keyframes (gotcha #18); a single-key
        axis is written exactly as one key.

        Two separate FRAM-only refinements turned out to both actively
        hurt a character rig's JOIN curves, not just be unnecessary for
        them - confirmed by diffing this method's own output against the
        original script's, node by node, curve by curve, after the first
        attempt (padding removed, but still calling the *current*,
        gotcha-#13-refined `_unwrap_degrees`) still reproduced the
        reported flung-limb corruption on `baby_new2_2660`:
        1. Padding every axis to >= 2 keys (gotcha #18) - dropped here, as
           in the first attempt.
        2. `_unwrap_degrees` itself: gotcha #13 added an exception so a
           continuously-spinning FRAM part's genuine 0->360 full turn
           isn't collapsed to ~0. Diffing every JOIN rotation curve
           between the two scripts found ~20 axes with identical keyframe
           *counts* but different *values* - exactly this exception
           firing on a character's dense, fast mocap-style keyframes
           where a large delta between adjacent samples is coincidentally
           close to a multiple of 360 but is NOT a real full turn, so the
           exception wrongly leaves the long-way-around raw delta in
           place instead of correcting it - directly producing a limb
           that swings the wrong, long way. `_unwrap_degrees_unconditional`
           (gotcha #6's original, exception-free form) is used here
           instead.
        """
        axes = ("x", "y", "z")
        result = {}
        raw_values = unpacked.get("animation") or {}
        eased = bool(raw_values.get("interpolation"))
        for track in ("translation", "rotation", "scale"):
            anim = raw_values.get(track)
            if not anim:
                continue
            times = anim.get("times")
            values = anim.get("values")
            if not times or not values:
                continue
            track_hash = {}
            for ax in axes:
                tlist = times.get(ax)
                vlist = values.get(ax)
                if not tlist or not vlist:
                    continue
                frames = [float(t) * FPS for t in tlist]
                vals = [float(v) for v in vlist]
                if track == "rotation":
                    vals = [v * RAD2DEG for v in vals]
                    vals = NmfSceneConverter._unwrap_degrees_unconditional(vals)
                frames, vals = NmfSceneConverter._apply_ease_supersampling(
                    frames, vals, eased
                )
                track_hash[ax] = {"frames": frames, "values": vals}
            if track_hash:
                result[track] = track_hash
        return result

    # -- per-node-type conversion -----------------------------------------

    def _convert_root_node(self, node):
        unpacked = node["payload"]
        mm = self._dx_to_blender_matrix(unpacked["local_matrix"])
        # The DirectX-Y-up to Blender/FBX-Z-up axis swap is applied exactly
        # once, here at the scene root; every other node's matrix stays in
        # its own parent-relative local space and the swap cascades down
        # through ordinary hierarchical transform composition.
        y_up_to_z_up = [
            [1, 0, 0, 0],
            [0, 0, 1, 0],
            [0, 1, 0, 0],
            [0, 0, 0, 1],
        ]
        world_matrix = self._mat_mul(y_up_to_z_up, mm)
        t, s, r = self._decompose_directx_row_major(world_matrix)
        # Note: ROOT is never observed to carry animation in this engine's
        # assets, so (unlike FRAM/JOIN/LOCA below) this intentionally does
        # not branch on `unpacked.get("animation")` or set "animations".
        return {
            "node_type": "fram",
            "node_name": node["name"],
            "mesh": False,
            "translation": list(t),
            "scale": list(s),
            "rotation": [x * RAD2DEG for x in r],
        }

    _PIVOT_EPSILON = 1e-6

    @staticmethod
    def _vec_nonzero(v, eps=_PIVOT_EPSILON):
        return any(abs(c) > eps for c in v)

    @staticmethod
    def _is_identity_segment(seg, eps=_PIVOT_EPSILON):
        """A pivot-chain segment (see `_convert_fram_node`, gotcha #12) that
        contributes nothing - no animation and a plain T=0/R=0/S=1 transform
        - can be dropped from the chain instead of emitting a pointless
        pass-through Null."""
        if seg.get("animations"):
            return False
        return (
            not NmfSceneConverter._vec_nonzero(seg.get("translation", [0, 0, 0]), eps)
            and not NmfSceneConverter._vec_nonzero(seg.get("rotation", [0, 0, 0]), eps)
            and all(abs(c - 1.0) <= eps for c in seg.get("scale", [1, 1, 1]))
        )

    @staticmethod
    def _build_rotation_axis_nodes(node_name, static_rotation_deg, rotation_animations):
        """Gotcha #23: splits a node's compound X/Y/Z "Lcl Rotation" into 3
        separate nodes, each animated on exactly one axis, chained
        RotateZ -> RotateY -> RotateX to match this file's R = Rz*Ry*Rx
        composition convention (see `_decompose_directx_row_major`) via
        unambiguous parent-child hierarchy.

        Confirmed necessary, not just theoretical, by dumping Blender's
        own imported F-curve keyframes from its Python console: for a
        genuinely multi-axis rotation, Blender's FBX importer round-trips
        the WHOLE curve through a rotation matrix/quaternion on import and
        re-decomposes it back to XYZ Euler itself - regardless of what
        literal per-key values were written (gotcha #22's fix of pre-
        supplying every axis with matching, already-correct keyframe times
        made no difference; Blender still re-derived its own values and
        picked the OTHER of the two mathematically-equivalent Euler
        branches, (rx+180, 180-ry, rz+180), at the keys next to a wrap
        crossing). A single-axis rotation has no such branch ambiguity -
        there is only one way to decompose "rotate around Z alone" - so
        splitting removes the compound decomposition Blender's importer
        was reprocessing, rather than trying to out-guess how it picks a
        branch.

        Reintroduces gotcha #18 per node: each of these has its own "Lcl
        Rotation" AnimCurveNode carrying only its own axis, so the RZ/RY
        nodes (whose real axis isn't X) need a dummy constant d|X curve
        added again for Blender to recognize them at all."""
        axes = [("z", 2, "_rz"), ("y", 1, "_ry"), ("x", 0, "_rx")]
        nodes = []
        for axis, idx, suffix in axes:
            rot = [0.0, 0.0, 0.0]
            rot[idx] = static_rotation_deg[idx]
            track = rotation_animations.get(axis)
            node_animations = {}
            if track:
                node_animations["rotation"] = {axis: track}
                if axis != "x":
                    node_animations["rotation"]["x"] = {
                        "frames": [track["frames"][0], track["frames"][-1]],
                        "values": [0.0, 0.0],
                        "linear": track.get("linear", False),
                    }
            nodes.append(
                {
                    "node_type": "fram",
                    "node_name": node_name + suffix,
                    "mesh": False,
                    "translation": [0.0, 0.0, 0.0],
                    "rotation": rot,
                    "scale": [1.0, 1.0, 1.0],
                    "animations": node_animations,
                }
            )
        return nodes

    @staticmethod
    def _offset_translation_track(translation_track, offset):
        """Gotcha #24: an animated "Lcl Translation" curve is used as-is by
        FBX/Blender at every keyframe - the static Model property default
        (here, `unpacked["translation"] + rotate_pivot_translate`, see
        `outer["translation"]` above) is *only* a fallback for when no curve
        is connected at all, and is otherwise completely ignored once a
        curve exists. The raw NMF `translation` animation channel only ever
        carries `unpacked["translation"]`'s own animated value - it knows
        nothing about `rotate_pivot_translate` (RotationOffset), which is a
        separate static pivot field that still has to land in the same
        "Lcl Translation" curve on `outer` (there's nowhere else for it to
        go, since `outer` is the one node in the chain that actually carries
        the animated T). Skipping this addition silently drops
        RotationOffset for any FRAM whose translation is animated *and* has
        a non-zero rotate_pivot_translate (confirmed on the mummy's
        `pSphere8`: its baked-in position was off by exactly this offset,
        rotated into world space by its parent chain - found by comparing
        ufbx's evaluated `Lcl Translation` against the raw NMF `anim.
        translation.values`, which matched exactly, while the *static*
        default matched `rotate_pivot_translate` alone).
        """
        axes = ("x", "y", "z")
        return {
            axis: {
                **translation_track[axis],
                "values": [
                    v + offset[i] for v in translation_track[axis]["values"]
                ],
            }
            for i, axis in enumerate(axes)
            if axis in translation_track
        }

    def _split_fram_pivot_chain(
        self,
        node,
        unpacked,
        animations,
        rotate_pivot,
        rotate_pivot_translate,
        scale_pivot,
        scale_pivot_translate,
    ):
        """Gotcha #12/#20: decomposes an animated FRAM's Maya-style pivot
        transform - T * RotationOffset * RotationPivot * R * RotationPivot^-1
        * ScalingOffset * ScalingPivot * S * ScalingPivot^-1 (the same chain
        FBX's RotationPivot/RotationOffset/ScalingPivot/ScalingOffset Model
        properties encode) - into a chain of plain nodes, each using only
        ordinary Translation/Rotation/Scaling, one node per raw pivot field
        instead of gotcha #12's algebraic Roff+Rp / Sp+Soff-Rp re-grouping:

            outer                (animated): T + RotationOffset
            _rotatePivot         (animated): RotationPivot, R
            _scalePivotTranslate (static):   ScalingOffset - RotationPivot
            _scalePivot          (animated): ScalingPivot, S
            _pivot                (static):  -ScalingPivot

        `_scalePivotTranslate` absorbs RotationPivot's inverse (there's no
        named field for that "undo" step - nothing else in the chain can
        cancel it before ScalingOffset/ScalingPivot happen) and `_pivot`
        absorbs ScalingPivot's inverse the same way, for the same reason
        relative to wherever this FRAM's own children attach. Every other
        node carries exactly one raw pivot field's own value, unmodified -
        no algebraic combining beyond what's mathematically unavoidable.
        Verified exact by hand against the formula above (same derivation
        as gotcha #12, just not re-grouped down to 3 nodes).

        (Gotcha #17 replaced the original 3-node version with a
        single-node, baked-Translation version to sidestep gotchas
        #14/#15/#16's Blender misattribution chase - reverted after the
        baked version turned out to compute genuinely wrong transforms,
        not just an importer-compatibility issue. Gotcha #20 then tried
        splitting the rotation itself across 3 single-axis nodes to test a
        rotation-order hypothesis for a still-open wrong-direction report -
        reverted in favor of this per-pivot-field split instead, since the
        report at the time didn't point at rotation specifically. Gotchas
        #21/#22 chased the same report further and, this time with actual
        evidence (Blender's own imported keyframes dumped from its Python
        console), confirmed it *was* about compound rotation after all -
        gotcha #23 brings the per-axis split back, layered on top of this
        per-pivot-field chain rather than replacing it, once `R` needs it.)
        """
        DEBUG and debug_output(
            f"[pivot] {node['name']} (index {node['index']}): "
            f"rotate_pivot={rotate_pivot} rotate_pivot_translate={rotate_pivot_translate} "
            f"scale_pivot={scale_pivot} scale_pivot_translate={scale_pivot_translate} "
            f"static_translation={unpacked['translation']} static_rotation_deg="
            f"{[x * RAD2DEG for x in unpacked['rotation']]} static_scale={unpacked['scale']} "
            f"anim_tracks={list(animations.keys())}"
        )
        outer = {
            "node_type": "fram",
            "node_name": node["name"],
            "mesh": False,
            "translation": [
                unpacked["translation"][i] + rotate_pivot_translate[i]
                for i in range(3)
            ],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "animations": (
                {
                    "translation": self._offset_translation_track(
                        animations["translation"], rotate_pivot_translate
                    )
                }
                if "translation" in animations
                else {}
            ),
        }
        rotate_pivot_node = {
            "node_type": "fram",
            "node_name": node["name"] + "_rotatePivot",
            "mesh": False,
            "translation": list(rotate_pivot),
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "animations": {},
        }
        # Gotcha #23: the rotation itself is no longer a single compound
        # X/Y/Z curve on `rotate_pivot_node` - it's 3 chained single-axis
        # nodes instead, see `_build_rotation_axis_nodes`.
        rotation_axis_nodes = self._build_rotation_axis_nodes(
            node["name"] + "_rotatePivot",
            [x * RAD2DEG for x in unpacked["rotation"]],
            animations.get("rotation", {}),
        )
        scale_pivot_translate_node = {
            "node_type": "fram",
            "node_name": node["name"] + "_scalePivotTranslate",
            "mesh": False,
            "translation": [
                scale_pivot_translate[i] - rotate_pivot[i] for i in range(3)
            ],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "animations": {},
        }
        scale_pivot_node = {
            "node_type": "fram",
            "node_name": node["name"] + "_scalePivot",
            "mesh": False,
            "translation": list(scale_pivot),
            "rotation": [0.0, 0.0, 0.0],
            "scale": list(unpacked["scale"]),
            "animations": (
                {"scale": animations["scale"]} if "scale" in animations else {}
            ),
        }
        inner = {
            "node_type": "fram",
            "node_name": node["name"] + "_pivot",
            "mesh": False,
            "translation": [-c for c in scale_pivot],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "animations": {},
        }
        chain_tail = [
            seg
            for seg in (
                rotate_pivot_node,
                *rotation_axis_nodes,
                scale_pivot_translate_node,
                scale_pivot_node,
                inner,
            )
            if not self._is_identity_segment(seg)
        ]
        DEBUG and debug_output(
            f"[pivot] {node['name']}: chain = "
            f"[outer:{outer['node_name']} T={outer['translation']} "
            f"anim={list(outer['animations'].keys())}] -> "
            + " -> ".join(
                f"[{seg['node_name']} T={seg['translation']} R={seg['rotation']} "
                f"S={seg['scale']} anim={list(seg['animations'].keys())}]"
                for seg in chain_tail
            )
            if chain_tail
            else f"[pivot] {node['name']}: chain = [outer only, rest identity]"
        )
        outer["_pivot_chain"] = chain_tail
        return outer

    def _convert_fram_node(self, node, fold):
        unpacked = node["payload"]
        if unpacked.get("animation"):
            # TRS/pivot fields are reliable when animation is present (see
            # NMF_FORMAT.md's transform-reliability notes) - but FBX's own
            # RotationPivot/RotationOffset/ScalingPivot/ScalingOffset Model
            # properties (the obvious way to represent them) are only
            # honoured by most importers for the *static* pose - once
            # Rotation is an animated curve, they silently rotate around the
            # node's own local origin instead, so an off-centre hinge (e.g.
            # a door) spins in place rather than swinging. See gotcha #12:
            # `_split_fram_pivot_chain` sidesteps this entirely by baking
            # the pivot algebra into a short chain of plain Translation/
            # Rotation/Scaling nodes instead of relying on those properties.
            rotate_pivot = unpacked.get("rotate_pivot", [0.0, 0.0, 0.0])
            rotate_pivot_translate = unpacked.get(
                "rotate_pivot_translate", [0.0, 0.0, 0.0]
            )
            scale_pivot = unpacked.get("scale_pivot", [0.0, 0.0, 0.0])
            scale_pivot_translate = unpacked.get(
                "scale_pivot_translate", [0.0, 0.0, 0.0]
            )
            animations = self._animation_build_tracks_by_axis(unpacked)

            if self._vec_nonzero(rotate_pivot) or self._vec_nonzero(
                rotate_pivot_translate
            ) or self._vec_nonzero(scale_pivot) or self._vec_nonzero(
                scale_pivot_translate
            ):
                processed = self._split_fram_pivot_chain(
                    node,
                    unpacked,
                    animations,
                    rotate_pivot,
                    rotate_pivot_translate,
                    scale_pivot,
                    scale_pivot_translate,
                )
            else:
                # Gotcha #23: even with no pivot to worry about, rotation
                # is still split across 3 single-axis nodes - see
                # `_build_rotation_axis_nodes` - instead of one node's
                # compound X/Y/Z "Lcl Rotation" curve, for the same reason
                # as the pivoted case: Blender's importer round-trips a
                # genuinely multi-axis curve through a matrix/quaternion on
                # import and can re-decompose it onto the wrong (but
                # locally equivalent) Euler branch. `translate` carries
                # Translation only; Scaling is folded onto the innermost
                # (X) rotation node, right above where this FRAM's own
                # children attach.
                translate = {
                    "node_type": "fram",
                    "node_name": node["name"],
                    "mesh": False,
                    "translation": unpacked["translation"],
                    "rotation": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                    "animations": (
                        {"translation": animations["translation"]}
                        if "translation" in animations
                        else {}
                    ),
                }
                rotation_axis_nodes = self._build_rotation_axis_nodes(
                    node["name"],
                    [x * RAD2DEG for x in unpacked["rotation"]],
                    animations.get("rotation", {}),
                )
                innermost = rotation_axis_nodes[-1]
                innermost["scale"] = list(unpacked["scale"])
                if "scale" in animations:
                    innermost["animations"]["scale"] = animations["scale"]

                chain_tail = [
                    seg
                    for seg in rotation_axis_nodes
                    if not self._is_identity_segment(seg)
                ]
                translate["_pivot_chain"] = chain_tail
                processed = translate
            return processed
        elif node["index"] in fold.fold_as_identity:
            # Folded away: this node's matrix (possibly containing shear)
            # gets baked into descendant mesh vertices instead - see
            # `_compute_transform_folds`. Left as an identity pass-through.
            processed = {"node_type": "fram", "node_name": node["name"], "mesh": False}
        else:
            mm = self._dx_to_blender_matrix(unpacked["local_matrix"])
            t, s, r = self._decompose_directx_row_major(mm)
            processed = {
                "node_type": "fram",
                "node_name": node["name"],
                "mesh": False,
                "translation": t,
                "scale": s,
                "rotation": [x * RAD2DEG for x in r],
            }
        processed["animations"] = self._animation_build_tracks_by_axis(unpacked)
        return processed

    def _convert_join_node(self, node, fold):
        unpacked = node["payload"]
        if unpacked.get("animation"):
            processed = {
                "node_type": "joint",
                "node_name": node["name"],
                "mesh": False,
                "translation": unpacked["translation"],
                "scale": unpacked["scale"],
                "rotation": [r * RAD2DEG for r in unpacked["rotation"]],
            }
            m3 = self._extract_3x3(unpacked.get("joint_orient_matrix"))
            processed["joint_orient"] = self._matrix_rowmajor_to_euler_xyz_standard(m3)
        elif node["index"] in fold.fold_as_identity:
            # See `_compute_transform_folds` - folded into descendant meshes.
            processed = {"node_type": "fram", "node_name": node["name"], "mesh": False}
        else:
            mm = self._dx_to_blender_matrix(unpacked["local_matrix"])
            t, s, r = self._decompose_directx_row_major(mm)
            processed = {
                "node_type": "fram",
                "node_name": node["name"],
                "mesh": False,
                "translation": t,
                "scale": s,
                "rotation": [x * RAD2DEG for x in r],
            }
        # Gotcha #27: JOIN uses the deliberately primitive
        # `_animation_build_tracks_by_axis_join` instead of FRAM's
        # wrap/subdivide/padding pipeline - see that method's docstring.
        processed["animations"] = self._animation_build_tracks_by_axis_join(unpacked)
        return processed

    def _convert_loca_node(self, node):
        unpacked = node["payload"]
        return {
            "node_type": "locator",
            "node_name": node["name"],
            "mesh": False,
            "translation": unpacked.get("translation", [0.0, 0.0, 0.0]),
            "scale": unpacked.get("scale", [1.0, 1.0, 1.0]),
            "rotation": [r * RAD2DEG for r in unpacked.get("rotation", [0.0, 0.0, 0.0])],
            "animations": self._animation_build_tracks_by_axis(unpacked),
        }

    def _build_mesh_materials(self, materials_in, node_name, raw_vbuf):
        if not materials_in:
            return [
                {
                    "mat_name": f"lambert_{node_name}",
                    "r": 0.8,
                    "g": 0.8,
                    "b": 0.8,
                    "a": 1.0,
                    "has_tex": False,
                }
            ]

        mesh_uv_us = [v[6] for v in raw_vbuf] if raw_vbuf else [0.0]
        mesh_uv_vs = [v[7] for v in raw_vbuf] if raw_vbuf else [0.0]
        mesh_uv_bounds = (
            min(mesh_uv_us),
            min(mesh_uv_vs),
            max(mesh_uv_us),
            max(mesh_uv_vs),
        )

        materials_out = []
        for m in materials_in:
            mat_name = (m.get("name") or "lambert") + f"_{node_name}"
            diffuse = m.get("diffuse", [0.8, 0.8, 0.8, 1.0])
            alpha = float(diffuse[3]) if len(diffuse) > 3 else 1.0
            tex_data = m.get("texture")
            tex_info = None
            if isinstance(tex_data, dict) and tex_data.get("kind") == "TXPG":
                atlas_rect = tex_data.get("atlas_rect", [0, 0, 0, 0])
                tex_info = self._resolve_material_texture(
                    tex_data.get("page", 0),
                    tex_data.get("index_on_page", 0),
                    tex_data.get("name", "?"),
                    atlas_rect[0] if len(atlas_rect) > 0 else 0,
                    atlas_rect[1] if len(atlas_rect) > 1 else 0,
                    atlas_rect[2] if len(atlas_rect) > 2 else 0,
                    atlas_rect[3] if len(atlas_rect) > 3 else 0,
                    mesh_uv_bounds,
                )
            tex_path = tex_info["path"] if tex_info is not None else None

            materials_out.append(
                {
                    "mat_name": mat_name,
                    "r": float(diffuse[0]) if len(diffuse) > 0 else 0.8,
                    "g": float(diffuse[1]) if len(diffuse) > 1 else 0.8,
                    "b": float(diffuse[2]) if len(diffuse) > 2 else 0.8,
                    "opacity": alpha,
                    "blend_mode": int(m.get("blend_mode", 0)),
                    "has_tex": bool(tex_path),
                    "tex_path": tex_path,
                    # uv_flip_u/uv_flip_v is intentionally NOT re-applied as
                    # a ModelUVScaling sign flip here - see gotcha #4 in the
                    # module docstring.
                    "repeatU": float(m.get("uv_scale_u", 1.0)),
                    "repeatV": float(m.get("uv_scale_v", 1.0)),
                    "offsetU": 0.0,
                    "offsetV": 0.0,
                    "rotateUV": self._uv_rotation_degrees(m.get("uv_rotation", 0)),
                }
            )
        return materials_out

    @staticmethod
    def _build_mesh_vertex_animations(vertex_animation_clips, vbuf, bake_matrix):
        """Gotcha #25: normalizes each vertex-animation clip's up-to-3
        independent per-axis delta curves into a flat list of per-axis
        channels, one per (vertex group, animated axis), ready for
        `FbxSceneAssembler._build_mesh_blendshape_data`. Also returns a
        `{vertex_index: [dx, dy, dz]}` base-position correction - almost
        always empty, since a clip's declared `rest_position` matches
        `vbuf[idx][0:3]` almost everywhere, but not quite in the "water
        ripple" assets, where `vbuf` already has a small baked-in offset
        from the perfectly flat grid `rest_position` describes; without
        this correction those meshes would visibly pop by that offset the
        instant the animation starts (t=0's curve value is always 0, so
        nothing else would supply it). `bake_matrix` (see
        `_bake_matrix_into_vertices`) is applied the same way it already is
        to this mesh's own vertex positions/normals, so a folded-away
        static parent transform doesn't leave the vertex animation
        pointing the wrong way or at the wrong base position.
        """
        channels = []
        corrections = {}
        axis_fields = (
            ("key_count_x", "delta_x", 0),
            ("key_count_y", "delta_y", 1),
            ("key_count_z", "delta_z", 2),
        )
        has_bake = bake_matrix is not None and bake_matrix != _IDENTITY4
        for clip in vertex_animation_clips or []:
            eased = bool(clip.get("interpolation"))
            indices = [
                vi for vi in (clip.get("vertex_indices") or []) if vi < len(vbuf)
            ]
            if not indices:
                continue
            base = clip.get("rest_position", [0.0, 0.0, 0.0])
            if has_bake:
                base = NmfSceneConverter._transform_point(bake_matrix, base)
            for vi in indices:
                correction = [base[k] - vbuf[vi][k] for k in range(3)]
                if any(abs(c) > 1e-6 for c in correction):
                    corrections[vi] = correction
            for size_key, values_key, axis in axis_fields:
                n = clip.get(size_key, 0)
                if not n:
                    continue
                flat = clip.get(values_key) or []
                # Raw NMF times are in seconds, same as FRAM/JOIN's own
                # `anim.<track>.keys` - `_animation_build_tracks_by_axis`
                # converts those to frame-numbers via `* FPS` before they
                # ever reach a KeyTime formula (`f * KTIME_PER_FRAME`
                # expects frame-numbers, not seconds); this needs the same
                # conversion, or every mesh-anim curve plays back 24x too
                # fast (confirmed with ufbx: an unconverted 0.0-0.8333s
                # curve's last key round-tripped to t=0.0347s instead of
                # 0.8333s).
                frames = [float(t) * FPS for t in flat[:n]]
                values = list(flat[n : n * 2])
                if len(frames) < 2:
                    # Gotcha #18's single-key padding applies here too -
                    # Blender's FBX importer drops a curve with only 1 key.
                    if len(frames) != 1:
                        continue
                    frames = [frames[0], frames[0] + FPS]
                    values = [values[0], values[0]]
                frames, values = NmfSceneConverter._apply_ease_supersampling(
                    frames, values, eased
                )
                unit_dir = [0.0, 0.0, 0.0]
                unit_dir[axis] = 1.0
                if has_bake:
                    unit_dir = NmfSceneConverter._transform_vector(
                        bake_matrix, unit_dir
                    )
                # Gotcha #26: Blender's FBX importer defaults an imported
                # BlendShapeChannel's slider_min/slider_max to 0/1 and,
                # unlike plain FCurve evaluation, actually clamps the
                # shape key's real `value` property to that range once
                # the driving animation is applied - a negative (or
                # >100%) weight gets silently discarded before it ever
                # reaches the mesh, even though the curve itself still
                # evaluates correctly in isolation. Confirmed directly on
                # the user's own Blender console: `FCurve.evaluate()`
                # returned the right (negative) number for
                # Maschine4x4_2621's pPlaneShape227, while the shape key's
                # actual `value` read back 0.0 at the same frame -
                # widening `slider_min` to -10 and assigning the value by
                # hand confirmed the clamp was the only thing standing
                # between a correct curve and a visibly broken mesh (a
                # part that was supposed to be "under the model" at that
                # frame stayed at its rest pose instead). Fixed by never
                # emitting a channel whose weight needs to leave [0, 1]:
                # each axis is split into up to two channels - one for the
                # positive-going part of the curve, one for the negative-
                # going part - each normalized against its own peak
                # magnitude (which is also usually not 1.0 - e.g. the
                # crate's -10.68 spike - so this doubles as the fix for
                # magnitudes over 100% too) with the direction vector
                # scaled by that same peak to compensate, so
                # weight(t)*scaled_dir reconstructs the exact original
                # signed delta at every keyframe regardless of the split.
                pos_peak = max([0.0] + [v for v in values if v > 0.0])
                neg_peak = max([0.0] + [-v for v in values if v < 0.0])
                for peak, sign in ((pos_peak, 1.0), (neg_peak, -1.0)):
                    if peak <= 0.0:
                        continue
                    weights = [
                        (max(0.0, v) if sign > 0.0 else max(0.0, -v)) / peak
                        for v in values
                    ]
                    channels.append(
                        {
                            "indices": indices,
                            "delta_dir": [c * peak * sign for c in unit_dir],
                            "frames": list(frames),
                            "values": weights,
                        }
                    )
        return channels, corrections

    def _convert_mesh_node(self, node, fold):
        unpacked = node["payload"]
        raw_vbuf = unpacked["vertices"]

        bake_matrix = fold.mesh_bake_matrix.get(node["index"])
        if bake_matrix is not None and bake_matrix != _IDENTITY4:
            raw_vbuf = self._bake_matrix_into_vertices(raw_vbuf, bake_matrix)

        mesh_animations, vertex_corrections = self._build_mesh_vertex_animations(
            unpacked.get("vertex_animations"), raw_vbuf, bake_matrix
        )
        if vertex_corrections:
            raw_vbuf = [list(v) for v in raw_vbuf]
            for vi, correction in vertex_corrections.items():
                for k in range(3):
                    raw_vbuf[vi][k] += correction[k]

        raw_ibuf = [[t[0], t[1], t[2]] for t in unpacked["indices"]]
        # Checked exactly once, before per-material vertex index shifting
        # below - see gotcha #9 in the module docstring.
        # if not self._is_mesh_right_handed(raw_ibuf, raw_vbuf):
            # raw_ibuf = [[t[0], t[1], t[2]] for t in raw_ibuf]

        materials_in = unpacked.get("materials", []) or []
        poly_mat_indices = self._assign_polygon_materials(raw_ibuf, materials_in)

        vrts = [[t[0], t[1], t[2]] for t in raw_vbuf]
        pvi = self._make_polygon_vertex_index_from_tris(raw_ibuf)
        uv_direct, uv_index = self._build_fbx_uv_layer(raw_vbuf, raw_ibuf)
        normals, normals_w = self._build_fbx_normals_flat(vrts, raw_ibuf)

        return {
            "node_type": "mesh",
            "node_name": node["name"],
            "vrts": vrts,
            "PolygonVertexIndex": pvi,
            "Edges": self._build_fbx_edges_from_pvi(pvi),
            "poly_mat_indices": poly_mat_indices,
            "UV": uv_direct,
            "UVIndex": uv_index,
            "Normals": normals,
            "NormalsW": normals_w,
            "materials_data": self._build_mesh_materials(
                materials_in, node["name"], raw_vbuf
            ),
            "mesh_animations": mesh_animations,
        }

    # -- entry point -------------------------------------------------------

    def convert(self, nodes):
        """Node ids are assigned up front so `parent` references below
        always resolve, regardless of the parent/child order in `nodes`."""
        index_map = {n["index"]: n for n in nodes}
        for node in nodes:
            node["id"] = self.uid_gen.next()

        fold = self._compute_transform_folds(nodes)

        result = []
        for node in nodes:
            node_type = node["type"]
            if node_type == "ROOT":
                processed = self._convert_root_node(node)
            elif node_type == "FRAM":
                processed = self._convert_fram_node(node, fold)
            elif node_type == "JOIN":
                processed = self._convert_join_node(node, fold)
            elif node_type == "LOCA":
                processed = self._convert_loca_node(node)
            elif node_type == "MESH":
                processed = self._convert_mesh_node(node, fold)
            else:
                processed = None

            if processed:
                parent = index_map.get(node.get("parent"))
                parent_fbx_id = parent["id"] if parent else 0

                # Gotcha #12: an animated FRAM with an off-centre pivot
                # comes back as an `outer` node plus a `_pivot_chain` of 1-2
                # extra static/animated segments (see
                # `_split_fram_pivot_chain`). The chain's last segment
                # reuses this raw node's own id, so any other raw NMF node
                # whose `parent` points at this one (via `index_map`
                # above) still resolves to the right FBX parent - the
                # innermost segment, exactly where this node's own children
                # belong.
                chain_tail = processed.pop("_pivot_chain", None)
                chain = [processed] + chain_tail if chain_tail else [processed]

                prev_id = parent_fbx_id
                for i, seg in enumerate(chain):
                    seg_id = node["id"] if i == len(chain) - 1 else self.uid_gen.next()
                    seg["id"] = seg_id
                    seg["parent_id"] = prev_id
                    seg["with_animation"] = bool(seg.get("animations"))
                    result.append(seg)
                    DEBUG and len(chain) > 1 and debug_output(
                        f"[wire] '{seg['node_name']}' id={seg_id} parent_id={prev_id} "
                        f"with_animation={seg['with_animation']} "
                        f"anim_tracks={list(seg.get('animations', {}).keys())}"
                    )
                    prev_id = seg_id

        self._mark_fram_parents_with_mesh_children(result)
        return result
