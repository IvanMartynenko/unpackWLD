#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) Shadow Fixer (POT Fix)

Description:
    This tool attempts to repair shadow maps within .wld files by ensuring
    their dimensions are Powers of Two (POT).

    Some rendering engines (or specific graphics wrappers like DGVoodoo/Wine)
    require texture dimensions to be powers of two (e.g., 32x32, 64x16) to
    display correctly, otherwise artifacts or crashes may occur.

    This script:
    1. Unpacks the WLD file.
    2. Iterates through all world objects.
    3. Resizes shadow maps to the nearest POT dimensions.
    4. Repacks the WLD file.

License: MIT License

Usage:
    python wld_shadow_fixer.py <input.wld> [output.wld]
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math


try:
    import common.wld_unpacking as wld_unpacking
    import common.wld_packing as wld_packing
except ImportError:
    print(
        "Error: The 'common' folder containing wld_unpacking and wld_packing modules was not found."
    )
    sys.exit(1)

# --- POT (Power of Two) LOGIC ---


def next_power_of_two(n):
    """Returns the nearest power of two greater than or equal to n."""
    if n <= 0:
        return 2
    # If it is already a power of two, return as is
    if (n & (n - 1) == 0) and n > 0:
        return n
    return 1 << (n.bit_length() - 1)


def fix_shadow_data(item):
    """
    Accepts a world element object (node).
    If it has a shadow, extends it to POT (32x16, 64x64, etc.).
    Returns True if changes were made.
    """
    shad = item.get("shadow")
    if not shad:
        return False

    w = shad["size1"]
    h = shad["size2"]
    data = shad["data"]  # This is a list of numbers (uint16)

    # 1. Calculate new dimensions (minimum 4x4 for safety)
    pot_w = max(1, next_power_of_two(w))
    pot_h = max(1, next_power_of_two(h))

    # If dimensions are already perfect, skip
    if pot_w == w and pot_h == h:
        return False

    # 2. Create a new buffer
    # Fill "emptiness" with 0xFFFF (White, Opaque).
    # This corresponds to the "no shadow" value in original files.
    PADDING_PIXEL = 0xFFFF

    new_data = []

    # 3. Transfer pixels
    # Note: 'data' may contain slightly more elements due to read alignment,
    # but we are interested only in the first w*h pixels.

    for y in range(pot_h):
        for x in range(pot_w):
            if x < w and y < h:
                # Copy pixel from the old image
                src_idx = y * w + x
                if src_idx < len(data):
                    val = data[src_idx]
                else:
                    val = PADDING_PIXEL  # In case of index failure
                new_data.append(val)
            else:
                # Fill new areas
                new_data.append(PADDING_PIXEL)

    # 4. Update data in the object
    shad["size1"] = pot_w
    shad["size2"] = pot_h
    shad["data"] = new_data

    print(f"  Fixed shadow: {w}x{h} -> {pot_w}x{pot_h}")
    return True


def process_wld(input_path, output_path):
    print(f"Reading file: {input_path} ...")

    # 1. UNPACKING
    try:
        # unpack_wld_to_data returns a dictionary with all resources
        data = wld_unpacking.unpack_wld_to_data(input_path)
    except Exception as e:
        print(f"Error during unpacking: {e}")
        return

    # 2. DATA PREPARATION FOR PACKER
    # The unpacker separates metadata (_info) and raw bytes (raw_).
    # The packer expects raw_bytes to be inside _info dictionaries.
    # We need to merge them.

    # Merging textures
    if "texture_pages_info" in data and "raw_textures" in data:
        data["texture_pages"] = data["texture_pages_info"]
        if len(data["texture_pages"]) == len(data["raw_textures"]):
            for i, page in enumerate(data["texture_pages"]):
                page["raw_bytes"] = data["raw_textures"][i]["raw_bytes"]
        else:
            print("Warning: Mismatch in number of texture pages!")

    # Merging models
    if "models_info" in data and "raw_models" in data:
        if len(data["models_info"]) == len(data["raw_models"]):
            for i, model in enumerate(data["models_info"]):
                model["raw_bytes"] = data["raw_models"][i]["raw_bytes"]
        else:
            print("Warning: Mismatch in number of models!")

    # 3. FIXING SHADOWS
    print("Fixing shadows (POT Fix)...")
    fixed_count = 0
    total_shadows = 0

    if "world_tree" in data:
        for item in data["world_tree"]:
            if "shadow" in item:
                total_shadows += 1
                if fix_shadow_data(item):
                    fixed_count += 1

    print(f"Total shadows: {total_shadows}")
    print(f"Fixed (resized): {fixed_count}")

    # 4. PACKING
    print(f"Writing file: {output_path} ...")
    try:
        binary_data = wld_packing.pack_wld_data(data)
        with open(output_path, "wb") as f:
            f.write(binary_data)
        print("Done!")
    except Exception as e:
        print(f"Error during packing: {e}")
        # For debugging, uncomment:
        # import traceback
        # traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_all_shadows.py <input.wld> [output.wld]")
    else:
        inp = sys.argv[1]
        out = sys.argv[2] if len(sys.argv) > 2 else inp.replace(".wld", "_fixed.wld")
        process_wld(inp, out)
