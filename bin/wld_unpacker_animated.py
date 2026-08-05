#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) World Unpacker — Animated-only variant

Description:
    Unpacks a .wld file like wld_unpacker.py, but keeps only 3D models that
    carry animation data (FRAM/JOIN/MESH), regrouped by animation category
    instead of their original folder structure:
      - Textures are extracted unchanged (texture_pages.json + texture_pages/*.dds).
      - model_list_tree.json is replaced with one folder per animation
        category actually present (FRAM, JOIN, FRAM+JOIN, MESH, FRAM+MESH,
        JOIN+MESH, FRAM+JOIN+MESH, OTHER), same grouping as find_anim.py.
        Original folders are dropped.
      - models_info.json / models/: only models that have animation, with
        parent_folder_id repointed at their new category folder and
        system_filepath moved under models/<category>/.
      - Models without any animation are dropped entirely (not written to
        disk, not listed in models_info.json).
      - world_tree.json, object_list.json and object_list_tree.json are not
        produced at all — this variant is model-only.

License: MIT License

Usage:
    python wld_unpacker_animated.py <path_to.wld>
"""
import sys, os
import json
import struct
import tempfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import unpack_wld_to_data, Nmf


CORE_ANIM_TYPES = {"FRAM", "JOIN", "MESH"}
OTHER_CATEGORY = "OTHER"

# Order controls both find_anim.py's grouping and the resulting folder
# order in model_list_tree.json. OTHER (anim on ROOT/LOCA/etc.) always
# comes last, same as find_anim.py's output.
CATEGORY_ORDER = [
    (frozenset({"FRAM"}), "FRAM"),
    (frozenset({"JOIN"}), "JOIN"),
    (frozenset({"FRAM", "JOIN"}), "FRAM+JOIN"),
    (frozenset({"MESH"}), "MESH"),
    (frozenset({"FRAM", "MESH"}), "FRAM+MESH"),
    (frozenset({"JOIN", "MESH"}), "JOIN+MESH"),
    (frozenset({"FRAM", "JOIN", "MESH"}), "FRAM+JOIN+MESH"),
]
CATEGORY_NAMES = {core: name for core, name in CATEGORY_ORDER}


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
    Recursively reconstructs the folder path from a {index: folder} map.
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


def get_animated_node_types(nmf_bytes, tmp_dir):
    """
    Parses raw .nmf bytes and returns the set of node types (word) that
    carry animation data, e.g. {"FRAM", "MESH"}.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".nmf", dir=tmp_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(nmf_bytes)
        raw_nodes = Nmf().unpack(tmp_path)
    finally:
        os.remove(tmp_path)

    animated_types = set()
    for node in raw_nodes:
        payload = node.get("payload", {})
        if payload.get("animation") or payload.get("vertex_animations"):
            animated_types.add(node.get("type", "UNKNOWN"))
    return animated_types


def classify(anim_types):
    """
    Maps a set of animated node types to an output category name, or None
    if the model has no animation at all.
    """
    if not anim_types:
        return None
    core_types = anim_types & CORE_ANIM_TYPES
    has_other = len(anim_types) > len(core_types)
    if has_other:
        return OTHER_CATEGORY
    return CATEGORY_NAMES.get(frozenset(core_types), OTHER_CATEGORY)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python wld_unpacker_animated.py <path_to.wld>")
        sys.exit(1)

    path = sys.argv[1]

    try:
        print(f"Reading {path}...")
        wld_data = unpack_wld_to_data(path)

        pack_dir = os.path.splitext(path)[0] + "_unpack_animated"
        os.makedirs(pack_dir, exist_ok=True)
        print(f"Unpacking animated-only content to {pack_dir}...")

        # 1. Save Textures (untouched, same as wld_unpacker.py)
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

        # 2. Classify every model by its animation content
        raw_models_map = {rm["index"]: rm["raw_bytes"] for rm in wld_data["raw_models"]}
        tmp_dir = os.path.join(pack_dir, "_tmp")
        os.makedirs(tmp_dir, exist_ok=True)

        print("Scanning models for animation...")
        kept = []  # list of (model, raw_bytes, category)
        categories_present = []  # preserves CATEGORY_ORDER / OTHER ordering
        for model in wld_data["models_info"]:
            idx = model["index"]
            raw_bytes = raw_models_map.get(idx)
            if raw_bytes is None:
                continue

            anim_types = get_animated_node_types(raw_bytes, tmp_dir)
            category = classify(anim_types)
            if category is None:
                continue  # no animation at all -> drop entirely

            if category not in categories_present:
                categories_present.append(category)
            kept.append((model, raw_bytes, category))

        os.rmdir(tmp_dir)

        print(f"Kept {len(kept)} animated model(s) out of {len(wld_data['models_info'])}.")

        # 3. Build model_list_tree.json with only the categories actually used
        ordered_names = [name for _, name in CATEGORY_ORDER if name in categories_present]
        if OTHER_CATEGORY in categories_present:
            ordered_names.append(OTHER_CATEGORY)

        model_folders = []
        category_id_map = {}
        next_index = 2
        for name in ordered_names:
            model_folders.append(
                {"index": next_index, "name": name, "parent_folder_id": 1}
            )
            category_id_map[name] = next_index
            next_index += 1

        with open(os.path.join(pack_dir, "model_list_tree.json"), "w") as f:
            json.dump(model_folders, f, indent=2)

        # 4. Save the kept models, repointed at their new category folder
        folder_map = {f["index"]: f for f in model_folders}
        kept_models_info = []
        for model, raw_bytes, category in kept:
            idx = model["index"]
            model["parent_folder_id"] = category_id_map[category]

            sub_folder_path = get_folder_path(model["parent_folder_id"], folder_map)
            nmf_filename = f"{model['name']}_{idx}.nmf"
            full_folder_path = os.path.join(pack_dir, "models", sub_folder_path)
            os.makedirs(full_folder_path, exist_ok=True)

            with open(os.path.join(full_folder_path, nmf_filename), "wb") as f:
                f.write(raw_bytes)

            rel_path = os.path.join("models", sub_folder_path, nmf_filename)
            model["system_filepath"] = rel_path.replace("\\", "/")
            kept_models_info.append(model)

        with open(os.path.join(pack_dir, "models_info.json"), "w") as f:
            json.dump(kept_models_info, f, indent=2)

        print("Unpack complete.")

    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"Error: {e}")
