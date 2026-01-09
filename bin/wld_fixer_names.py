#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) World Names fixer

Description:
    This standalone utility addresses character encoding issues within proprietary
    .wld (World) files. It parses the binary structure in-memory to identify
    and sanitize string values containing Windows-1252 special characters
    (e.g., 'ß' -> 'b', 'ä' -> 'a', 'ö' -> 'o', 'ü' -> 'u').

    Key features:
    - Merges metadata with raw binary data to prevent data loss.
    - Scans and fixes texture file paths in Texture Pages (TEXP chunks).
    - Parses embedded raw NMF 3D models to fix internal material and
      texture names that may cause encoding errors or packing failures.
    - Repacks the sanitized data into a clean .wld file without requiring
      full extraction to disk.

License: MIT License

Usage:
    python wld_fixer_names.py <input_file.wld> <output_file.wld>
"""

import os
import sys
import tempfile
import re

# Add path to modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from common.wld_unpacking import unpack_wld_to_data
    from common.wld_packing import pack_wld_data
    from common.nmf_parser import Nmf
    from common.nmf_builder import NmfBuilder
except ImportError as e:
    print("Import error: ensure the 'common' folder is located next to the script.")
    print(f"Details: {e}")
    sys.exit(1)


def fix_string(text):
    """
    Replaces windows-1252 special characters with ASCII equivalents.
    """
    if not text or not isinstance(text, str):
        return text

    # Replacement dictionary according to your request
    replacements = {
        "ß": "b",
        "ä": "a",
        "ö": "o",
        "ü": "u",
        "ÿ": "y",
        # Uppercase (just in case)
        "Ä": "A",
        "Ö": "O",
        "Ü": "U",
    }

    original = text
    for char, repl in replacements.items():
        text = text.replace(char, repl)

    if original != text:
        print(f"    [RENAME] '{original}' -> '{text}'")
    return text


def merge_models(models_info, raw_models):
    """
    Merges model metadata with their raw bytes (NMF).
    """
    # Create a dictionary for quick lookup by index
    raw_map = {item["index"]: item["raw_bytes"] for item in raw_models}

    merged_count = 0
    for model in models_info:
        idx = model["index"]
        if idx in raw_map:
            model["raw_bytes"] = raw_map[idx]
            merged_count += 1
        else:
            print(
                f"WARNING: raw_bytes not found for model index {idx} ({model.get('name')})"
            )

    print(f"  Models merged: {merged_count}")
    return models_info


def merge_textures(pages_info, raw_textures):
    """
    Merges texture page metadata with their raw bytes (DDS).
    """
    # In pages_info key is 'id', in raw_textures key is 'page_id'
    raw_map = {item["page_id"]: item["raw_bytes"] for item in raw_textures}

    merged_count = 0
    for page in pages_info:
        page_id = page["id"]
        if page_id in raw_map:
            page["raw_bytes"] = raw_map[page_id]
            merged_count += 1
        else:
            print(f"WARNING: raw_bytes not found for page ID {page_id}")

    print(f"  Texture pages merged: {merged_count}")
    return pages_info


def process_nmf_data(raw_bytes, model_name="unknown"):
    """
    Unpacks NMF, fixes texture names, packs back.
    """
    # NMF parser works with files, using temporary ones
    with tempfile.NamedTemporaryFile(delete=False, suffix=".nmf") as tmp_in:
        tmp_in.write(raw_bytes)
        tmp_in_path = tmp_in.name

    try:
        parser = Nmf()
        try:
            nodes = parser.unpack(tmp_in_path)
        except Exception as e:
            print(f"  [Error] Model parsing failed '{model_name}': {e}")
            return raw_bytes

        modified = False

        # Iterate through NMF nodes
        for node in nodes:
            # 1. If it is MESH, it may contain materials with textures
            if node.get("word") == "MESH":
                data = node.get("data", {})
                materials = data.get("materials", [])
                for mat in materials:
                    # Check texture name inside material
                    if "texture" in mat:
                        tex = mat["texture"]
                        if "name" in tex:
                            new_name = fix_string(tex["name"])
                            if new_name != tex["name"]:
                                tex["name"] = new_name
                                modified = True

        if not modified:
            return raw_bytes

        # Pack back
        with tempfile.NamedTemporaryFile(delete=False, suffix=".nmf") as tmp_out:
            tmp_out_path = tmp_out.name

        builder = NmfBuilder()
        builder.pack(nodes, tmp_out_path)

        with open(tmp_out_path, "rb") as f:
            new_bytes = f.read()

        os.unlink(tmp_out_path)
        return new_bytes

    except Exception as e:
        print(f"  [Error] Error processing NMF '{model_name}': {e}")
        return raw_bytes
    finally:
        if os.path.exists(tmp_in_path):
            os.unlink(tmp_in_path)


def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_wld_encoding.py <input.wld> [output.wld]")
        return

    input_path = sys.argv[1]
    output_path = (
        sys.argv[2] if len(sys.argv) > 2 else input_path.replace(".wld", "_ascii.wld")
    )

    if not os.path.exists(input_path):
        print(f"File {input_path} not found.")
        return

    print(f"--- 1. Reading and unpacking {input_path} ---")
    wld_data = unpack_wld_to_data(input_path)

    # === DATA MERGING STAGE ===
    # This fixes the 'Missing raw_bytes' error
    print("--- 2. Merging raw data and metadata ---")

    # 1. Textures
    # Packer expects 'texture_pages' key containing everything together
    if "texture_pages_info" in wld_data and "raw_textures" in wld_data:
        wld_data["texture_pages"] = merge_textures(
            wld_data["texture_pages_info"], wld_data["raw_textures"]
        )

    # 2. Models
    # Packer uses models_info, expecting raw_bytes there
    if "models_info" in wld_data and "raw_models" in wld_data:
        wld_data["models_info"] = merge_models(
            wld_data["models_info"], wld_data["raw_models"]
        )

    # === CHARACTER REPLACEMENT STAGE ===
    print("\n--- 3. Character replacement (ß->b, ä->a, etc.) ---")

    # A. In texture page paths (WLD TEXP)
    count_tex_wld = 0
    if "texture_pages" in wld_data:
        for page in wld_data["texture_pages"]:
            for tex in page.get("textures", []):
                if "filepath" in tex:
                    old = tex["filepath"]
                    tex["filepath"] = fix_string(tex["filepath"])
                    if old != tex["filepath"]:
                        count_tex_wld += 1
    print(f"  Fixed paths in WLD TEXP: {count_tex_wld}")

    # B. Inside 3D models (NMF MTRL)
    count_models = 0
    if "models_info" in wld_data:
        for model in wld_data["models_info"]:
            if "raw_bytes" in model:
                model_name = model.get("name", "unknown")
                # Processing NMF binary data
                new_nmf = process_nmf_data(model["raw_bytes"], model_name)
                # If data changed (size or content), update
                if new_nmf != model["raw_bytes"]:
                    model["raw_bytes"] = new_nmf
                    count_models += 1
    print(f"  Fixed 3D models (NMF): {count_models}")

    # === PACKING STAGE ===
    print(f"\n--- 4. Packing to {output_path} ---")
    try:
        new_binary = pack_wld_data(wld_data)
        with open(output_path, "wb") as f:
            f.write(new_binary)
        print("Successfully completed.")
    except Exception as e:
        print(f"CRITICAL PACKING ERROR: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
