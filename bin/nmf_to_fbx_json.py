#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) NMF to FBX JSON Converter

Description:
    This tool converts extracted NMF models into an intermediate JSON format
    representing the FBX structure. This JSON can be useful for debugging
    the FBX hierarchy or can be further processed into a binary FBX file
    using external tools (e.g., Blender scripts).

Features:
    - Parses NMF data and reconstructs the scene graph.
    - Generates FBX-compliant JSON structure (Objects, Connections, Definitions).
    - Handles geometry, materials, and animations.
    - Useful for inspecting the data structure before binary encoding.

License: MIT License

Usage:
    python nmf_to_fbx_json.py <input.nmf> <output_fbx.json>
"""

# Convert to JSON. The file can be packed into binary FBX using Blender scripts
# This file is well-suited for debugging

import json
import sys
import time
import random
import math
import os

from common import Nmf

# -----------------------------------------------------------------------------
# CONSTANTS & CONFIG
# -----------------------------------------------------------------------------
FPS = 24.0
RAD2DEG = 180.0 / math.pi
KTIME_SEC = 46186158000
KTIME_PER_FRAME = int(KTIME_SEC / FPS)


# -----------------------------------------------------------------------------
# MATH & VECTOR UTILS
# -----------------------------------------------------------------------------
def normalize(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if l == 0.0:
        return (0.0, 0.0, 0.0)
    return (v[0] / l, v[1] / l, v[2] / l)


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return (a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2])


def _len3(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def extract_3x3(m4):
    if not m4:
        return None
    a = [c for row in m4 for c in row]  # flatten
    return [[a[0], a[1], a[2]], [a[4], a[5], a[6]], [a[8], a[9], a[10]]]


def matrix_rowmajor_to_euler_xyz_standard(m):
    """
    Extract Euler XYZ from 3x3 matrix (for Joint Orient calculation).
    MATCHING MAYA CONVERTER LOGIC (TRANSPOSED).
    """
    if m is None:
        return [0.0, 0.0, 0.0]

    # Read as Row-Major
    m00, m01, m02 = m[0]
    m10, m11, m12 = m[1]
    m20, m21, m22 = m[2]

    # TRANSPOSE (as in the working Maya script)
    # This turns rows into columns before angle calculation
    r00, r01, r02 = m00, m10, m20
    r10, r11, r12 = m01, m11, m21
    r20, r21, r22 = m02, m12, m22

    # Calculate angles based on transposed data (rXX)
    if abs(r20) < 0.999999:
        y = math.asin(-r20)
        x = math.atan2(r21, r22)
        z = math.atan2(r10, r00)
    else:
        y = math.asin(-r20)
        x = math.atan2(-r12, r11)
        z = 0.0

    return [x * RAD2DEG, y * RAD2DEG, z * RAD2DEG]


def _dx_to_blender_matrix(dx_m):
    """
    DirectX (Row-Major) to Blender/OpenGL (Column-Major conceptually or just Transposed).
    This effectively transposes the matrix.
    """
    return [[dx_m[j][i] for j in range(4)] for i in range(4)]


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


def decompose_directx_row_major(m_raw):
    m = _dx_to_blender_matrix(m_raw)
    """
    Decomposes a 4x4 matrix (Row-Major) into Translation, Scale, and Rotation (XYZ Euler).
    Added check for negative determinant (Scale Mirroring).
    """
    # 1. Translation (usually the last row in Row-Major)
    tx, ty, tz = m[0][3], m[1][3], m[2][3]

    # 2. Extract Rows (Basis vectors: X, Y, Z axes)
    r0 = [m[0][0], m[1][0], m[2][0]]  # Axis X
    r1 = [m[0][1], m[1][1], m[2][1]]  # Axis Y
    r2 = [m[0][2], m[1][2], m[2][2]]  # Axis Z

    # 3. Calculate Scale (magnitude of axes)
    # _len3 - assuming this is your vector length function
    # (if missing, replace with math.sqrt(x*x + y*y + z*z))
    sx = _len3(r0)
    sy = _len3(r1)
    sz = _len3(r2)

    # 4. Determinant Check (Mirroring logic)
    # Calculate triple product: (r0 x r1) . r2
    det = (
        r0[0] * (r1[1] * r2[2] - r1[2] * r2[1])
        - r0[1] * (r1[0] * r2[2] - r1[2] * r2[0])
        + r0[2] * (r1[0] * r2[1] - r1[1] * r2[0])
    )

    if det < 0:
        # If determinant is negative, invert Z scale (as in your example)
        sz = -sz

    # Protection against division by zero
    sx = sx if sx != 0 else 1.0
    sy = sy if sy != 0 else 1.0
    sz = sz if sz != 0 else 1.0

    # 5. Normalize Rows to get pure Rotation Matrix components
    # WARNING: If sz was inverted above, division here
    # automatically inverts vector r2, removing mirroring from rotation.
    r00, r10, r20 = r0[0] / sx, r0[1] / sx, r0[2] / sx
    r01, r11, r21 = r1[0] / sy, r1[1] / sy, r1[2] / sy
    r02, r12, r22 = r2[0] / sz, r2[1] / sz, r2[2] / sz

    # 6. Extract Euler Angles (XYZ order logic)
    # m[2][0] (row 2, col 0) corresponds to -sin(y) in standard rotation matrices,
    # but check your specific matrix convention. Assuming standard here based on input code.
    ry = math.asin(-r20) if abs(r20) <= 1.0 else math.asin(-1.0 if r20 > 0 else 1.0)

    if abs(math.cos(ry)) > 1e-6:
        ry = math.asin(-r20)
        rx = math.atan2(r21, r22)
        rz = math.atan2(r10, r00)
    else:
        # Gimbal lock case
        ry = math.asin(-1.0 if r20 > 0 else 1.0)
        rx = math.atan2(-r12, r11)
        rz = 0.0

    return ((tx, ty, tz), (sx, sy, sz), (rx, ry, rz))


def is_mesh_right_handed(ibuf, vbuf):
    pos = [[r[0], r[1], r[2]] for r in vbuf]
    nrm = [[r[3], r[4], r[5]] for r in vbuf] if len(vbuf[0]) > 5 else []
    if not nrm:
        return True

    pos_cnt = 0
    neg_cnt = 0
    for i0, i1, i2 in ibuf:
        p0, p1, p2 = pos[i0], pos[i1], pos[i2]
        n_geom = normalize(cross(sub(p1, p0), sub(p2, p0)))
        n_avg = normalize(
            [
                nrm[i0][0] + nrm[i1][0] + nrm[i2][0],
                nrm[i0][1] + nrm[i1][1] + nrm[i2][1],
                nrm[i0][2] + nrm[i1][2] + nrm[i2][2],
            ]
        )
        s = dot(n_geom, n_avg)
        if s >= 0:
            pos_cnt += 1
        else:
            neg_cnt += 1
    return pos_cnt >= neg_cnt


# -----------------------------------------------------------------------------
# GEOMETRY PROCESSING HELPERS
# -----------------------------------------------------------------------------
def make_polygon_vertex_index_from_tris(ibuf):
    out = []
    for a, b, c in ibuf:
        out.append(a)
        out.append(b)
        out.append(-(c + 1))
    return out


def _pvi_vertex(pvi_val: int) -> int:
    return -pvi_val - 1 if pvi_val < 0 else pvi_val


def build_fbx_edges_from_pvi(pvi):
    edges_positions = []
    seen = set()
    poly_start = 0
    i = 0
    n = len(pvi)
    while i < n:
        if pvi[i] < 0:
            poly_end = i
            for j in range(poly_start, poly_end + 1):
                v_a = _pvi_vertex(pvi[j])
                v_b = (
                    _pvi_vertex(pvi[j + 1])
                    if j < poly_end
                    else _pvi_vertex(pvi[poly_start])
                )
                key = (v_a, v_b) if v_a < v_b else (v_b, v_a)
                if key not in seen:
                    seen.add(key)
                    edges_positions.append(j)
            poly_start = i + 1
        i += 1
    return edges_positions


def build_fbx_normals_flat(verts, ibuf):
    normals = []
    normals_w = []
    for a, b, c in ibuf:
        v0 = verts[a]
        v1 = verts[b]
        v2 = verts[c]
        e1 = sub(v1, v0)
        e2 = sub(v2, v0)
        n = normalize(cross(e1, e2))
        for _ in range(3):
            normals.extend(n)
            normals_w.append(1.0)
    return normals, normals_w


def build_fbx_uv_layer(vbuf, ibuf):
    uv_src = []
    for t in vbuf:
        u = float(t[6]) if len(t) > 6 else 0.0
        v = float(t[7]) if len(t) > 7 else 0.0
        uv_src.append([u, v])
    uv_direct = []
    for u, v in uv_src:
        uv_direct.append(u)
        uv_direct.append(v)
    uv_index = []
    for a, b, c in ibuf:
        uv_index.extend([int(a), int(b), int(c)])
    return uv_direct, uv_index


def animation_build_tracks_by_axis(raw_values):
    axes = ("x", "y", "z")
    result = {}
    for track in ("translation", "rotation", "scaling"):
        anim = raw_values.get(track)
        if not anim:
            continue
        keys = anim.get("keys")
        values = anim.get("values")
        if not keys or not values:
            continue
        track_hash = {}
        for ax in axes:
            tlist = keys.get(ax)
            vlist = values.get(ax)
            if not tlist or not vlist:
                continue
            frames = [float(t) * FPS for t in tlist]
            vals = [float(v) for v in vlist]
            if track == "rotation":
                vals = [v * RAD2DEG for v in vals]
            track_hash[ax] = {"frames": frames, "values": vals}
        if track_hash:
            result[track] = track_hash
    return result


# -----------------------------------------------------------------------------
# ID GENERATOR
# -----------------------------------------------------------------------------
class UidGen:
    def __init__(self, start=10_000_000_000):
        self.v = int(start)

    def next(self):
        self.v += 1
        return self.v


# -----------------------------------------------------------------------------
# NODE PROCESSING
# -----------------------------------------------------------------------------
def process_scene_nodes(nodes, uid_gen):
    result = []
    index_map = {n["index"]: n for n in nodes}

    # Assign IDs first
    for node in nodes:
        node["id"] = uid_gen.next()

    for node in nodes:
        unpacked = node["data"]
        w = node["word"]

        # Parent resolution
        parent = index_map.get(node.get("parent_id"))
        parent_id = parent["id"] if parent else 0

        processed = None

        # --- FRAM & ROOT ---
        if w == "ROOT" or w == "FRAM":
            processed = {
                "node_type": "fram",
                "node_name": node["name"],
                "mesh": False,
                "rotate_pivot_translate": unpacked.get(
                    "rotate_pivot_translate", [0, 0, 0]
                ),
                "rotate_pivot": unpacked.get("rotate_pivot", [0, 0, 0]),
                "scale_pivot_translate": unpacked.get(
                    "scale_pivot_translate", [0, 0, 0]
                ),
                "scale_pivot": unpacked.get("scale_pivot", [0, 0, 0]),
            }
            if w == "ROOT":
                base_matrix = unpacked["matrix"]
                S = [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
                M2 = _mat_mul(S, base_matrix)
                t, s, r = decompose_directx_row_major(M2)
                processed["translation"] = [x * 1 for x in t]
                # processed["translation"][2] = processed["translation"][2] * -1
                processed["scaling"] = [x * 1 for x in s]
                processed["rotation"] = [x * RAD2DEG for x in r]
            else:

                if (
                    processed["rotate_pivot_translate"] == [0, 0, 0]
                    and processed["rotate_pivot"] == [0, 0, 0]
                    and processed["scale_pivot_translate"] == [0, 0, 0]
                    and processed["scale_pivot"] == [0, 0, 0]
                ):
                    t, s, r = decompose_directx_row_major(unpacked["matrix"])
                    processed["translation"] = t
                    processed["scaling"] = s
                    processed["rotation"] = [x * RAD2DEG for x in r]
                else:
                    processed["translation"] = unpacked["translation"]
                    processed["scaling"] = unpacked["scaling"]
                    processed["rotation"] = [x * RAD2DEG for x in unpacked["rotation"]]

            processed["animations"] = animation_build_tracks_by_axis(
                unpacked.get("anim", {})
            )

        # --- JOINT ---
        elif w == "JOIN":
            processed = {
                "node_type": "joint",
                "node_name": node["name"],
                "mesh": False,
                "translation": unpacked["translation"],
                "scaling": unpacked["scaling"],
                "rotation": [r * RAD2DEG for r in unpacked["rotation"]],
            }
            # Extract Joint Orient (Pre-rotation in FBX)
            # unpacked["rotation_matrix"] is usually 4x4 or 3x3 depending on parser
            # Assume it's the raw matrix from which we extract orient
            m3 = extract_3x3(unpacked.get("rotation_matrix"))
            processed["joint_orient"] = matrix_rowmajor_to_euler_xyz_standard(m3)

            processed["animations"] = animation_build_tracks_by_axis(
                unpacked.get("anim", {})
            )

        # --- LOCATOR ---
        elif w == "LOCA":
            processed = {
                "node_type": "locator",
                "node_name": node["name"],
                "mesh": False,
                # Locators might not have explicit TRS in some formats, defaults to identity
                "translation": unpacked.get("translation", [0.0, 0.0, 0.0]),
                "scaling": unpacked.get("scaling", [1.0, 1.0, 1.0]),
                "rotation": [
                    r * RAD2DEG for r in unpacked.get("rotation", [0.0, 0.0, 0.0])
                ],
                "animations": animation_build_tracks_by_axis(unpacked.get("anim", {})),
            }

        # --- MESH ---
        elif w == "MESH":
            processed = {
                "node_type": "mesh",
                "node_name": node["name"],
            }
            raw_vbuf = unpacked["vbuf"]
            # Check winding order (as you had it)
            raw_ibuf = [[t[0], t[1], t[2]] for t in unpacked["ibuf"]]
            if not is_mesh_right_handed(raw_ibuf, raw_vbuf):
                raw_ibuf = [[t[0], t[2], t[1]] for t in raw_ibuf]

            processed["vrts"] = [[t[0], t[1], t[2]] for t in raw_vbuf]
            processed["PolygonVertexIndex"] = make_polygon_vertex_index_from_tris(
                raw_ibuf
            )
            processed["Edges"] = build_fbx_edges_from_pvi(
                processed["PolygonVertexIndex"]
            )

            uv_direct, uv_index = build_fbx_uv_layer(raw_vbuf, raw_ibuf)
            processed["UV"] = uv_direct
            processed["UVIndex"] = uv_index

            normals, normals_w = build_fbx_normals_flat(processed["vrts"], raw_ibuf)
            processed["Normals"] = normals
            processed["NormalsW"] = normals_w

            # --- MATERIALS & TEXTURES (Logic ported from Maya script) ---
            materials_in = unpacked.get("materials", []) or []
            materials_out = []

            # If no materials, create default (as in Maya script)
            if not materials_in:
                mat_name = f"lambert_{processed['node_name']}"
                materials_out.append(
                    {
                        "mat_name": mat_name,
                        "r": 0.8,
                        "g": 0.8,
                        "b": 0.8,
                        "a": 1.0,  # Alpha 1.0 = Opaque
                        "has_tex": False,
                    }
                )
            else:
                for m in materials_in:
                    mat_name = (
                        m.get("name") or "lambert"
                    ) + f"_{processed['node_name']}"
                    # In NMF alpha is usually transparency (0 - transparent?), in FBX TransparencyFactor (0 - opaque, 1 - transparent)
                    # But usually diffuse alpha is opacity. We will treat 'a' as Opacity (1 = visible).
                    a = float(m.get("alpha", 1.0))

                    tex_data = m.get("texture")
                    tex_path = (
                        tex_data.get("name") if isinstance(tex_data, dict) else None
                    )

                    if tex_path:
                        # 1. Normalize slashes (just in case)
                        tex_path = tex_path.replace("\\", "/")

                        # 2. Get only the filename (discard old path)
                        filename = os.path.basename(tex_path)

                        # 3. Separate name from old extension
                        name_without_ext = (
                            os.path.splitext(filename)[0]
                            + "_"
                            + str(tex_data.get("texture_page", 0))
                        )

                        # 4. Form a new hardcoded path with .dds extension
                        # Final look: /home/user/textures/filename.dds
                        tex_path = f"{name_without_ext}.dds"

                    materials_out.append(
                        {
                            "mat_name": mat_name,
                            "r": float(m.get("red", 0.8)),
                            "g": float(m.get("green", 0.8)),
                            "b": float(m.get("blue", 0.8)),
                            "opacity": a,
                            "has_tex": bool(tex_path),
                            "tex_path": tex_path,
                            # Tiling parameters
                            "repeatU": float(m.get("horizontal_stretch", 1.0)),
                            "repeatV": float(m.get("vertical_stretch", 1.0)),
                            "offsetU": 0.0,  # Can be improved if NMF has offset
                            "offsetV": 0.0,
                            "rotateUV": float(m.get("rotate", 0.0)),
                        }
                    )

            processed["materials_data"] = materials_out

        if processed:
            processed["id"] = node["id"]
            processed["parent_id"] = parent_id
            processed["with_animation"] = bool(processed.get("animations"))
            result.append(processed)

    # Post-process: Mark FRAMs as meshes if they have MESH children
    id_to_node = {n["id"]: n for n in result}
    for node in result:
        if node["node_type"] == "mesh":
            pid = node["parent_id"]
            if pid in id_to_node:
                parent_node = id_to_node[pid]
                if parent_node["node_type"] == "fram":
                    parent_node["mesh"] = True

    return result


# -----------------------------------------------------------------------------
# FBX WRITER LOGIC
# -----------------------------------------------------------------------------
def generate_fbx_header_json():
    t = time.localtime()
    ms = int(time.time() * 1000) % 1000
    return [
        [
            "FBXHeaderExtension",
            [],
            "",
            [
                ["FBXHeaderVersion", [1003], "I", []],
                ["FBXVersion", [7500], "I", []],
                ["EncryptionType", [0], "I", []],
                [
                    "CreationTimeStamp",
                    [],
                    "",
                    [
                        ["Version", [1000], "I", []],
                        ["Year", [t.tm_year], "I", []],
                        ["Month", [t.tm_mon], "I", []],
                        ["Day", [t.tm_mday], "I", []],
                        ["Hour", [t.tm_hour], "I", []],
                        ["Minute", [t.tm_min], "I", []],
                        ["Second", [t.tm_sec], "I", []],
                        ["Millisecond", [ms], "I", []],
                    ],
                ],
                ["Creator", ["FBX SDK/FBX Plugins version 2020.3.6"], "S", []],
                [
                    "SceneInfo",
                    ["GlobalInfo::SceneInfo", "UserData"],
                    "SS",
                    [
                        ["Type", ["UserData"], "S", []],
                        ["Version", [100], "I", []],
                        [
                            "MetaData",
                            [],
                            "",
                            [
                                ["Version", [100], "I", []],
                                ["Title", [""], "S", []],
                                ["Subject", [""], "S", []],
                                ["Author", [""], "S", []],
                                ["Keywords", [""], "S", []],
                                ["Revision", [""], "S", []],
                                ["Comment", [""], "S", []],
                            ],
                        ],
                        [
                            "Properties70",
                            [],
                            "",
                            [
                                [
                                    "P",
                                    [
                                        "DocumentUrl",
                                        "KString",
                                        "Url",
                                        "",
                                        "D:\\export.fbx",
                                    ],
                                    "SSSSS",
                                    [],
                                ],
                                [
                                    "P",
                                    [
                                        "SrcDocumentUrl",
                                        "KString",
                                        "Url",
                                        "",
                                        "D:\\export.fbx",
                                    ],
                                    "SSSSS",
                                    [],
                                ],
                                [
                                    "P",
                                    [
                                        "Original|ApplicationVendor",
                                        "KString",
                                        "",
                                        "",
                                        "Autodesk",
                                    ],
                                    "SSSSS",
                                    [],
                                ],
                                [
                                    "P",
                                    [
                                        "Original|ApplicationName",
                                        "KString",
                                        "",
                                        "",
                                        "Maya",
                                    ],
                                    "SSSSS",
                                    [],
                                ],
                                [
                                    "P",
                                    [
                                        "Original|ApplicationVersion",
                                        "KString",
                                        "",
                                        "",
                                        "2025",
                                    ],
                                    "SSSSS",
                                    [],
                                ],
                            ],
                        ],
                    ],
                ],
            ],
        ],
        [
            "FileId",
            [",\\xb0(\\xea\\xb7%\\xcd\\xc0\\xbd\\xc8\\xb3 \\xa6!\\xf6\\xff"],
            "R",
            [],
        ],
        [
            "CreationTime",
            [
                f"{t.tm_year}-{t.tm_mon:02}-{t.tm_mday:02} {t.tm_hour:02}:{t.tm_min:02}:{t.tm_sec:02}:{ms:03}"
            ],
            "S",
            [],
        ],
        ["Creator", ["FBX SDK/FBX Plugins version 2020.3.6 build=0"], "S", []],
        [
            "GlobalSettings",
            [],
            "",
            [
                ["Version", [1000], "I", []],
                [
                    "Properties70",
                    [],
                    "",
                    [
                        ["P", ["UpAxis", "int", "Integer", "", 2], "SSSSI", []],
                        ["P", ["UpAxisSign", "int", "Integer", "", 1], "SSSSI", []],
                        ["P", ["FrontAxis", "int", "Integer", "", 1], "SSSSI", []],
                        ["P", ["FrontAxisSign", "int", "Integer", "", -1], "SSSSI", []],
                        ["P", ["CoordAxis", "int", "Integer", "", 0], "SSSSI", []],
                        ["P", ["CoordAxisSign", "int", "Integer", "", 1], "SSSSI", []],
                        [
                            "P",
                            ["UnitScaleFactor", "double", "Number", "", 1.0],
                            "SSSSD",
                            [],
                        ],
                        [
                            "P",
                            ["OriginalUnitScaleFactor", "double", "Number", "", 1.0],
                            "SSSSD",
                            [],
                        ],
                        ["P", ["TimeMode", "enum", "", "", 11], "SSSSI", []],
                        ["P", ["TimeProtocol", "enum", "", "", 2], "SSSSI", []],
                        ["P", ["SnapOnFrameMode", "enum", "", "", 0], "SSSSI", []],
                    ],
                ],
            ],
        ],
        [
            "Documents",
            [],
            "",
            [
                ["Count", [1], "I", []],
                [
                    "Document",
                    [1780765614704, "", "Scene"],
                    "LSS",
                    [
                        [
                            "Properties70",
                            [],
                            "",
                            [
                                ["P", ["SourceObject", "object", "", ""], "SSSS", []],
                                [
                                    "P",
                                    [
                                        "ActiveAnimStackName",
                                        "KString",
                                        "",
                                        "",
                                        "Take 001",
                                    ],
                                    "SSSSS",
                                    [],
                                ],
                            ],
                        ],
                        ["RootNode", [0], "L", []],
                    ],
                ],
            ],
        ],
        ["References", [], "", []],
    ]


def generate_fbx_definitions(nodes):
    # 'Model' includes fram, joint, locator
    model_count = sum(
        1 for n in nodes if n["node_type"] in ["fram", "joint", "locator"]
    )
    mesh_count = sum(1 for n in nodes if n["node_type"] == "mesh")

    return [
        [
            "Definitions",
            [],
            "",
            [
                ["Version", [100], "I", []],
                ["Count", [model_count + mesh_count + 1], "I", []],
                ["ObjectType", ["GlobalSettings"], "S", [["Count", [1], "I", []]]],
                [
                    "ObjectType",
                    ["Model"],
                    "S",
                    [
                        ["Count", [model_count], "I", []],
                        [
                            "PropertyTemplate",
                            ["FbxNode"],
                            "S",
                            [["Properties70", [], "", []]],
                        ],
                    ],
                ],
                [
                    "ObjectType",
                    ["Geometry"],
                    "S",
                    [
                        ["Count", [mesh_count], "I", []],
                        [
                            "PropertyTemplate",
                            ["FbxMesh"],
                            "S",
                            [["Properties70", [], "", []]],
                        ],
                    ],
                ],
                [
                    "ObjectType",
                    ["AnimationStack"],
                    "S",
                    [
                        ["Count", [1], "I", []],
                        ["PropertyTemplate", ["FbxAnimStack"], "S", []],
                    ],
                ],
                [
                    "ObjectType",
                    ["AnimationLayer"],
                    "S",
                    [
                        ["Count", [1], "I", []],
                        ["PropertyTemplate", ["FbxAnimLayer"], "S", []],
                    ],
                ],
                ["ObjectType", ["AnimationCurve"], "S", [["Count", [0], "I", []]]],
                [
                    "ObjectType",
                    ["AnimationCurveNode"],
                    "S",
                    [
                        ["Count", [0], "I", []],
                        ["PropertyTemplate", ["FbxAnimCurveNode"], "S", []],
                    ],
                ],
            ],
        ],
    ]


def vector3d_prop(name, values):
    # Force convert to float
    return [
        "P",
        [
            name,
            "Vector3D",
            "Vector",
            "",
            float(values[0]),
            float(values[1]),
            float(values[2]),
        ],
        "SSSSDDD",
        [],
    ]


def model_values_prop(name, values):
    # Force convert to float
    return [
        "P",
        [name, name, "", "A+", float(values[0]), float(values[1]), float(values[2])],
        "SSSSDDD",
        [],
    ]


def generate_rnd_id():
    return int(time.time() * 10000) + random.randint(0, 100000)


def create_fbx_animation_data(node, model_id, layer_id):
    fbx_objects = []
    fbx_connections = []

    spec_map = {
        "translation": {
            "prop": "Lcl Translation",
            "prefix": "T",
            "def": [0.0, 0.0, 0.0],
        },
        "rotation": {"prop": "Lcl Rotation", "prefix": "R", "def": [0.0, 0.0, 0.0]},
        "scaling": {"prop": "Lcl Scaling", "prefix": "S", "def": [1.0, 1.0, 1.0]},
    }
    axes = ["x", "y", "z"]
    axis_labels = ["d|X", "d|Y", "d|Z"]

    for track, spec in spec_map.items():
        tdata = node.get("animations", {}).get(track)
        if not tdata:
            continue

        has_keys = False
        for ax in axes:
            if tdata.get(ax) and tdata[ax].get("frames"):
                has_keys = True
                break
        if not has_keys:
            continue

        curve_node_id = generate_rnd_id()
        curve_node_name = f"{spec['prefix']}::AnimCurveNode"

        props_list = []
        for i in range(3):
            props_list.append(
                ["P", [axis_labels[i], "Number", "", "A", spec["def"][i]], "SSSSD", []]
            )

        fbx_objects.append(
            [
                "AnimationCurveNode",
                [curve_node_id, curve_node_name, ""],
                "LSS",
                [["Properties70", [], "", props_list]],
            ]
        )

        fbx_connections.append(
            ["C", ["OP", curve_node_id, model_id, spec["prop"]], "SLLS", []]
        )
        fbx_connections.append(["C", ["OO", curve_node_id, layer_id], "SLL", []])

        for i, ax in enumerate(axes):
            ax_data = tdata.get(ax)
            if not ax_data:
                continue

            frames = ax_data.get("frames")
            values = ax_data.get("values")
            if not frames:
                continue

            curve_id = generate_rnd_id()
            n_keys = len(frames)

            times = [int(f * KTIME_PER_FRAME) for f in frames]
            vals = [float(v) for v in values]
            flags = [8456] * n_keys
            refs = [1] * n_keys

            fbx_objects.append(
                [
                    "AnimationCurve",
                    [curve_id, "::AnimCurve", ""],
                    "LSS",
                    [
                        ["Default", [0.0], "D", []],
                        ["KeyVer", [4009], "I", []],
                        ["KeyTime", [times], "l", []],
                        ["KeyValueFloat", [vals], "f", []],
                        ["KeyAttrFlags", [flags], "i", []],
                        ["KeyAttrRefCount", [refs], "i", []],
                    ],
                ]
            )
            fbx_connections.append(
                ["C", ["OP", curve_id, curve_node_id, axis_labels[i]], "SLLS", []]
            )

    return fbx_objects, fbx_connections


def assemble_fbx(nodes, uid_gen):
    # Dynamic generation of IDs
    animation_layer_id = uid_gen.next()
    anim_stack_id = uid_gen.next()

    animation_layer = [
        "AnimationLayer",
        [animation_layer_id, "BaseLayer::AnimLayer", ""],
        "LSS",
        [],
    ]

    objects = []
    connections = []

    for node in nodes:
        nt = node["node_type"]

        # --- MODELS ---
        if nt in ["fram", "joint", "locator", "mesh"]:

            props70 = []
            # Use float() for default values
            t_def = node.get("translation", [0.0, 0.0, 0.0])
            r_def = node.get("rotation", [0.0, 0.0, 0.0])
            s_def = node.get("scaling", [1.0, 1.0, 1.0])

            props70.append(model_values_prop("Lcl Translation", t_def))
            props70.append(model_values_prop("Lcl Rotation", r_def))
            props70.append(model_values_prop("Lcl Scaling", s_def))

            model_type = "Null"
            if nt == "fram":
                model_type = "Mesh" if node.get("mesh") else "Null"
                if node.get("rotate_pivot_translate"):
                    props70.append(
                        vector3d_prop("RotationOffset", node["rotate_pivot_translate"])
                    )
                if node.get("rotate_pivot"):
                    props70.append(vector3d_prop("RotationPivot", node["rotate_pivot"]))
                if node.get("scale_pivot_translate"):
                    props70.append(
                        vector3d_prop("ScalingOffset", node["scale_pivot_translate"])
                    )
                if node.get("scale_pivot"):
                    props70.append(vector3d_prop("ScalingPivot", node["scale_pivot"]))
                props70.append(
                    ["P", ["RotationActive", "bool", "", "", 1], "SSSSI", []]
                )
                props70.append(["P", ["InheritType", "enum", "", "", 1], "SSSSI", []])

            elif nt == "joint":
                model_type = "LimbNode"
                if node.get("joint_orient"):
                    props70.append(vector3d_prop("PreRotation", node["joint_orient"]))
                props70.append(
                    ["P", ["RotationActive", "bool", "", "", 1], "SSSSI", []]
                )
                props70.append(["P", ["InheritType", "enum", "", "", 1], "SSSSI", []])

            elif nt == "mesh":
                model_type = "Mesh"

            model_name = f'{node["node_name"]}::Model'
            model_id = node["id"]

            fram_obj = [
                "Model",
                [model_id, model_name, model_type],
                "LSS",
                [
                    ["Version", [232], "I", []],
                    ["Properties70", [], "", props70],
                    ["Shading", ["Y"], "C", []],
                    ["Culling", ["CullingOff"], "S", []],
                ],
            ]
            objects.append(fram_obj)

            # Parent connection
            if node.get("parent_id"):
                connections.append(
                    ["C", ["OO", model_id, node["parent_id"]], "SLL", []]
                )
            else:
                connections.append(["C", ["OO", model_id, 0], "SLL", []])

            # --- GEOMETRY & MATERIALS (Only for Mesh) ---
            if nt == "mesh":
                geom_id = uid_gen.next()

                # 1. Create Materials & Textures
                mat_data_list = node.get("materials_data", [])

                # Material Layer Element (default)
                mapping_mode = "AllSame"
                ref_mode = "IndexToDirect"

                # If no materials or 1, use index 0
                mat_indices = [0]

                # IMPORTANT: If materials > 1, FBX requires ByPolygon and an array of indices.
                # Keeping logic simplified for now (take first material for the whole mesh),
                # to avoid complicating code if you don't have multi-materials on one mesh.

                for m_idx, mat_data in enumerate(mat_data_list):
                    mat_id = uid_gen.next()

                    transparency_factor = 1.0 - float(mat_data["opacity"])

                    mat_props = [
                        [
                            "P",
                            ["ShadingModel", "KString", "", "", "Lambert"],
                            "SSSSS",
                            [],
                        ],
                        ["P", ["MultiLayer", "bool", "", "", 0], "SSSSI", []],
                        [
                            "P",
                            ["EmissiveColor", "Color", "", "A", 0.0, 0.0, 0.0],
                            "SSSSDDD",
                            [],
                        ],
                        [
                            "P",
                            ["AmbientColor", "Color", "", "A", 0.0, 0.0, 0.0],
                            "SSSSDDD",
                            [],
                        ],
                        [
                            "P",
                            [
                                "DiffuseColor",
                                "Color",
                                "",
                                "A",
                                float(mat_data["r"]),
                                float(mat_data["g"]),
                                float(mat_data["b"]),
                            ],
                            "SSSSDDD",
                            [],
                        ],
                        [
                            "P",
                            [
                                "TransparencyFactor",
                                "Number",
                                "",
                                "A",
                                float(transparency_factor),
                            ],
                            "SSSSD",
                            [],
                        ],
                        [
                            "P",
                            [
                                "Opacity",
                                "double",
                                "Number",
                                "",
                                float(mat_data["opacity"]),
                            ],
                            "SSSSD",
                            [],
                        ],
                    ]

                    mat_obj = [
                        "Material",
                        [mat_id, f"{mat_data['mat_name']}::Material", ""],
                        "LSS",
                        [
                            ["Version", [102], "I", []],
                            ["ShadingModel", ["lambert"], "S", []],
                            ["MultiLayer", [0], "I", []],
                            ["Properties70", [], "", mat_props],
                        ],
                    ]
                    objects.append(mat_obj)
                    connections.append(["C", ["OO", mat_id, model_id], "SLL", []])

                    if mat_data["has_tex"]:
                        tex_id = uid_gen.next()
                        vid_id = uid_gen.next()
                        file_path = mat_data["tex_path"]
                        # Slash normalization
                        file_path = file_path.replace("\\", "/")

                        # Filename for use in node name
                        filename_raw = os.path.basename(file_path)

                        # --- VIDEO OBJECT ---
                        # Format: "Name::Video" (Class must be Video)
                        # This can be kept if Blender accepts it, but better:
                        # Correct for FBX SDK: f"{filename_raw}::Video"
                        # But Blender often looks at ClassName on the right.

                        # LET'S DO STRICTLY BY STANDARD: "Name::Class"

                        vid_obj_name = f"{filename_raw}::Video"
                        tex_obj_name = f"{filename_raw}::Texture"

                        vid_obj = [
                            "Video",
                            [vid_id, vid_obj_name, "Clip"],
                            "LSS",
                            [
                                ["Type", ["Clip"], "S", []],
                                [
                                    "Properties70",
                                    [],
                                    "",
                                    [
                                        [
                                            "P",
                                            [
                                                "Path",
                                                "KString",
                                                "XRefUrl",
                                                "",
                                                file_path,
                                            ],
                                            "SSSSS",
                                            [],
                                        ]
                                    ],
                                ],
                                ["UseMipMap", [0], "I", []],
                                ["Filename", [file_path], "S", []],
                                ["RelativeFilename", [filename_raw], "S", []],
                            ],
                        ]
                        objects.append(vid_obj)

                        # --- TEXTURE OBJECT ---
                        # Fixed: texture name is now on the left, ::Texture on the right
                        tex_props = [
                            [
                                "P",
                                ["CurrentTextureBlendMode", "enum", "", "", 0],
                                "SSSSI",
                                [],
                            ],
                            ["P", ["UVSet", "KString", "", "", "map1"], "SSSSS", []],
                            ["P", ["UseMaterial", "bool", "", "", 1], "SSSSI", []],
                            [
                                "P",
                                ["Translation", "Vector", "", "A", 0.0, 0.0, 0.0],
                                "SSSSDDD",
                                [],
                            ],
                            [
                                "P",
                                [
                                    "Rotation",
                                    "Vector",
                                    "",
                                    "A",
                                    0.0,
                                    0.0,
                                    float(mat_data["rotateUV"]),
                                ],
                                "SSSSDDD",
                                [],
                            ],
                            [
                                "P",
                                [
                                    "Scaling",
                                    "Vector",
                                    "",
                                    "A",
                                    float(mat_data["repeatU"]),
                                    float(mat_data["repeatV"]),
                                    1.0,
                                ],
                                "SSSSDDD",
                                [],
                            ],
                        ]

                        tex_obj = [
                            "Texture",
                            [tex_id, tex_obj_name, "TextureVideoClip"],
                            "LSS",
                            [
                                ["Type", ["TextureVideoClip"], "S", []],
                                ["Version", [202], "I", []],
                                [
                                    "TextureName",
                                    [tex_obj_name],
                                    "S",
                                    [],
                                ],  # Update here as well
                                ["Properties70", [], "", tex_props],
                                [
                                    "Media",
                                    [vid_obj_name],
                                    "S",
                                    [],
                                ],  # Reference to Video also by new name
                                ["FileName", [file_path], "S", []],
                                ["ModelUVTranslation", [0.0, 0.0], "DD", []],
                                [
                                    "ModelUVScaling",
                                    [
                                        float(mat_data["repeatU"]),
                                        float(mat_data["repeatV"]),
                                    ],
                                    "DD",
                                    [],
                                ],
                                ["Texture_Alpha_Source", ["None"], "S", []],
                            ],
                        ]
                        objects.append(tex_obj)

                        connections.append(["C", ["OO", vid_id, tex_id], "SLL", []])
                        connections.append(
                            ["C", ["OP", tex_id, mat_id, "DiffuseColor"], "SLLS", []]
                        )
                # 2. Create Geometry
                layer_material = [
                    "LayerElementMaterial",
                    [0],
                    "I",
                    [
                        ["Version", [101], "I", []],
                        ["Name", [""], "S", []],
                        ["MappingInformationType", [mapping_mode], "S", []],
                        ["ReferenceInformationType", [ref_mode], "S", []],
                        ["Materials", [[0]], "i", []],
                    ],
                ]

                mesh_obj = [
                    "Geometry",
                    [geom_id, f"{node['node_name']}::Geometry", "Mesh"],
                    "LSS",
                    [
                        ["Vertices", [[x for v in node["vrts"] for x in v]], "d", []],
                        ["PolygonVertexIndex", [node["PolygonVertexIndex"]], "i", []],
                        ["Edges", [node["Edges"]], "i", []],
                        ["GeometryVersion", [124], "I", []],
                        [
                            "LayerElementNormal",
                            [0],
                            "I",
                            [
                                ["Version", [102], "I", []],
                                ["Name", [""], "S", []],
                                [
                                    "MappingInformationType",
                                    ["ByPolygonVertex"],
                                    "S",
                                    [],
                                ],
                                ["ReferenceInformationType", ["Direct"], "S", []],
                                ["Normals", [node["Normals"]], "d", []],
                                ["NormalsW", [node["NormalsW"]], "d", []],
                            ],
                        ],
                        [
                            "LayerElementUV",
                            [0],
                            "I",
                            [
                                ["Version", [101], "I", []],
                                ["Name", ["map1"], "S", []],
                                [
                                    "MappingInformationType",
                                    ["ByPolygonVertex"],
                                    "S",
                                    [],
                                ],
                                [
                                    "ReferenceInformationType",
                                    ["IndexToDirect"],
                                    "S",
                                    [],
                                ],
                                ["UV", [node["UV"]], "d", []],
                                ["UVIndex", [node["UVIndex"]], "i", []],
                            ],
                        ],
                        layer_material,
                        [
                            "Layer",
                            [0],
                            "I",
                            [
                                ["Version", [100], "I", []],
                                [
                                    "LayerElement",
                                    [],
                                    "",
                                    [
                                        ["Type", ["LayerElementNormal"], "S", []],
                                        ["TypedIndex", [0], "I", []],
                                    ],
                                ],
                                [
                                    "LayerElement",
                                    [],
                                    "",
                                    [
                                        ["Type", ["LayerElementMaterial"], "S", []],
                                        ["TypedIndex", [0], "I", []],
                                    ],
                                ],
                                [
                                    "LayerElement",
                                    [],
                                    "",
                                    [
                                        ["Type", ["LayerElementUV"], "S", []],
                                        ["TypedIndex", [0], "I", []],
                                    ],
                                ],
                            ],
                        ],
                    ],
                ]
                objects.append(mesh_obj)
                connections.append(["C", ["OO", geom_id, model_id], "SLL", []])

            # Animation connections
            if node.get("with_animation"):
                anim_objs, anim_conns = create_fbx_animation_data(
                    node, node["id"], animation_layer_id
                )
                objects.extend(anim_objs)
                connections.extend(anim_conns)

    # Global Animation Objects
    objects.append(animation_layer)
    objects.append(
        [
            "AnimationStack",
            [anim_stack_id, "Take 001::AnimStack", ""],
            "LSS",
            [
                [
                    "Properties70",
                    [],
                    "",
                    [
                        ["P", ["LocalStart", "KTime", "Time", "", 0], "SSSSL", []],
                        [
                            "P",
                            [
                                "LocalStop",
                                "KTime",
                                "Time",
                                "",
                                int(100 * KTIME_PER_FRAME),
                            ],
                            "SSSSL",
                            [],
                        ],
                    ],
                ]
            ],
        ]
    )
    connections.append(["C", ["OO", animation_layer_id, anim_stack_id], "SLL", []])

    out = []
    out.extend(generate_fbx_header_json())
    out.extend(generate_fbx_definitions(nodes))
    out.append(["Objects", [], "", objects])
    out.append(["Connections", [], "", connections])
    out.append(
        [
            "Takes",
            [],
            "",
            [
                ["Current", ["Take 001"], "S", []],
                ["Take", ["Take 001"], "S", [["FileName", ["Take_001.tak"], "S", []]]],
            ],
        ]
    )

    return out


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main(argv):
    if len(argv) < 3:
        sys.stderr.write(f"Usage: python {argv[0]} input.nmf output_fbx.json\n")
        return 1

    input_path, output_path = argv[1], argv[2]

    # Init ID Generator
    uid_gen = UidGen(start=1776339759000)

    parser = Nmf()
    raw_nodes = parser.unpack(input_path)

    # Process (consuming IDs)
    scene_nodes = process_scene_nodes(raw_nodes, uid_gen)

    # Export (consuming more IDs for global anim objects)
    fbx_json = assemble_fbx(scene_nodes, uid_gen)

    with open(output_path, "w", encoding="utf-8") as io:
        json.dump(fbx_json, io, ensure_ascii=False, indent=2)

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
