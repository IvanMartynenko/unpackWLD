# io_import_nmf.py
# Blender add-on: Import NMF (binary) → objects, meshes, materials, animations

bl_info = {
    "name": "Import: NMF (Neo Model Format)",
    "author": "You + ChatGPT",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "File > Import > NMF (.nmf)",
    "description": "Import .nmf models (meshes, hierarchy, UVs, materials, textures, basic animation)",
    "category": "Import-Export",
}

import bpy
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty
from mathutils import Euler
import math
import struct
import os
from typing import Any, Dict, List, Optional, Tuple

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

                model.append({"word": token, "name": name, "parent_id": parent_id, "data": data, "index": index})
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

# ---------------- helpers / geometry ----------------

class MeshGeom:
    EPS = 1e-8
    @staticmethod
    def normalize(v: List[float]) -> List[float]:
        l = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
        if l < MeshGeom.EPS:
            return [0.0, 0.0, 0.0]
        return [v[0]/l, v[1]/l, v[2]/l]
    @staticmethod
    def sub(a, b): return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]
    @staticmethod
    def cross(a, b):
        return [(a[1]*b[2])-(a[2]*b[1]), (a[2]*b[0])-(a[0]*b[2]), (a[0]*b[1])-(a[1]*b[0])]
    @staticmethod
    def dot(a, b): return (a[0]*b[0])+(a[1]*b[1])+(a[2]*b[2])
    @staticmethod
    def pos_of(row): return row[0:3]
    @staticmethod
    def nrm_of(row): return row[3:6]

    @staticmethod
    def mesh_right_handed(ibuf: List[List[int]], mesh_data: Dict[str, Any]) -> bool:
        vbuf = mesh_data['vbuf']
        pos = [MeshGeom.pos_of(r) for r in vbuf]
        nrm = [MeshGeom.nrm_of(r) for r in vbuf]
        pos_cnt = 0
        neg_cnt = 0
        for (i0, i1, i2) in ibuf:
            p0, p1, p2 = pos[i0], pos[i1], pos[i2]
            n_geom = MeshGeom.normalize(MeshGeom.cross(MeshGeom.sub(p1, p0), MeshGeom.sub(p2, p0)))
            n_avg = MeshGeom.normalize([nrm[i0][0]+nrm[i1][0]+nrm[i2][0],
                                        nrm[i0][1]+nrm[i1][1]+nrm[i2][1],
                                        nrm[i0][2]+nrm[i1][2]+nrm[i2][2]])
            s = MeshGeom.dot(n_geom, n_avg)
            if s >= 0: pos_cnt += 1
            else: neg_cnt += 1
        return pos_cnt >= neg_cnt

