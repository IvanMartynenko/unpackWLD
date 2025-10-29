bl_info = {
    "name": "Import NMF (custom 3D format)",
    "author": "you + ChatGPT",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "File > Import > NMF (.nmf)",
    "description": "Imports custom NMF models using an external parser",
    "category": "Import-Export",
}

import bpy
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, FloatProperty
from mathutils import Matrix, Vector, Euler
import math
import struct
import os
import copy
import json
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

# ---------------- constants ----------------
FPS = 24.0
DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi
MATRIX_SIZE = 16

# ---------------- low-level NMF reader ----------------

def read_aligned_string(f):
    bytes_list = []
    while True:
        b = f.read(1)
        if not b:
            break
        if b == b'\x00':
            break
        bytes_list.append(b)
    raw = b''.join(bytes_list)
    name = raw.decode('windows-1252', errors='ignore')
    total_len = len(raw) + 1
    padding = (4 - (total_len % 4)) % 4
    if padding:
        f.read(padding)
    return name


class Nmf:
    def unpack(self, path):
        model = []
        index = 1
        with open(path, "rb") as f:
            token = f.read(4).decode("ascii", errors="ignore")
            if token != "NMF ":
                raise RuntimeError(f"Bad start of ModelList. Expected 'NMF ' but got '{token}'")
            f.read(4)  # int32 == 0

            while True:
                token_bytes = f.read(4)
                if len(token_bytes) == 0:
                    raise EOFError("Unexpected end of file while reading token")
                token = token_bytes.decode("ascii", errors="ignore")

                _size = struct.unpack(">I", f.read(4))[0]
                if token == "END ":
                    break

                _skip = struct.unpack("<i", f.read(4))[0]
                parent_id = struct.unpack("<i", f.read(4))[0]
                name = read_aligned_string(f)

                if token == "ROOT":
                    data = self._parse_fram(f)
                elif token == "LOCA":
                    data = {}
                elif token == "FRAM":
                    data = self._parse_fram(f)
                elif token == "JOIN":
                    data = self._parse_join(f)
                elif token == "MESH":
                    data = self._parse_mesh(f)
                else:
                    raise RuntimeError(f"Unexpected token in MODEL: {token}")

                model.append({"type": token, "name": name, "parent_id": parent_id, "data": data, "id": index})
                index += 1
        return model

    def _parse_fram(self, f):
        res = {}
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["matrix"] = [vals[i:i+4] for i in range(0, MATRIX_SIZE, 4)]
        for key in ["translation","scaling","rotation","rotate_pivot_translate","rotate_pivot",
                    "scale_pivot_translate","scale_pivot","shear"]:
            res[key] = list(struct.unpack("<3f", f.read(12)))
        peek = f.read(4)
        if len(peek) != 4:
            return res
        word = peek.decode("ascii", errors="ignore")
        if word == "ANIM":
            res["anim"] = self._parse_anim(f)
        return res

    def _parse_join(self, f):
        res = {}
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["matrix"] = [vals[i:i+4] for i in range(0, MATRIX_SIZE, 4)]
        for key in ["translation", "scaling", "rotation"]:
            res[key] = list(struct.unpack("<3f", f.read(12)))
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["rotation_matrix"] = [vals[i:i+4] for i in range(0, MATRIX_SIZE, 4)]
        res["min_rot_limit"] = list(struct.unpack("<3f", f.read(12)))
        res["max_rot_limit"] = list(struct.unpack("<3f", f.read(12)))
        peek = f.read(4)
        if len(peek) != 4:
            return res
        word = peek.decode("ascii", errors="ignore")
        if word == "ANIM":
            res["anim"] = self._parse_anim(f)
        return res

    def _parse_anim(self, f):
        res = {}
        sizes = {}
        res["unknown"] = struct.unpack("<i", f.read(4))[0]
        keys = ["translation", "rotation", "scaling"]
        for key in keys:
            res[key] = {}
            sizes[key] = {}
        for key in keys:
            sizes[key]["sizes"] = list(struct.unpack("<3i", f.read(12)))
        for key in keys:
            axis_sizes = sizes[key]["sizes"]
            cur = {"values": {}, "keys": {}}
            n = axis_sizes[0]
            if n > 0:
                cur["keys"]["x"] = list(struct.unpack(f"<{n}f", f.read(4*n)))
                cur["values"]["x"] = list(struct.unpack(f"<{n}f", f.read(4*n)))
            n = axis_sizes[1]
            if n > 0:
                cur["keys"]["y"] = list(struct.unpack(f"<{n}f", f.read(4*n)))
                cur["values"]["y"] = list(struct.unpack(f"<{n}f", f.read(4*n)))
            n = axis_sizes[2]
            if n > 0:
                cur["keys"]["z"] = list(struct.unpack(f"<{n}f", f.read(4*n)))
                cur["values"]["z"] = list(struct.unpack(f"<{n}f", f.read(4*n)))
            res[key] = cur
        return res

    def _parse_mesh(self, f):
        res = {}
        res["tnum"] = struct.unpack("<i", f.read(4))[0]
        res["vnum"] = struct.unpack("<i", f.read(4))[0]

        vbuf_count = 10
        uvbuf_count = 2
        vbuf_count_float = res["vnum"] * vbuf_count
        uvbuf_count_float = res["vnum"] * uvbuf_count

        vbuf_flat = list(struct.unpack(f"<{vbuf_count_float}f", f.read(4 * vbuf_count_float)))
        res["vbuf"] = [vbuf_flat[i:i+vbuf_count] for i in range(0, len(vbuf_flat), vbuf_count)]

        uv_flat = list(struct.unpack(f"<{uvbuf_count_float}f", f.read(4 * uvbuf_count_float)))
        res["uvpt"] = [uv_flat[i:i+uvbuf_count] for i in range(0, len(uv_flat), uvbuf_count)]

        res["inum"] = struct.unpack("<i", f.read(4))[0]
        ibuf_flat = list(struct.unpack(f"<{res['inum']}h", f.read(2 * res["inum"])))
        res["ibuf"] = [ibuf_flat[i:i+3] for i in range(0, len(ibuf_flat), 3)]

        if res["inum"] % 2 == 1:
            _ = struct.unpack("<h", f.read(2))[0]

        res["backface_culling"] = struct.unpack("<i", f.read(4))[0]
        res["complex"] = struct.unpack("<i", f.read(4))[0]
        res["inside"] = struct.unpack("<i", f.read(4))[0]
        res["smooth"] = struct.unpack("<i", f.read(4))[0]
        res["light_flare"] = struct.unpack("<i", f.read(4))[0]

        material_count = struct.unpack("<i", f.read(4))[0]
        if material_count > 0:
            res["materials"] = []
            for _ in range(material_count):
                res["materials"].append(self._parse_mtrl(f))

        peek = f.read(4)
        if len(peek) == 4 and peek.decode("ascii", errors="ignore") == "ANIM":
            res["mesh_anim"] = self._parse_anim_mesh(f)
        # anti-ground
        raw = f.read(4)
        unknown_count_of_floats = struct.unpack("<i", raw)[0]
        if unknown_count_of_floats > 0:
            cnt = unknown_count_of_floats * 3
            res["unknown_floats"] = list(struct.unpack(f"<{cnt}f", f.read(4 * cnt)))
        unknown_count_of_ints = struct.unpack("<i", f.read(4))[0]
        if unknown_count_of_ints > 0:
            res["unknown_ints"] = list(struct.unpack(f"<{unknown_count_of_ints}i", f.read(4 * unknown_count_of_ints)))
        return res

    def _parse_mtrl(self, f):
        res = {}
        token = f.read(4).decode("ascii", errors="ignore")
        if token != "MTRL":
            raise RuntimeError(f"Expected 'MTRL' but got '{token}'")
        name = read_aligned_string(f)
        res["name"] = name

        res["blend_mode"] = struct.unpack("<i", f.read(4))[0]
        res["unknown_ints"] = list(struct.unpack("<4i", f.read(16)))
        res["uv_mapping_flip_horizontal"] = struct.unpack("<i", f.read(4))[0]
        res["uv_mapping_flip_vertical"] = struct.unpack("<i", f.read(4))[0]
        res["rotate"] = struct.unpack("<i", f.read(4))[0]
        res["horizontal_stretch"] = struct.unpack("<f", f.read(4))[0]
        res["vertical_stretch"] = struct.unpack("<f", f.read(4))[0]
        res["red"] = struct.unpack("<f", f.read(4))[0]
        res["green"] = struct.unpack("<f", f.read(4))[0]
        res["blue"] = struct.unpack("<f", f.read(4))[0]
        res["alpha"] = struct.unpack("<f", f.read(4))[0]
        res["red2"] = struct.unpack("<f", f.read(4))[0]
        res["green2"] = struct.unpack("<f", f.read(4))[0]
        res["blue2"] = struct.unpack("<f", f.read(4))[0]
        res["alpha2"] = struct.unpack("<f", f.read(4))[0]
        res["unknown_zero_ints"] = list(struct.unpack("<9i", f.read(36)))

        next_token_bytes = f.read(4)
        if len(next_token_bytes) == 4:
            next_token = next_token_bytes.decode("ascii", errors="ignore")
            if next_token == "TXPG":
                name = read_aligned_string(f)
                res["texture"] = {
                    "name": name,
                    "texture_page": struct.unpack("<i", f.read(4))[0],
                    "index_texture_on_page": struct.unpack("<i", f.read(4))[0],
                    "x0": struct.unpack("<i", f.read(4))[0],
                    "y0": struct.unpack("<i", f.read(4))[0],
                    "x2": struct.unpack("<i", f.read(4))[0],
                    "y2": struct.unpack("<i", f.read(4))[0],
                }
            elif next_token == "TEXT":
                name = read_aligned_string(f)
                res["text"] = {"name": name}
        return res

    def _parse_anim_mesh(self, f):
        anim_meshes = [self._parse_single_anim_mesh(f)]
        while True:
            peek = f.read(4)
            if len(peek) != 4:
                break
            word = peek.decode("ascii", errors="ignore")
            if word == "ANIM":
                anim_meshes.append(self._parse_single_anim_mesh(f))
            else:
                break
        return anim_meshes

    def _parse_single_anim_mesh(self, f):
        unknown_bool = struct.unpack("<i", f.read(4))[0]
        size = struct.unpack("<i", f.read(4))[0]
        unknown_ints = list(struct.unpack(f"<{size}i", f.read(4 * size)))
        unknown_floats = list(struct.unpack("<3f", f.read(12)))
        s1 = struct.unpack("<i", f.read(4))[0]
        s2 = struct.unpack("<i", f.read(4))[0]
        s3 = struct.unpack("<i", f.read(4))[0]
        unknown_floats1 = list(struct.unpack(f"<{s1*2}f", f.read(4 * (s1 * 2))))
        unknown_floats2 = list(struct.unpack(f"<{s2*2}f", f.read(4 * (s2 * 2))))
        unknown_floats3 = list(struct.unpack(f"<{s3*2}f", f.read(4 * (s3 * 2))))
        return {
            "unknown_bool": unknown_bool,
            "unknown_size_of_ints": size,
            "unknown_ints": unknown_ints,
            "unknown_floats": unknown_floats,
            "unknown_size1": s1,
            "unknown_size2": s2,
            "unknown_size3": s3,
            "unknown_floats1": unknown_floats1,
            "unknown_floats2": unknown_floats2,
            "unknown_floats3": unknown_floats3,
        }

