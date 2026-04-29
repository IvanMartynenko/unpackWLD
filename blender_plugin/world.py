# -*- coding: utf-8 -*-

"""
NMF Parser (Neo Model Format)

Description:
    Parses .nmf files used in "Der Clou! 2" (The Sting!).
    These files contain hierarchical 3D model data, including:
    - Transform (FRAM)
    - Skeletons/Bones (JOIN)
    - Meshes (MESH) and Materials (MTRL)
    - Animation data (ANIM)
    - Locators (LOCA)

    The parser reads the structure into a list of dictionaries representing
    the scene graph nodes.

License: MIT License
"""

import struct
import math

MATRIX_SIZE = 16


def read_aligned_string(f):
    """Reads a null-terminated string padded to 4-byte boundaries."""
    bytes_list = []
    while True:
        b = f.read(1)
        if not b:
            break
        if b == b"\x00":
            break
        bytes_list.append(b)
    raw = b"".join(bytes_list)
    name = raw.decode("windows-1252", errors="ignore")
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
                raise RuntimeError(
                    f"Bad start of ModelList. Expected 'NMF ' but got '{token}'"
                )
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

                model.append(
                    {
                        "word": token,
                        "name": name,
                        "parent_id": parent_id,
                        "data": data,
                        "index": index,
                    }
                )
                index += 1
        return model

    def _parse_fram(self, f):
        res = {}
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]
        for key in [
            "translation",
            "scaling",
            "rotation",
            "rotate_pivot_translate",
            "rotate_pivot",
            "scale_pivot_translate",
            "scale_pivot",
            "shear",
        ]:
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
        res["matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]
        for key in ["translation", "scaling", "rotation"]:
            res[key] = list(struct.unpack("<3f", f.read(12)))
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["rotation_matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]
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
                cur["keys"]["x"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["x"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
            n = axis_sizes[1]
            if n > 0:
                cur["keys"]["y"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["y"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
            n = axis_sizes[2]
            if n > 0:
                cur["keys"]["z"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["z"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
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

        vbuf_flat = list(
            struct.unpack(f"<{vbuf_count_float}f", f.read(4 * vbuf_count_float))
        )
        raw_vbuf = [
            vbuf_flat[i : i + vbuf_count] for i in range(0, len(vbuf_flat), vbuf_count)
        ]
        for v in raw_vbuf:
            # Check normal X, Y, Z components
            if math.isnan(v[3]) or math.isnan(v[4]) or math.isnan(v[5]):
                # Replace with a safe "up" vector (0, 1, 0)
                v[3] = 0.0
                v[4] = 1.0
                v[5] = 0.0
        res["vbuf"] = raw_vbuf

        uv_flat = list(
            struct.unpack(f"<{uvbuf_count_float}f", f.read(4 * uvbuf_count_float))
        )
        res["uvpt"] = [
            uv_flat[i : i + uvbuf_count] for i in range(0, len(uv_flat), uvbuf_count)
        ]

        res["inum"] = struct.unpack("<i", f.read(4))[0]
        ibuf_flat = list(struct.unpack(f"<{res['inum']}h", f.read(2 * res["inum"])))
        res["ibuf"] = [ibuf_flat[i : i + 3] for i in range(0, len(ibuf_flat), 3)]

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
            res["collision_vertices"] = list(struct.unpack(f"<{cnt}f", f.read(4 * cnt)))
        unknown_count_of_ints = struct.unpack("<i", f.read(4))[0]
        if unknown_count_of_ints > 0:
            res["collision_indices"] = list(
                struct.unpack(
                    f"<{unknown_count_of_ints}i", f.read(4 * unknown_count_of_ints)
                )
            )
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
        vbuf = mesh_data["vbuf"]
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
    table = {
        0: 0.0,
        1: math.radians(90),
        2: math.radians(180),
        3: math.radians(270),
    }
    return table.get(rot, 0)


def convert_and_filter_nodes(nodes, filepath):
    new_nodes = []
    transform_new_id = -1

    for node in nodes:
        if node["word"] == "ROOT":
            base_matrix = _dx_to_blender_matrix(node["data"]["matrix"])

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
                    "parent_id": node["parent_id"],
                    "matrix": M2,
                }
            )
        if node["word"] == "FRAM":
            if node["data"].get("anim"):
                matrix = _dx_to_blender_matrix(node["data"]["matrix"])
                pivot_bl = node["data"]["scale_pivot"]

                parent_matrix = _mat_mul(matrix, _make_translation_matrix(pivot_bl))
                pivot_matrix = _make_translation_matrix([-1 * j for j in pivot_bl])

                id = transform_new_id
                transform_new_id -= 1
                new_nodes.append(
                    {
                        "type": "transform",
                        "name": node["name"],
                        "id": id,
                        "parent_id": node["parent_id"],
                        "matrix": parent_matrix,
                        "animation": node["data"].get("anim"),
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
                        "parent_id": node["parent_id"],
                        "matrix": _dx_to_blender_matrix(node["data"]["matrix"]),
                    }
                )
        if node["word"] == "JOIN":
            id = transform_new_id
            transform_new_id -= 1

            matrix = _dx_to_blender_matrix(node["data"]["matrix"])
            new_nodes.append(
                {
                    "type": "transform",
                    "name": node["name"],
                    "id": id,
                    "parent_id": node["parent_id"],
                    "matrix": matrix,
                }
            )

            rot_bl = node["data"]["rotation_matrix"]
            new_nodes.append(
                {
                    "type": "transform",
                    "name": node["name"] + "_ROT",
                    "id": node["index"],
                    "parent_id": id,
                    "matrix": rot_bl,
                    "animation": node["data"].get("anim"),
                }
            )
        if node["word"] == "LOCA":
            new_nodes.append(
                {
                    "type": "empty",
                    "name": node["name"],
                    "id": node["index"],
                    "parent_id": node["parent_id"],
                }
            )
        if node["word"] == "MESH":
            mesh_data = node["data"]
            vrts = [[t[0], t[1], t[2]] for t in mesh_data["vbuf"]]
            ibuf = [[tri[0], tri[1], tri[2]] for tri in mesh_data["ibuf"]]
            if MeshGeom.mesh_right_handed(ibuf, mesh_data):
                ibuf = [[tri[0], tri[1], tri[2]] for tri in mesh_data["ibuf"]]

            edge, face = EdgesFaces.build(ibuf)
            edge = [e + [0] if len(e) == 2 else e for e in edge]

            materials_in = mesh_data.get("materials", []) or []
            materials_out = []
            for m in materials_in:
                mat_name = (m.get("name") or "lambert") + f"_{node['name']}"
                nmf_dir = os.path.dirname(filepath)
                tex_info = m.get("texture")
                tex_path = None

                if isinstance(tex_info, dict):
                    # 1. Get name
                    raw_name = tex_info.get("name")
                    if raw_name:
                        fname = raw_name.replace("\\", "/").split("/")[-1]
                        root, _ = os.path.splitext(fname)
                        page = tex_info.get("texture_page")

                        base = f"{root}_{page}.dds"
                        tex_path = os.path.join(nmf_dir, base)

                materials_out.append(
                    {
                        "mat_name": mat_name,
                        "r": m["red"] / 255.0,
                        "g": m["green"] / 255.0,
                        "b": m["blue"] / 255.0,
                        "a": m["alpha"],
                        "repeatU": m["vertical_stretch"],
                        "repeatV": m["horizontal_stretch"],
                        "mirrorU": m["uv_mapping_flip_vertical"],
                        "mirrorV": m["uv_mapping_flip_horizontal"],
                        "rotateUV": _get_rotation_degrees(m["rotate"]),
                        "tex_path": tex_path,
                        "has_tex": bool(tex_path),
                        "blend_mode": m["blend_mode"],
                    }
                )

            new_nodes.append(
                {
                    "type": "mesh",
                    "name": node["name"],
                    "id": node["index"],
                    "parent_id": node["parent_id"],
                    "vrts": vrts,
                    "ibuf": ibuf,
                    "edge": edge,
                    "face": face,
                    "uvpt": mesh_data["uvpt"],
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
# -*- coding: utf-8 -*-

"""
Import NMF

Description:
    Core logic for importing NMF data into the Blender scene.
    - Creates Materials with Principled BSDF nodes.
    - Imports Textures and configures UV mapping.
    - Builds the Scene Graph (Objects, Meshes, Empties).
    - Applies Animation tracks.

License: MIT License
"""

import bpy
import math
from mathutils import Matrix
#from .nmf_parser import Nmf
#from .nmf_convertor import convert_and_filter_nodes


# ------------------------------------------------------------------------
# Materials
# ------------------------------------------------------------------------


def _create_material_from_nmf(mat_info):
    """
    mat_info:
        {
            "mat_name": str,
            "r": float, "g": float, "b": float, "a": float,
            "repeatU": float, "repeatV": float,
            "mirrorU": int, "mirrorV": int,
            "rotateUV": float,
            "tex_path": str | None,
            "has_tex": bool,
        }
    """
    name = mat_info.get("mat_name", "NMF_Material")

    # mat = bpy.data.materials.get(name)
    # if mat is None:
    mat = bpy.data.materials.new(name)

    # Enable nodes in new Blender versions, ignore in old ones
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        # Look for existing Principled BSDF
        bsdf = None
        for n in nodes:
            if n.type == "BSDF_PRINCIPLED":
                bsdf = n
                break

        # If missing — create simple tree: BSDF -> Output
        if bsdf is None:
            nodes.clear()
            out = nodes.new("ShaderNodeOutputMaterial")
            out.location = (400, 0)

            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.location = (0, 0)

            links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    else:
        # Old Blender Internal — no nodes, exit immediately
        return mat

    # -------- Color / Alpha --------
    r = mat_info["r"]
    g = float(mat_info.get("g", 1.0))
    b = float(mat_info.get("b", 1.0))
    a_src = float(mat_info.get("a", 1.0))

    # If alpha = transparency instead of opacity, you can invert:
    # a = 1.0 - a_src
    a = a_src

    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Alpha"].default_value = a

    # Transparency - only if Blender supports it
    mode = mat_info.get("blend_mode", 0)
    if mode == 0:  # decal
        if hasattr(mat, "blend_method"):
            mat.blend_method = "OPAQUE"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "OPAQUE"

    elif mode == 1:  # alpha
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "HASHED"

    elif mode == 2:  # additive
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "NONE"
        # Additive effect needs node setup: MixRGB(Add)

    elif mode == 3:  # multiply
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "HASHED"
        # Multiply is done in nodes (MixRGB(Multiply))

    # -------- Texture / UV --------
    tex_path = mat_info.get("tex_path")
    has_tex = bool(mat_info.get("has_tex") and tex_path)

    if has_tex:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # UV Map
        uv_node = None
        for n in nodes:
            if n.type == "UVMAP":
                uv_node = n
                break
        if uv_node is None:
            uv_node = nodes.new("ShaderNodeUVMap")
            uv_node.location = (-800, 0)
            uv_node.uv_map = "UVMap"

        # Mapping
        mapping_node = None
        for n in nodes:
            if n.type == "MAPPING":
                mapping_node = n
                break
        if mapping_node is None:
            mapping_node = nodes.new("ShaderNodeMapping")
            mapping_node.location = (-600, 0)

        # Image Texture
        tex_node = None
        for n in nodes:
            if n.type == "TEX_IMAGE":
                tex_node = n
                break
        if tex_node is None:
            tex_node = nodes.new("ShaderNodeTexImage")
            tex_node.location = (-400, 0)

        # Try to load image
        image = None
        try:
            image = bpy.data.images.load(tex_path)
        except Exception:
            image = None

        if image is not None:
            tex_node.image = image

        # Repeats / mirrors / rotation
        repeatU = float(mat_info.get("repeatU", 1.0))
        repeatV = float(mat_info.get("repeatV", 1.0))
        mirrorU = int(mat_info.get("mirrorU", 0))
        mirrorV = int(mat_info.get("mirrorV", 0))
        rotateUV = float(mat_info.get("rotateUV", 0.0))

        # if rotateUV is in degrees:
        # rotate = math.radians(rotateUV)
        rotate = rotateUV

        scale_x = repeatU * (-1.0 if mirrorU else 1.0)
        scale_y = repeatV * (-1.0 if mirrorV else 1.0)

        mapping_node.inputs["Scale"].default_value[0] = scale_x
        mapping_node.inputs["Scale"].default_value[1] = scale_y
        mapping_node.inputs["Scale"].default_value[2] = 1.0

        mapping_node.inputs["Rotation"].default_value[0] = 0.0
        mapping_node.inputs["Rotation"].default_value[1] = 0.0
        mapping_node.inputs["Rotation"].default_value[2] = rotate

        # Helper function for linking without duplicates
        def safe_link(src, dst):
            if src is None or dst is None:
                return
            for link in dst.links:
                if link.from_socket == src:
                    return
            links.new(src, dst)

        safe_link(uv_node.outputs.get("UV"), mapping_node.inputs.get("Vector"))
        safe_link(mapping_node.outputs.get("Vector"), tex_node.inputs.get("Vector"))
        safe_link(tex_node.outputs.get("Color"), bsdf.inputs.get("Base Color"))
        safe_link(tex_node.outputs.get("Alpha"), bsdf.inputs.get("Alpha"))

        # Texture transparency - only if attributes exist
        # if hasattr(mat, "blend_method"):
        #     mat.blend_method = "BLEND"
        # if hasattr(mat, "shadow_method"):
        #     mat.shadow_method = "HASHED"

    return mat


def _apply_anim_to_object(obj, anim_tracks):
    """
    Writes keys directly to the object:
      translation -> location
      rotation    -> rotation_euler (XYZ, rad)
      scaling     -> scale
    """
    if not anim_tracks:
        return

    obj.rotation_mode = "XYZ"
    fps = bpy.context.scene.render.fps  # e.g., 24

    spec = {
        "translation": ("location", (0, 1, 2), 1.0),
        "rotation": ("rotation_euler", (0, 1, 2), 1.0),  # already in radians
        "scaling": ("scale", (0, 1, 2), 1.0),
    }

    for track, (prop, idxs, scale) in spec.items():
        track_data = anim_tracks.get(track)
        if not track_data:
            continue

        values = track_data.get("values", {})
        keys = track_data.get("keys", {})

        for ax_name, ax_i in zip(("x", "y", "z"), idxs):
            vals = values.get(ax_name)
            frames = keys.get(ax_name)
            if not vals or not frames:
                continue

            for t, v in zip(frames, vals):
                frame = int(round(t * fps))  # <--- KEY CHANGE
                arr = getattr(obj, prop)
                arr[ax_i] = float(v) * scale
                obj.keyframe_insert(
                    data_path=prop,
                    index=ax_i,
                    frame=frame,
                )


def _parent_objects_by_ids(nodes, id_to_obj):
    for node in nodes:
        nid = node["id"]
        pid = node["parent_id"]

        obj = id_to_obj.get(nid)
        if obj is None:
            continue

        # Parent is a standard object
        parent_obj = id_to_obj.get(pid)
        if parent_obj is not None:
            obj.parent = parent_obj


def _build_objects_from_nodes(nodes, collection):
    """
    Creates Blender objects for types:
      - transform  -> Empty
      - empty      -> Empty
      - mesh       -> Mesh Object
    Bones are created in a separate function.
    Returns:
      id_to_obj: { node_id: bpy.types.Object }
      imported_objects: list[bpy.types.Object]
      bone_nodes: list[dict] (nodes of type "bone")
    """
    id_to_obj = {}
    imported_objects = []
    bone_nodes = []

    # First pass: create all objects except bones
    for node in nodes:
        ntype = node["type"]
        nid = node["id"]
        name = node["name"]

        if ntype == "transform":
            obj = bpy.data.objects.new(name, None)
            obj.matrix_world = Matrix(node.get("matrix"))
            if node.get("animation"):
                _apply_anim_to_object(obj, node.get("animation"))

            collection.objects.link(obj)
            id_to_obj[nid] = obj
            imported_objects.append(obj)

        elif ntype == "empty":
            obj = bpy.data.objects.new(name, None)
            # For LOCA in convert_and_filter_nodes there is no matrix - leave at (0,0,0)
            collection.objects.link(obj)
            id_to_obj[nid] = obj
            imported_objects.append(obj)

        elif ntype == "mesh":
            mesh = bpy.data.meshes.new(name)

            verts = [tuple(v) for v in node["vrts"]]
            faces = [tuple(tri) for tri in node["ibuf"]]

            mesh.from_pydata(verts, [], faces)

            # --- UV ---
            uvpt = node.get("uvpt") or []
            uv_index_of_vertex = node.get("uv_index_of_vertex") or list(
                range(len(verts))
            )
            if uvpt:
                uv_layer = mesh.uv_layers.new(name="UVMap")
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        vidx = mesh.loops[li].vertex_index
                        uvidx = uv_index_of_vertex[vidx]
                        if 0 <= uvidx < len(uvpt):
                            u, v = uvpt[uvidx]
                            # if you want to invert V:
                            # uv_layer.data[li].uv = (u, 1.0 - v)
                            uv_layer.data[li].uv = (u, v)

            # --- Materials on mesh ---
            materials_list = node.get("materials") or []
            existing_names = [slot.name for slot in mesh.materials]

            for mat_info in materials_list:
                mat = _create_material_from_nmf(mat_info)
                if mat is None:
                    continue

                if mat.name not in existing_names:
                    mesh.materials.append(mat)
                    existing_names.append(mat.name)

            obj = bpy.data.objects.new(name, mesh)
            collection.objects.link(obj)
            id_to_obj[nid] = obj
            imported_objects.append(obj)

        else:
            # Just in case - ignore other types
            pass

    return id_to_obj, imported_objects, bone_nodes


# ------------------------------------------------------------------------
# Main Import Function
# ------------------------------------------------------------------------


def load(operator, context, filepath):
    # Parse NMF and convert to normalized node list
    try:
        parser = Nmf()
        nodes_raw = parser.unpack(filepath)
        nodes = convert_and_filter_nodes(nodes_raw, filepath)
    except Exception as e:
        operator.report({"ERROR"}, f"NMF parse error: {e}")
        return {"CANCELLED"}

    collection = context.collection
    imported_objects = []

    # 1) Create objects (transform/empty/mesh)
    id_to_obj, objs_created, bone_nodes = _build_objects_from_nodes(nodes, collection)
    imported_objects.extend(objs_created)

    # 3) Build hierarchy
    _parent_objects_by_ids(nodes, id_to_obj)

    operator.report({"INFO"}, f"Imported NMF: {filepath}")
    return {"FINISHED"}
# -*- coding: utf-8 -*-

"""
NMF Addon Registration

Description:
    Registers the addon in Blender, adding the import menu entry.
"""

bl_info = {
    "name": "Neo Software NMF format",
    "author": "Ivan Martyneko / GPT",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "File > Import",
    "description": "Import Neo Software 3D files (.nmf) from Der Clou2!/The Sting!/VaBank",
    "warning": "Experimental",
    "doc_url": "",
    "support": "COMMUNITY",
    "category": "Import-Export",
}

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper


class IMPORT_SCENE_OT_nmf(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.nmf"
    bl_label = "Import NMF"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".nmf"
    filter_glob: StringProperty(default="*.nmf", options={"HIDDEN"})

    def execute(self, context):
        try:
            load(self, context, filepath=self.filepath)
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"NMF import failed: {e}")
            return {"CANCELLED"}


def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_nmf.bl_idname, text="NMF (.nmf)")


def register():
    bpy.utils.register_class(IMPORT_SCENE_OT_nmf)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_SCENE_OT_nmf)
import bpy
import json
import os
import sys
from mathutils import Matrix, Euler

# --- НАСТРОЙКИ ПУТЕЙ ---
UNPACK_DIR = r"/home/user/VaBank/VaBank_unpack"

def debug_log(message):
    print(f"[NMF_BUILDER] {message}")


# --- ГЛОБАЛЬНЫЕ КЭШИ ---
MATERIAL_CACHE = {}
IMAGE_CACHE = {}

# ------------------------------------------------------------------------
# Импорт Материалов
# ------------------------------------------------------------------------


def _create_material_from_nmf(mat_info):
    name = mat_info.get("mat_name", "NMF_Material")

    # Берем из кэша, если уже создавали для другой модели
    if name in MATERIAL_CACHE:
        return MATERIAL_CACHE[name]

    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)

    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        bsdf = None
        for n in nodes:
            if n.type == "BSDF_PRINCIPLED":
                bsdf = n
                break

        if bsdf is None:
            nodes.clear()
            out = nodes.new("ShaderNodeOutputMaterial")
            out.location = (400, 0)
            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.location = (0, 0)
            links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    else:
        MATERIAL_CACHE[name] = mat
        return mat

    r = mat_info["r"]
    g = float(mat_info.get("g", 1.0))
    b = float(mat_info.get("b", 1.0))
    a = float(mat_info.get("a", 1.0))

    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Alpha"].default_value = a

    mode = mat_info.get("blend_mode", 0)
    if mode in (0, 1, 2, 3):
        mat.blend_method = "OPAQUE" if mode == 0 else "BLEND"

    tex_path = mat_info.get("tex_path")
    has_tex = bool(mat_info.get("has_tex") and tex_path)

    if has_tex:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.location = (-800, 0)
        uv_node.uv_map = "UVMap"

        mapping_node = nodes.new("ShaderNodeMapping")
        mapping_node.location = (-600, 0)

        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.location = (-400, 0)

        # Текстуры грузим 1 раз
        try:
            if tex_path in IMAGE_CACHE:
                tex_node.image = IMAGE_CACHE[tex_path]
            else:
                image = bpy.data.images.load(tex_path)
                tex_node.image = image
                IMAGE_CACHE[tex_path] = image
        except Exception:
            pass

        repeatU = float(mat_info.get("repeatU", 1.0))
        repeatV = float(mat_info.get("repeatV", 1.0))
        mirrorU = int(mat_info.get("mirrorU", 0))
        mirrorV = int(mat_info.get("mirrorV", 0))
        rotateUV = float(mat_info.get("rotateUV", 0.0))

        scale_x = repeatU * (-1.0 if mirrorU else 1.0)
        scale_y = repeatV * (-1.0 if mirrorV else 1.0)

        mapping_node.inputs["Scale"].default_value[0] = scale_x
        mapping_node.inputs["Scale"].default_value[1] = scale_y
        mapping_node.inputs["Rotation"].default_value[2] = rotateUV

        def safe_link(src, dst):
            if src is None or dst is None:
                return
            for link in dst.links:
                if link.from_socket == src:
                    return
            links.new(src, dst)

        safe_link(uv_node.outputs.get("UV"), mapping_node.inputs.get("Vector"))
        safe_link(mapping_node.outputs.get("Vector"), tex_node.inputs.get("Vector"))
        safe_link(tex_node.outputs.get("Color"), bsdf.inputs.get("Base Color"))
        safe_link(tex_node.outputs.get("Alpha"), bsdf.inputs.get("Alpha"))

    MATERIAL_CACHE[name] = mat
    return mat


def _apply_anim_to_object(obj, anim_tracks):
    if not anim_tracks:
        return
    obj.rotation_mode = "XYZ"
    fps = bpy.context.scene.render.fps
    spec = {
        "translation": ("location", (0, 1, 2), 1.0),
        "rotation": ("rotation_euler", (0, 1, 2), 1.0),
        "scaling": ("scale", (0, 1, 2), 1.0),
    }
    for track, (prop, idxs, scale) in spec.items():
        track_data = anim_tracks.get(track)
        if not track_data:
            continue
        values = track_data.get("values", {})
        keys = track_data.get("keys", {})
        for ax_name, ax_i in zip(("x", "y", "z"), idxs):
            vals = values.get(ax_name)
            frames = keys.get(ax_name)
            if not vals or not frames:
                continue
            for t, v in zip(frames, vals):
                frame = int(round(t * fps))
                arr = getattr(obj, prop)
                arr[ax_i] = float(v) * scale
                obj.keyframe_insert(data_path=prop, index=ax_i, frame=frame)


# ------------------------------------------------------------------------
# Импорт 3D-Модели в скрытую коллекцию
# ------------------------------------------------------------------------


def import_nmf_as_collection(nmf_rel_path, model_id, source_models_coll):
    """
    Парсит NMF один раз и собирает его в эталонную (мастер) коллекцию.
    """
    abs_path = os.path.join(UNPACK_DIR, nmf_rel_path)
    if not os.path.exists(abs_path):
        return None

    coll_name = f"NMF_Asset_{model_id}"

    # Если коллекция уже была создана ранее — просто возвращаем её!
    if coll_name in bpy.data.collections:
        return bpy.data.collections[coll_name]

    new_coll = bpy.data.collections.new(coll_name)
    source_models_coll.children.link(new_coll)

    parser = Nmf()
    try:
        nodes_raw = parser.unpack(abs_path)
        nodes = convert_and_filter_nodes(nodes_raw, abs_path)
    except Exception as e:
        debug_log(f"Ошибка парсинга {nmf_rel_path}: {e}")
        return None

    id_to_obj = {}

    # ЭТАП 1: Создаем объекты и применяем их абсолютные (глобальные) координаты NMF
    for node in nodes:
        ntype = node["type"]
        nid = node["id"]
        name = node["name"]

        if ntype in ("transform", "empty"):
            obj = bpy.data.objects.new(name, None)
            obj.empty_display_size = 0.5
            if node.get("matrix"):
                obj.matrix_world = Matrix(node.get("matrix"))
            if node.get("animation"):
                _apply_anim_to_object(obj, node.get("animation"))
            new_coll.objects.link(obj)
            id_to_obj[nid] = obj

        elif ntype == "mesh":
            mesh = bpy.data.meshes.new(name)
            verts = [tuple(v) for v in node["vrts"]]
            faces = [tuple(tri) for tri in node["ibuf"]]
            mesh.from_pydata(verts, [], faces)

            uvpt = node.get("uvpt") or []
            uv_index = node.get("uv_index_of_vertex") or list(range(len(verts)))
            if uvpt:
                uv_layer = mesh.uv_layers.new(name="UVMap")
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        vidx = mesh.loops[li].vertex_index
                        uvidx = uv_index[vidx]
                        if 0 <= uvidx < len(uvpt):
                            uv_layer.data[li].uv = uvpt[uvidx]

            mats = node.get("materials") or []
            existing_names = []
            for mat_info in mats:
                mat = _create_material_from_nmf(mat_info)
                if mat and mat.name not in existing_names:
                    mesh.materials.append(mat)
                    existing_names.append(mat.name)

            obj = bpy.data.objects.new(name, mesh)
            if node.get("matrix"):
                obj.matrix_world = Matrix(node.get("matrix"))
            new_coll.objects.link(obj)
            id_to_obj[nid] = obj

    # ЭТАП 2: Иерархия. Blender сам высчитает правильные смещения (matrix_parent_inverse)
    for node in nodes:
        nid = node["id"]
        pid = node["parent_id"]
        if nid in id_to_obj and pid in id_to_obj:
            id_to_obj[nid].parent = id_to_obj[pid]

    return new_coll


# ------------------------------------------------------------------------
# Сборка мира (Instance Builder)
# ------------------------------------------------------------------------


def load_json(filename):
    path = os.path.join(UNPACK_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_world():
    debug_log("Начало сборки карты через Collection Instances...")

    world_tree = load_json("world_tree.json")
    models_info = load_json("models_info.json")

    if not world_tree or not models_info:
        return

    model_map = {m["index"]: m["system_filepath"] for m in models_info}
    nodes_map = {n["index"]: n for n in world_tree}

    # Основная папка карты
    main_world_coll = bpy.data.collections.get("TheSting_WorldMap")
    if not main_world_coll:
        main_world_coll = bpy.data.collections.new("TheSting_WorldMap")
        bpy.context.scene.collection.children.link(main_world_coll)

    # Скрытая папка для хранения оригиналов моделей (Мастер-ассеты)
    source_coll_name = "NMF_Source_Models"
    source_models_coll = bpy.data.collections.get(source_coll_name)
    if not source_models_coll:
        source_models_coll = bpy.data.collections.new(source_coll_name)
        bpy.context.scene.collection.children.link(source_models_coll)
        # Исключаем из рендера и вьюпорта
        bpy.context.view_layer.layer_collection.children[source_coll_name].exclude = (
            True
        )

    id_to_coll = {}
    markers_by_id = {}

    # 1. Создаем коллекции-папки из world_tree
    for item in world_tree:
        if item.get("type") == 0:
            name = item.get("folder_name") or f"Folder_{item['index']}"
            new_coll = bpy.data.collections.new(name)
            id_to_coll[item["index"]] = new_coll

    for index, coll in id_to_coll.items():
        parent_id = nodes_map[index].get("parent_id")
        if parent_id in id_to_coll:
            id_to_coll[parent_id].children.link(coll)
        else:
            if coll.name not in main_world_coll.children:
                main_world_coll.children.link(coll)

    count = 0
    cached_folders = {}

    # 2. Создаем Инстансы на карте
    for item in world_tree:
        if item.get("type") == 1:
            model_id = item.get("model_id")
            if model_id is None or model_id not in model_map:
                continue

            nmf_path = model_map[model_id]

            # Находим нужную папку для инстанса
            parent_id = item.get("parent_id")
            if parent_id not in cached_folders:
                target_coll = id_to_coll.get(parent_id, main_world_coll)
                temp_p = parent_id
                while temp_p in nodes_map and temp_p not in id_to_coll:
                    temp_p = nodes_map[temp_p].get("parent_id")
                    if temp_p in id_to_coll:
                        target_coll = id_to_coll[temp_p]
                        break
                cached_folders[parent_id] = target_coll
            target_coll = cached_folders[parent_id]

            # Создаем/получаем мастер-коллекцию модели
            asset_coll = import_nmf_as_collection(
                nmf_path, model_id, source_models_coll
            )

            if asset_coll:
                # Создаем маркер-пустышку, который будет рендерить коллекцию
                obj_name = item.get("name") or f"Instance_{item['index']}"
                map_marker = bpy.data.objects.new(obj_name, None)
                map_marker.instance_type = "COLLECTION"
                map_marker.instance_collection = asset_coll

                target_coll.objects.link(map_marker)
                markers_by_id[item["index"]] = map_marker

                # Позиционируем инстанс на карте (с учетом инверсии вращения!)
                map_marker.location = (item["x"], item["z"], item["y"])
                map_marker.rotation_euler = Euler(
                    (0, 0, -item.get("rotation", 0.0)), "XYZ"
                )
                s = item.get("scaling", 1.0)
                map_marker.scale = (s, s, s)

                count += 1

    # 3. Привязка маркеров-инстансов друг к другу
    for item in world_tree:
        if item.get("type") == 1 and item["index"] in markers_by_id:
            parent_id = item.get("parent_id")
            if parent_id in markers_by_id:
                child_marker = markers_by_id[item["index"]]
                parent_marker = markers_by_id[parent_id]
                child_marker.parent = parent_marker
                child_marker.matrix_parent_inverse.identity()

    debug_log(
        f"Сборка завершена (Collection Instances)! Импортировано {count} инстансов на карту."
    )


if __name__ == "__main__":
    build_world()
