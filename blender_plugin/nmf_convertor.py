# -*- coding: utf-8 -*-

"""
NMF Converter

Description:
    Processes raw NMF node data into a format suitable for Blender.
    - Handles coordinate system conversion (DirectX to Blender).
    - Calculates geometry data (edges, faces, normals).
    - Optimizes the hierarchy by baking static transforms into meshes.
    - converting materials and texture paths.

License: MIT License
"""

import os
import math

class EdgesFaces:
    @staticmethod
    def build(tris):
        edge_map = {}
        edges = []
        for a, b, c in tris:
            for u, v in ((a, b), (b, c), (c, a)):
                va, vb = (u, v) if u <= v else (v, u)
                key = f"{va}|{vb}"
                if key not in edge_map:
                    edge_map[key] = len(edges)
                    edges.append([va, vb])
        faces_signed = []
        for a, b, c in tris:
            e0 = EdgesFaces.signed_edge_index(edge_map, a, b)
            e1 = EdgesFaces.signed_edge_index(edge_map, b, c)
            e2 = EdgesFaces.signed_edge_index(edge_map, c, a)
            faces_signed.append([e0, e1, e2])
        return edges, faces_signed

    @staticmethod
    def signed_edge_index(edge_map, a, b):
        va, vb = (a, b) if a <= b else (b, a)
        key = f"{va}|{vb}"
        idx = edge_map.get(key)
        if idx is None:
            raise RuntimeError(f"edge not found for {a}-{b}")
        same_dir = (a == va) and (b == vb)
        return idx if same_dir else -(idx + 1)


class MeshGeom:
    EPS = 1e-8

    @staticmethod
    def normalize(v):
        l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        if l < MeshGeom.EPS:
            return [0.0, 0.0, 0.0]
        return [v[0] / l, v[1] / l, v[2] / l]

    @staticmethod
    def sub(a, b):
        return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]

    @staticmethod
    def cross(a, b):
        return [
            (a[1] * b[2]) - (a[2] * b[1]),
            (a[2] * b[0]) - (a[0] * b[2]),
            (a[0] * b[1]) - (a[1] * b[0]),
        ]

    @staticmethod
    def dot(a, b):
        return (a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2])

    @staticmethod
    def pos_of(row):
        return row[0:3]

    @staticmethod
    def nrm_of(row):
        return row[3:6]

    @staticmethod
    def mesh_right_handed(ibuf, mesh_data):
        vbuf = mesh_data["vertices"]
        pos = [MeshGeom.pos_of(r) for r in vbuf]
        nrm = [MeshGeom.nrm_of(r) for r in vbuf]
        pos_cnt = 0
        neg_cnt = 0
        for i0, i1, i2 in ibuf:
            p0, p1, p2 = pos[i0], pos[i1], pos[i2]
            n_geom = MeshGeom.normalize(
                MeshGeom.cross(MeshGeom.sub(p1, p0), MeshGeom.sub(p2, p0))
            )
            n_avg = MeshGeom.normalize(
                [
                    nrm[i0][0] + nrm[i1][0] + nrm[i2][0],
                    nrm[i0][1] + nrm[i1][1] + nrm[i2][1],
                    nrm[i0][2] + nrm[i1][2] + nrm[i2][2],
                ]
            )
            s = MeshGeom.dot(n_geom, n_avg)
            if s >= 0:
                pos_cnt += 1
            else:
                neg_cnt += 1
        return pos_cnt >= neg_cnt


def _collapse_single_mesh_transforms(nodes):
    def _apply_matrix_to_point(M, p):
        x, y, z = p
        return [
            M[0][0] * x + M[0][1] * y + M[0][2] * z + M[0][3],
            M[1][0] * x + M[1][1] * y + M[1][2] * z + M[1][3],
            M[2][0] * x + M[2][1] * y + M[2][2] * z + M[2][3],
        ]

    """
    If a transform has exactly one mesh child and no other children/animation,
    bake the matrix into the mesh vertices and remove the transform node.
    """
    # Index by ID for convenience
    id_to_node = {n["id"]: n for n in nodes if "id" in n}

    # Map parent_id -> list of children
    children_map = {}
    for n in nodes:
        pid = n.get("parent_id")
        if pid is None:
            continue
        children_map.setdefault(pid, []).append(n)

    to_remove_ids = set()

    for n in nodes:
        if n.get("type") != "transform":
            continue

        # Do not touch if animation exists
        if "animation" in n and n["animation"]:
            continue

        nid = n["id"]
        childs = children_map.get(nid, [])

        if not childs:
            continue

        mesh_children = [c for c in childs if c.get("type") == "mesh"]
        other_children = [c for c in childs if c.get("type") != "mesh"]

        # Exactly one mesh and no other children
        if len(mesh_children) == 1 and not other_children:
            mesh = mesh_children[0]

            M = n.get("matrix")
            if M is None:
                continue  # Just in case

            # Bake matrix into vertices
            vrts = mesh.get("vrts")
            if vrts:
                mesh["vrts"] = [_apply_matrix_to_point(M, v) for v in vrts]

            # Move mesh's parent_id to transform's parent
            mesh["parent_id"] = n.get("parent_id")

            # Mark transform for removal
            to_remove_ids.add(nid)

    # Return new list without removed transforms
    return [n for n in nodes if not ("id" in n and n["id"] in to_remove_ids)]