#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#  END PARSE NMF
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
import numpy as np
import math

def mat4_identity():
    return np.eye(4, dtype=float)

def T(v):
    m = mat4_identity()
    m[:3, 3] = v
    return m

def Rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([
        [1, 0, 0, 0],
        [0, c, -s, 0],
        [0, s,  c, 0],
        [0, 0, 0, 1]
    ], dtype=float)

def Ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([
        [ c, 0, s, 0],
        [ 0, 1, 0, 0],
        [-s, 0, c, 0],
        [ 0, 0, 0, 1]
    ], dtype=float)

def Rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([
        [c, -s, 0, 0],
        [s,  c, 0, 0],
        [0,  0, 1, 0],
        [0,  0, 0, 1]
    ], dtype=float)

def Rxyz(v):
    rx, ry, rz = v
    return Rx(rx) @ Ry(ry) @ Rz(rz)

def S(v):
    sx, sy, sz = v
    return np.diag([sx, sy, sz, 1.0])

def build_pivoted(tr, rot, sca, rp, rpt=None, sp=None, spt=None, radians=True):
    """
    Собирает матрицу TRS с пивотами.
    - Если rpt/spt не заданы, они будут вычислены как (I - R)@rp и (I - S)@sp.
    - rot может быть в градусах (radians=False).
    """
    tr = np.asarray(tr, float)
    rp = np.asarray(rp, float)
    sp = np.asarray(sp if sp is not None else [0,0,0], float)
    sca = np.asarray(sca, float)

    rx, ry, rz = rot
    if not radians:
        rx = math.radians(rx); ry = math.radians(ry); rz = math.radians(rz)

    R = Rxyz((rx, ry, rz))
    S_m = S(sca)

    # Пересчёт компенсаций, если надо
    if rpt is None:
        # RpT = (I - R) * Rp
        rpt = (np.eye(3) - R[:3,:3]) @ rp
    else:
        rpt = np.asarray(rpt, float)

    if spt is None:
        # SpT = (I - S) * Sp  (S — диагональная)
        S3 = np.diag(sca)
        spt = (np.eye(3) - S3) @ sp
    else:
        spt = np.asarray(spt, float)

    M = np.eye(4)
    M = M @ T(tr)
    M = M @ T(rpt)    # rotatePivotTranslate
    M = M @ T(rp)     # rotatePivot
    M = M @ R         # rotation
    M = M @ T(-rp)
    M = M @ T(spt)    # scalePivotTranslate
    M = M @ T(sp)     # scalePivot
    M = M @ S_m       # scale
    M = M @ T(-sp)
    return M


