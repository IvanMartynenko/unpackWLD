# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) NMF Builder Library

Description:
    This module provides the core logic for packing dictionary data back into the
    binary NMF format. It acts as the inverse of the parser, handling low-level
    byte writing, alignment, and endianness required by the game engine.

    Features:
    - Handles complex binary packing (Big-Endian block sizes, Little-Endian data).
    - Manages specific data alignment (4-byte string padding, odd index count padding).
    - Supports all NMF node types including skeletal animation and mesh data.

    Field names match docs/NMF_SPEC.md.

License: MIT License

Usage:
    Imported and used by `json_to_nmf.py` or other packing tools.
"""

from .binary_writer import BinaryWriter

MATRIX_SIZE = 16


def flatten_matrix(matrix_list):
    """Flattens [[1,2,3,4], [5,6,7,8]...] to [1,2,3,4,5,6,7,8...]"""
    if not matrix_list:
        return []
    return [val for row in matrix_list for val in row]


class NmfBuilder:
    def pack(self, model_data, output_path):
        writer = BinaryWriter()

        # Header
        writer.push_word("NMF ")
        writer.push_int(0)  # int32 == 0

        for node in model_data:
            token = node.get("type", "UNK ")
            name = node.get("name", "")
            parent = node.get("parent", -1)
            payload = node.get("payload", {})

            # Create a temporary writer for the chunk content
            # to verify its size before writing the block header
            chunk_writer = BinaryWriter()

            # Route to specific data packers
            if token in ["ROOT", "FRAM"]:
                chunk_writer.push_int(2)
                chunk_writer.push_int(parent)
                chunk_writer.push_string(name)
                self._pack_fram(chunk_writer, payload)
            elif token == "LOCA":
                chunk_writer.push_int(0)
                chunk_writer.push_int(parent)
                chunk_writer.push_string(name)
                pass  # Empty data
            elif token == "JOIN":
                chunk_writer.push_int(2)
                chunk_writer.push_int(parent)
                chunk_writer.push_string(name)
                self._pack_join(chunk_writer, payload)
            elif token == "MESH":
                chunk_writer.push_int(14)
                chunk_writer.push_int(parent)
                chunk_writer.push_string(name)
                self._pack_mesh(chunk_writer, payload)
            else:
                print(f"Warning: Unknown token {token}, writing header only.")

            chunk_data = chunk_writer.get_data()
            chunk_size = len(chunk_data)

            # Write Token (Word)
            writer.push_word(token)

            # Write Size (Big Endian per parser spec)
            writer.push_big_endian_int(chunk_size)

            # Write the actual chunk data
            writer.push_bytes(chunk_data)

        # Write END token
        writer.push_word("END ")
        writer.push_big_endian_int(0)

        # Save to file
        with open(output_path, "wb") as f:
            f.write(writer.get_data())

    def _pack_fram(self, writer, data):
        # Matrix
        flat_mtx = flatten_matrix(data.get("local_matrix", []))
        writer.push_floats(flat_mtx)

        # Vectors
        vec_keys = [
            "translation",
            "scale",
            "rotation",
            "rotate_pivot_translate",
            "rotate_pivot",
            "scale_pivot_translate",
            "scale_pivot",
            "shear",
        ]
        for key in vec_keys:
            vec = data.get(key, [0.0, 0.0, 0.0])
            writer.push_floats(vec)

        if "animation" in data:
            self._pack_anim(writer, data["animation"])
        else:
            writer.push_int(0)

    def _pack_join(self, writer, data):
        # Matrix 1
        flat_mtx = flatten_matrix(data.get("local_matrix", []))
        writer.push_floats(flat_mtx)

        # Basic Vectors
        for key in ["translation", "scale", "rotation"]:
            vec = data.get(key, [0.0, 0.0, 0.0])
            writer.push_floats(vec)

        # Matrix 2 (Joint Orient Matrix)
        flat_orient_mtx = flatten_matrix(data.get("joint_orient_matrix", []))
        writer.push_floats(flat_orient_mtx)

        # Limits
        writer.push_floats(data.get("rotation_limit_min", [0.0, 0.0, 0.0]))
        writer.push_floats(data.get("rotation_limit_max", [0.0, 0.0, 0.0]))

        if "animation" in data:
            self._pack_anim(writer, data["animation"])
        else:
            writer.push_int(0)

    def _pack_anim(self, writer, anim_data):
        if not anim_data:
            return

        # Write 'ANIM' marker
        writer.push_word("ANIM")

        interpolation = anim_data.get("interpolation", 0)
        writer.push_int(interpolation)

        channels = ["translation", "rotation", "scale"]
        sizes = {"translation": [0, 0, 0], "rotation": [0, 0, 0], "scale": [0, 0, 0]}

        # Pre-calculate sizes
        for key in channels:
            if key in anim_data:
                axes = anim_data[key].get("times", {})
                sizes[key][0] = len(axes.get("x", []))
                sizes[key][1] = len(axes.get("y", []))
                sizes[key][2] = len(axes.get("z", []))

        # Write sizes table
        for key in channels:
            writer.push_ints(sizes[key])

        # Write data
        for key in channels:
            cur = anim_data.get(key, {})
            t_dict = cur.get("times", {})
            v_dict = cur.get("values", {})

            # X, Y, Z channels
            for axis in ["x", "y", "z"]:
                idx = {"x": 0, "y": 1, "z": 2}[axis]
                n = sizes[key][idx]
                if n > 0:
                    writer.push_floats(t_dict.get(axis, []))
                    writer.push_floats(v_dict.get(axis, []))

    def _pack_mesh(self, writer, data):
        triangle_count = data.get("triangle_count", 0)
        vertex_count = data.get("vertex_count", 0)
        writer.push_int(triangle_count)
        writer.push_int(vertex_count)

        # Vertex buffer
        vbuf_lists = data.get("vertices", [])
        vbuf_flat = [val for sublist in vbuf_lists for val in sublist]
        writer.push_floats(vbuf_flat)

        # Source UV
        source_uv_lists = data.get("source_uv", [])
        source_uv_flat = [val for sublist in source_uv_lists for val in sublist]
        writer.push_floats(source_uv_flat)

        # Indices
        index_count = data.get("index_count", 0)
        writer.push_int(index_count)

        indices_lists = data.get("indices", [])
        indices_flat = [val for sublist in indices_lists for val in sublist]
        writer.push_uints16(indices_flat)

        # Padding for odd indices count (Critical!)
        if index_count % 2 == 1:
            writer.push_uint16(0)

        # Flags
        writer.push_int(data.get("backface_culling", 0))
        writer.push_int(data.get("complex", 0))
        writer.push_int(data.get("inside", 0))
        writer.push_int(data.get("smooth", 0))
        writer.push_int(data.get("light_flare", 0))

        # Materials
        materials = data.get("materials", [])
        writer.push_int(len(materials))
        for mat in materials:
            self._pack_mtrl(writer, mat)

        # Vertex animations
        # Parser logic loops while checking for "ANIM" token
        if "vertex_animations" in data:
            for anim_chunk in data["vertex_animations"]:
                writer.push_word("ANIM")
                self._pack_single_anim_mesh(writer, anim_chunk)
            writer.push_int(0)
        else:
            writer.push_int(0)

        # Anti-ground / collision data
        collision_vertices = data.get("collision_vertices", [])
        collision_vertex_count = len(collision_vertices) // 3
        writer.push_int(collision_vertex_count)
        if collision_vertex_count > 0:
            writer.push_floats(collision_vertices)

        collision_indices = data.get("collision_indices", [])
        writer.push_int(len(collision_indices))
        if len(collision_indices) > 0:
            writer.push_ints(collision_indices)

    def _pack_mtrl(self, writer, mat):
        writer.push_word("MTRL")
        writer.push_string(mat.get("name", ""))

        writer.push_int(mat.get("blend_mode", 0))
        writer.push_ints(
            [
                mat.get("vertex_offset", 0),
                mat.get("vertex_count", 0),
                mat.get("index_offset", 0),
                mat.get("index_count", 0),
            ]
        )
        writer.push_int(mat.get("uv_flip_u", 0))
        writer.push_int(mat.get("uv_flip_v", 0))
        writer.push_int(mat.get("uv_rotation", 0))

        writer.push_float(mat.get("uv_scale_u", 1.0))
        writer.push_float(mat.get("uv_scale_v", 1.0))

        diffuse = mat.get("diffuse", [1.0, 1.0, 1.0, 1.0])
        writer.push_floats(diffuse)

        ambient = mat.get("ambient", [0.0, 0.0, 0.0, 0.0])
        writer.push_floats(ambient)

        specular = mat.get("specular", [0, 0, 0, 0])
        emissive = mat.get("emissive", [0, 0, 0, 0])
        specular_power = mat.get("specular_power", 0)
        writer.push_ints(list(specular) + list(emissive) + [specular_power])

        texture = mat.get("texture")
        if texture and texture.get("kind") == "TXPG":
            writer.push_word("TXPG")
            writer.push_string(texture.get("name", ""))
            writer.push_int(texture.get("page", 0))
            writer.push_int(texture.get("index_on_page", 0))
            atlas_rect = texture.get("atlas_rect", [0, 0, 0, 0])
            writer.push_ints(atlas_rect)
        elif texture and texture.get("kind") == "TEXT":
            writer.push_word("TEXT")
            writer.push_string(texture.get("name", ""))
        else:
            writer.push_int(0)

    def _pack_single_anim_mesh(self, writer, data):
        writer.push_int(data.get("interpolation", 0))

        vertex_count = data.get("vertex_count", 0)
        writer.push_int(vertex_count)
        writer.push_ints(data.get("vertex_indices", []))

        writer.push_floats(data.get("rest_position", [0.0] * 3))

        key_count_x = data.get("key_count_x", 0)
        key_count_y = data.get("key_count_y", 0)
        key_count_z = data.get("key_count_z", 0)

        writer.push_int(key_count_x)
        writer.push_int(key_count_y)
        writer.push_int(key_count_z)

        writer.push_floats(data.get("delta_x", []))
        writer.push_floats(data.get("delta_y", []))
        writer.push_floats(data.get("delta_z", []))
