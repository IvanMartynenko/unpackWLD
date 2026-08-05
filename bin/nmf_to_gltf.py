#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

"""
Der Clou! 2 (The Sting! / Ва-Банк!) NMF to glTF/GLB Converter

Converts extracted NMF models directly into binary glTF 2.0 (.glb): a JSON
scene/animation graph plus one flat binary buffer, no external libraries
required. Sibling of `nmf_to_fbx.py`, sharing its entire Stage 1
(`nmf_scene_converter.NmfSceneConverter` - raw NMF nodes -> processed node
list, format-agnostic) - only Stage 2 (`GltfSceneAssembler`, building the
glTF JSON graph) and Stage 3 (`GlbWriter`, binary packing) differ.

Usage:
    python nmf_to_gltf.py [--debug] input.nmf output.glb

Why glTF instead of just extending nmf_to_fbx.py further: FBX was
originally chosen for this project because of Maya-style pivot support
(RotationOffset/RotationPivot/ScalingOffset/ScalingPivot) - but gotcha #12
in nmf_to_fbx.py's own docstring already abandoned those native FBX
properties in favour of manually expanding an animated FRAM's pivot into a
chain of plain Translation/Rotation/Scale nodes, because the native
properties don't reliably combine with animated rotation. That expansion
works identically well in any format with a plain TRS node hierarchy,
glTF included - so essentially nothing FBX-specific is left to justify
the format choice. Meanwhile FBX's own rotation representation (three
independent Euler X/Y/Z angles, each on its own animation curve) is
directly responsible for a long chain of bugs this project hit (gotchas
#6, #13, #19, #20-23, #26, #27): any importer that needs to resample or
recompose a multi-axis Lcl Rotation curve has to round-trip it through a
rotation matrix/quaternion, and can pick the wrong (but locally
equivalent) Euler branch doing so - Blender's FBX importer visibly does,
on both FRAM pivots and JOIN skeletons. glTF stores rotation as a
**quaternion** directly, at every keyframe - there is no Euler
decomposition step for an importer to get wrong, so this whole class of
bug does not exist here. See `_euler_xyz_deg_to_quat`/
`_build_rotation_channel` below for the (much simpler) replacement: this
file does its own Euler-to-quaternion conversion once, up front, using
authoritative source data, and only has to handle the standard, well-
understood "shortest path" quaternion sign-continuity fix - not an
importer's opaque internal branch choice.

Mesh-vertex animation / MESH_ANIM (blend shapes in the FBX path, gotcha
#25/#26): glTF's native representation is morph targets, one per
`mesh_animations` channel (`NmfSceneConverter._build_mesh_vertex_
animations`), each a `POSITION`-delta accessor on every primitive of that
mesh (glTF requires every primitive to declare the same target count/
order, so a channel that doesn't touch a given material-primitive's
vertices gets an explicit all-zero target rather than being skipped -
see `_add_zero_vec3_accessor`). Since NMF only ever displaces a named
vertex group by one shared delta vector, each target is written as a
`sparse` accessor (`_add_sparse_vec3_delta_accessor`) - a much more
direct fit than FBX's `Shape`/`BlendShapeChannel` deformer graph, and
without gotcha #26's Blender-importer slider-clamp problem: glTF's
morph target `weights` have no min/max at all, so the split-into-signed-
halves workaround `_build_mesh_vertex_animations` already does for the
FBX path (kept as-is, shared code) is unnecessary here but harmless -
each half just becomes its own morph target. All of a node's channels
are driven by one `weights` animation channel (glTF requires this - see
`_build_weights_channel`), not one channel per morph target.

Coordinate systems: `NmfSceneConverter` converts the source engine's
DirectX-Y-up matrices into Blender/FBX's Z-up convention once, at the
scene root (see its own docstring) - that conversion is shared with
`nmf_to_fbx.py` and is NOT re-done here. glTF's own spec mandates +Y up,
so `GltfSceneAssembler.assemble` wraps the single real root node in one
extra glTF node with a fixed -90-degree X rotation (Z-up -> Y-up),
instead of touching the shared Stage 1 conversion.

UV: glTF's spec fixes (0,0) at the *top-left* of a texture image - the
same convention the source data is already baked in (DirectX-style,
V increasing downward). `NmfSceneConverter._build_fbx_uv_layer` already
flipped V once for FBX/OpenGL-style consumers (gotcha #2) - that flip is
undone here (`v = 1.0 - flipped_v`) to recover the original raw V glTF
actually wants; applying FBX's flip to glTF would land every texture
upside down.

Geometry: `NmfSceneConverter`'s mesh output has per-vertex position/UV but
per-triangle-corner ("flat"/faceted) normals (`_build_fbx_normals_flat`) -
FBX's LayerElement system can index positions and normals independently,
but glTF's accessor model can't (one shared index per primitive). Rather
than force shared vertex normals (changing the shading look), this file
expands every triangle corner into its own vertex (no index buffer at
all - glTF primitives without `indices` just draw attributes in order,
grouped by 3 for TRIANGLES) - more data, zero ambiguity, identical
faceted look to the FBX path. Materials are per-primitive in glTF (no
per-polygon material index like FBX's `LayerElementMaterial`), so a
multi-material mesh becomes one primitive per material, each with its own
flat vertex range - the `PolygonVertexIndex`/`poly_mat_indices`
`NmfSceneConverter` already computed are reused here directly.

Two-sided rendering: `material.doubleSided` is set from the source
`MESH.backface_culling` flag (`main()` attaches it to each processed mesh
node - see there and `GltfSceneAssembler._build_material`). The raw flag
correlates on real assets with 0 on thin/open geometry - glass panes,
open cylinders/tori, interior-facing surfaces - and 1 (~91% of meshes) on
closed volumes; `doubleSided` is deliberately the *inverse* of the flag's
own name (`backface_culling=1` -> `doubleSided=True`, `=0` ->
`doubleSided=False`) - confirmed with the user after that correlation was
found, not a guess. `NmfSceneConverter`
used to unconditionally double every mesh's triangle count with an
identically-wound "mirrored" copy for this instead (`_convert_mesh_node`'s
old `mirrored_ibuf`) - removed once we found it never worked in the first
place: it duplicated each triangle with the *same* vertex order, so
`_build_fbx_normals_flat`'s cross-product gave the duplicate the exact
same normal too - geometrically inert, just double the triangles for zero
visual effect on either export path.

License: MIT License
"""