def decompose_trs_XYZ(M):
    # translation
    t = M[:3, 3].copy()
    # remove translation
    A = M.copy()
    A[:3, 3] = 0.0
    # columns
    c0, c1, c2 = A[:3, 0], A[:3, 1], A[:3, 2]
    sx, sy, sz = np.linalg.norm(c0), np.linalg.norm(c1), np.linalg.norm(c2)
    r0, r1, r2 = c0 / sx, c1 / sy, c2 / sz
    R = np.column_stack((r0, r1, r2))
    if np.linalg.det(R) < 0:
        sz = -sz
        R[:, 2] *= -1

    ry = math.asin(max(-1.0, min(1.0, R[0, 2])))
    cy = math.cos(ry)
    if abs(cy) > 1e-6:
        rx = math.atan2(-R[1, 2], R[2, 2])
        rz = math.atan2(-R[0, 1], R[0, 0])
    else:
        rx = math.atan2(R[2, 1], R[1, 1])
        rz = 0.0
    return t.tolist(), [rx, ry, rz], [sx, sy, sz]

# ---------- НОВОЕ: разворачивание углов (unwrap) ----------
def unwrap_angles(vals, period=2*math.pi, tol=1e-9):
    """
    Делает углы непрерывными: каждый следующий угол сдвигается на k*2π,
    чтобы разница с предыдущим попала в (-π, π].
    """
    if not vals:
        return vals
    out = [float(vals[0])]
    for v in vals[1:]:
        v = float(v)
        delta = v - out[-1]
        # приведём delta в (-π, π]
        delta = (delta + math.pi) % (2*math.pi) - math.pi
        if abs(delta) < tol:
            delta = 0.0  # устранить -0.0
        out.append(out[-1] + delta)
    return out

def bake_pivots_in_array(objects):
    for obj in objects:
        if obj.get("word") != "FRAM":
            continue
        data = obj.get("data", {})
        anim = data.get("anim")
        if not anim:
            continue

        rp  = np.array(data.get("rotate_pivot", [0,0,0]), dtype=float)
        rpt = np.array(data.get("rotate_pivot_translate", [0,0,0]), dtype=float)
        sp  = np.array(data.get("scale_pivot", [0,0,0]), dtype=float)
        spt = np.array(data.get("scale_pivot_translate", [0,0,0]), dtype=float)

        # Ключи времени (как у тебя)
        keys = anim["rotation"]["x"]["keys"]

        new_trans = {"x": {"keys": [], "values": []},
                     "y": {"keys": [], "values": []},
                     "z": {"keys": [], "values": []}}
        new_rot = {"x": {"keys": [], "values": []},
                   "y": {"keys": [], "values": []},
                   "z": {"keys": [], "values": []}}
        new_sca = {"x": {"keys": [], "values": []},
                   "y": {"keys": [], "values": []},
                   "z": {"keys": [], "values": []}}

        for i, t_key in enumerate(keys):
            tr = np.array([
                anim["translation"]["x"]["values"][i],
                anim["translation"]["y"]["values"][i],
                anim["translation"]["z"]["values"][i],
            ], dtype=float)

            rot = np.array([
                anim["rotation"]["x"]["values"][i],
                anim["rotation"]["y"]["values"][i],
                anim["rotation"]["z"]["values"][i],
            ], dtype=float)

            sca = np.array([
                anim["scaling"]["x"]["values"][i],
                anim["scaling"]["y"]["values"][i],
                anim["scaling"]["z"]["values"][i],
            ], dtype=float)

            M = build_pivoted(tr, rot, sca, rp, rpt, sp, spt)
            tr_new, rot_new, sca_new = decompose_trs_XYZ(M)

            new_trans["x"]["keys"].append(t_key); new_trans["x"]["values"].append(tr_new[0])
            new_trans["y"]["keys"].append(t_key); new_trans["y"]["values"].append(tr_new[1])
            new_trans["z"]["keys"].append(t_key); new_trans["z"]["values"].append(tr_new[2])

            new_rot["x"]["keys"].append(t_key); new_rot["x"]["values"].append(rot_new[0])
            new_rot["y"]["keys"].append(t_key); new_rot["y"]["values"].append(rot_new[1])
            new_rot["z"]["keys"].append(t_key); new_rot["z"]["values"].append(rot_new[2])

            new_sca["x"]["keys"].append(t_key); new_sca["x"]["values"].append(sca_new[0])
            new_sca["y"]["keys"].append(t_key); new_sca["y"]["values"].append(sca_new[1])
            new_sca["z"]["keys"].append(t_key); new_sca["z"]["values"].append(sca_new[2])

        # ---------- НОВОЕ: фиксируем «скачки» углов X/Y/Z ----------
        for axis in ("x", "y", "z"):
            vals = new_rot[axis]["values"]
            vals = unwrap_angles(vals)
            # если первый ≈ -0, сдвинем дорожку так, чтобы стартовал с +0
            if vals and vals[0] < 0 and abs(vals[0]) < 1e-6:
                shift = -vals[0]
                vals = [v + shift for v in vals]
            new_rot[axis]["values"] = vals
            
        data["anim"]["translation"] = new_trans
        data["anim"]["rotation"]    = new_rot
        data["anim"]["scaling"]     = new_sca

        # Обнуляем пивоты
        data["rotate_pivot"] = [0,0,0]
        data["rotate_pivot_translate"] = [0,0,0]
        data["scale_pivot"] = [0,0,0]
        data["scale_pivot_translate"] = [0,0,0]

        obj["data"] = data
    return objects

