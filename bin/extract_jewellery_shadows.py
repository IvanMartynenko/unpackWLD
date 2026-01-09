#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) Extract shadow

Description:
    This script extracts shadow map data from 'Jewellery' folder objects
    found within .wld resource files. It identifies the target folder
    in the object hierarchy and extracts specific shadow data blocks
    associated with those objects.

    Features:
    - Parses WRLD file structure (TREE chunks).
    - Identifies specific folder hierarchies by name.
    - Extracts compressed/raw shadow data.
    - Exports to JSON or Binary format via CLI arguments.

License: MIT License

Usage:
    python extract_jewellery_shadows.py <path_to_wld> [--format json|bin]
"""

import sys, os
import argparse
import struct
import json

# Assuming common.py exists in the same directory or parent
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import BinaryReader, BinaryWriter


TARGET_FOLDER_NAME = "Jewellery"  # Folder name to extract shadows from
OUTPUT_FILENAME_JSON = "jewellery_shadows.json"
OUTPUT_FILENAME_BIN = "jewellery_shadows.bin"


def build_jewellery_map(data):
    """Builds a list of IDs for the Jewellery folder and its descendants."""
    print(f"Searching for folder '{TARGET_FOLDER_NAME}'...")
    reader = BinaryReader(data)

    if reader.read_word() != "WRLD":
        return set()
    reader.read_int()

    tree_offset = -1
    while not reader.eof():
        token = reader.peek_word()
        if not token or token == "EOF ":
            break
        if token == "TREE":
            tree_offset = reader.offset
            break
        else:
            reader.read_word()
            reader.read_int()
            while True:
                sub = reader.read_word()
                if sub == "END ":
                    reader.read_int()
                    break
                sz = reader.read_big_endian_int()
                reader.read_bytes(sz)

    if tree_offset == -1:
        return set()

    reader.read_word()  # TREE
    reader.read_int()  # unk

    nodes = {}
    current_index = 2

    while True:
        sub = reader.read_word()
        if sub == "END ":
            break

        size = reader.read_big_endian_int()
        start = reader.offset

        reader.read_int()  # unk15
        parent_id = reader.read_int()
        name = reader.read_string()

        nodes[current_index] = {"id": current_index, "parent": parent_id, "name": name}

        reader.offset = start + size
        current_index += 1

    jewellery_id = None
    for nid, data in nodes.items():
        if data["name"] == TARGET_FOLDER_NAME and data["id"] != 119:
            # ID 119 is excluded based on specific logic
            jewellery_id = data["id"]
            break

    if not jewellery_id:
        print(f"Folder '{TARGET_FOLDER_NAME}' not found!")
        return set()

    target_ids = set()
    target_ids.add(jewellery_id)

    added = True
    while added:
        added = False
        for nid, data in nodes.items():
            if data["id"] not in target_ids and data["parent"] in target_ids:
                target_ids.add(data["id"])
                added = True

    print(f"Found {len(target_ids)} objects in branch '{TARGET_FOLDER_NAME}'.")
    return target_ids


def extract_shadows(src_path, output_format="json"):
    with open(src_path, "rb") as f:
        data = f.read()

    target_ids = build_jewellery_map(data)
    if not target_ids:
        return

    reader = BinaryReader(data)
    # Skip header
    reader.read_word()
    reader.read_int()

    extracted_shadows = []

    while not reader.eof():
        token = reader.peek_word()
        if not token or token == "EOF ":
            break

        if token == "TREE":
            print("Scanning object tree...")
            reader.read_word()
            reader.read_int()

            node_index = 2

            while True:
                sub = reader.read_word()
                if sub == "END ":
                    reader.read_int()
                    break

                size = reader.read_big_endian_int()
                start_offset = reader.offset

                reader.read_int()  # unk15
                reader.read_int()  # parent
                name = reader.read_string()  # name
                reader.read_bytes(24)  # transform
                reader.read_int()  # unk1
                type_val = reader.read_int()

                if type_val == 1:  # Model
                    reader.read_int()  # id
                    cc = reader.read_int()
                    if cc > 0:
                        reader.read_bytes(cc * 8)
                    reader.read_int()  # 0

                    shad = reader.read_word()
                    if shad == "SHAD":
                        s1 = reader.read_int()
                        s2 = reader.read_int()

                        extra = 1 if (s1 % 2 != 0 and s2 % 2 != 0) else 0
                        # IMPORTANT: size - is this the number of 4-byte blocks?
                        # In wld_shadow_aligner_v2 it was determined that bytes are (size * 4)
                        calc_size_blocks = (s1 * s2 // 2) + extra
                        total_bytes = calc_size_blocks * 4

                        raw = reader.read_bytes(total_bytes)

                        # If this shadow belongs to our target folder -> Save
                        if node_index in target_ids:
                            extracted_shadows.append(
                                {
                                    "index": node_index,
                                    "name": name,
                                    "s1": s1,
                                    "s2": s2,
                                    "data_hex": raw.hex(),
                                    "data_raw": raw,  # Store raw bytes for binary output
                                }
                            )
                    else:
                        # Skip token if not SHAD (usually 0000)
                        pass

                # Skip the rest of the node
                curr = reader.offset - start_offset
                if curr < size:
                    reader.read_bytes(size - curr)

                node_index += 1

        else:
            # Skip other blocks
            reader.read_word()
            reader.read_int()
            while True:
                sub = reader.read_word()
                if sub == "END ":
                    reader.read_int()
                    break
                sz = reader.read_big_endian_int()
                reader.read_bytes(sz)

    print(f"Extracted {len(extracted_shadows)} shadows.")

    # Saving based on format
    if output_format == "json":
        out_path = os.path.join(os.path.dirname(src_path), OUTPUT_FILENAME_JSON)

        # Prepare data for JSON (remove raw bytes object)
        json_output = []
        for item in extracted_shadows:
            json_entry = item.copy()
            del json_entry["data_raw"]  # Remove raw bytes for JSON serialization
            json_output.append(json_entry)

        with open(out_path, "w") as f:
            json.dump(json_output, f, indent=2)
        print(f"File saved: {out_path}")

    elif output_format == "bin":
        out_path = os.path.join(os.path.dirname(src_path), OUTPUT_FILENAME_BIN)
        shadow_writer = BinaryWriter()

        for sh in extracted_shadows:
            shadow_writer.push_int(sh["index"])
            shadow_writer.push_int(sh["s1"])
            shadow_writer.push_int(sh["s2"])
            # Assuming BinaryWriter has push_bytes, or we assume raw data write
            # If BinaryWriter doesn't handle raw bytes easily, we append directly
            # logic here mimics the structure: ID, S1, S2, DATA
            if hasattr(shadow_writer, "push_bytes"):
                shadow_writer.push_bytes(sh["data_raw"])
            else:
                # Fallback if specific method is missing in common.py
                # This appends raw bytes to the internal buffer
                shadow_writer.data.extend(sh["data_raw"])

        with open(out_path, "wb") as f:
            f.write(shadow_writer.get_data())
        print(f"File saved: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract shadows from WRLD file.")
    parser.add_argument("input_file", help="Path to the .wld file")
    parser.add_argument(
        "--format",
        choices=["json", "bin"],
        default="json",
        help="Output format: 'json' (default) or 'bin'",
    )

    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Error: File '{args.input_file}' not found.")
    else:
        extract_shadows(args.input_file, args.format)