def _dx_to_blender_matrix(dx_m):
    return [[dx_m[j][i] for j in range(4)] for i in range(4)]


def _make_translation_matrix(v):
    x, y, z = v
    return [
        [1.0, 0.0, 0.0, x],
        [0.0, 1.0, 0.0, y],
        [0.0, 0.0, 1.0, z],
        [0.0, 0.0, 0.0, 1.0],
    ]


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


def _get_rotation_degrees(rot):
    print("rot", rot)
    table = {
        0: 0.0,
        1: math.radians(-90),
        2: math.radians(-180),
        3: math.radians(-270),
    }
    return table.get(rot, 0)


def convert_and_filter_nodes(nodes, filepath):
    new_nodes = []
    transform_new_id = -1

    for node in nodes:
        if node["type"] == "ROOT":
            base_matrix = _dx_to_blender_matrix(node["payload"]["local_matrix"])

            # --- ADD MIRROR ONLY FOR ROOT ---
            S = [
                [1, 0, 0, 0],
                [0, 0, 1, 0],
                [0, 1, 0, 0],
                [0, 0, 0, 1],
            ]

            # Multiply S * base_matrix
            M2 = _mat_mul(S, base_matrix)
            new_nodes.append(
                {
                    "type": "transform",
                    "name": node["name"],
                    "id": node["index"],
                    "parent_id": node.get("parent"),
                    "matrix": M2,
                }
            )
        if node["type"] == "FRAM":
            if node["payload"].get("animation"):
                matrix = _dx_to_blender_matrix(node["payload"]["local_matrix"])
                pivot_bl = node["payload"]["scale_pivot"]

                parent_matrix = _mat_mul(matrix, _make_translation_matrix(pivot_bl))
                pivot_matrix = _make_translation_matrix([-1 * j for j in pivot_bl])

                id = transform_new_id
                transform_new_id -= 1
                new_nodes.append(
                    {
                        "type": "transform",
                        "name": node["name"],
                        "id": id,
                        "parent_id": node.get("parent"),
                        "matrix": parent_matrix,
                        "animation": node["payload"].get("animation"),
                    }
                )
                new_nodes.append(
                    {
                        "type": "transform",
                        "name": node["name"] + "_PIVOT",
                        "id": node["index"],
                        "parent_id": id,
                        "matrix": pivot_matrix,
                    }
                )
            else:
                new_nodes.append(
                    {
                        "type": "transform",
                        "name": node["name"],
                        "id": node["index"],
                        "parent_id": node.get("parent"),
                        "matrix": _dx_to_blender_matrix(node["payload"]["local_matrix"]),
                    }
                )
        if node["type"] == "JOIN":
            if node["payload"].get("animation"):
                id = transform_new_id
                transform_new_id -= 1

                matrix = _dx_to_blender_matrix(node["payload"]["local_matrix"])
                new_nodes.append(
                    {
                        "type": "transform",
                        "name": node["name"],
                        "id": id,
                        "parent_id": node.get("parent"),
                        "matrix": matrix,
                    }
                )

                rot_bl = node["payload"]["joint_orient_matrix"]
                new_nodes.append(
                    {
                        "type": "transform",
                        "name": node["name"] + "_ROT",
                        "id": node["index"],
                        "parent_id": id,
                        "matrix": rot_bl,
                        "animation": node["payload"].get("animation"),
                    }
                )
            else:
                new_nodes.append(
                    {
                        "type": "transform",
                        "name": node["name"],
                        "id": node["index"],
                        "parent_id": node.get("parent"),
                        "matrix": _dx_to_blender_matrix(node["payload"]["local_matrix"]),
                    }
                )
        if node["type"] == "LOCA":
            new_nodes.append(
                {
                    "type": "empty",
                    "name": node["name"],
                    "id": node["index"],
                    "parent_id": node.get("parent"),
                }
            )
        if node["type"] == "MESH":
            mesh_data = node["payload"]
            vrts = [[t[0], t[1], t[2]] for t in mesh_data["vertices"]]
            ibuf = [[tri[0], tri[1], tri[2]] for tri in mesh_data["indices"]]
            if MeshGeom.mesh_right_handed(ibuf, mesh_data):
                ibuf = [[tri[0], tri[2], tri[1]] for tri in mesh_data["indices"]]

            edge, face = EdgesFaces.build(ibuf)
            edge = [e + [0] if len(e) == 2 else e for e in edge]

            materials_in = mesh_data.get("materials", []) or []
            materials_out = []

            for m in materials_in:
                if "vertex_offset" in m:
                    min_vertex = m["vertex_offset"]    # Сдвиг вершин (BaseVertexIndex)
                    start_index = m.get("index_offset", 0)   # Откуда начинаются индексы этого куска
                    num_indices = m.get("index_count", 0)    # Сколько всего индексов в куске

                    start_face = start_index // 3
                    num_faces = num_indices // 3
                    
                    for f_idx in range(start_face, start_face + num_faces):
                        if f_idx < len(ibuf):
                            ibuf[f_idx][0] += min_vertex
                            ibuf[f_idx][1] += min_vertex
                            ibuf[f_idx][2] += min_vertex

            for m in materials_in:
                mat_name = (m.get("name") or "lambert") + f"_{node['name']}"
                nmf_dir = os.path.dirname(filepath)
                tex_info = m.get("texture")
                tex_path = None

            # Указываем нужную директорию для сохранения
            output_dir = "/home/iwan/Source/output_textures/Textures/"
            if isinstance(tex_info, dict):
                # 1. Get name
                raw_name = tex_info.get("name")
                if raw_name:
                    # Извлекаем имя файла, игнорируя пути Windows (\) и Linux (/)
                    fname = raw_name.replace("\\", "/").split("/")[-1]
                    root, _ = os.path.splitext(fname)
                    page = tex_info.get("page", 0)

                    base = f"{root}_{page}.dds"

                    # Собираем путь с новой директорией
                    tex_path = os.path.join(output_dir, base)



                # Читаем исходные значения из словаря (предполагаем, что там 1 или 0, либо True/False)
                flip_u = bool(m.get("uv_flip_u", 0))
                flip_v = bool(m.get("uv_flip_v", 0))

                diffuse = m.get("diffuse", [0.8, 0.8, 0.8, 1.0])
                materials_out.append(
                    {
                        "mat_name": mat_name,
                        "r": diffuse[0] if len(diffuse) > 0 else 0.8,
                        "g": diffuse[1] if len(diffuse) > 1 else 0.8,
                        "b": diffuse[2] if len(diffuse) > 2 else 0.8,
                        "a": diffuse[3] if len(diffuse) > 3 else 1.0,
                        "repeatU": m["uv_scale_u"],
                        "repeatV": m["uv_scale_v"],

                        # Инвертируем флаг V! (Если в игре 0, то в Blender будет True)
                        "mirrorV": not flip_v,

                        # Для U обычно инверсия не нужна, но если текстуры будут отзеркалены по горизонтали,
                        # попробуйте сделать "mirrorU": not flip_u
                        "mirrorU": flip_u,

                        "rotateUV": _get_rotation_degrees(m["uv_rotation"]),
                        "tex_path": tex_path,
                        "has_tex": bool(tex_path),
                        "blend_mode": m["blend_mode"],
                        "unknown_ints": [
                            m.get("vertex_offset", 0),
                            m.get("vertex_count", 0),
                            m.get("index_offset", 0),
                            m.get("index_count", 0),
                        ],
                    }
                )
                print("materials_out:", materials_out)

            new_nodes.append(
                {
                    "type": "mesh",
                    "name": node["name"],
                    "id": node["index"],
                    "parent_id": node.get("parent"),
                    "vrts": vrts,
                    "ibuf": ibuf,
                    "edge": edge,
                    "face": face,
                    "uvpt": mesh_data["source_uv"],
                    "uv_index_of_vertex": list(range(len(vrts))),
                    "flip_normals": bool(mesh_data["inside"]),
                    "backface_culling": bool(mesh_data["backface_culling"]),
                    "smooth_shading": bool(mesh_data["smooth"]),
                    "light_flare": bool(mesh_data["light_flare"]),
                    "materials": materials_out,
                }
            )

    # new_nodes = _collapse_single_mesh_transforms(new_nodes)
    return new_nodes
