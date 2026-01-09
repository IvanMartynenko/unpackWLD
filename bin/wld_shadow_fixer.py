#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) Shadow Fixer

Description:
    This tool attempts to repair corrupted shadow maps within .wld files.
    Shadow corruption often occurs due to endianness mismatches (PC vs Console)
    or format shifts (555 vs 565 color space) when moving assets between
    different versions or platforms.

    The tool analyzes the pixel variance of shadow blocks to heuristically
    detect the correct format, decodes it, and repacks it into the standard
    Little Endian 555 format used by the PC version.

Features:
    - Auto-detection of pixel formats (LE_555, BE_565, LE_565).
    - Heuristic analysis based on color noise (pixel variance).
    - Conversion of shadow data to standard X1R5G5B5 Little Endian.
    - Preserves the rest of the WLD structure intact.

License: MIT License

Usage:
    python wld_shadow_fixer.py <input.wld> [output.wld]
"""

import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import struct
from common import BinaryReader, BinaryWriter

FORCE_FIX = True


def get_pixel_variance(r, g, b):
    avg = (r + g + b) / 3.0
    return abs(r - avg) + abs(g - avg) + abs(b - avg)


def decode_shadow_buffer_auto(raw_bytes):
    """
    Determines the format (555 vs 565, LE vs BE) and returns corrected pixels.
    """

    def try_decode(mode, limit=100):
        total_var = 0
        count = 0
        check_len = min(len(raw_bytes) // 2, limit)
        for i in range(check_len):
            b1, b2 = raw_bytes[i * 2], raw_bytes[i * 2 + 1]
            val = 0
            r, g, b = 0, 0, 0

            if mode == "LE_555":  # PC Standard
                val = b1 | (b2 << 8)
                r, g, b = (val >> 10) & 0x1F, (val >> 5) & 0x1F, val & 0x1F
            elif mode == "BE_565":  # Consoles / Voodoo
                val = (b1 << 8) | b2
                r = (val >> 11) & 0x1F
                g = ((val >> 5) & 0x3F) >> 1  # Convert 6bit to 5bit
                b = val & 0x1F
            elif mode == "LE_565":
                val = b1 | (b2 << 8)
                r = (val >> 11) & 0x1F
                g = ((val >> 5) & 0x3F) >> 1
                b = val & 0x1F
            elif mode == "BE_555":
                val = (b1 << 8) | b2
                r, g, b = (val >> 10) & 0x1F, (val >> 5) & 0x1F, val & 0x1F

            total_var += get_pixel_variance(r, g, b)
            count += 1
        return total_var / count if count > 0 else 9999

    # 1. Try variants
    var_le555 = try_decode("LE_555")
    var_be565 = try_decode("BE_565")
    var_le565 = try_decode("LE_565")

    # 2. Select the best one
    # Default assumption is LE_555 (if difference is negligible)
    selected_mode = "LE_555"

    # If BE_565 is clearly better (less "color noise")
    if var_be565 < var_le555 * 0.5 and var_be565 < 5.0:
        selected_mode = "BE_565"
    elif var_le565 < var_le555 * 0.5 and var_le565 < 5.0:
        selected_mode = "LE_565"

    print(
        f"   -> Detected: {selected_mode} (Var: {min(var_le555, var_be565, var_le565):.2f})"
    )

    # 3. Decode everything in selected mode
    pixels = []
    num_pixels = len(raw_bytes) // 2
    for i in range(num_pixels):
        b1, b2 = raw_bytes[i * 2], raw_bytes[i * 2 + 1]
        val = 0
        r, g, b, x = 0, 0, 0, 1  # X default is 1 (opaque)

        if selected_mode == "LE_555":
            val = b1 | (b2 << 8)
            r, g, b, x = (
                (val >> 10) & 0x1F,
                (val >> 5) & 0x1F,
                val & 0x1F,
                (val >> 15) & 0x01,
            )
        elif selected_mode == "BE_565":
            val = (b1 << 8) | b2
            r = (val >> 11) & 0x1F
            g = ((val >> 5) & 0x3F) >> 1
            b = val & 0x1F
            x = 1  # No X in 565
        elif selected_mode == "LE_565":
            val = b1 | (b2 << 8)
            r = (val >> 11) & 0x1F
            g = ((val >> 5) & 0x3F) >> 1
            b = val & 0x1F
            x = 1
        else:
            # Fallback
            val = b1 | (b2 << 8)
            r, g, b, x = (
                (val >> 10) & 0x1F,
                (val >> 5) & 0x1F,
                val & 0x1F,
                (val >> 15) & 0x01,
            )

        pixels.append((r, g, b, x))
    return pixels


def repack_pixels_to_le555(pixels):
    """Packs back into standard X1R5G5B5 Little Endian"""
    out = bytearray()
    for r, g, b, x in pixels:
        # Clamping just in case
        r = max(0, min(31, r))
        g = max(0, min(31, g))
        b = max(0, min(31, b))
        x = max(0, min(1, x))

        # Pack: X RRRRR GGGGG BBBBB
        val = (x << 15) | (r << 10) | (g << 5) | b
        out.extend(struct.pack("<H", val))
    return out


# --- MAIN PROCESS ---


def copy_until_end(reader, writer, block_name):
    """Copies TOKEN + SIZE + DATA blocks until END is met"""
    while True:
        token = reader.read_word()
        writer.push_word(token)

        if token == "END ":
            val = reader.read_int()  # 0
            writer.push_int(val)
            break

        # For most blocks format is: Token -> Size (BE) -> Data
        # But we need to be careful with TALI/COND inside INFO, the structure is more complex.
        # Fortunately, this script works on the top level of the WRLD file.
        # Structures TEXP, GROU, OBGR, LIST, OBJS follow the rule TOKEN+SIZE+DATA

        size = reader.read_big_endian_int()
        writer.push_big_endian_int(size)

        # Copy body
        chunk = reader.read_bytes(size)
        writer.push_bytes(chunk)

        # Often there is int 0 after the body, but is it usually inside size?
        # In WLD format WRLD -> LIST -> MODL -> Size -> Data.
        # Inside unpack_models it reads: size, then int(9), int(1)...
        # So the size includes the whole body. Everything is OK.


def fix_tree_block(reader, writer):
    token = reader.read_word()  # TREE
    if token != "TREE":
        raise ValueError("Expected TREE")
    writer.push_word(token)
    writer.push_int(reader.read_int())

    node_count = 0
    fixed_count = 0

    while True:
        sub_token = reader.read_word()
        writer.push_word(sub_token)

        if sub_token == "END ":
            writer.push_int(reader.read_int())
            break

        if sub_token != "NODE":
            raise ValueError(f"Error: Unknown token in TREE: {sub_token}")

        # Read NODE size

        size = reader.read_big_endian_int()
        item_offset = reader.offset

        writer.push_big_endian_int(size)
        writer.push_int(reader.read_int())  # unknown 15
        writer.push_int(reader.read_int())  # parent_id
        writer.push_string(reader.read_string())  # folder_name
        writer.push_float(reader.read_float())  # x
        writer.push_float(reader.read_float())  # y
        writer.push_float(reader.read_float())  # z
        writer.push_float(reader.read_float())  # rotation
        writer.push_float(reader.read_float())  # unknown_n
        writer.push_float(reader.read_float())  # scaling
        writer.push_int(reader.read_int())  # unknown1

        item_type = reader.read_int()
        writer.push_int(item_type)

        if item_type != 1:  # MODEL
            item_bytes = reader.read_bytes(size - (reader.offset - item_offset))
            writer.push_bytes(item_bytes)
        else:
            writer.push_int(reader.read_int())  # model_id
            con_count = reader.read_int()
            writer.push_int(con_count)
            if con_count > 0:
                writer.push_bytes(reader.read_bytes(con_count * 8))  # connections
            writer.push_int(reader.read_int())  # 0

            # Check for SHAD presence
            shad_token = reader.read_word()

            if shad_token == "SHAD":
                # print(f"Checking Shadow in Node {node_count}...")
                s1 = reader.read_int()
                s2 = reader.read_int()
                extra = 1 if (s1 % 2 != 0 and s2 % 2 != 0) else 0
                pixel_count = (s1 * s2) + extra
                # raw_bytes = reader.read_bytes(pixel_count * 4 * 4)
                raw_bytes = reader.read_bytes(pixel_count * 2)

                # --- FIXING ---
                pixels = decode_shadow_buffer_auto(raw_bytes)
                fixed_bytes = repack_pixels_to_le555(pixels)
                fixed_count += 1
                # --------------

                writer.push_word("SHAD")
                writer.push_int(s1)
                writer.push_int(s2)
                writer.push_bytes(fixed_bytes)
                # writer.push_bytes(raw_bytes)

            else:
                writer.push_word(shad_token)  # Usually 0000 if no shadow

    # writer.push_int(reader.read_int())  # unknown1
    print(f"Tree processed. Nodes: {node_count}. Shadows fixed: {fixed_count}")


def process_file(src_path, dst_path):
    with open(src_path, "rb") as f:
        data = f.read()

    reader = BinaryReader(data)
    writer = BinaryWriter()

    header = reader.read_word()
    if header != "WRLD":
        print("Error: Not a WLD file")
        return
    writer.push_word(header)
    writer.push_int(reader.read_int())  # 0

    while not reader.eof():
        token = reader.peek_word()
        if not token:
            break

        if token == "EOF ":
            writer.push_word(reader.read_word())
            writer.push_int(reader.read_int())
            break

        print(f"Block: {token}")

        if token == "TREE":
            fix_tree_block(reader, writer)
        elif token in ["TEXP", "GROU", "OBGR", "LIST", "OBJS", "MAKL"]:
            writer.push_word(reader.read_word())
            writer.push_int(reader.read_int())
            while True:
                sub_token = reader.read_word()
                writer.push_word(sub_token)

                if sub_token == "END ":
                    val = reader.read_int()  # 0
                    writer.push_int(val)
                    break

                size = reader.read_big_endian_int()
                writer.push_big_endian_int(size)

                # Copy body
                chunk = reader.read_bytes(size)
                writer.push_bytes(chunk)
        else:
            print(f"Unknown block: {token}")
            break

    with open(dst_path, "wb") as f:
        f.write(writer.get_data())
    print(f"Done! Saved to {dst_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python wld_shadow_fixer.py <input.wld> [output.wld]")
    else:
        inp = sys.argv[1]
        out = sys.argv[2] if len(sys.argv) > 2 else inp.replace(".wld", "_fixed.wld")
        process_file(inp, out)
