#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) JSON to NMF Packer

Description:
    This script compiles JSON data back into the binary NMF format used by the game.
    It reads the structured text data and uses the builder library to generate
    a valid game-ready model file.

    Features:
    - Converts edited JSON files back to binary NMF.
    - Validates input structure before packing.
    - Utilizes `nmf_builder.py` for accurate binary construction.
    - Strict command-line argument handling for safe file operations.

License: MIT License

Usage:
    python json_to_nmf.py <input.json> <output.nmf>
"""

import json
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import NmfBuilder


def convert_json_to_nmf(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"Error: File {input_path} not found.")
        return

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        builder = NmfBuilder()
        builder.pack(data, output_path)

        print(f"Success: Built {output_path} from {input_path}")

    except Exception as e:
        print(f"Error packing {input_path}: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python json_to_nmf.py <input.json> <output.nmf>")
    else:
        convert_json_to_nmf(sys.argv[1], sys.argv[2])
