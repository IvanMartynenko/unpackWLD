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
            token = node.get("word", "UNK ")
            name = node.get("name", "")
            parent_id = node.get("parent_id", -1)
            data = node.get("data", {})

            # Create a temporary writer for the chunk content
            # to verify its size before writing the block header
            chunk_writer = BinaryWriter()

            # Route to specific data packers
            if token in ["ROOT", "FRAM"]:
                chunk_writer.push_int(2)
                chunk_writer.push_int(parent_id)
                chunk_writer.push_string(name)
                self._pack_fram(chunk_writer, data)
            elif token == "LOCA":
                chunk_writer.push_int(0)
                chunk_writer.push_int(parent_id)
                chunk_writer.push_string(name)
                pass  # Empty data
            elif token == "JOIN":
                chunk_writer.push_int(2)
                chunk_writer.push_int(parent_id)
                chunk_writer.push_string(name)
                self._pack_join(chunk_writer, data)
            elif token == "MESH":
                chunk_writer.push_int(14)
                chunk_writer.push_int(parent_id)
                chunk_writer.push_string(name)
                self._pack_mesh(chunk_writer, data)
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
        flat_mtx = flatten_matrix(data.get("matrix", []))
        writer.push_floats(flat_mtx)

        # Vectors
        vec_keys = [
            "translation",
            "scaling",
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

        if "anim" in data:
            self._pack_anim(writer, data["anim"])
        else:
            writer.push_int(0)

    def _pack_join(self, writer, data):
        # Matrix 1
        flat_mtx = flatten_matrix(data.get("matrix", []))
        writer.push_floats(flat_mtx)

        # Basic Vectors
        for key in ["translation", "scaling", "rotation"]:
            vec = data.get(key, [0.0, 0.0, 0.0])
            writer.push_floats(vec)

        # Matrix 2 (Rotation Matrix)
        flat_rot_mtx = flatten_matrix(data.get("rotation_matrix", []))
        writer.push_floats(flat_rot_mtx)

        # Limits
        writer.push_floats(data.get("min_rot_limit", [0.0, 0.0, 0.0]))
        writer.push_floats(data.get("max_rot_limit", [0.0, 0.0, 0.0]))

        if "anim" in data:
            self._pack_anim(writer, data["anim"])
        else:
            writer.push_int(0)

    def _pack_anim(self, writer, anim_data):
        if not anim_data:
            return

        # Write 'ANIM' marker
        writer.push_word("ANIM")

        unknown = anim_data.get("unknown", 0)
        writer.push_int(unknown)

        keys = ["translation", "rotation", "scaling"]
        sizes = {"translation": [0, 0, 0], "rotation": [0, 0, 0], "scaling": [0, 0, 0]}

        # Pre-calculate sizes
        for key in keys:
            if key in anim_data:
                axes = anim_data[key].get("keys", {})
                sizes[key][0] = len(axes.get("x", []))
                sizes[key][1] = len(axes.get("y", []))
                sizes[key][2] = len(axes.get("z", []))

        # Write sizes table
        for key in keys:
            writer.push_ints(sizes[key])

        # Write data
        for key in keys:
            cur = anim_data.get(key, {})
            k_dict = cur.get("keys", {})
            v_dict = cur.get("values", {})

            # X, Y, Z channels
            for axis in ["x", "y", "z"]:
                idx = {"x": 0, "y": 1, "z": 2}[axis]
                n = sizes[key][idx]
                if n > 0:
                    writer.push_floats(k_dict.get(axis, []))
                    writer.push_floats(v_dict.get(axis, []))

    def _pack_mesh(self, writer, data):
        tnum = data.get("tnum", 0)
        vnum = data.get("vnum", 0)
        writer.push_int(tnum)
        writer.push_int(vnum)

        # VBUF
        vbuf_lists = data.get("vbuf", [])
        vbuf_flat = [val for sublist in vbuf_lists for val in sublist]
        writer.push_floats(vbuf_flat)

        # UVPT
        uvpt_lists = data.get("uvpt", [])
        uvpt_flat = [val for sublist in uvpt_lists for val in sublist]
        writer.push_floats(uvpt_flat)

        # Indices (IBUF)
        inum = data.get("inum", 0)
        writer.push_int(inum)

        ibuf_lists = data.get("ibuf", [])
        ibuf_flat = [val for sublist in ibuf_lists for val in sublist]
        writer.push_uints16(ibuf_flat)

        # Padding for odd indices count (Critical!)
        if inum % 2 == 1:
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

        # Mesh Anim
        # Parser logic loops while checking for "ANIM" token
        if "mesh_anim" in data:
            for anim_chunk in data["mesh_anim"]:
                writer.push_word("ANIM")
                self._pack_single_anim_mesh(writer, anim_chunk)
            writer.push_int(0)
        else:
            writer.push_int(0)

        # Anti-ground / Unknown floats
        unknown_floats = data.get("unknown_floats", [])
        cnt_floats = len(unknown_floats) // 3
        writer.push_int(cnt_floats)
        if cnt_floats > 0:
            writer.push_floats(unknown_floats)

        unknown_ints = data.get("unknown_ints", [])
        writer.push_int(len(unknown_ints))
        if len(unknown_ints) > 0:
            writer.push_ints(unknown_ints)

    def _pack_mtrl(self, writer, mat):
        writer.push_word("MTRL")
        writer.push_string(mat.get("name", ""))

        writer.push_int(mat.get("blend_mode", 0))
        writer.push_ints(mat.get("unknown_ints", [0] * 4))
        writer.push_int(mat.get("uv_mapping_flip_horizontal", 0))
        writer.push_int(mat.get("uv_mapping_flip_vertical", 0))
        writer.push_int(mat.get("rotate", 0))

        writer.push_float(mat.get("horizontal_stretch", 1.0))
        writer.push_float(mat.get("vertical_stretch", 1.0))

        writer.push_float(mat.get("red", 1.0))
        writer.push_float(mat.get("green", 1.0))
        writer.push_float(mat.get("blue", 1.0))
        writer.push_float(mat.get("alpha", 1.0))

        writer.push_float(mat.get("red2", 0.0))
        writer.push_float(mat.get("green2", 0.0))
        writer.push_float(mat.get("blue2", 0.0))
        writer.push_float(mat.get("alpha2", 0.0))

        writer.push_ints(mat.get("unknown_zero_ints", [0] * 9))

        if "texture" in mat:
            writer.push_word("TXPG")
            tex = mat["texture"]
            writer.push_string(tex.get("name", ""))
            writer.push_int(tex.get("texture_page", 0))
            writer.push_int(tex.get("index_texture_on_page", 0))
            writer.push_int(tex.get("x0", 0))
            writer.push_int(tex.get("y0", 0))
            writer.push_int(tex.get("x2", 0))
            writer.push_int(tex.get("y2", 0))
        elif "text" in mat:
            writer.push_word("TEXT")
            writer.push_string(mat["text"].get("name", ""))
        else:
            writer.push_int(0)

    def _pack_single_anim_mesh(self, writer, data):
        # Using push_int for bool as parser reads int (0 or -1 usually, but generic int here)
        writer.push_int(data.get("unknown_bool", 0))

        size = data.get("unknown_size_of_ints", 0)
        writer.push_int(size)
        writer.push_ints(data.get("unknown_ints", []))

        writer.push_floats(data.get("unknown_floats", [0.0] * 3))

        s1 = data.get("unknown_size1", 0)
        s2 = data.get("unknown_size2", 0)
        s3 = data.get("unknown_size3", 0)

        writer.push_int(s1)
        writer.push_int(s2)
        writer.push_int(s3)

        writer.push_floats(data.get("unknown_floats1", []))
        writer.push_floats(data.get("unknown_floats2", []))
        writer.push_floats(data.get("unknown_floats3", []))