def add_v(a, b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def neg_v(a): return (-a[0], -a[1], -a[2])

def create_transform_chain(node, parent_obj: Optional[bpy.types.Object]):
    # безопасные имена контроллеров для всех типов узлов (fram/joint/locator)
    base = node.get('node_name', 'Node')
    t_name   = node.get('t_name',   base + "_TCTL")
    r_name   = node.get('r_name',   base + "_RPIV")
    r_off    = node.get('r_off_name', base + "_ROFF")
    s_name   = node.get('s_name',   base + "_SPIV")
    s_off    = node.get('s_off_name', base + "_SOFF")
    anchor_n = node.get('anchor_name', base)

    T  = tuple(node.get('translation', (0,0,0)))
    R  = tuple(node.get('rotation', (0,0,0)))        # градусы
    S  = tuple(node.get('scaling', (1,1,1)))

    Rp  = tuple(node.get('rotate_pivot', (0,0,0)))
    RpT = tuple(node.get('rotate_pivot_translate', (0,0,0)))

    Sp  = tuple(node.get('scale_pivot', (0,0,0)))
    SpT = tuple(node.get('scale_pivot_translate', (0,0,0)))

    # 1) T-CTL
    tctl = create_empty(t_name, parent_obj, T, (0,0,0), (1,1,1), type='PLAIN_AXES')

    # 2) R-CTL в точке RpT + Rp (rotation живёт здесь)
    rctl_loc = add_v(RpT, Rp)               # <-- было v_add/v_add
    rctl = create_empty(r_name, tctl, rctl_loc, R, (1,1,1), type='ARROWS')

    # 3) R-OFF на −Rp
    roff_obj = create_empty(r_off, rctl, neg_v(Rp), (0,0,0), (1,1,1), type='PLAIN_AXES')  # <-- было v_neg

    # 4) S-CTL в SpT + Sp (scale живёт здесь)
    sctl_loc = add_v(SpT, Sp)               # <-- было v_add
    sctl = create_empty(s_name, roff_obj, sctl_loc, (0,0,0), S, type='PLAIN_AXES')

    # 5) S-OFF на −Sp
    soff = create_empty(s_off, sctl, neg_v(Sp), (0,0,0), (1,1,1), type='PLAIN_AXES')

    # 6) конечная точка (узел/локатор)
    disp = 'ARROWS' if node.get('node_type') == 'joint' else 'PLAIN_AXES'
    anchor = create_empty(anchor_n, soff, (0,0,0), (0,0,0), (1,1,1), type=disp)

    return {'T': tctl, 'R': rctl, 'R_OFF': roff_obj, 'S': sctl, 'S_OFF': soff, 'ANCHOR': anchor}

def convert_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    index_map = {n["index"]: n for n in nodes}
    for node in nodes:
        unpacked = node["data"]
        node_name = node["name"] or f"node_{node['index']}"
        parent = index_map.get(node.get("parent_id"))
        parent_name = parent["name"] if parent else None
        if node.get("parent_id") == 1:
            parent_name = None

        w = node["word"]
        if w in ("ROOT", "FRAM"):
            result.append(create_fram(unpacked, node_name=node_name, parent_node_name=parent_name))
        elif w == "JOIN":
            result.append(create_joint(unpacked, node_name=node_name, parent_node_name=parent_name))
        elif w == "LOCA":
            result.append(create_locator(unpacked, node_name=node_name, parent_node_name=parent_name))
        elif w == "MESH":
            result.append(create_mesh(unpacked, node_name=node_name, parent_node_name=parent_name))
    return result

def animation_build_tracks_by_axis(raw_values: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, List[float]]]]:
    axes = ("x", "y", "z")
    result: Dict[str, Dict[str, Dict[str, List[float]]]] = {}
    for track in ("translation", "rotation", "scaling"):
        anim = raw_values.get(track)
        if not anim:
            continue
        keys = anim.get("keys")
        values = anim.get("values")
        if not keys or not values:
            continue
        track_hash: Dict[str, Dict[str, List[float]]] = {}
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

def extract_3x3(m4: Optional[List[List[float]]]) -> Optional[List[List[float]]]:
    if not m4:
        return None
    a = [c for row in m4 for c in row]
    return [[a[0], a[1], a[2]],
            [a[4], a[5], a[6]],
            [a[8], a[9], a[10]]]

def matrix_rowmajor_to_euler_xyz_standard(m: Optional[List[List[float]]]) -> List[float]:
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

def build_edges_and_faces_signed(tris: List[List[int]]) -> Tuple[List[List[int]], List[List[int]]]:
    edge_map: Dict[str, int] = {}
    edges: List[List[int]] = []
    for (a, b, c) in tris:
        for u, v in ((a, b), (b, c), (c, a)):
            va, vb = (u, v) if u <= v else (v, u)
            key = f"{va}|{vb}"
            if key not in edge_map:
                edge_map[key] = len(edges)
                edges.append([va, vb])
    faces_signed: List[List[int]] = []
    for (a, b, c) in tris:
        e0 = signed_edge_index(edge_map, a, b)
        e1 = signed_edge_index(edge_map, b, c)
        e2 = signed_edge_index(edge_map, c, a)
        faces_signed.append([e0, e1, e2])
    return edges, faces_signed