import sys, os
import json
import math
import struct
from struct import pack

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import Nmf
import nmf_scene_converter
from nmf_scene_converter import NmfSceneConverter, FPS

DEBUG = False


def debug_output(data):
    if DEBUG:
        print(data, file=sys.stderr)


# =============================================================================
# Quaternion / rotation-curve math
# =============================================================================


def _quat_mul(a, b):
    """Hamilton product, (x, y, z, w) order throughout (matches glTF's own
    quaternion component order)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _euler_xyz_deg_to_quat(rx_deg, ry_deg, rz_deg):
    """Converts (rx, ry, rz) in degrees to a quaternion, composing
    R = Rz(rz) * Ry(ry) * Rx(rx) - the exact same rotation-order
    convention `nmf_scene_converter`/`nmf_to_fbx.py` use everywhere else
    (see `_decompose_directx_row_major`'s own docstring), so a node's
    static rotation here always matches what the FBX path would have
    shown for the same node."""
    hx = math.radians(rx_deg) * 0.5
    hy = math.radians(ry_deg) * 0.5
    hz = math.radians(rz_deg) * 0.5
    qx = (math.sin(hx), 0.0, 0.0, math.cos(hx))
    qy = (0.0, math.sin(hy), 0.0, math.cos(hy))
    qz = (0.0, 0.0, math.sin(hz), math.cos(hz))
    return _quat_mul(_quat_mul(qz, qy), qx)


def _node_orient_quat(node):
    """JOIN's `joint_orient` (set by `_convert_join_node`, only when the
    JOIN is animated) is the FBX-path's "PreRotation": a fixed rest-pose
    orientation composed *before* the node's own (static+animated)
    `rotation`, not folded into it - the FBX path writes it as a separate
    `PreRotation` Model property for exactly this reason (mixing it into
    `Lcl Rotation` would double-apply it once real rotation animation
    exists). Missed here entirely at first: every JOIN's rotation was
    silently missing its own rest orientation, and since bones chain
    (each one's position depends on every ancestor's *correct*
    orientation), that collapsed a whole skeleton into a pile at the
    origin rather than just rotating individual bones wrong. Returns the
    quaternion to left-multiply onto `_euler_xyz_deg_to_quat(*rotation)`
    - identity (a no-op) if the node has no `joint_orient` at all (every
    other node type, and any non-animated JOIN, whose own `rotation`
    already has everything baked in via `_decompose_directx_row_major`)."""
    orient = node.get("joint_orient")
    if not orient:
        return (0.0, 0.0, 0.0, 1.0)
    return _euler_xyz_deg_to_quat(orient[0], orient[1], orient[2])


def _effective_rest_vec3(node, track, raw_key, default):
    """The value a `translation`/`rotation`/`scale` axis actually holds
    at time 0 (and, since this project never sets curve pre-extrapolation
    to anything but "hold the first key" - matching ufbx's own default
    behaviour - at any time before the first keyframe too), per axis.

    Found via a real character rig (`baby_new2`): several JOIN nodes
    carry a translation *animation curve* with just one keyframe (e.g.
    `x`, `y` each a single sample at t=0) while their raw `translation`
    field - a separate, independently-stored value in the NMF data - is
    plain `[0, 0, 0]`. ufbx (and any FBX importer) always prefers an
    AnimCurve over a Model property's static default whenever the curve
    exists, even with only one key, so the *true* rest position comes
    from the curve, not the raw field. Since `_build_vec3_channel`/
    `_build_rotation_channel` skip creating an actual glTF animation
    channel when a track has fewer than 2 distinct time points (a
    single-key curve carries no real motion), that true value would
    otherwise be silently dropped - the glTF node's static default fell
    back to the raw (wrong) field instead, collapsing the whole joint
    chain to the wrong place even though every node's own local
    rotation/scale had already been verified byte-exact against ufbx.

    Falls back to `raw_key`'s value per axis whenever that axis has no
    curve at all (including entirely non-animated nodes, where `track`
    isn't in `animations` and this is a plain passthrough)."""
    vals = list(node.get(raw_key, default))
    data = (node.get("animations") or {}).get(track)
    if data:
        for i, ax in enumerate(("x", "y", "z")):
            curve = data.get(ax)
            if curve and curve.get("values"):
                vals[i] = curve["values"][0]
    return vals


def _fix_quat_shortest_path(quats):
    """`q` and `-q` represent the identical rotation, but interpolating
    from one keyframe to the next with mismatched signs takes the "long
    way around" (the same underlying issue `_unwrap_degrees` exists to
    fix for Euler angles - see nmf_to_fbx.py's gotcha #6 - but for
    quaternions the fix is the textbook, well-understood one: flip the
    sign whenever consecutive keys' dot product goes negative). Mutates
    nothing - returns a new list."""
    if not quats:
        return quats
    out = [quats[0]]
    for q in quats[1:]:
        prev = out[-1]
        dot = prev[0] * q[0] + prev[1] * q[1] + prev[2] * q[2] + prev[3] * q[3]
        out.append(tuple(-c for c in q) if dot < 0.0 else q)
    return out


# glTF accessor componentType constants used below (the only ones this
# writer ever emits: everything is plain float32 data - no index buffers,
# see the module docstring's "Geometry" note for why).
_COMPONENT_FLOAT = 5126

# -90 degrees about X: the standard Z-up (this project's/Blender's/FBX's
# convention, produced once by `NmfSceneConverter._convert_root_node`) to
# Y-up (glTF's mandated convention) axis correction, applied as a single
# wrapper node around the whole real scene rather than by touching the
# shared Stage 1 conversion.
_Z_UP_TO_Y_UP_QUAT = _euler_xyz_deg_to_quat(-90.0, 0.0, 0.0)


class GltfSceneAssembler:
    """Stage 2+3 combined for glTF: builds the glTF JSON graph (nodes,
    meshes, materials, textures, animations) from the processed node list
    produced by `NmfSceneConverter.convert` (see that class - shared with
    `nmf_to_fbx.py`, no glTF knowledge at all), and owns the single flat
    binary buffer every accessor's data is appended to. `assemble` returns
    `(gltf_json_dict, buffer_bytes)`, ready for `GlbWriter.write`."""

    def __init__(self):
        self.buffer = bytearray()
        self.accessors = []
        self.buffer_views = []
        self.materials = []
        self.textures = []
        self.images = []
        self.samplers = []
        self._image_cache = {}  # abs path -> image index, gotcha #10's
        # FBX-side reasoning (avoid re-embedding the same shared texture
        # page once per material) applies identically here.

    # -- low-level buffer/accessor plumbing --------------------------------

    def _align4(self):
        while len(self.buffer) % 4 != 0:
            self.buffer.append(0)

    def _add_buffer_view(self, data_bytes):
        self._align4()
        offset = len(self.buffer)
        self.buffer.extend(data_bytes)
        idx = len(self.buffer_views)
        self.buffer_views.append(
            {"buffer": 0, "byteOffset": offset, "byteLength": len(data_bytes)}
        )
        return idx

    _ACCESSOR_NUM_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

    def _add_float_accessor(self, flat_values, gltf_type, with_bounds=False):
        """`flat_values` is a flat list of floats, `gltf_type` one of
        SCALAR/VEC2/VEC3/VEC4. `with_bounds=True` computes the per-
        component min/max glTF requires on POSITION accessors (and is
        harmless/allowed elsewhere)."""
        n = self._ACCESSOR_NUM_COMPONENTS[gltf_type]
        count = len(flat_values) // n
        packed = struct.pack(f"<{len(flat_values)}f", *flat_values)
        bv_idx = self._add_buffer_view(packed)
        accessor = {
            "bufferView": bv_idx,
            "componentType": _COMPONENT_FLOAT,
            "count": count,
            "type": gltf_type,
        }
        if with_bounds:
            comps = [flat_values[i::n] for i in range(n)]
            accessor["min"] = [min(c) for c in comps]
            accessor["max"] = [max(c) for c in comps]
        idx = len(self.accessors)
        self.accessors.append(accessor)
        return idx

    def _add_sparse_vec3_delta_accessor(self, count, sparse_pairs):
        """A morph target `POSITION` accessor: `count` entries, all zero
        except the `(corner_index, [dx,dy,dz])` pairs in `sparse_pairs`
        (`corner_index` must already be ascending - see
        `_build_mesh_primitives`'s per-channel loop order). Uses glTF's
        `sparse` accessor form (spec-designed for exactly this - a mostly-
        zero displacement set) instead of writing `count` mostly-zero
        floats: NMF's MESH_ANIM only ever displaces one named vertex
        group per channel (`NmfSceneConverter._build_mesh_vertex_
        animations`), typically a small fraction of the mesh. No
        `bufferView` on the accessor itself - the glTF spec has the
        reader zero-fill everything not covered by `sparse` in that case.
        min/max still has to cover the whole (mostly-zero) accessor, not
        just the sparse override values - every position bit is 0."""
        indices_flat = [i for i, _ in sparse_pairs]
        values_flat = [c for _, delta in sparse_pairs for c in delta]
        indices_bytes = struct.pack(f"<{len(indices_flat)}I", *indices_flat)
        values_bytes = struct.pack(f"<{len(values_flat)}f", *values_flat)
        indices_bv = self._add_buffer_view(indices_bytes)
        values_bv = self._add_buffer_view(values_bytes)
        xs = [0.0] + [d[0] for _, d in sparse_pairs]
        ys = [0.0] + [d[1] for _, d in sparse_pairs]
        zs = [0.0] + [d[2] for _, d in sparse_pairs]
        accessor = {
            "componentType": _COMPONENT_FLOAT,
            "count": count,
            "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
            "sparse": {
                "count": len(sparse_pairs),
                "indices": {"bufferView": indices_bv, "componentType": 5125},
                "values": {"bufferView": values_bv},
            },
        }
        idx = len(self.accessors)
        self.accessors.append(accessor)
        return idx

    def _add_zero_vec3_accessor(self, count):
        """A morph target `POSITION` accessor that's exactly zero
        everywhere - used for a mesh_animations channel that happens to
        touch none of one particular material-primitive's vertices (see
        `_build_mesh_primitives`'s "all primitives need the same target
        count/order" note). No `bufferView` at all - the whole accessor
        reads as zero-filled per spec, same trick as the sparse case
        above with an empty override set."""
        accessor = {
            "componentType": _COMPONENT_FLOAT,
            "count": count,
            "type": "VEC3",
            "min": [0.0, 0.0, 0.0],
            "max": [0.0, 0.0, 0.0],
        }
        idx = len(self.accessors)
        self.accessors.append(accessor)
        return idx

    # -- materials / textures ----------------------------------------------

    def _get_or_create_image(self, tex_path):
        if tex_path in self._image_cache:
            return self._image_cache[tex_path]
        with open(tex_path, "rb") as f:
            png_bytes = f.read()
        bv_idx = self._add_buffer_view(png_bytes)
        image_idx = len(self.images)
        self.images.append({"bufferView": bv_idx, "mimeType": "image/png"})
        texture_idx = len(self.textures)
        self.textures.append({"source": image_idx})
        self._image_cache[tex_path] = texture_idx
        return texture_idx

    def _build_material(self, mat, double_sided=True):
        """`mat` is one entry of `NmfSceneConverter._build_mesh_materials`'s
        output - either the textured/full form (`r`/`g`/`b`/`opacity`/
        `blend_mode`/`has_tex`/`tex_path` - `repeatU`/`repeatV`/`offsetU`/
        `offsetV`/`rotateUV` are also present but deliberately unused, see
        the "No KHR_texture_transform" comment below) or its no-materials
        fallback (`r`/`g`/`b`/`a` only). `double_sided` comes from the
        owning mesh node's raw `backface_culling` flag (see
        `_build_mesh_primitives`) - not part of `mat` itself, since it's a
        per-MESH, not per-material, NMF field. Returns a glTF
        `materials[]` entry index."""
        opacity = mat.get("opacity", mat.get("a", 1.0))
        # The source MTRL's red/green/blue/alpha floats aren't restricted
        # to [0,1] (confirmed on real assets - values >1 do occur; FBX's
        # DiffuseColor doesn't restrict its range either), but glTF's
        # baseColorFactor spec requires every component in [0,1] - clamp
        # rather than let a strict reader (the official Khronos validator
        # included) reject the material outright.
        base_color_factor = [
            max(0.0, min(1.0, mat["r"])),
            max(0.0, min(1.0, mat["g"])),
            max(0.0, min(1.0, mat["b"])),
            max(0.0, min(1.0, opacity)),
        ]
        pbr = {
            "baseColorFactor": base_color_factor,
            "metallicFactor": 0.0,
            # No PBR roughness data in the source format at all - fixed at
            # fully rough, which reads closest to the original flat/
            # Lambert-ish look (avoids an unintentionally shiny/plastic
            # default look a lower roughness would give every material).
            "roughnessFactor": 1.0,
        }
        # `double_sided` comes from the owning mesh's `backface_culling`
        # flag, deliberately inverted from that flag's own name - see the
        # module docstring's "Two-sided rendering" note and
        # `GltfSceneAssembler._build_mesh_primitives`.
        material = {
            "name": mat["mat_name"],
            "pbrMetallicRoughness": pbr,
            "doubleSided": double_sided,
        }
        if mat.get("has_tex") and mat.get("tex_path"):
            texture_idx = self._get_or_create_image(mat["tex_path"])
            # No KHR_texture_transform here (unlike an earlier version of
            # this file) - repeatU/repeatV/rotateUV are NOT a separate,
            # live UV transform to layer on top of TEXCOORD_0. Verified on
            # real assets (`Alarmanlage_169.nmf`'s `pCylinderShape11`,
            # `vertical_stretch=4.0`): the mesh's own vbuf UV already
            # spans V=[0,3.98], i.e. the 4x tiling is already baked into
            # the vertex UV itself - confirmed as the general rule across
            # hundreds of stretched materials (span scales with stretch,
            # not always exactly 1 unit per tile - it's stretch times
            # that material's own atlas sub-rect size). `rotate` likewise
            # was already shown (see `uvpt`'s investigation - its exact
            # affine relationship to the primary UV encodes `MTRL.rotate`)
            # to be baked into vbuf UV too. Applying repeatU/repeatV/
            # rotateUV *again* here double-applies an already-resolved
            # transform - exactly what produced the visibly wrong/skewed
            # texture sampling reported on this same file. FBX likely has
            # the identical bug (`nmf_to_fbx.py` writes the same
            # Rotation/ModelUVScaling Texture properties) - just probably
            # masked there because Blender's FBX importer doesn't reliably
            # apply per-texture UV transforms the way its glTF importer
            # (and `KHR_texture_transform`) does.
            pbr["baseColorTexture"] = {"index": texture_idx}
        if mat.get("blend_mode") in (1, 2):
            material["alphaMode"] = "BLEND"
        material_idx = len(self.materials)
        self.materials.append(material)
        return material_idx

    # -- mesh geometry -------------------------------------------------

    def _build_mesh_primitives(self, node):
        """Builds one glTF `mesh.primitives[]` entry per material used by
        this mesh node, each a flat (non-indexed, one vertex per triangle
        corner - see module docstring) POSITION/NORMAL/TEXCOORD_0 triple.

        `node["PolygonVertexIndex"]` is FBX-encoded (each triangle's last
        corner is `-(v+1)`, `NmfSceneConverter._pvi_vertex` undoes that).
        Two-sided rendering is handled entirely via `material.doubleSided`
        (see module docstring) - no geometry duplication involved.
        """
        pvi = node["PolygonVertexIndex"]
        poly_mat_indices = node["poly_mat_indices"]
        n_tris = len(poly_mat_indices)
        vrts = node["vrts"]
        uv_direct = node["UV"]
        normals = node["Normals"]

        # `backface_culling` is a per-MESH NMF field (not per-material),
        # attached to this node by `main()` from the raw NMF data since
        # the shared `NmfSceneConverter` processed-node output doesn't
        # carry it - see `_build_material`'s docstring. Missing (e.g. a
        # synthetic node) defaults to 1, the overwhelming majority case.
        # Inverted from the flag's own name on purpose (confirmed with
        # the user after the data-only correlation - see module
        # docstring - pointed the other way): `backface_culling=1`
        # (~91% of meshes, closed volumes) maps to `doubleSided=True`,
        # `backface_culling=0` (~9%, thin/open geometry) to
        # `doubleSided=False`.
        double_sided = node.get("backface_culling", 1) == 1

        materials_data = node.get("materials_data") or []
        material_indices = [
            self._build_material(m, double_sided) for m in materials_data
        ] or [
            self._build_material(
                {"mat_name": f"lambert_{node['node_name']}", "r": 0.8, "g": 0.8, "b": 0.8, "a": 1.0, "has_tex": False},
                double_sided,
            )
        ]

        by_material = {}
        for tri_idx in range(n_tris):
            mat_idx_local = poly_mat_indices[tri_idx] if poly_mat_indices else 0
            by_material.setdefault(mat_idx_local, []).append(tri_idx)

        mesh_animations = node.get("mesh_animations") or []
        channel_index_sets = [set(ch["indices"]) for ch in mesh_animations]

        primitives = []
        for mat_idx_local, tri_indices in sorted(by_material.items()):
            positions = []
            uvs = []
            corner_normals = []
            corner_vidx = []
            for tri_idx in tri_indices:
                for corner in range(3):
                    raw = pvi[tri_idx * 3 + corner]
                    v_idx = NmfSceneConverter._pvi_vertex(raw)
                    corner_vidx.append(v_idx)
                    positions.extend(vrts[v_idx])
                    u = uv_direct[v_idx * 2]
                    v_flipped = uv_direct[v_idx * 2 + 1]
                    # Undo gotcha #2's FBX/OpenGL-style V-flip - glTF's
                    # own convention already matches the raw, un-flipped
                    # value (see module docstring's "UV" note).
                    uvs.extend([u, 1.0 - v_flipped])
                    n_off = (tri_idx * 3 + corner) * 3
                    n_vec = normals[n_off : n_off + 3]
                    if n_vec == [0.0, 0.0, 0.0]:
                        # Degenerate (zero-area) source triangle -
                        # `_build_fbx_normals_flat`'s cross product is
                        # zero and `_normalize` returns (0,0,0) rather
                        # than divide by zero. FBX/Blender tolerate a
                        # zero normal silently (the triangle has zero
                        # area, so it's invisible either way), but
                        # glTF's spec requires unit-length NORMAL
                        # values - same fallback convention
                        # `common/nmf_parser.py` already uses for NaN
                        # normals in the raw vbuf (a safe "up" vector).
                        n_vec = [0.0, 1.0, 0.0]
                    corner_normals.extend(n_vec)
            if not positions:
                continue
            pos_acc = self._add_float_accessor(positions, "VEC3", with_bounds=True)
            norm_acc = self._add_float_accessor(corner_normals, "VEC3")
            uv_acc = self._add_float_accessor(uvs, "VEC2")
            primitive = {
                "attributes": {
                    "POSITION": pos_acc,
                    "NORMAL": norm_acc,
                    "TEXCOORD_0": uv_acc,
                },
                "material": material_indices[mat_idx_local]
                if mat_idx_local < len(material_indices)
                else material_indices[0],
            }
            if mesh_animations:
                # Every primitive of a mesh must declare the same number
                # of morph targets, in the same order (glTF spec) - even
                # ones this particular material-primitive's vertices
                # happen not to be part of (e.g. a blend shape only
                # touching a different material's faces), hence the
                # all-zero fallback rather than skipping the target.
                n_corners = len(positions) // 3
                targets = []
                for indices_set, ch in zip(channel_index_sets, mesh_animations):
                    dx, dy, dz = ch["delta_dir"]
                    sparse_pairs = [
                        (ci, (dx, dy, dz))
                        for ci, vidx in enumerate(corner_vidx)
                        if vidx in indices_set
                    ]
                    if sparse_pairs:
                        target_acc = self._add_sparse_vec3_delta_accessor(
                            n_corners, sparse_pairs
                        )
                    else:
                        target_acc = self._add_zero_vec3_accessor(n_corners)
                    targets.append({"POSITION": target_acc})
                primitive["targets"] = targets
            primitives.append(primitive)
        return primitives

    # -- animation -----------------------------------------------------

    @staticmethod
    def _to_float32(x):
        return struct.unpack("<f", struct.pack("<f", x))[0]

    def _times_to_seconds(self, frame_times):
        """Converts frame-number keyframe times to the glTF animation
        sampler `input` this project actually needs: non-negative and
        strictly increasing.

        Non-negative: some real character rigs have a genuinely negative
        first keyframe in the raw NMF data (confirmed on
        `SisterNancy_2674` - most JOINs there start at frame -5, a "pre-
        roll" pose a few frames before 0) - perfectly valid against FBX's
        `KeyTime` (a signed int64, gotcha #27 deliberately keeps JOIN's
        raw times untouched), but glTF's spec requires `input` >= 0. Fixed
        by subtracting `self.time_offset_frames` (the minimum frame across
        every animated node in the whole scene, computed once up front)
        from every keyframe, so the whole scene's relative timing is
        preserved and everything just starts a few frames later at t=0.

        Strictly increasing: `all_times` is already deduplicated at full
        float64 precision (a plain `sorted(set(...))`), but the accessor
        itself stores float32 - two source keyframes close enough to
        collapse to the *same* float32 value once converted to seconds
        would violate that requirement despite being distinct going in.
        Returns `(kept_indices, times_seconds)` - `kept_indices` indexes
        back into `frame_times` (and whatever per-key value list the
        caller built in parallel) for the entries that survived.
        """
        kept_indices = []
        times_seconds = []
        last = None
        for i, ft in enumerate(frame_times):
            t = self._to_float32((ft - self.time_offset_frames) / FPS)
            if last is None or t > last:
                kept_indices.append(i)
                times_seconds.append(t)
                last = t
        return kept_indices, times_seconds

    def _build_rotation_channel(self, node, gltf_node_index, channels, samplers):
        """The core reason this file exists instead of just extending
        nmf_to_fbx.py further - see the module docstring's long
        explanation. Builds one authoritative quaternion per union
        keyframe time (own axis interpolated where animated, static
        value elsewhere), fixes quaternion sign continuity, and writes a
        single glTF `rotation` animation channel - no Euler
        decomposition happens on the reading end at all, so there is no
        importer branch-choice left to get wrong."""
        rot_data = (node.get("animations") or {}).get("rotation")
        if not rot_data:
            return
        axes = ("x", "y", "z")
        all_times = sorted(
            {t for ax in axes if ax in rot_data for t in rot_data[ax]["frames"]}
        )
        if len(all_times) < 2:
            return
        static_rot = _effective_rest_vec3(node, "rotation", "rotation", [0.0, 0.0, 0.0])
        orient_quat = _node_orient_quat(node)
        quats = []
        for t in all_times:
            vals = list(static_rot)
            for i, ax in enumerate(axes):
                curve = rot_data.get(ax)
                if curve:
                    vals[i] = NmfSceneConverter._interp_linear(
                        curve["frames"], curve["values"], t
                    )
            quats.append(
                _quat_mul(orient_quat, _euler_xyz_deg_to_quat(vals[0], vals[1], vals[2]))
            )
        kept_indices, times_sec = self._times_to_seconds(all_times)
        if len(kept_indices) < 2:
            return
        quats = _fix_quat_shortest_path([quats[i] for i in kept_indices])
        input_acc = self._add_float_accessor(times_sec, "SCALAR", with_bounds=True)
        output_acc = self._add_float_accessor(
            [c for q in quats for c in q], "VEC4"
        )
        sampler_idx = len(samplers)
        samplers.append(
            {"input": input_acc, "output": output_acc, "interpolation": "LINEAR"}
        )
        channels.append(
            {"sampler": sampler_idx, "target": {"node": gltf_node_index, "path": "rotation"}}
        )

    def _build_vec3_channel(self, node, gltf_node_index, track, path, static_default, channels, samplers):
        """`translation`/`scale` glTF channels - plain vec3, no Euler-
        style ambiguity to worry about, so this is just the union-time-
        merge half of `_build_rotation_channel` without the quaternion
        step."""
        data = (node.get("animations") or {}).get(track)
        if not data:
            return
        axes = ("x", "y", "z")
        all_times = sorted(
            {t for ax in axes if ax in data for t in data[ax]["frames"]}
        )
        if len(all_times) < 2:
            return
        static_vals = _effective_rest_vec3(
            node,
            track,
            "translation" if track == "translation" else "scale",
            static_default,
        )
        per_time_vals = []
        for t in all_times:
            vals = list(static_vals)
            for i, ax in enumerate(axes):
                curve = data.get(ax)
                if curve:
                    vals[i] = NmfSceneConverter._interp_linear(
                        curve["frames"], curve["values"], t
                    )
            per_time_vals.append(vals)
        kept_indices, times_sec = self._times_to_seconds(all_times)
        if len(kept_indices) < 2:
            return
        output_flat = [c for i in kept_indices for c in per_time_vals[i]]
        input_acc = self._add_float_accessor(times_sec, "SCALAR", with_bounds=True)
        output_acc = self._add_float_accessor(output_flat, "VEC3")
        sampler_idx = len(samplers)
        samplers.append(
            {"input": input_acc, "output": output_acc, "interpolation": "LINEAR"}
        )
        channels.append(
            {"sampler": sampler_idx, "target": {"node": gltf_node_index, "path": path}}
        )

    def _build_weights_channel(self, mesh_animations, gltf_node_index, channels, samplers):
        """One glTF `weights` animation channel per mesh node, driving
        every blend-shape/morph-target channel built by
        `_build_mesh_primitives` at once - glTF requires all of a node's
        target weights to be animated by a single sampler, its output a
        flat `[w0_t0, w1_t0, ..., wN_t0, w0_t1, ...]` array (spec: output
        count = input count * target count), unlike `translation`/
        `rotation`/`scale` which each get their own channel. Each
        channel's own curve is independent (union-time-merge, same
        pattern as `_build_vec3_channel`) - a channel with no key at a
        given union time just holds its own last/first value via
        `_interp_linear`'s constant extrapolation, exactly like
        `KeyAttrFlags`-driven FBX `AnimCurve`s already do on the FBX
        side."""
        if not mesh_animations:
            return
        all_times = sorted({t for ch in mesh_animations for t in ch["frames"]})
        if len(all_times) < 2:
            return
        kept_indices, times_sec = self._times_to_seconds(all_times)
        if len(kept_indices) < 2:
            return
        output_flat = []
        for i in kept_indices:
            t = all_times[i]
            for ch in mesh_animations:
                output_flat.append(
                    NmfSceneConverter._interp_linear(ch["frames"], ch["values"], t)
                )
        input_acc = self._add_float_accessor(times_sec, "SCALAR", with_bounds=True)
        output_acc = self._add_float_accessor(output_flat, "SCALAR")
        sampler_idx = len(samplers)
        samplers.append(
            {"input": input_acc, "output": output_acc, "interpolation": "LINEAR"}
        )
        channels.append(
            {"sampler": sampler_idx, "target": {"node": gltf_node_index, "path": "weights"}}
        )

    def _build_node_animation(self, node, gltf_node_index, channels, samplers):
        self._build_vec3_channel(
            node, gltf_node_index, "translation", "translation",
            [0.0, 0.0, 0.0], channels, samplers,
        )
        self._build_rotation_channel(node, gltf_node_index, channels, samplers)
        self._build_vec3_channel(
            node, gltf_node_index, "scale", "scale",
            [1.0, 1.0, 1.0], channels, samplers,
        )

    # -- entry point -----------------------------------------------------

    def assemble(self, nodes):
        # Global minimum keyframe time (frame-number units) across every
        # animated node's every track - see `_times_to_seconds` for why
        # this needs to be scene-wide (some real character rigs have
        # genuinely negative keyframes) rather than computed per-node,
        # which would desync different nodes' relative timing.
        all_frame_times = [
            t
            for n in nodes
            for tdata in (n.get("animations") or {}).values()
            for curve in tdata.values()
            for t in curve.get("frames", [])
        ] + [
            t
            for n in nodes
            for ch in (n.get("mesh_animations") or [])
            for t in ch["frames"]
        ]
        self.time_offset_frames = min(all_frame_times, default=0.0)
        if self.time_offset_frames > 0.0:
            self.time_offset_frames = 0.0

        id_to_index = {}
        gltf_nodes = []
        for n in nodes:
            idx = len(gltf_nodes)
            id_to_index[n["id"]] = idx
            entry = {"name": n["node_name"]}
            t = _effective_rest_vec3(n, "translation", "translation", [0.0, 0.0, 0.0])
            s = _effective_rest_vec3(n, "scale", "scale", [1.0, 1.0, 1.0])
            r = _effective_rest_vec3(n, "rotation", "rotation", [0.0, 0.0, 0.0])
            if any(c != 0.0 for c in t):
                entry["translation"] = [float(c) for c in t]
            if any(c != 1.0 for c in s):
                entry["scale"] = [float(c) for c in s]
            quat = _quat_mul(_node_orient_quat(n), _euler_xyz_deg_to_quat(r[0], r[1], r[2]))
            if quat != (0.0, 0.0, 0.0, 1.0):
                entry["rotation"] = list(quat)
            gltf_nodes.append(entry)

        for n in nodes:
            parent_id = n.get("parent_id")
            if parent_id and parent_id in id_to_index:
                gltf_nodes[id_to_index[parent_id]].setdefault("children", []).append(
                    id_to_index[n["id"]]
                )

        meshes = []
        anim_channels = []
        anim_samplers = []
        for n in nodes:
            gi = id_to_index[n["id"]]
            if n["node_type"] == "mesh":
                primitives = self._build_mesh_primitives(n)
                # A handful of real assets have a genuinely empty MESH node
                # (tnum=vnum=inum=0 in the raw NMF data - confirmed on
                # Elefant_1694's pCylinderShape40) - FBX tolerates an empty
                # Geometry object, but glTF's spec requires
                # mesh.primitives to be non-empty, so such a node just gets
                # no "mesh" property at all (an empty transform-only node,
                # same net visual effect).
                if primitives:
                    mesh_idx = len(meshes)
                    mesh_entry = {"name": n["node_name"], "primitives": primitives}
                    mesh_animations = n.get("mesh_animations") or []
                    if mesh_animations:
                        # Rest weight per channel is that channel's own
                        # first authored value, not a hardcoded 0.0 - the
                        # same lesson as `_effective_rest_vec3` (a single-
                        # key curve is this project's way of encoding a
                        # constant, possibly non-zero, value).
                        mesh_entry["weights"] = [
                            ch["values"][0] for ch in mesh_animations
                        ]
                        self._build_weights_channel(
                            mesh_animations, gi, anim_channels, anim_samplers
                        )
                        DEBUG and debug_output(
                            f"[meshanim] '{n['node_name']}' gltf_node={gi} "
                            f"channels={len(mesh_animations)}"
                        )
                    meshes.append(mesh_entry)
                    gltf_nodes[gi]["mesh"] = mesh_idx
            if n.get("with_animation"):
                self._build_node_animation(n, gi, anim_channels, anim_samplers)
                DEBUG and debug_output(
                    f"[anim] '{n['node_name']}' gltf_node={gi} "
                    f"tracks={list((n.get('animations') or {}).keys())}"
                )

        # Gotcha (glTF-specific, see module docstring "Coordinate systems"):
        # wrap every real root in one Y-up axis-correction node rather than
        # touching the shared Z-up Stage 1 conversion.
        real_roots = [id_to_index[n["id"]] for n in nodes if not n.get("parent_id")]
        wrapper_index = len(gltf_nodes)
        gltf_nodes.append(
            {
                "name": "Z_up_to_Y_up",
                "rotation": list(_Z_UP_TO_Y_UP_QUAT),
                "children": real_roots,
            }
        )

        gltf = {
            "asset": {"version": "2.0", "generator": "nmf_to_gltf.py"},
            "scene": 0,
            "scenes": [{"nodes": [wrapper_index]}],
            "nodes": gltf_nodes,
            "buffers": [{"byteLength": len(self.buffer)}],
            "bufferViews": self.buffer_views,
            "accessors": self.accessors,
        }
        if meshes:
            gltf["meshes"] = meshes
        if self.materials:
            gltf["materials"] = self.materials
        if self.textures:
            gltf["textures"] = self.textures
            gltf["images"] = self.images
        if anim_channels:
            gltf["animations"] = [
                {
                    "name": "Take 001",
                    "channels": anim_channels,
                    "samplers": anim_samplers,
                }
            ]
        return gltf, bytes(self.buffer)


# =============================================================================
# Stage 3: GlbWriter - (gltf json dict, binary buffer) -> .glb file.
# Plain binary packing per the glTF 2.0 GLB container spec - a 12-byte
# header, a JSON chunk, and a BIN chunk. Vastly simpler than FBX's binary
# tree format: no element offsets to precompute, no per-value type codes,
# no name/id/connection graph to keep consistent by hand.
# =============================================================================


class GlbWriter:
    _MAGIC = 0x46546C67  # "glTF"
    _VERSION = 2
    _CHUNK_TYPE_JSON = 0x4E4F534A  # "JSON"
    _CHUNK_TYPE_BIN = 0x004E4942  # "BIN\0"

    def write(self, gltf_json, binary_buffer, output_path):
        json_text = json.dumps(gltf_json, separators=(",", ":")).encode("utf-8")
        # GLB chunks must be 4-byte aligned; JSON is padded with spaces
        # (valid whitespace, keeps the JSON parseable), BIN with zeros.
        json_pad = (-len(json_text)) % 4
        json_text += b" " * json_pad

        bin_pad = (-len(binary_buffer)) % 4
        binary_buffer = binary_buffer + (b"\0" * bin_pad)

        total_length = (
            12  # header
            + 8 + len(json_text)  # JSON chunk header + data
            + (8 + len(binary_buffer) if binary_buffer else 0)
        )

        with open(output_path, "wb") as f:
            f.write(pack("<III", self._MAGIC, self._VERSION, total_length))
            f.write(pack("<II", len(json_text), self._CHUNK_TYPE_JSON))
            f.write(json_text)
            if binary_buffer:
                f.write(pack("<II", len(binary_buffer), self._CHUNK_TYPE_BIN))
                f.write(binary_buffer)


class UidGen:
    """Trivial sequential id generator - `NmfSceneConverter.convert` only
    needs *some* unique, stable per-node id source (it doesn't care what
    for). A local copy rather than importing `nmf_to_fbx.UidGen` so this
    file has no dependency on `nmf_to_fbx.py` (which requires numpy at
    import time) at all."""

    def __init__(self, start=0):
        self.v = int(start)

    def next(self):
        self.v += 1
        return self.v


def main():
    global DEBUG
    args = sys.argv[1:]
    if "--debug" in args:
        DEBUG = True
        nmf_scene_converter.DEBUG = True
        args = [a for a in args if a != "--debug"]

    if len(args) < 2:
        sys.stderr.write(f"Usage: python {sys.argv[0]} [--debug] input.nmf output.glb\n")
        return 1

    input_path = args[0]
    output_path = args[1]

    debug_output(f"Reading {input_path}...")
    uid_gen = UidGen(start=1)
    parser = Nmf()
    raw_nodes = parser.unpack(input_path)

    debug_output("Processing scene nodes...")
    input_dir = os.path.dirname(os.path.abspath(input_path))
    textures_dir = NmfSceneConverter.find_textures_dir(input_dir)
    if not textures_dir:
        textures_dir = os.path.join(input_dir, "textures")
    page_manifest = NmfSceneConverter.load_texture_page_manifest(input_dir)
    converter = NmfSceneConverter(uid_gen, textures_dir, page_manifest)
    scene_nodes = converter.convert(raw_nodes)

    # `NmfSceneConverter.convert` mutates each raw node in place, adding
    # an `"id"` that a MESH node's own processed dict reuses verbatim
    # (see that method's docstring) - so raw and processed MESH nodes can
    # be matched up by `id` after the fact, letting `backface_culling`
    # (see `GltfSceneAssembler._build_mesh_primitives`) reach the glTF
    # side without adding a glTF-specific field to the shared, FBX-path-
    # used `NmfSceneConverter` output.
    raw_backface_culling = {
        n["id"]: n["payload"].get("backface_culling", 1)
        for n in raw_nodes
        if n["type"] == "MESH" and "id" in n
    }
    for sn in scene_nodes:
        if sn.get("node_type") == "mesh":
            sn["backface_culling"] = raw_backface_culling.get(sn["id"], 1)

    debug_output("Building glTF structure...")
    assembler = GltfSceneAssembler()
    gltf_json, binary_buffer = assembler.assemble(scene_nodes)

    GlbWriter().write(gltf_json, binary_buffer, output_path)

    debug_output("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
