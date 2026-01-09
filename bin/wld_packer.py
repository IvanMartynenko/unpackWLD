#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) World Packer Executable

Description:
    This tool reads extracted game assets (JSON, DDS, NMF, BIN) from a directory,
    assembles them into a data structure, and uses the common packing logic
    to generate a .wld file.

    It handles:
    - Reading JSON metadata.
    - Reading and dimension-checking DDS textures (handling HD upscaling).
    - Reading raw NMF models.
    - Reading shadow maps and mapping them to World Tree nodes.

License: MIT License

Usage:
    python wld_packer.py <path_to_unpack_folder>
"""

import sys, os, json, struct

# Ensure we can import from common
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import pack_wld_data
from common.binary_reader import BinaryReader


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def gather_texture_pages(pack_dir):
    print("Gathering Texture Pages...")
    tex_json_path = os.path.join(pack_dir, "texture_pages.json")
    pages = load_json(tex_json_path)
    if not pages:
        return []

    processed_pages = []
    for page in pages:
        dds_path = os.path.join(pack_dir, "texture_pages", f"{page['id']}.dds")
        if not os.path.exists(dds_path):
            print(f"Warning: DDS file not found: {dds_path}")
            continue

        with open(dds_path, "rb") as f:
            dds_data = f.read()

        # Parse DDS header (height at offset 12)
        # Magic (4) + Size (4) + Flags (4) + Height (4)
        if len(dds_data) > 16:
            real_height = struct.unpack("<I", dds_data[12:16])[0]
            json_height = page.get("height", 1)
            if json_height == 0:
                json_height = 1

            scale = real_height // json_height
            if scale != 1:
                # Scale parameters if the texture was upscaled (HD modding)
                page["width"] *= scale
                page["height"] *= scale
                for tex in page.get("textures", []):
                    for k in ["x0", "y0", "x2", "y2"]:
                        tex["box"][k] *= scale

        # DDS pixel data usually starts at 128 (standard header)
        page["raw_bytes"] = dds_data[128:]
        processed_pages.append(page)

    return processed_pages


def gather_models(pack_dir):
    print("Gathering Models...")
    models_path = os.path.join(pack_dir, "models_info.json")
    models = load_json(models_path)
    if not models:
        return []

    processed_models = []
    for model in models:
        rel_path = model.get("system_filepath", "")
        rel_path = rel_path.replace("/", os.sep).replace("\\", os.sep)
        nmf_path = os.path.join(pack_dir, rel_path)

        if not os.path.exists(nmf_path):
            raise FileNotFoundError(f"NMF file not found: {nmf_path}")

        with open(nmf_path, "rb") as f:
            model["raw_bytes"] = f.read()

        processed_models.append(model)

    return processed_models


def gather_shadows(pack_dir):
    """Parses shadows.bin into a dictionary indexed by tree node index."""
    shadows_map = {}
    shadows_path = os.path.join(pack_dir, "shadows.bin")
    if os.path.exists(shadows_path):
        print("Loading Shadows...")
        with open(shadows_path, "rb") as f:
            sdata = f.read()
            sreader = BinaryReader(sdata)
            while not sreader.eof():
                idx = sreader.read_int()
                s1 = sreader.read_int()
                s2 = sreader.read_int()
                # Replicating logic from unpacker to calculate size
                extra = 1 if (s1 % 2 != 0 and s2 % 2 != 0) else 0
                size = (s1 * s2 // 2) + extra
                data = sreader.read_uints16(size * 2)
                shadows_map[idx] = {"size1": s1, "size2": s2, "data": data}
    return shadows_map


def gather_world_tree(pack_dir):
    print("Gathering World Tree...")
    world_path = os.path.join(pack_dir, "world_tree.json")
    world_tree = load_json(world_path)
    if not world_tree:
        return []

    # Load shadows and attach them to the nodes
    shadows_map = gather_shadows(pack_dir)

    for item in world_tree:
        idx = item.get("index")
        if idx in shadows_map:
            item["shadow"] = shadows_map[idx]

    return world_tree


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python wld_packer.py <path_to_unpack_folder>")
        sys.exit(1)

    unpack_folder = sys.argv[1]
    if not os.path.isdir(unpack_folder):
        print(f"Error: {unpack_folder} is not a directory.")
        sys.exit(1)

    # Generate output filename
    clean_folder_path = unpack_folder.rstrip("/\\")
    folder_name = os.path.basename(clean_folder_path)
    out_file = os.path.join(unpack_folder, f"{folder_name}.wld")

    print(f"Preparing to pack data from: {unpack_folder}")

    try:
        # Assemble the data dictionary
        wld_data = {
            "texture_pages": gather_texture_pages(unpack_folder),
            "model_folders": load_json(
                os.path.join(unpack_folder, "model_list_tree.json")
            )
            or [],
            "object_folders": load_json(
                os.path.join(unpack_folder, "object_list_tree.json")
            )
            or [],
            "models_info": gather_models(unpack_folder),
            "objects": load_json(os.path.join(unpack_folder, "object_list.json")) or [],
            "world_tree": gather_world_tree(unpack_folder),
        }

        # Pack
        print("Packing binary data...")
        wld_bytes = pack_wld_data(wld_data)

        # Write
        with open(out_file, "wb") as f:
            f.write(wld_bytes)

        print(f"Success! Created: {out_file}")

    except Exception as e:
        print(f"Error during packing: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
