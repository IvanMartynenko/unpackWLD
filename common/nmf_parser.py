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
    the scene graph nodes. Field names match docs/NMF_SPEC.md.

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

                _version = struct.unpack("<i", f.read(4))[0]
                parent = struct.unpack("<i", f.read(4))[0]
                name = read_aligned_string(f)

                if token == "ROOT":
                    payload = self._parse_fram(f)
                elif token == "LOCA":
                    payload = {}
                elif token == "FRAM":
                    payload = self._parse_fram(f)
                elif token == "JOIN":
                    payload = self._parse_join(f)
                elif token == "MESH":
                    payload = self._parse_mesh(f)
                else:
                    raise RuntimeError(f"Unexpected token in MODEL: {token}")

                model.append(
                    {
                        "type": token,
                        "name": name,
                        "parent": parent,
                        "payload": payload,
                        "index": index,
                    }
                )
                index += 1
        return model

    def _parse_fram(self, f):
        res = {}
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["local_matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]
        for key in [
            "translation",
            "scale",
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
            res["animation"] = self._parse_anim(f)
        return res

    def _parse_join(self, f):
        res = {}
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["local_matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]
        for key in ["translation", "scale", "rotation"]:
            res[key] = list(struct.unpack("<3f", f.read(12)))
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["joint_orient_matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]
        res["rotation_limit_min"] = list(struct.unpack("<3f", f.read(12)))
        res["rotation_limit_max"] = list(struct.unpack("<3f", f.read(12)))
        peek = f.read(4)
        if len(peek) != 4:
            return res
        word = peek.decode("ascii", errors="ignore")
        if word == "ANIM":
            res["animation"] = self._parse_anim(f)
        return res

    def _parse_anim(self, f):
        res = {}
        sizes = {}
        res["interpolation"] = struct.unpack("<i", f.read(4))[0]
        channels = ["translation", "rotation", "scale"]
        for key in channels:
            res[key] = {}
            sizes[key] = {}
        for key in channels:
            sizes[key]["sizes"] = list(struct.unpack("<3i", f.read(12)))
        for key in channels:
            axis_sizes = sizes[key]["sizes"]
            cur = {"values": {}, "times": {}}
            n = axis_sizes[0]
            if n > 0:
                cur["times"]["x"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["x"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
            n = axis_sizes[1]
            if n > 0:
                cur["times"]["y"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["y"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
            n = axis_sizes[2]
            if n > 0:
                cur["times"]["z"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["z"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
            res[key] = cur
        return res

    def _parse_mesh(self, f):
        res = {}
        res["triangle_count"] = struct.unpack("<i", f.read(4))[0]
        res["vertex_count"] = struct.unpack("<i", f.read(4))[0]

        vbuf_count = 10
        uvbuf_count = 2
        vbuf_count_float = res["vertex_count"] * vbuf_count
        uvbuf_count_float = res["vertex_count"] * uvbuf_count

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
        res["vertices"] = raw_vbuf

        uv_flat = list(
            struct.unpack(f"<{uvbuf_count_float}f", f.read(4 * uvbuf_count_float))
        )
        res["source_uv"] = [
            uv_flat[i : i + uvbuf_count] for i in range(0, len(uv_flat), uvbuf_count)
        ]

        res["index_count"] = struct.unpack("<i", f.read(4))[0]
        ibuf_flat = list(
            struct.unpack(f"<{res['index_count']}h", f.read(2 * res["index_count"]))
        )
        res["indices"] = [ibuf_flat[i : i + 3] for i in range(0, len(ibuf_flat), 3)]

        if res["index_count"] % 2 == 1:
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
            res["vertex_animations"] = self._parse_anim_mesh(f)
        # anti-ground / collision data
        raw = f.read(4)
        collision_vertex_count = struct.unpack("<i", raw)[0]
        if collision_vertex_count > 0:
            cnt = collision_vertex_count * 3
            res["collision_vertices"] = list(struct.unpack(f"<{cnt}f", f.read(4 * cnt)))
        collision_index_count = struct.unpack("<i", f.read(4))[0]
        if collision_index_count > 0:
            res["collision_indices"] = list(
                struct.unpack(
                    f"<{collision_index_count}i", f.read(4 * collision_index_count)
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
        vertex_offset, vertex_count, index_offset, index_count = struct.unpack(
            "<4i", f.read(16)
        )
        res["vertex_offset"] = vertex_offset
        res["vertex_count"] = vertex_count
        res["index_offset"] = index_offset
        res["index_count"] = index_count
        res["uv_flip_u"] = struct.unpack("<i", f.read(4))[0]
        res["uv_flip_v"] = struct.unpack("<i", f.read(4))[0]
        res["uv_rotation"] = struct.unpack("<i", f.read(4))[0]
        res["uv_scale_u"] = struct.unpack("<f", f.read(4))[0]
        res["uv_scale_v"] = struct.unpack("<f", f.read(4))[0]
        res["diffuse"] = list(struct.unpack("<4f", f.read(16)))
        res["ambient"] = list(struct.unpack("<4f", f.read(16)))
        zero_ints = list(struct.unpack("<9i", f.read(36)))
        res["specular"] = zero_ints[0:4]
        res["emissive"] = zero_ints[4:8]
        res["specular_power"] = zero_ints[8]

        next_token_bytes = f.read(4)
        if len(next_token_bytes) == 4:
            next_token = next_token_bytes.decode("ascii", errors="ignore")
            if next_token == "TXPG":
                name = read_aligned_string(f)
                res["texture"] = {
                    "kind": "TXPG",
                    "name": name,
                    "page": struct.unpack("<i", f.read(4))[0],
                    "index_on_page": struct.unpack("<i", f.read(4))[0],
                    "atlas_rect": list(struct.unpack("<4i", f.read(16))),
                }
            elif next_token == "TEXT":
                name = read_aligned_string(f)
                res["texture"] = {"kind": "TEXT", "name": name}
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
        interpolation = struct.unpack("<i", f.read(4))[0]
        vertex_count = struct.unpack("<i", f.read(4))[0]
        vertex_indices = list(
            struct.unpack(f"<{vertex_count}i", f.read(4 * vertex_count))
        )
        rest_position = list(struct.unpack("<3f", f.read(12)))
        key_count_x = struct.unpack("<i", f.read(4))[0]
        key_count_y = struct.unpack("<i", f.read(4))[0]
        key_count_z = struct.unpack("<i", f.read(4))[0]
        delta_x = list(
            struct.unpack(f"<{key_count_x*2}f", f.read(4 * (key_count_x * 2)))
        )
        delta_y = list(
            struct.unpack(f"<{key_count_y*2}f", f.read(4 * (key_count_y * 2)))
        )
        delta_z = list(
            struct.unpack(f"<{key_count_z*2}f", f.read(4 * (key_count_z * 2)))
        )
        return {
            "interpolation": interpolation,
            "vertex_count": vertex_count,
            "vertex_indices": vertex_indices,
            "rest_position": rest_position,
            "key_count_x": key_count_x,
            "key_count_y": key_count_y,
            "key_count_z": key_count_z,
            "delta_x": delta_x,
            "delta_y": delta_y,
            "delta_z": delta_z,
        }