def signed_edge_index(edge_map: Dict[str, int], a: int, b: int) -> int:
    va, vb = (a, b) if a <= b else (b, a)
    key = f"{va}|{vb}"
    idx = edge_map.get(key)
    if idx is None:
        raise RuntimeError(f"edge not found for {a}-{b}")
    same_dir = (a == va) and (b == vb)
    return idx if same_dir else -(idx + 1)

def create_fram(fram_data: Dict[str, Any], *, parent_node_name: Optional[str], node_name: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    result['node_name'] = node_name
    result['parent_node_name'] = parent_node_name
    result['translation'] = fram_data['translation']
    result['scaling'] = fram_data['scaling']
    result['rotation'] = [r * RAD2DEG for r in fram_data['rotation']]
    result['node_type'] = 'fram'
    result['matrix'] = fram_data['matrix']
    result['rotate_pivot_translate'] = fram_data.get('rotate_pivot_translate', [0.0, 0.0, 0.0])
    result['rotate_pivot'] = fram_data.get('rotate_pivot', [0.0, 0.0, 0.0])

    result['scale_pivot_translate'] = fram_data.get('scale_pivot_translate', [0.0, 0.0, 0.0])
    result['scale_pivot'] = fram_data.get('scale_pivot', [0.0, 0.0, 0.0])

    result['has_rpivot'] = any(abs(x) > 1e-8 for x in result['rotate_pivot'])
    result['has_spivot'] = any(abs(x) > 1e-8 for x in result['scale_pivot'])
    
    result['shear'] = fram_data.get('shear', [0.0, 0.0, 0.0])

    base = node_name
    result['t_name'] = base + "_TCTL"
    result['r_name'] = base + "_RPIV"
    result['r_off_name'] = base + "_ROFF"
    result['s_name'] = base + "_SPIV"
    result['s_off_name'] = base + "_SOFF"
    result['anchor_name'] = base

    anim = animation_build_tracks_by_axis(fram_data.get('anim', {}))
    result['with_animation'] = bool(anim)
    result['animations'] = anim
    return result

def create_joint(fram_data: Dict[str, Any], *, parent_node_name: Optional[str], node_name: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    result['node_name'] = node_name
    result['parent_node_name'] = parent_node_name
    result['translation'] = fram_data['translation']
    result['scaling'] = fram_data['scaling']
    result['rotation'] = [r * RAD2DEG for r in fram_data['rotation']]
    result['node_type'] = 'joint'
    result['matrix'] = fram_data['matrix']
    result['rotation_matrix'] = fram_data['rotation_matrix']
    result['min_rot_limit'] = fram_data['min_rot_limit']
    result['max_rot_limit'] = fram_data['max_rot_limit']
    m3 = extract_3x3(result['rotation_matrix'])
    result['joint_orient'] = matrix_rowmajor_to_euler_xyz_standard(m3)  # градусы

    # имена контроллеров цепочки joint
    base = node_name
    result['t_name'] = base + "_TCTL"
    result['jbase_name'] = base + "_JBASE"
    result['janim_name'] = base + "_JANIM"
    result['anchor_name'] = base

    anim = animation_build_tracks_by_axis(fram_data.get('anim', {}))
    result['with_animation'] = bool(anim)
    result['animations'] = anim
    return result

def create_joint_chain(node, parent_obj: Optional[bpy.types.Object]):
    T  = tuple(node.get('translation', (0,0,0)))
    R0 = tuple(node.get('joint_orient', (0,0,0)))   # статичный orient (градусы)
    R1 = tuple(node.get('rotation', (0,0,0)))       # базовая локальная rotation (может быть 0)
    S  = tuple(node.get('scaling', (1,1,1)))

    t_name   = node['t_name']
    jbase_n  = node['jbase_name']
    janim_n  = node['janim_name']
    anchor_n = node['anchor_name']

    # 1) translation-контроллер
    tctl = create_empty(t_name, parent_obj, T, (0,0,0), (1,1,1), type='PLAIN_AXES')

    # 2) базовая ориентация сустава (joint orient) — статично
    jbase = create_empty(jbase_n, tctl, (0,0,0), R0, (1,1,1), type='ARROWS')

    # 3) узел, куда пишем rotation/scale (анимация)
    janim = create_empty(janim_n, jbase, (0,0,0), R1, S, type='ARROWS')

    # 4) конечная точка (узел, за который будут цепляться дети/меши)
    anchor = create_empty(anchor_n, janim, (0,0,0), (0,0,0), (1,1,1),
                          type='ARROWS')

    return {'T': tctl, 'J_BASE': jbase, 'R_ANIM': janim, 'ANCHOR': anchor}

def create_locator(_: Dict[str, Any], *, node_name: str, parent_node_name: Optional[str]) -> Dict[str, Any]:
    return {'node_type': 'locator', 'node_name': node_name, 'parent_node_name': parent_node_name}

def create_mesh(mesh_data: Dict[str, Any], *, node_name: str, parent_node_name: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {'node_type': 'mesh'}
    result['node_name'] = node_name
    result['parent_node_name'] = parent_node_name

    result['vrts'] = [[t[0], t[1], t[2]] for t in mesh_data['vbuf']]
    ibuf = [[tri[0], tri[1], tri[2]] for tri in mesh_data['ibuf']]

    ibuf = [[tri[0], tri[2], tri[1]] for tri in mesh_data['ibuf']] \
        if MeshGeom.mesh_right_handed(ibuf, mesh_data) \
        else [[tri[0], tri[1], tri[2]] for tri in mesh_data['ibuf']]
    result['ibuf'] = ibuf

    edge, face = build_edges_and_faces_signed(ibuf)
    result['edge'] = [e + [0] if len(e) == 2 else e for e in edge]
    result['face'] = face

    # UVs: приоритет — отдельный uvpt, иначе из vbuf[6:8]
    if 'uvpt' in mesh_data and mesh_data['uvpt']:
        uv_from = mesh_data['uvpt']
    else:
        uv_from = [[float((t[6] if len(t) > 6 else 0.0)),
                    float((t[7] if len(t) > 7 else 0.0))] for t in mesh_data['vbuf']]
    result['uvpt'] = [[float(u), float(v)] for (u, v) in uv_from]

    result['uv_index_of_vertex'] = list(range(len(result['vrts'])))

    materials_in = mesh_data.get('materials', []) or []
    materials_out = []
    for m in materials_in:
        mat_name = (m.get('name') or 'lambert') + f"_{result['node_name']}"
        a = float(m.get('alpha', 0.0))
        tex_path = m.get('texture', {}).get('name') if isinstance(m.get('texture'), dict) else None
        if tex_path:
            tex_path = tex_path.replace('\\', '/')
        materials_out.append({
            'mat_name': mat_name,
            'r': float(m.get('red', 0.8)),
            'g': float(m.get('green', 0.8)),
            'b': float(m.get('blue', 0.8)),
            'a': a,
            'repeatU': float(m.get('horizontal_stretch', 1)),
            'repeatV': float(m.get('vertical_stretch', 1)),
            'mirrorU': int(m.get('uv_mapping_flip_horizontal', 0)),
            'mirrorV': int(m.get('uv_mapping_flip_vertical', 0)),
            'rotateUV': float(m.get('rotate', 0)),
            'tex_path': tex_path,
            'has_tex': bool(tex_path),
        })
    if not materials_out:
        materials_out.append({
            'mat_name': f"lambert_{result['node_name']}",
            'r': 0.8, 'g': 0.8, 'b': 0.8, 'a': 0.0,
            'repeatU': 1.0, 'repeatV': 1.0, 'mirrorU': 0, 'mirrorV': 0, 'rotateUV': 0.0,
            'tex_path': None, 'has_tex': False,
        })
    result['materials'] = materials_out
    return result

# ---------------- Blender building ----------------

def ensure_collection(name: str) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if not col:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col

def to_euler_xyz_deg(vals):
    # Blender uses radians in data, but we'll set in degrees then convert
    return Euler((math.radians(vals[0]), math.radians(vals[1]), math.radians(vals[2])), 'XYZ')

def create_empty(name: str, parent: Optional[bpy.types.Object], loc, rot_deg, scl, type='PLAIN_AXES'):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = type
    obj.location = loc
    obj.rotation_mode = 'XYZ'
    obj.rotation_euler = to_euler_xyz_deg(rot_deg)
    obj.scale = scl
    if parent:
        obj.parent = parent
    bpy.context.collection.objects.link(obj)
    return obj

def create_transform_with_pivot(node, parent_obj: Optional[bpy.types.Object]):
    name = node['node_name']
    rp = tuple(node.get('rotate_pivot', (0.0, 0.0, 0.0)))
    rpt = tuple(node.get('rotate_pivot_translate', (0.0, 0.0, 0.0)))
    loc = tuple(node.get('translation', (0.0, 0.0, 0.0)))
    rot = tuple(node.get('rotation', (0.0, 0.0, 0.0)))
    scl = tuple(node.get('scaling', (1.0, 1.0, 1.0)))

    # Пивот-empty ставим в точку T + RpT + Rp (см. примечание ниже)
    pivot_loc = add_v(add_v(loc, rpt), rp)
    pivot = create_empty(node['pivot_object_name'], parent_obj, pivot_loc, rot, scl, type='ARROWS')

    # Сам узел/маркер смещаем на -Rp, без собственных поворотов/масштабов — они на пивоте
    child_loc = neg_v(rp)
    child = create_empty(name, pivot, child_loc, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0),
                         type=('ARROWS' if node['node_type'] == 'joint' else 'PLAIN_AXES'))
    return pivot, child

def create_mesh_object(node: Dict[str, Any], parent: Optional[bpy.types.Object]) -> bpy.types.Object:
    name = node['node_name']
    verts = [tuple(v) for v in node['vrts']]
    faces = [tuple(t) for t in node['ibuf']]

    me = bpy.data.meshes.new(name + "_Mesh")
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()

    # UV layer
    uv_data = node.get('uvpt', [])
    if uv_data:
        uv_layer = me.uv_layers.new(name="UVMap")
        # Assign per-loop UVs (triangles)
        for poly in me.polygons:
            for li, loop_idx in enumerate(range(poly.loop_start, poly.loop_start + poly.loop_total)):
                v_idx = me.loops[loop_idx].vertex_index
                u, v = uv_data[v_idx]
                # NMF v обычно снизу-вверх? Если нужно, инвертируйте v:
                uv_layer.data[loop_idx].uv = (u, 1.0 - v)

    # Materials
    for m in node.get('materials', []):
        mat = build_material(m)
        if mat and mat.name not in [x.name for x in me.materials]:
            me.materials.append(mat)

    obj = bpy.data.objects.new(name, me)
    if parent:
        obj.parent = parent
    bpy.context.collection.objects.link(obj)
    return obj

def build_material(mdef: Dict[str, Any]) -> Optional[bpy.types.Material]:
    mat = bpy.data.materials.new(mdef['mat_name'])
    mat.use_nodes = True
    nt = mat.node_tree
    for n in nt.nodes:
        nt.nodes.remove(n)
    # Nodes
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (-200, 0)
    out.location = (200, 0)
    nt.links.new(principled.outputs["BSDF"], out.inputs["Surface"])

    # Color/Alpha
    principled.inputs["Base Color"].default_value = (mdef['r'], mdef['g'], mdef['b'], 1.0)
    principled.inputs["Alpha"].default_value = max(0.0, min(1.0, 1.0 - mdef['a']))
    if mdef.get('a', 0.0) > 0.0:
        mat.blend_method = 'BLEND'
        # mat.shadow_method = 'HASHED'

    if mdef.get('has_tex'):
        tex_img = nt.nodes.new("ShaderNodeTexImage")
        tex_img.location = (-600, 100)
        # Try load image (may be missing; Blender will show warning)
        img_path = mdef.get('tex_path') or ""
        try:
            # If relative, try relative to current blend or to the nmf
            tex_img.image = bpy.data.images.load(img_path)
        except Exception:
            # leave empty image slot
            pass

        map_node = nt.nodes.new("ShaderNodeMapping")
        map_node.inputs['Scale'].default_value[0] = mdef.get('repeatU', 1.0) or 1.0
        map_node.inputs['Scale'].default_value[1] = mdef.get('repeatV', 1.0) or 1.0
        # rotateUV in degrees → radians, around Z
        map_node.inputs['Rotation'].default_value[2] = math.radians(float(mdef.get('rotateUV', 0.0)) or 0.0)

        tex_coord = nt.nodes.new("ShaderNodeTexCoord")

        # Mirror support is not native; approximated by negative scale
        if int(mdef.get('mirrorU', 0)) != 0:
            map_node.inputs['Scale'].default_value[0] *= -1.0
        if int(mdef.get('mirrorV', 0)) != 0:
            map_node.inputs['Scale'].default_value[1] *= -1.0

        # Links
        nt.links.new(tex_coord.outputs["UV"], map_node.inputs["Vector"])
        nt.links.new(map_node.outputs["Vector"], tex_img.inputs["Vector"])
        nt.links.new(tex_img.outputs["Color"], principled.inputs["Base Color"])
        # If image has alpha, plug it too
        nt.links.new(tex_img.outputs.get("Alpha"), principled.inputs["Alpha"])

    return mat

def apply_node_animation(obj: bpy.types.Object, anim: Dict[str, Any]):
    # anim: {"translation":{"x":{"frames":[], "values":[]}, ...}, "rotation":..., "scaling":...}
    if not anim:
        return
    obj.rotation_mode = 'XYZ'

    # Ensure scene fps = 24 (optional — won’t override user setting unless asked)
    # bpy.context.scene.render.fps = int(FPS)

    spec = {
        'translation': ('location', (0, 1, 2), 1.0),
        'rotation': ('rotation_euler', (0, 1, 2), math.pi/180.0),  # degrees → radians
        'scaling': ('scale', (0, 1, 2), 1.0),
    }

    for track, (prop, axes_idx, scale) in spec.items():
        tdata = anim.get(track)
        if not tdata:
            continue
        # axis order x,y,z
        for ax_name, ax_i in zip(('x','y','z'), axes_idx):
            ax = tdata.get(ax_name)
            if not ax:
                continue
            frames = ax.get('frames') or []
            values = ax.get('values') or []
            if not frames or not values or len(frames) != len(values):
                continue
            for f, v in zip(frames, values):
                # Set property component
                arr = getattr(obj, prop)
                arr[ax_i] = float(v) * scale
                obj.keyframe_insert(data_path=prop, index=ax_i, frame=int(round(f)))


def apply_node_animation_component(obj: bpy.types.Object, anim_part: Dict[str, Any]):
    # переиспользуем твою apply_node_animation, но подаём фрагмент (один трек)
    apply_node_animation(obj, anim_part)
# ---------------- import pipeline ----------------

def apply_node_animation_split(chain: Dict[str, bpy.types.Object], anim: Dict[str, Any]):
    # Определяем, chain это joint-цепочка или обычная
    is_joint = 'R_ANIM' in chain

    # Безопасно выбираем объекты-цели для каждого трека
    t_target = chain.get('T') or chain.get('R_ANIM') or chain.get('ANCHOR')
    r_target = (chain.get('R') if not is_joint else chain.get('R_ANIM')) or chain.get('ANCHOR')
    s_target = (chain.get('S') if not is_joint else chain.get('R_ANIM')) or chain.get('ANCHOR')

    # Применяем анимацию по имеющимся трекам
    if anim.get('translation') and t_target:
        apply_node_animation_component(t_target, {'translation': anim['translation']})

    if anim.get('rotation') and r_target:
        apply_node_animation_component(r_target, {'rotation': anim['rotation']})

    if anim.get('scaling') and s_target:
        apply_node_animation_component(s_target, {'scaling': anim['scaling']})


def build_scene_from_nodes(nodes: List[Dict[str, Any]]):
    name_to_obj: Dict[str, bpy.types.Object] = {}
    ctrls: Dict[str, Dict[str, bpy.types.Object]] = {}

    # Запомним, кто кому должен быть родителем (по именам), чтобы допривязать позже
    pending_parent: List[Tuple[str, str]] = []  # (child_root_name, parent_anchor_name)
    pending_mesh_parent: List[Tuple[str, str]] = []  # (mesh_name, parent_anchor_name)

    # 1) создаем трансформы / меши (родителя может еще не быть)
    for node in nodes:
        parent_name = node.get('parent_node_name')
        parent_obj = name_to_obj.get(parent_name) if parent_name else None
        nt = node['node_type']

        if nt == 'joint':
            chain = create_joint_chain(node, parent_obj)
            ctrls[node['node_name']] = chain
            name_to_obj[node['node_name']] = chain['ANCHOR']
            # если родителя пока нет — перепривяжем корень цепочки позже
            if parent_name and parent_obj is None:
                pending_parent.append((chain['T'].name, parent_name))

        elif nt in ('fram', 'locator'):
            chain = create_transform_chain(node, parent_obj)
            ctrls[node['node_name']] = chain
            name_to_obj[node['node_name']] = chain['ANCHOR']
            if parent_name and parent_obj is None:
                pending_parent.append((chain['T'].name, parent_name))

        elif nt == 'mesh':
            obj = create_mesh_object(node, parent_obj)
            name_to_obj[node['node_name']] = obj
            if parent_name and parent_obj is None:
                pending_mesh_parent.append((obj.name, parent_name))

    # 2) второй проход — выставляем родителей, когда они уже созданы
    for child_root_name, parent_anchor_name in pending_parent:
        parent_anchor = name_to_obj.get(parent_anchor_name)
        child_root = bpy.data.objects.get(child_root_name)
        if parent_anchor and child_root and child_root.parent is None:
            child_root.parent = parent_anchor

    for mesh_name, parent_anchor_name in pending_mesh_parent:
        parent_anchor = name_to_obj.get(parent_anchor_name)
        mesh_obj = bpy.data.objects.get(mesh_name)
        if parent_anchor and mesh_obj and mesh_obj.parent is None:
            mesh_obj.parent = parent_anchor

    # 3) Анимация — после того, как иерархия корректна
    for node in nodes:
        if not node.get('with_animation'):
            continue
        anim = node.get('animations', {})
        ch = ctrls.get(node['node_name'])
        if ch:
            apply_node_animation_split(ch, anim)
        else:
            # на всякий случай для старых узлов без цепочки
            obj = name_to_obj.get(node['node_name'])
            if obj:
                apply_node_animation(obj, anim)

# ---------------- glue: import operator ----------------

class IMPORT_OT_nmf(Operator, ImportHelper):
    bl_idname = "import_scene.nmf"
    bl_label = "Import NMF"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext: StringProperty(default=".nmf")
    filter_glob: StringProperty(default="*.nmf", options={'HIDDEN'})
    create_collection: BoolProperty(
        name="Put into Collection",
        default=True,
        description="Create a new collection named after the file"
    )

    def execute(self, context):
        nmf_path = self.filepath
        try:
            parser = Nmf()
            nodes_raw = parser.unpack(nmf_path)
            nodes = convert_nodes(nodes_raw)

            # optional collection
            target_layer = context.collection
            if self.create_collection:
                base = os.path.splitext(os.path.basename(nmf_path))[0]
                col = ensure_collection(f"NMF_{base}")
                # switch active collection to it during import
                with context.temp_override(collection=col):
                    build_scene_from_nodes(nodes)
            else:
                build_scene_from_nodes(nodes)

        except Exception as e:
            self.report({'ERROR'}, f"NMF import failed: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, "NMF import finished")
        return {'FINISHED'}

# ---------------- menu & register ----------------

def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_nmf.bl_idname, text="NMF (.nmf)")

classes = (IMPORT_OT_nmf,)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