#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
def Tmat(t: np.ndarray) -> np.ndarray:
    M = np.eye(4, dtype=np.float64)
    M[:3, 3] = t[:3]
    return M

def Smat(s: np.ndarray) -> np.ndarray:
    M = np.eye(4, dtype=np.float64)
    M[0,0], M[1,1], M[2,2] = s[0], s[1], s[2]
    return M

def Shmat(sh: np.ndarray) -> np.ndarray:
    """Shear with components (shXY, shXZ, shYZ). Convention:
       x' = x + shXY*y + shXZ*z
       y' = y + shYZ*z
       z' = z
       Matrix (column-vector convention):
       [1   shXY shXZ 0
        0   1    shYZ 0
        0   0    1    0
        0   0    0    1]
    """
    shXY, shXZ, shYZ = sh[0], sh[1], sh[2]
    M = np.eye(4, dtype=np.float64)
    M[0,1] = shXY
    M[0,2] = shXZ
    M[1,2] = shYZ
    return M

def Rx(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    M = np.eye(4, dtype=np.float64)
    M[1,1] = c; M[1,2] = -s
    M[2,1] = s; M[2,2] = c
    return M

def Ry(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    M = np.eye(4, dtype=np.float64)
    M[0,0] = c;  M[0,2] = s
    M[2,0] = -s; M[2,2] = c
    return M

def Rz(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    M = np.eye(4, dtype=np.float64)
    M[0,0] = c; M[0,1] = -s
    M[1,0] = s; M[1,1] = c
    return M

def Rxyz(euler: np.ndarray) -> np.ndarray:
    """Rotation order XYZ: rotate around X, then Y, then Z.
       Column-vector convention => M = Rz * Ry * Rx
    """
    rx, ry, rz = euler[0], euler[1], euler[2]
    return (Rz(rz) @ Ry(ry) @ Rx(rx))

def extract_trs_no_shear(M: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decompose 4x4 affine matrix into T, EulerXYZ (radians), Scale, removing shear.
       Uses Gram–Schmidt on the 3x3 part, then converts to XYZ Euler.
    """
    # Translation
    T = M[:3, 3].copy()

    # 3x3
    A = M[:3, :3].astype(np.float64).copy()

    # Columns (column-vector convention)
    aX = A[:, 0]
    aY = A[:, 1]
    aZ = A[:, 2]

    def length(v):
        return np.linalg.norm(v)

    def normalize(v):
        n = length(v)
        if n < 1e-12:
            return v * 0.0
        return v / n

    sx = length(aX)
    nx = normalize(aX)

    shXY = float(np.dot(nx, aY))
    y_   = aY - shXY * nx
    sy   = length(y_)
    ny   = normalize(y_) if sy > 1e-12 else np.array([0.0,1.0,0.0], dtype=np.float64)

    shXZ = float(np.dot(nx, aZ))
    z_   = aZ - shXZ * nx
    shYZ = float(np.dot(ny, z_))
    z__  = z_ - shYZ * ny
    sz   = length(z__)
    nz   = normalize(z__) if sz > 1e-12 else normalize(np.cross(nx, ny))

    R = np.column_stack([nx, ny, nz])

    # Fix determinant to be positive; fold reflection into scale.x
    if np.linalg.det(R) < 0.0:
        sx *= -1.0
        nx *= -1.0
        R = np.column_stack([nx, ny, nz])

    # Convert R to Euler XYZ (column-vector, M = Rz*Ry*Rx)
    # Derivation for XYZ:
    # From R = Rz*Ry*Rx, we have:
    # r02 = R[0,2] = sY
    # r12 = R[1,2] = -cY*sX
    # r22 = R[2,2] = cY*cX
    # r01 = R[0,1] = -cZ*sY + sZ*cY*sX
    # r00 = R[0,0] =  cZ*cY + sZ*sY*sX
    sy_sin = np.clip(R[0,2], -1.0, 1.0)
    ry = math.asin(sy_sin)
    cy = math.cos(ry)

    if abs(cy) > 1e-6:
        rx = math.atan2(-R[1,2], R[2,2])
        rz = math.atan2(-R[0,1], R[0,0])
    else:
        # Gimbal lock: cy ~ 0 => ry ~ ±pi/2
        # Set rz = 0 and compute rx from other terms
        rz = 0.0
        rx = math.atan2(R[2,1], R[1,1])

    S = np.array([sx, sy, sz], dtype=np.float64)
    euler_xyz = np.array([rx, ry, rz], dtype=np.float64)
    return T, euler_xyz, S

def unwrap_angle(prev: float, cur: float) -> float:
    """Choose cur + k*2π closest to prev to avoid jumps."""
    two_pi = 2.0 * math.pi
    k = round((prev - cur) / two_pi)
    return cur + k * two_pi

def compose_local_matrix_with_pivots(Tv: np.ndarray,
                                     Rxyz_v: np.ndarray,
                                     Sv: np.ndarray,
                                     rp: np.ndarray,
                                     rpt: np.ndarray,
                                     sp: np.ndarray,
                                     spt: np.ndarray,
                                     shear: np.ndarray) -> np.ndarray:
    """Compose local matrix using assumed order:
       M = T * RpT * Rp * R(XYZ) * Rp^-1 * SpT * Sp * Sh * S * Sp^-1
       All vectors are 3D arrays; angles in radians.
    """
    M_T   = Tmat(Tv)
    M_RpT = Tmat(rpt)
    M_Rp  = Tmat(rp)
    M_R   = Rxyz(Rxyz_v)
    M_SpT = Tmat(spt)
    M_Sp  = Tmat(sp)
    M_Sh  = Shmat(shear)
    M_S   = Smat(Sv)
    M_Rp_inv = Tmat(-rp)
    M_Sp_inv = Tmat(-sp)

    # Note: matrix multiply order with column vectors: rightmost applies first
    M = (M_T @ M_RpT @ M_Rp @ M_R @ M_Rp_inv @ M_SpT @ M_Sp @ M_Sh @ M_S @ M_Sp_inv)
    return M

# ------------- Animation sampling helpers -------------

def get_key_times(anim: Dict[str, Any]) -> List[float]:
    # Prefer translation.x if exists, else rotation.x, else scaling.x
    for channel in ["translation", "rotation", "scaling"]:
        if channel in anim and "x" in anim[channel] and "keys" in anim[channel]["x"]:
            return list(anim[channel]["x"]["keys"])
    return []

def sample_channel(anim_axis: Dict[str, Any], default_val: float) -> List[float]:
    if not anim_axis or "values" not in anim_axis:
        return [default_val]
    return list(anim_axis["values"])

def as_vec(vals: List[float]) -> np.ndarray:
    return np.array([vals[0], vals[1], vals[2]], dtype=np.float64)

# ------------- Core bake function -------------

def bake_pivots_in_array(nodes: List[Dict[str, Any]], degrees: bool=False) -> List[Dict[str, Any]]:
    """Bake all nodes so that rotate/scale pivots and shear become zero, folding them into TRS animation.
       - nodes: array of node dicts with fields like in the user's schema.
       - degrees: if True, interpret rotation channels as degrees; output also in degrees.
    """
    result = copy.deepcopy(nodes)

    for node in result:
        if node.get("word") != "FRAM":
            continue
        data = node.get("data", {})
        anim = data.get("anim", {})
        if not anim:
            # No animation: still zero pivots/shear and decompose current matrix once if present.
            data["rotate_pivot"] = [0.0, 0.0, 0.0]
            data["scale_pivot"] = [0.0, 0.0, 0.0]
            data["rotate_pivot_translate"] = [0.0, 0.0, 0.0]
            data["scale_pivot_translate"] = [0.0, 0.0, 0.0]
            data["shear"] = [0.0, 0.0, 0.0]
            continue

        # Base static values (used when channel is constant)
        base_T = as_vec(data.get("translation", [0.0, 0.0, 0.0]))
        base_R = as_vec(data.get("rotation",    [0.0, 0.0, 0.0]))
        base_S = as_vec(data.get("scaling",     [1.0, 1.0, 1.0]))

        if degrees:
            base_R = np.deg2rad(base_R)

        rp  = as_vec(data.get("rotate_pivot",            [0.0, 0.0, 0.0]))
        rpt = as_vec(data.get("rotate_pivot_translate",  [0.0, 0.0, 0.0]))
        sp  = as_vec(data.get("scale_pivot",             [0.0, 0.0, 0.0]))
        spt = as_vec(data.get("scale_pivot_translate",   [0.0, 0.0, 0.0]))
        sh  = as_vec(data.get("shear",                   [0.0, 0.0, 0.0]))

        # Key times
        times = get_key_times(anim)
        if not times:
            # Fallback: single sample at t=0
            times = [0.0]

        # Prepare axis arrays (use existing if present, otherwise constants)
        Txs = sample_channel(anim.get("translation", {}).get("x", {}), float(base_T[0]))
        Tys = sample_channel(anim.get("translation", {}).get("y", {}), float(base_T[1]))
        Tzs = sample_channel(anim.get("translation", {}).get("z", {}), float(base_T[2]))

        Rxs = sample_channel(anim.get("rotation", {}).get("x", {}), float(base_R[0]))
        Rys = sample_channel(anim.get("rotation", {}).get("y", {}), float(base_R[1]))
        Rzs = sample_channel(anim.get("rotation", {}).get("z", {}), float(base_R[2]))

        Sxs = sample_channel(anim.get("scaling", {}).get("x", {}), float(base_S[0]))
        Sys = sample_channel(anim.get("scaling", {}).get("y", {}), float(base_S[1]))
        Szs = sample_channel(anim.get("scaling", {}).get("z", {}), float(base_S[2]))

        nkeys = len(times)
        # Defensive: ensure all lists have same length
        def ensure_len(lst, n, fill_last=True):
            if len(lst) == n:
                return lst
            if not lst:
                return [0.0]*n
            if fill_last:
                return lst + [lst[-1]]*(n - len(lst))
            else:
                return (lst + [0.0]*(n - len(lst)))[:n]

        Txs = ensure_len(Txs, nkeys); Tys = ensure_len(Tys, nkeys); Tzs = ensure_len(Tzs, nkeys)
        Rxs = ensure_len(Rxs, nkeys); Rys = ensure_len(Rys, nkeys); Rzs = ensure_len(Rzs, nkeys)
        Sxs = ensure_len(Sxs, nkeys); Sys = ensure_len(Sys, nkeys); Szs = ensure_len(Szs, nkeys)

        if degrees:
            Rxs = [math.radians(v) for v in Rxs]
            Rys = [math.radians(v) for v in Rys]
            Rzs = [math.radians(v) for v in Rzs]

        # Output arrays
        out_Tx, out_Ty, out_Tz = [], [], []
        out_Rx, out_Ry, out_Rz = [], [], []
        out_Sx, out_Sy, out_Sz = [], [], []

        prev_rx = None; prev_ry = None; prev_rz = None

        for i in range(nkeys):
            Tv = np.array([Txs[i], Tys[i], Tzs[i]], dtype=np.float64)
            Rv = np.array([Rxs[i], Rys[i], Rzs[i]], dtype=np.float64)
            Sv = np.array([Sxs[i], Sys[i], Szs[i]], dtype=np.float64)

            # Build original local matrix including pivots and shear
            M_old = compose_local_matrix_with_pivots(Tv, Rv, Sv, rp, rpt, sp, spt, sh)

            # Decompose to TRS without pivots/shear
            T_new, R_new, S_new = extract_trs_no_shear(M_old)

            # Unwrap angles to avoid jumps
            if prev_rx is not None:
                R_new[0] = unwrap_angle(prev_rx, R_new[0])
                R_new[1] = unwrap_angle(prev_ry, R_new[1])
                R_new[2] = unwrap_angle(prev_rz, R_new[2])

            prev_rx, prev_ry, prev_rz = R_new[0], R_new[1], R_new[2]

            out_Tx.append(float(T_new[0]))
            out_Ty.append(float(T_new[1]))
            out_Tz.append(float(T_new[2]))

            out_Rx.append(float(R_new[0]))
            out_Ry.append(float(R_new[1]))
            out_Rz.append(float(R_new[2]))

            out_Sx.append(float(S_new[0]))
            out_Sy.append(float(S_new[1]))
            out_Sz.append(float(S_new[2]))

        # Convert back to degrees if requested
        if degrees:
            out_Rx = [math.degrees(v) for v in out_Rx]
            out_Ry = [math.degrees(v) for v in out_Ry]
            out_Rz = [math.degrees(v) for v in out_Rz]

        # Write results back
        # Preserve the same key times
        anim_out = anim
        if "translation" not in anim_out: anim_out["translation"] = {"x":{}, "y":{}, "z":{}}
        if "rotation" not in anim_out:    anim_out["rotation"]    = {"x":{}, "y":{}, "z":{}}
        if "scaling" not in anim_out:     anim_out["scaling"]     = {"x":{}, "y":{}, "z":{}}

        anim_out["translation"]["x"]["keys"] = times; anim_out["translation"]["x"]["values"] = out_Tx
        anim_out["translation"]["y"]["keys"] = times; anim_out["translation"]["y"]["values"] = out_Ty
        anim_out["translation"]["z"]["keys"] = times; anim_out["translation"]["z"]["values"] = out_Tz

        anim_out["rotation"]["x"]["keys"] = times; anim_out["rotation"]["x"]["values"] = out_Rx
        anim_out["rotation"]["y"]["keys"] = times; anim_out["rotation"]["y"]["values"] = out_Ry
        anim_out["rotation"]["z"]["keys"] = times; anim_out["rotation"]["z"]["values"] = out_Rz

        anim_out["scaling"]["x"]["keys"] = times; anim_out["scaling"]["x"]["values"] = out_Sx
        anim_out["scaling"]["y"]["keys"] = times; anim_out["scaling"]["y"]["values"] = out_Sy
        anim_out["scaling"]["z"]["keys"] = times; anim_out["scaling"]["z"]["values"] = out_Sz

        data["anim"] = anim_out

        node["data"] = data

    return result
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
# ---------------- Blender helpers ----------------
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
def import_nmf_file(context, filepath, global_scale=1.0, apply_unit_scale=True):
    nmf = Nmf()
    model_nodes = nmf.unpack(filepath)  # <- ваш список узлов
    normalizer = AnimationNormalizer()
    model_nodes = normalizer.normalize(model_nodes)
    model_nodes = bake_pivots_in_array(model_nodes)

    # Карта id -> объект Blender
    id_to_obj = {}
    # Карта индекс (по вашему коду) -> узел
    index_to_node = {n["id"]: n for n in model_nodes}

    # 1) Сначала создаём все объекты без родительства
    for node in model_nodes:
        kind = node["type"]
        name = node["name"] or f"{kind}_{node['id']}"
        data = node["data"]

        if kind == "MESH":
            obj = _create_mesh_object(name, data, global_scale)
        elif kind == "ROOT":
            data["matrix"] = [[1.0,0.0,0.0,0.0],[0.0,1.0,0.0,0.0],[0.0,0.0,1.0,0.0],[0.0,0.0,0.0,1.0]]
            obj = _create_empty(name, kind, data, global_scale)
        elif kind == "LOCA":
            pass
        else:
            # пустышки для FRAM/ROOT/JOIN/LOCA
            obj = _create_empty(name, kind, data, global_scale)

        id_to_obj[node["id"]] = obj

    # 2) Восстанавливаем иерархию по parent_id
    for node in model_nodes:
        pid = node["parent_id"]
        if pid > 0 and pid in id_to_obj:
            child = id_to_obj[node["id"]]
            parent = id_to_obj[pid]
            child.parent = parent

    # 3) Материалы/текстуры для всех мешей
    for node in model_nodes:
        if node["type"] == "MESH":
            obj = id_to_obj[node["id"]]
            _apply_materials(obj, node["data"], base_dir=os.path.dirname(filepath))

    # 4) Опционально — применяем единицы сцены/масштаб
    if apply_unit_scale and global_scale != 1.0:
        for obj in id_to_obj.values():
            obj.scale *= global_scale

    # 5) Выделим корневой
    roots = [id_to_obj[n["id"]] for n in model_nodes if n["parent_id"] <= 0]
    for r in roots:
        r.select_set(True)
    if roots:
        context.view_layer.objects.active = roots[0]

    # 6) Анимации: применяем, если есть
    fps = context.scene.render.fps
    for node in model_nodes:
        data = node.get("data") or {}
        anim_raw = data.get("anim")
        if not anim_raw:
            continue
        obj = id_to_obj.get(node["id"])
        if not obj:
            continue
        anim_tracks = _build_anim_tracks(anim_raw, fps)
        _apply_anim_to_object(obj, anim_tracks)

# ---------- helpers ----------

def _to_matrix4x4(vals_4x4):
    """
    Конвертирует row-major (как обычно в бинарных файлах и DirectX)
    в column-major (как ожидает Blender/Mathutils).
    """
    # поддерживаем [[...],[...],[...],[...]] и плоский список из 16 значений
    if isinstance(vals_4x4[0], (list, tuple)):
        flat = sum(vals_4x4, [])
    else:
        flat = list(vals_4x4)

    m = Matrix((
        (flat[0],  flat[1],  flat[2],  flat[3]),
        (flat[4],  flat[5],  flat[6],  flat[7]),
        (flat[8],  flat[9],  flat[10], flat[11]),
        (flat[12], flat[13], flat[14], flat[15]),
    ))

    # Blender хранит матрицы в column-major виде, поэтому транспонируем
    return m.transposed()

def _rotation_only_4x4(vals_4x4):
    """Зануляем перенос, оставляем чистую ротацию (и, если есть, non-uniform scale НЕ трогаем)."""
    rows = [Vector(row) for row in vals_4x4]
    m = Matrix(rows)
    # m[0][3] = m[1][3] = m[2][3] = 0.0
    # m[3] = (0.0, 0.0, 0.0, 1.0)
    return m

def _scale_mat_from_data(data):
    scl = data.get("scaling")
    if scl:
        sx, sy, sz = float(scl[0]), float(scl[1]), float(scl[2])
        return Matrix(((sx, 0,  0,  0),
                       (0,  sy, 0,  0),
                       (0,  0,  sz, 0),
                       (0,  0,  0,  1)))
    return Matrix.Identity(4)

def _to_vec3(v, scale=1.0):
    x, y, z = (float(v[0]), float(v[1]), float(v[2]))
    return Vector((x*scale, y*scale, z*scale))

def trs_matrix_rad(translation, rotation_rad_xyz, scaling):
    tx, ty, tz = translation
    rx, ry, rz = rotation_rad_xyz
    sx, sy, sz = scaling

    T = Matrix.Translation(Vector((tx, ty, tz)))
    R = Euler((rx, ry, rz), 'XYZ').to_matrix().to_4x4()
    S = Matrix.Diagonal((sx, sy, sz, 1.0))

    return T @ R @ S

def _create_empty(name, kind, data, global_scale):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)

    # Применяем матрицу, если есть
    if kind == "ROOT":
        obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = 0.25
        obj.color = (1.0, 0.9, 0.2, 1.0)   # жёлтый
    elif kind == "FRAM":
        obj.empty_display_type = 'ARROWS'
        obj.empty_display_size = 0.2
        obj.color = (0.4, 0.8, 1.0, 1.0)   # голубой
    elif kind == "JOIN":
        obj.empty_display_type = 'CUBE'
        obj.empty_display_size = 0.15
        obj.color = (0.8, 0.3, 1.0, 1.0)   # фиолетовый
    elif kind == "LOCA":
        obj.empty_display_type = 'SPHERE'
        obj.empty_display_size = 0.1
        obj.color = (0.3, 1.0, 0.3, 1.0)   # зелёный
    else:
        obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = 0.1
        obj.color = (0.8, 0.8, 0.8, 1.0)   # серый

    if kind == "LOCA":
        return obj

    M = _to_matrix4x4(data["matrix"])

    if kind == "JOIN":
        R = _rotation_only_4x4(data["rotation_matrix"])
        obj.matrix_world = M
        print("Matrix:\n", M,"\nROTATION:\n", R, "\nM @ R:\n", M @ R, "\n\n\n")
        return obj

    if kind == "FRAM":
        # FRAM / LOCA / прочее — применяем полную цепочку пивотов
        RP  = _to_vec3(data.get("rotate_pivot"),            global_scale)
        RPT = _to_vec3(data.get("rotate_pivot_translate"),  global_scale)
        SP  = _to_vec3(data.get("scale_pivot"),             global_scale)
        SPT = _to_vec3(data.get("scale_pivot_translate"),   global_scale)

        T_RP   = Matrix.Translation(RP)
        T_iRP  = Matrix.Translation(-RP)
        T_RPT  = Matrix.Translation(RPT)

        T_SP   = Matrix.Translation(SP)
        T_iSP  = Matrix.Translation(-SP)
        T_SPT  = Matrix.Translation(SPT)

        # r/s-компоненты
        R = _rotation_only_4x4(Matrix.Identity(4))
        S = _to_matrix4x4([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]])

        # итог: M @ T(RPT) @ T(RP) @ R @ T(-RP) @ T(SPT) @ T(SP) @ S @ T(-SP)
        # obj.matrix_world = M @ T_RPT @ T_RP @ R @ T_iRP @ T_SPT @ T_SP @ S @ T_iSP
        obj.matrix_world = M

    return obj

def _create_mesh_object(name, mdata, global_scale):
    # Геометрия
    me = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)

    vbuf = mdata.get("vbuf") or []   # [[x,y,z, ... 10 floats], ...]
    uvpt = mdata.get("uvpt") or []   # [[u,v], ...] длиной vnum
    ibuf = mdata.get("ibuf") or []   # [[i0,i1,i2], ...]

    # Берем только координаты
    verts = [(v[0] * global_scale, v[1] * global_scale, v[2] * global_scale) for v in vbuf]
    faces = [tuple(tri) for tri in ibuf if len(tri) == 3]

    me.from_pydata(verts, [], faces)
    me.validate(clean_customdata=False)
    me.update()

    # UV
    if uvpt and len(uvpt) == len(verts):
        if not me.uv_layers:
            me.uv_layers.new(name="UVMap")
        uv_layer = me.uv_layers.active.data
        # пробегаем по полигону и его лупам
        loop_index = 0
        for poly in me.polygons:
            for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                vidx = me.loops[li].vertex_index
                u, v = uvpt[vidx]
                uv_layer[loop_index].uv = (u, 1.0 - v)  # V-flip, если нужно
                loop_index += 1

    # Матрица трансформа
    if "matrix" in mdata:
        obj.matrix_world = _to_matrix4x4(mdata["matrix"])

    # Гладкость
    if mdata.get("smooth", 0):
        for p in me.polygons:
            p.use_smooth = True

    return obj

def _apply_materials(obj, mdata, base_dir):
    mats = mdata.get("materials")
    if not mats:
        return

    me = obj.data
    # убедимся что слоты материалов существуют
    for _ in range(len(mats) - len(me.materials)):
        me.materials.append(None)

    for i, m in enumerate(mats):
        mat = bpy.data.materials.new(name=m.get("name") or f"Mat_{i}")
        mat.use_nodes = True
        nt = mat.node_tree; nodes = nt.nodes; links = nt.links

        # очистим стандартные
        for n in list(nodes):
            nodes.remove(n)
        out = nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
        bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (0, 0)
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

        # Цвета (если есть)
        if "red" in m:
            base_col = (m["red"], m["green"], m["blue"], m.get("alpha", 1.0))
            bsdf.inputs["Base Color"].default_value = base_col
            bsdf.inputs["Alpha"].default_value = base_col[3]

        # Текстура страница TXPG
        tex = m.get("texture")
        txt = m.get("text")
        img = None

        if tex and tex.get("name"):
            # предполагаем имя — путь/файл
            img_path = _resolve_image_path(tex["name"], base_dir)
            if img_path and os.path.exists(img_path):
                img = bpy.data.images.load(img_path, check_existing=True)
        elif txt and txt.get("name"):
            img_path = _resolve_image_path(txt["name"], base_dir)
            if img_path and os.path.exists(img_path):
                img = bpy.data.images.load(img_path, check_existing=True)

        if img:
            tex_node = nodes.new("ShaderNodeTexImage"); tex_node.image = img; tex_node.location = (-350, 0)
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
            # альфа, если есть
            if img.channels == 4:
                links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])
                mat.blend_method = 'BLEND'

        me.materials[i] = mat

def _resolve_image_path(name, base_dir):
    # если в NMF хранится только имя, пробуем рядом с файлом
    candidate = os.path.join(base_dir, name)
    if os.path.exists(candidate):
        return candidate
    # можно добавить доп. стратегии поиска здесь
    return None

def _gather_axis_series(track_dict, axis):
    """Безопасно достаём пары (frames, values) по оси 'x'/'y'/'z'."""
    if not track_dict:
        return None, None
    keys = track_dict.get("keys", {}).get(axis)
    vals = track_dict.get("values", {}).get(axis)
    if not keys or not vals or len(keys) != len(vals):
        return None, None
    return list(map(float, keys)), list(map(float, vals))

def _guess_rot_in_degrees(anim_raw):
    """Грубая эвристика: если по любой оси значения > ~2π, считаем что приходят в градусах."""
    rot = anim_raw.get("rotation")
    if not rot:
        return False
    for ax in ("x","y","z"):
        vals = rot.get("values",{}).get(ax) or []
        if any(abs(float(v)) > 6.5 for v in vals):  # 6.5 ~ чуть больше 2π
            return True
    return False

def _build_anim_tracks(anim_raw, fps):
    """
    Преобразует raw anim в удобный вид:
    {
      'translation': {'x': (frames[], values[]), ...},
      'rotation':    {'x': (frames[], values[]), ...},  # значения в РАДИАНАХ на выходе!
      'scaling':     {'x': (frames[], values[]), ...},
    }
    """
    out = {}
    rot_in_deg = _guess_rot_in_degrees(anim_raw)
    rot_scale = (math.pi/180.0) if rot_in_deg else 1.0

    for track in ("translation", "rotation", "scaling"):
        src = anim_raw.get(track)
        if not src:
            continue
        per_axis = {}
        for ax in ("x","y","z"):
            frames, values = _gather_axis_series(src, ax)
            if not frames:
                continue
            # время → кадры
            frames = [float(t)*fps for t in frames]
            if track == "rotation":
                values = [float(v)*rot_scale for v in values]  # к рад.
            else:
                values = [float(v) for v in values]
            per_axis[ax] = (frames, values)
        if per_axis:
            out[track] = per_axis
    return out

def _apply_anim_to_object(obj, anim_tracks):
    """
    Пишет ключи сразу на объект:
      translation -> location
      rotation    -> rotation_euler (XYZ, rad)
      scaling     -> scale
    """
    if not anim_tracks:
        return

    obj.rotation_mode = 'XYZ'
    spec = {
        'translation': ('location', (0,1,2), 1.0),
        'rotation':    ('rotation_euler', (0,1,2), 1.0),  # уже в радианах
        'scaling':     ('scale', (0,1,2), 1.0),
    }

    for track, (prop, idxs, scale) in spec.items():
        per_axis = anim_tracks.get(track)
        if not per_axis:
            continue
        for ax_name, ax_i in zip(('x','y','z'), idxs):
            series = per_axis.get(ax_name)
            if not series:
                continue
            frames, values = series
            for f, v in zip(frames, values):
                arr = getattr(obj, prop)
                arr[ax_i] = float(v) * scale
                obj.keyframe_insert(data_path=prop, index=ax_i, frame=int(round(f)))

# ---------------- UI operator ----------------
class IMPORT_SCENE_OT_nmf(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.nmf"
    bl_label = "Import NMF"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".nmf"
    filter_glob: StringProperty(default="*.nmf", options={'HIDDEN'})

    apply_unit_scale: BoolProperty(
        name="Apply Unit Scale", default=True,
        description="Apply scene unit scale to imported data"
    )
    global_scale: FloatProperty(
        name="Scale", default=1.0, min=0.0001, max=1000.0
    )

    def execute(self, context):
        try:
            import_nmf_file(
                context=context,
                filepath=self.filepath,
                global_scale=self.global_scale,
                apply_unit_scale=self.apply_unit_scale,
            )
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"NMF import failed: {e}")
            return {'CANCELLED'}

def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_nmf.bl_idname, text="NMF (.nmf)")

def register():
    bpy.utils.register_class(IMPORT_SCENE_OT_nmf)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_SCENE_OT_nmf)
