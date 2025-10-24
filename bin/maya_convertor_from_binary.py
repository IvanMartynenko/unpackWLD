#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import struct
import sys
from pprint import pprint
from typing import Any, Dict, List, Optional, Tuple

FPS = 24.0
DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi
MATRIX_SIZE = 16


# ---------------------- низкоуровневый парсер бинарника NMF ----------------------

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


# -------------------------------- геометрия/конвертер -------------------------------

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


def convert_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Адаптация под структуру из Nmf(): parent_id/index, word."""
    result = []
    index_map = {n["index"]: n for n in nodes}
    for node in nodes:
        unpacked_node = node["data"]
        node_name = node["name"]
        parent = index_map.get(node.get("parent_id"))
        parent_name = parent["name"] if parent else None
        if node.get("parent_id") == 1:
            parent_name = None

        w = node["word"]
        if w in ("ROOT", "FRAM"):
            result.append(create_fram(unpacked_node, node_name=node_name, parent_node_name=parent_name))
        elif w == "JOIN":
            result.append(create_joint(unpacked_node, node_name=node_name, parent_node_name=parent_name))
        elif w == "LOCA":
            result.append(create_locator(unpacked_node, node_name=node_name, parent_node_name=parent_name))
        elif w == "MESH":
            result.append(create_mesh(unpacked_node, node_name=node_name, parent_node_name=parent_name))
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
            key = f"{va}|#{vb}" if False else f"{va}|{vb}"
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
    result['shear'] = fram_data.get('shear', [0.0, 0.0, 0.0])
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
    result['joint_orient'] = matrix_rowmajor_to_euler_xyz_standard(m3)
    anim = animation_build_tracks_by_axis(fram_data.get('anim', {}))
    result['with_animation'] = bool(anim)
    result['animations'] = anim
    return result


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

    # UVs: в бинарнике есть отдельный uvpt; если нет — возьмём из vbuf[6:8]
    # if 'uvpt' in mesh_data and mesh_data['uvpt']:
    #     result['uvpt'] = [[float(u), float(v)] for (u, v) in mesh_data['uvpt']]
    # else:
    result['uvpt'] = [[float((t[6] if len(t) > 6 else 0.0)),
                       float((t[7] if len(t) > 7 else 0.0))] for t in mesh_data['vbuf']]

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
            'sg_name': f"{mat_name}SG",
            'r': float(m.get('red', 0.8)),
            'g': float(m.get('green', 0.8)),
            'b': float(m.get('blue', 0.8)),
            'a': a,
            't': a,
            'repeatU': int(m.get('horizontal_stretch', 1)),
            'repeatV': int(m.get('vertical_stretch', 1)),
            'mirrorU': int(m.get('uv_mapping_flip_horizontal', 0)),
            'mirrorV': int(m.get('uv_mapping_flip_vertical', 0)),
            'rotateUV': int(m.get('rotate', 0)),
            'tex_path': tex_path,
            'has_tex': bool(tex_path),
            'place2d_name': f"{mat_name}_place2d",
            'file_name': f"{mat_name}_file",
        })
    if not materials_out:
        # хотя бы один дефолтный материал
        mat_name = f"lambert_{result['node_name']}"
        materials_out.append({
            'mat_name': mat_name, 'sg_name': f"{mat_name}SG",
            'r': 0.8, 'g': 0.8, 'b': 0.8, 'a': 0.0, 't': 0.0,
            'repeatU': 1, 'repeatV': 1, 'mirrorU': 0, 'mirrorV': 0, 'rotateUV': 0,
            'tex_path': None, 'has_tex': False,
            'place2d_name': f"{mat_name}_place2d", 'file_name': f"{mat_name}_file",
        })
    result['materials'] = materials_out
    return result


def fmt_f(x: float) -> str:
    s = f"{float(x):.9f}".rstrip('0').rstrip('.')
    return s if s else "0"


def model_to_maya(nodes: List[Dict[str, Any]]) -> str:
    out: List[str] = []
    out.append('//Maya ASCII 2.5 scene')
    out.append('requires maya "2.5";')
    out.append('currentUnit -linear centimeter -angle degree -time film;')

    for node in nodes:
        nt = node['node_type']

        if nt == 'fram':
            out.append('')
            header = (f'createNode transform -name "{node["node_name"]}" -parent "{node["parent_node_name"]}";'
                      if node.get('parent_node_name') else
                      f'createNode transform -name "{node["node_name"]}";')
            out.append(header)
            out.append(f'\tsetAttr ".translate" -type "double3" {" ".join(map(str, node["translation"]))};')
            out.append(f'\tsetAttr ".rotate" -type "double3" {" ".join(map(str, node["rotation"]))};')
            out.append(f'\tsetAttr ".scale" -type "double3" {" ".join(map(str, node["scaling"]))};')
            out.append(f'\tsetAttr ".rotatePivotTranslate" -type "double3" {" ".join(map(str, node["rotate_pivot_translate"]))};')
            out.append(f'\tsetAttr ".rotatePivot" -type "double3" {" ".join(map(str, node["rotate_pivot"]))};')
            out.append(f'\tsetAttr ".scalePivotTranslate" -type "double3" {" ".join(map(str, node["scale_pivot_translate"]))};')
            out.append(f'\tsetAttr ".scalePivot" -type "double3" {" ".join(map(str, node["scale_pivot"]))};')
            out.append(f'\tsetAttr ".shear" -type "double3" {" ".join(map(str, node["shear"]))};')

        if nt == 'joint':
            out.append('')
            header = (f'createNode joint -name "{node["node_name"]}" -parent "{node["parent_node_name"]}";'
                      if node.get('parent_node_name') else
                      f'createNode joint -name "{node["node_name"]}";')
            out.append(header)
            out.append(f'\tsetAttr ".translate" -type "double3" {" ".join(map(str, node["translation"]))};')
            out.append(f'\tsetAttr ".rotate" -type "double3" {" ".join(map(str, node["rotation"]))};')
            out.append(f'\tsetAttr ".scale" -type "double3" {" ".join(map(str, node["scaling"]))};')
            jo = " ".join(f"{d:.6f}" for d in node['joint_orient'])
            out.append(f'\tsetAttr ".jointOrient" -type "double3" {jo};')
            out.append(f'\tsetAttr ".minRotLimit" -type "double3" {" ".join(map(str, node["min_rot_limit"]))};')
            out.append(f'\tsetAttr ".maxRotLimit" -type "double3" {" ".join(map(str, node["max_rot_limit"]))};')

        if node.get('with_animation'):
            out.append('')
            spec_map = {
                'translation': {'curve': 'animCurveTL', 'attrs': ['translateX', 'translateY', 'translateZ'], 'axes': ['x','y','z']},
                'rotation':    {'curve': 'animCurveTA', 'attrs': ['rotateX', 'rotateY', 'rotateZ'],       'axes': ['x','y','z']},
                'scaling':     {'curve': 'animCurveTU', 'attrs': ['scaleX', 'scaleY', 'scaleZ'],          'axes': ['x','y','z']},
            }
            for track, spec in spec_map.items():
                tdata = node['animations'].get(track)
                if not tdata:
                    continue
                for i, ax in enumerate(spec['axes']):
                    ax_data = tdata.get(ax)
                    if not ax_data:
                        continue
                    curve_name = f'{node["node_name"]}_{spec["attrs"][i]}'
                    frames = ax_data.get('frames')
                    values = ax_data.get('values')
                    if frames:
                        n = len(frames)
                        pairs = " ".join(f'{fmt_f(frames[i])} {fmt_f(values[i])}' for i in range(n))
                        out.append(f'createNode {spec["curve"]} -name "{curve_name}";')
                        out.append('\tsetAttr ".tangentType" 9;')
                        out.append('\tsetAttr ".weightedTangents" no;')
                        out.append(f'\tsetAttr -size {n} ".keyTimeValue[0:{n-1}]" {pairs};')
                    out.append(f'connectAttr "{curve_name}.output" "{node["node_name"]}.{spec["attrs"][i]}";')

        if nt == 'locator':
            out.append('')
            out.append(f'createNode locator -name "{node["node_name"]}" -parent "{node["parent_node_name"]}";')

        if nt == 'mesh':
            out.append('')
            line = (f'createNode mesh -name "{node["node_name"]}" -parent "{node["parent_node_name"]}";'
                    if node.get('parent_node_name') else
                    f'createNode mesh -name "{node["node_name"]}";')
            out.append(line)
            out.append('\tsetAttr -keyable off ".visibility";')
            out.append('\tsetAttr -size 2 ".instObjGroups[0].objectGroups";')
            out.append('\tsetAttr ".opposite" yes;')
            out.append('\tsetAttr ".instObjGroups[0].objectGroups[0].objectGrpCompList" -type "componentList" 0;')
            out.append(f'\tsetAttr ".instObjGroups[0].objectGroups[1].objectGrpCompList" -type "componentList" 1 "f[0:{len(node["face"]) - 1}]";')

            vrts_payload = "\t\t" + "\t".join(f'{float(x)} {float(y)} {float(z)}' for x,y,z in node['vrts']) + ';'
            out.append(f'\tsetAttr -size {len(node["vrts"])} ".vrts[0:{len(node["vrts"]) - 1}]"  {vrts_payload}')
            edge_payload = "\t\t" + "\t".join(f'{x} {y} {z}' for x,y,z in node['edge']) + ';'
            out.append(f'\tsetAttr -size {len(node["edge"])} ".edge[0:{len(node["edge"]) - 1}]"  {edge_payload}')

            pair_strings = [f'{u} {v}' for u, v in node['uvpt']]
            uv_chunks = ["   ".join(pair_strings[i:i+6]) for i in range(0, len(pair_strings), 6)]
            uv_payload = "\t\t" + " \t".join(uv_chunks) + ';'
            out.append(f'\tsetAttr -size {len(node["uvpt"])} ".uvpt[0:{len(node["uvpt"]) - 1}]" -type "float2" {uv_payload}')

            face_lines = []
            for i, edges_triplet in enumerate(node['face']):
                f_part = f'f 3 {" ".join(map(str, edges_triplet))}'
                tri = node['ibuf'][i]
                uv_idx = [node['uv_index_of_vertex'][v] for v in tri]
                mf_part = f'mf 3 {" ".join(map(str, uv_idx))}'
                face_lines.append(f'\t\t{f_part}   {mf_part}')
            out.append(f'\tsetAttr -size {len(node["face"])} ".face[0:{len(node["face"]) - 1}]" -type "polyFaces"\n' +
                       " \n".join(face_lines) + ';')

            out.append('')
            for material in node['materials']:
                out.append(f'createNode lambert -name "{material["mat_name"]}";')
                out.append(f'\tsetAttr ".color" -type "float3" {material["r"]} {material["g"]} {material["b"]} ;')
                out.append(f'\tsetAttr ".transparency" -type "float3" {material["t"]} {material["t"]} {material["t"]} ;')
                out.append('\tsetAttr ".diffuse" 1;')
                out.append('\tsetAttr ".translucence" 0;')
                out.append('\tsetAttr ".ambientColor" -type "float3" 0 0 0;')

                out.append(f'createNode shadingEngine -name "{material["sg_name"]}";')
                out.append('\tsetAttr ".ihi" 0;')
                out.append(f'connectAttr "{material["mat_name"]}.outColor" "{material["sg_name"]}.surfaceShader";')

                if material['has_tex']:
                    out.append(f'createNode place2dTexture -name "{material["place2d_name"]}";')
                    out.append(f'\tsetAttr ".repeatU" {material["repeatU"]};')
                    out.append(f'\tsetAttr ".repeatV" {material["repeatV"]};')
                    out.append(f'\tsetAttr ".rotateUV" {material["rotateUV"]};')

                    out.append(f'createNode file -name "{material["file_name"]}";')
                    out.append(f'\tsetAttr ".fileTextureName" -type "string" "{material["tex_path"]}";')

                    out.append(f'connectAttr "{material["place2d_name"]}.coverage"           "{material["file_name"]}.coverage";')
                    out.append(f'connectAttr "{material["place2d_name"]}.translateFrame"     "{material["file_name"]}.translateFrame";')
                    out.append(f'connectAttr "{material["place2d_name"]}.rotateFrame"        "{material["file_name"]}.rotateFrame";')
                    out.append(f'connectAttr "{material["place2d_name"]}.repeatUV"           "{material["file_name"]}.repeatUV";')
                    out.append(f'connectAttr "{material["place2d_name"]}.offset"             "{material["file_name"]}.offset";')
                    out.append(f'connectAttr "{material["place2d_name"]}.rotateUV"           "{material["file_name"]}.rotateUV";')
                    out.append(f'connectAttr "{material["place2d_name"]}.outUV"              "{material["file_name"]}.uvCoord";')

                    out.append(f'connectAttr "{material["file_name"]}.outColor"         "{material["mat_name"]}.color";')

                out.append(f'connectAttr "{node["node_name"]}.instObjGroups" "{material["sg_name"]}.dagSetMembers" -nextAvailable;')

    return "\n".join(out)


# ------------------------------------ CLI ------------------------------------

def main(argv: List[str]) -> int:
    if len(argv) < 3:
        sys.stderr.write(f"Usage: python {argv[0]} input.nmf output.ma\n")
        return 1
    input_path, output_path = argv[1], argv[2]

    # читаем БИНАРНЫЙ .nmf
    parser = Nmf()
    nodes_raw = parser.unpack(input_path)

    # конверсия -> maya
    scene = model_to_maya(convert_nodes(nodes_raw))

    with open(output_path, 'w', encoding='utf-8') as io:
        io.write(scene)

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
