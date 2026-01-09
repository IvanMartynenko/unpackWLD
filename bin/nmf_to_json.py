#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) NMF to JSON Converter

Description:
    This script converts binary NMF 3D model files into human-readable JSON format.
    It utilizes the parser to read the game's hierarchical model data and exports
    it for analysis or modification.

    Features:
    - Decodes full node hierarchy (FRAM, MESH, JOIN, MTRL).
    - Exports 3D geometry, animations, and materials to structured JSON.
    - Preserves data types for accurate re-packing.
    - Requires `nmf_parser.py` for binary reading.

License: MIT License

Usage:
    python nmf_to_json.py <input.nmf> <output.json>
"""

import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import Nmf


def convert_nmf_to_json(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"Error: File {input_path} not found.")
        return

    try:
        parser = Nmf()
        data = parser.unpack(input_path)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"Success: Converted {input_path} -> {output_path}")

    except Exception as e:
        print(f"Error processing {input_path}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python nmf_to_json.py <input.nmf> <output.json>")
    else:
        convert_nmf_to_json(sys.argv[1], sys.argv[2])
