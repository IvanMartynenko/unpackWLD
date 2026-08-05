#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting!) NMF Anti-Ground Patcher

Description:
    This script automates the calculation of physics/collision data (Anti-Ground)
    for NMF 3D models. It reads an existing NMF file, recalculates the bounding box
    for every MESH node, updates the collision fields, and saves a new NMF file.

    Logic:
    1. Parses .nmf to dictionary structure.
    2. Finds 'MESH' nodes.
    3. Calculates Axis-Aligned Bounding Box (AABB) from 'vertices'.
    4. Writes Min/Max points to 'collision_vertices'.
    5. Sets 'collision_indices' to [0, 1].
    6. Re-packs into binary .nmf.

Usage:
    python nmf_antiground_patcher.py <input.nmf> <output.nmf>
"""

import os
import sys

# Add path to the common folder to import the parser and builder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from common.nmf_parser import Nmf
    from common.nmf_builder import NmfBuilder
except ImportError:
    print("Error: Could not import 'common.nmf_parser' or 'common.nmf_builder'.")
    print("Make sure this script is placed correctly relative to the 'common' folder.")
    sys.exit(1)


def calculate_aabb(vbuf):
    """
    Calculates the AABB (Axis-Aligned Bounding Box) for a list of vertices.
    Returns a list of 6 floats (MinX, MinY, MinZ, MaxX, MaxY, MaxZ)
    and a list of indices [0, 1].
    """
    if not vbuf:
        return None, None

    # vbuf is a list of lists, where the first 3 elements are X, Y, Z.
    # Example: [[x, y, z, nx, ny, nz...], ...]

    # Extract coordinates only
    xs = [v[0] for v in vbuf]
    ys = [v[1] for v in vbuf]
    zs = [v[2] for v in vbuf]

    min_point = [min(xs), min(ys), min(zs)]
    max_point = [max(xs), max(ys), max(zs)]

    # Form a list of floats: [MinPoint..., MaxPoint...]
    # This creates the box diagonal that the engine uses for collision
    floats_data = min_point + max_point

    # Indices [0, 1] tell the engine to use the 1st (Min) and 2nd (Max) points from the list above
    ints_data = [0, 1]

    return floats_data, ints_data


def patch_nmf_antiground(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"Error: File {input_path} not found.")
        return

    print(f"Reading {input_path}...")

    try:
        # 1. Unpacking (Reading)
        parser = Nmf()
        nodes = parser.unpack(input_path)

        mesh_count = 0
        patched_count = 0

        # 2. Data modification
        for node in nodes:
            # Look for MESH type nodes
            if node.get("type") == "MESH":
                mesh_data = node.get("payload", {})
                vbuf = mesh_data.get("vertices")

                if vbuf and len(vbuf) > 0:
                    mesh_count += 1

                    # Calculate physics
                    col_floats, col_ints = calculate_aabb(vbuf)

                    if col_floats:
                        mesh_data["collision_vertices"] = col_floats
                        mesh_data["collision_indices"] = col_ints

                        patched_count += 1

        print(
            f"Processed {mesh_count} meshes. Patched physics for {patched_count} meshes."
        )

        # 3. Packing (Writing)
        print(f"Writing to {output_path}...")
        builder = NmfBuilder()
        builder.pack(nodes, output_path)

        print("Done!")

    except Exception as e:
        print(f"Critical Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python nmf_antiground_patcher.py <input.nmf> <output.nmf>")
        print("Example: python nmf_antiground_patcher.py wall.nmf wall_fixed.nmf")
    else:
        patch_nmf_antiground(sys.argv[1], sys.argv[2])
