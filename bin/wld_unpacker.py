#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) World Unpacker

Description:
    This tool extracts assets from the proprietary .wld (World) format used
    by "The Sting!". It splits the monolithic binary file into editable
    components, facilitating modding and analysis.

Features:
    - Parses the binary WLD structure (TREE, LIST, OBJS, etc.).
    - Extracts textures to valid .DDS files with generated headers (TEXP).
    - Extracts 3D models to raw .NMF files and organizes them by folder structure.
    - Exports object metadata, task lists, and world hierarchy to JSON.
    - Extracts binary shadow maps to a separate file.

License: MIT License

Usage:
    python wld_unpacker.py <path_to.wld>
"""
import sys, os
import json
import struct

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import unpack_wld_to_data
from common import BinaryWriter


def generate_dds_header(width, height, is_alpha):
    """
    Generates a standard DDS header for the unpacked textures.
    """
    # DDS Magic
    header = b"DDS "
    # DDS_HEADER
    header += struct.pack("<I", 124)  # dwSize
    header += struct.pack(
        "<I", 0x1007
    )  # dwFlags (DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT)
    header += struct.pack("<I", height)
    header += struct.pack("<I", width)
    header += struct.pack("<I", width * 2)  # dwPitchOrLinearSize
    header += b"\x00" * 52  # dwDepth, dwMipMapCount, dwReserved1

    # DDS_PIXELFORMAT
    header += struct.pack("<I", 32)  # dwSize
    header += struct.pack("<I", 0x41)  # dwFlags (DDPF_RGB | DDPF_ALPHAPIXELS)
    header += b"\x00" * 4  # dwFourCC
    header += struct.pack("<I", 16)  # dwRGBBitCount
    header += struct.pack("<I", 0x7C00)  # dwRBitMask
    header += struct.pack("<I", 0x03E0)  # dwGBitMask
    header += struct.pack("<I", 0x001F)  # dwBBitMask
    header += struct.pack("<I", 0x8000 if is_alpha else 0)  # dwABitMask

    # DDS_CAPS
    header += struct.pack("<I", 0x1000)  # dwCaps (DDSCAPS_TEXTURE)
    header += b"\x00" * 16

    return header


def get_folder_path(folder_id, folder_map):
    """
    Recursively reconstructs the folder path from the model_folders list.
    """
    path_parts = []
    current_id = folder_id
    visited = set()

    while current_id > 1:
        if current_id in visited:
            print(
                f"Warning: Circular dependency in folder structure at ID {current_id}"
            )
            break
        visited.add(current_id)

        folder = folder_map.get(current_id)
        if not folder:
            break
        path_parts.append(folder["name"])
        current_id = folder["parent_folder_id"]

    return os.path.join(*reversed(path_parts)) if path_parts else ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python wld_unpacker.py <path_to.wld>")
        sys.exit(1)

    path = sys.argv[1]

    try:
        print(f"Reading {path}...")
        wld_data = unpack_wld_to_data(path)

        pack_dir = os.path.splitext(path)[0] + "_unpack"
        os.makedirs(pack_dir, exist_ok=True)
        print(f"Unpacking to {pack_dir}...")

        # 1. Save Textures
        if wld_data["texture_pages_info"]:
            print("Saving Textures...")
            with open(os.path.join(pack_dir, "texture_pages.json"), "w") as f:
                json.dump(wld_data["texture_pages_info"], f, indent=2)

            tex_dir = os.path.join(pack_dir, "texture_pages")
            os.makedirs(tex_dir, exist_ok=True)

            for raw_tex in wld_data["raw_textures"]:
                page_id = raw_tex["page_id"]
                header = generate_dds_header(
                    raw_tex["width"], raw_tex["height"], raw_tex["is_alpha"]
                )
                full_dds = header + raw_tex["raw_bytes"]

                with open(os.path.join(tex_dir, f"{page_id}.dds"), "wb") as f:
                    f.write(full_dds)

        # 2. Save Folders Trees
        folder_map = {}
        if wld_data["model_folders"]:
            folder_map = {f["index"]: f for f in wld_data["model_folders"]}
            with open(os.path.join(pack_dir, "model_list_tree.json"), "w") as f:
                json.dump(wld_data["model_folders"], f, indent=2)

        if wld_data["object_folders"]:
            with open(os.path.join(pack_dir, "object_list_tree.json"), "w") as f:
                json.dump(wld_data["object_folders"], f, indent=2)

        # 3. Save Models
        if wld_data["models_info"]:
            print("Saving Models...")
            raw_models_map = {
                rm["index"]: rm["raw_bytes"] for rm in wld_data["raw_models"]
            }

            for model in wld_data["models_info"]:
                idx = model["index"]
                sub_folder_path = get_folder_path(model["parent_folder_id"], folder_map)
                nmf_filename = f"{model['name']}_{idx}.nmf"

                full_folder_path = os.path.join(pack_dir, "models", sub_folder_path)
                os.makedirs(full_folder_path, exist_ok=True)

                if idx in raw_models_map:
                    with open(os.path.join(full_folder_path, nmf_filename), "wb") as f:
                        f.write(raw_models_map[idx])

                rel_path = os.path.join("models", sub_folder_path, nmf_filename)
                model["system_filepath"] = rel_path.replace("\\", "/")

            with open(os.path.join(pack_dir, "models_info.json"), "w") as f:
                json.dump(wld_data["models_info"], f, indent=2)

        # 4. Save Objects
        if wld_data["objects"]:
            with open(os.path.join(pack_dir, "object_list.json"), "w") as f:
                json.dump(wld_data["objects"], f, indent=2)

        # 5. Save World Tree & Shadows
        if wld_data["world_tree"]:
            print("Saving Shadows Binary...")
            # We iterate through the tree, find nodes with shadows, write to bin, then remove data from node for JSON
            shadow_writer = BinaryWriter()
            has_shadows = False

            for node in wld_data["world_tree"]:
                if "shadow" in node:
                    has_shadows = True
                    sh = node["shadow"]
                    shadow_writer.push_int(node["index"])
                    shadow_writer.push_int(sh["size1"])
                    shadow_writer.push_int(sh["size2"])
                    shadow_writer.push_uints16(sh["data"])

                    # Remove the shadow data blob so it doesn't clutter the JSON
                    del node["shadow"]

            if has_shadows:
                with open(os.path.join(pack_dir, "shadows.bin"), "wb") as f:
                    f.write(shadow_writer.get_data())

            print("Saving World Tree...")
            with open(os.path.join(pack_dir, "world_tree.json"), "w") as f:
                json.dump(wld_data["world_tree"], f, indent=2)

        print("Unpack complete.")

    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"Error: {e}")
