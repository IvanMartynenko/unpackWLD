#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) Texture Extractor

Description:
    This script parses the main game resource container (wld) of "Der Clou! 2".
    It identifies texture pages ('PAGE' blocks), generates a fast lookup table for
    A1R5G5B5 color conversion, and extracts textures.

    Features:
    - Extracts full texture atlases and individual sub-textures.
    - Converts 16-bit A1R5G5B5 textures to standard TIFF, PNG or DDS.
    - Supports cross-platform path handling (Windows/Linux).
    - Can list unique internal folder paths without extraction.

License: MIT License

Usage:
    python extract_textures.py <input_file> [options]
"""

import sys
import os
import struct
import argparse
import zlib
import io

DDS_MAGIC = 0x20534444
COLOR_LUT = []


def init_lookup_table():
    """
    Generates a lookup table for A1R5G5B5 -> RGBA conversion.
    Calculates all 65536 possible 16-bit color values once to speed up processing.
    """
    global COLOR_LUT
    if COLOR_LUT:
        return

    COLOR_LUT = [None] * 65536

    for pixel in range(65536):
        a_bit = (pixel & 0x8000) >> 15

        # Expand 5-bit color to 8-bit
        r = ((pixel & 0x7C00) >> 10) * 255 // 31
        g = ((pixel & 0x03E0) >> 5) * 255 // 31
        b = (pixel & 0x001F) * 255 // 31
        a = 255 if a_bit else 0

        COLOR_LUT[pixel] = struct.pack("4B", r, g, b, a)


init_lookup_table()


def read_int(stream):
    return struct.unpack("<i", stream.read(4))[0]


def read_word(stream):
    return stream.read(4).decode("ascii", errors="ignore")


def read_bool(stream):
    return read_int(stream) == -1


def read_string(stream, data_ref):
    start_offset = stream.tell()
    null_index = data_ref.find(b"\0", start_offset)

    if null_index == -1:
        raise ValueError("Null terminator not found for string")

    length = null_index - start_offset
    name_bytes = stream.read(length)
    stream.seek(1, 1)

    # Align to 4-byte boundary
    current_pos = stream.tell()
    remainder = current_pos % 4
    if remainder != 0:
        stream.read(4 - remainder)

    try:
        return name_bytes.decode("cp1252")
    except UnicodeDecodeError:
        return name_bytes.decode("utf-8", errors="replace")


def parse_box(stream):
    return {
        "x0": read_int(stream),
        "y0": read_int(stream),
        "x2": read_int(stream),
        "y2": read_int(stream),
    }


def create_dds_header(width, height, has_alpha):
    flags = (
        0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x8
    )  # CAPS, HEIGHT, WIDTH, PIXELFORMAT, MIPMAP, PITCH
    pf_flags = 0x40 | (0x1 if has_alpha else 0)

    header = struct.pack("<L", DDS_MAGIC)
    header += struct.pack("<L", 124)
    header += struct.pack("<L", flags)
    header += struct.pack("<L", height)
    header += struct.pack("<L", width)
    header += struct.pack("<L", width * 2)
    header += struct.pack("<L", 0)
    header += struct.pack("<L", 1)
    header += struct.pack("<11L", *([0] * 11))

    header += struct.pack("<L", 32)
    header += struct.pack("<L", pf_flags)
    header += struct.pack("<L", 0)
    header += struct.pack("<L", 16)
    header += struct.pack("<L", 0x7C00)
    header += struct.pack("<L", 0x03E0)
    header += struct.pack("<L", 0x001F)
    header += struct.pack("<L", 0x8000 if has_alpha else 0)

    header += struct.pack("<L", 0x1000)
    header += struct.pack("<L", 0) * 4
    return header


def make_png_chunk(tag, data):
    chunk = struct.pack(">I", len(data)) + tag + data
    crc = zlib.crc32(tag)
    crc = zlib.crc32(data, crc)
    chunk += struct.pack(">I", crc & 0xFFFFFFFF)
    return chunk


def convert_a1r5g5b5_to_rgba_fast(raw_bytes, width, height, png_mode=True):
    """
    Converts raw 16-bit data to 32-bit RGBA.
    If png_mode is True, prepends \x00 filter byte to each row for PNG writer.
    If png_mode is False, returns raw RGBA bytes for TIFF/DDS.
    """
    count = width * height
    shorts = struct.unpack(f"<{count}H", raw_bytes)
    scanlines = []

    # Process row by row for performance
    for y in range(height):
        row_start = y * width
        row_end = row_start + width
        row_shorts = shorts[row_start:row_end]

        # LUT lookup
        row_pixels = [COLOR_LUT[val] for val in row_shorts]

        raw_row = b"".join(row_pixels)

        if png_mode:
            # Prepend PNG filter byte (0x00)
            scanlines.append(b"\x00" + raw_row)
        else:
            scanlines.append(raw_row)

    return b"".join(scanlines)


def save_png_pure(path, width, height, raw_bytes):
    # PNG mode = True to get filter bytes
    scanlines = convert_a1r5g5b5_to_rgba_fast(raw_bytes, width, height, png_mode=True)
    # Level 1 compression is much faster for large batches
    compressed = zlib.compress(scanlines, level=1)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(
            make_png_chunk(
                b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
            )
        )
        f.write(make_png_chunk(b"IDAT", compressed))
        f.write(make_png_chunk(b"IEND", b""))


def save_tiff_pure(path, width, height, raw_bytes):
    """
    Saves Uncompressed RGBA TIFF using standard library only.
    """
    # PNG mode = False to get raw RGBA
    rgba_data = convert_a1r5g5b5_to_rgba_fast(raw_bytes, width, height, png_mode=False)

    # TIFF Header (Little Endian 'II', Version 42, Offset 8)
    header = struct.pack("<2sH I", b"II", 42, 8)

    # Tags setup
    # We need offsets for data > 4 bytes.
    # BitsPerSample (8,8,8,8) is 8 bytes, so it needs to be written after the directory.

    num_entries = 11
    dir_size = 2 + (num_entries * 12) + 4  # Count + Entries + NextOffset

    # Calculate offset for "BitsPerSample" array which comes immediately after IFD
    bits_per_sample_offset = 8 + dir_size
    # Image data comes after BitsPerSample (8 bytes)
    image_data_offset = bits_per_sample_offset + 8

    tags = []
    # Tag ID, Type (3=SHORT, 4=LONG), Count, Value/Offset
    tags.append(struct.pack("<HHII", 256, 4, 1, width))  # ImageWidth
    tags.append(struct.pack("<HHII", 257, 4, 1, height))  # ImageLength
    tags.append(
        struct.pack("<HHII", 258, 3, 4, bits_per_sample_offset)
    )  # BitsPerSample (Offset)
    tags.append(struct.pack("<HHII", 259, 3, 1, 1))  # Compression (1 = None)
    tags.append(
        struct.pack("<HHII", 262, 3, 1, 2)
    )  # PhotometricInterpretation (2 = RGB)
    tags.append(struct.pack("<HHII", 273, 4, 1, image_data_offset))  # StripOffsets
    tags.append(struct.pack("<HHII", 277, 3, 1, 4))  # SamplesPerPixel (RGBA)
    tags.append(struct.pack("<HHII", 278, 4, 1, height))  # RowsPerStrip
    tags.append(struct.pack("<HHII", 279, 4, 1, len(rgba_data)))  # StripByteCounts
    tags.append(struct.pack("<HHII", 284, 3, 1, 1))  # PlanarConfiguration (1 = Chunky)
    tags.append(
        struct.pack("<HHII", 338, 3, 1, 2)
    )  # ExtraSamples (2 = Unassociated Alpha)

    # Tags must be sorted by ID (added in order above, so it's safe)

    with open(path, "wb") as f:
        f.write(header)
        f.write(struct.pack("<H", num_entries))
        for t in tags:
            f.write(t)
        f.write(struct.pack("<I", 0))  # Next IFD offset (0 = none)

        # Write BitsPerSample data (8, 8, 8, 8)
        f.write(struct.pack("<4H", 8, 8, 8, 8))

        # Write Image Data
        f.write(rgba_data)


def format_path(full_path, keep_depth):
    # Normalize slashes for Linux/Windows compatibility
    full_path = full_path.replace("\\", "/")
    parts = [p for p in full_path.split("/") if p]

    if keep_depth <= 0 or keep_depth >= len(parts):
        return parts[-1]

    return os.path.join(*parts[-(keep_depth + 1) :])


def process_file(args):
    if not os.path.exists(args.input):
        print(f"Error: File {args.input} not found.")
        return

    print(f"Reading file into memory: {args.input}...")
    with open(args.input, "rb") as f:
        content = f.read()

    stream = io.BytesIO(content)
    unique_folders = set()

    search_offset = 0
    page_count = 0

    print("Scanning for textures...")

    # Determine formats to save based on args
    formats_to_save = []
    if args.format == "all":
        formats_to_save = ["tif", "png", "dds"]
    elif args.format == "both":  # Legacy support
        formats_to_save = ["png", "dds"]
    else:
        formats_to_save = [args.format]

    while True:
        try:
            found_index = content.find(b"PAGE", search_offset)
        except Exception:
            break

        if found_index == -1:
            break

        stream.seek(found_index + 8)

        try:
            # Check version (always 2)
            if read_int(stream) != 2:
                search_offset = found_index + 4
                continue

            page_info = {}
            page_info["width"] = read_int(stream)
            page_info["height"] = read_int(stream)
            page_info["id"] = read_int(stream)

            tex_count = read_int(stream)

            # Sanity check for false positives
            if tex_count < 0 or tex_count > 10000 or page_info["width"] <= 0:
                search_offset = found_index + 4
                continue

            textures = []
            for _ in range(tex_count):
                textures.append(
                    {
                        "filepath": read_string(stream, content),
                        "box": parse_box(stream),
                        "source_box": parse_box(stream),
                    }
                )

            marker = read_word(stream)
            if marker != "TXPG":
                search_offset = found_index + 4
                continue

            page_count += 1
            if args.verbose:
                print(
                    f"[PAGE {page_info['id']}] Found {len(textures)} textures inside."
                )

            page_info["is_alpha"] = read_bool(stream)

            img_size = page_info["width"] * page_info["height"] * 2

            if stream.tell() + img_size > len(content):
                print(f"[WARN] Page {page_info['id']} data truncated.")
                break

            image_data = stream.read(img_size)
            search_offset = stream.tell()

            if args.list:
                for t in textures:
                    # Normalize slashes before extracting dirname
                    folder = os.path.dirname(t["filepath"].replace("\\", "/"))
                    if folder:
                        unique_folders.add(folder)
                continue

            out_dir = args.output
            atlas_dir = os.path.join(out_dir, "atlases")
            parts_dir = os.path.join(out_dir, "Textures")

            if not os.path.exists(atlas_dir):
                os.makedirs(atlas_dir, exist_ok=True)
            if not os.path.exists(parts_dir):
                os.makedirs(parts_dir, exist_ok=True)

            # Save Atlas
            if args.mode in ["atlas", "both"]:
                base = f"atlas_{page_info['id']}"

                for fmt in formats_to_save:
                    path = os.path.join(atlas_dir, f"{base}.{fmt}")
                    if fmt == "dds":
                        with open(path, "wb") as f:
                            f.write(
                                create_dds_header(
                                    page_info["width"],
                                    page_info["height"],
                                    page_info["is_alpha"],
                                )
                            )
                            f.write(image_data)
                    elif fmt == "tif":
                        save_tiff_pure(
                            path, page_info["width"], page_info["height"], image_data
                        )
                    elif fmt == "png":
                        save_png_pure(
                            path,
                            page_info["width"],
                            page_info["height"],
                            image_data,
                        )

            # Extract Parts
            if args.mode in ["extract", "both"]:
                full_w = page_info["width"]

                for tex in textures:
                    box = tex["box"]
                    w = box["x2"] - box["x0"]
                    h = box["y2"] - box["y0"]
                    if w <= 0 or h <= 0:
                        continue

                    clean = format_path(tex["filepath"], args.keep_paths)

                    # Split path to get directory and filename
                    fdir_rel = os.path.dirname(clean)
                    fname_base = os.path.splitext(os.path.basename(clean))[0]

                    # Create full output directory
                    fdir = os.path.join(parts_dir, fdir_rel)
                    os.makedirs(fdir, exist_ok=True)

                    # Extract raw bytes
                    rows = []
                    row_len = w * 2
                    for y in range(box["y0"], box["y2"]):
                        off = (y * full_w + box["x0"]) * 2
                        rows.append(image_data[off : off + row_len])
                    sub_bytes = b"".join(rows)

                    for fmt in formats_to_save:
                        ext = f".{fmt}"
                        final_filename = f"{fname_base}{ext}"
                        full_path = os.path.join(fdir, final_filename)

                        # --- Renaming Logic ---
                        if args.naming == "always":
                            final_filename = f"{fname_base}_{page_info['id']}{ext}"
                            full_path = os.path.join(fdir, final_filename)

                        elif args.naming == "if_exists":
                            if os.path.exists(full_path):
                                final_filename = f"{fname_base}_{page_info['id']}{ext}"
                                full_path = os.path.join(fdir, final_filename)

                        # Save File
                        if fmt == "dds":
                            with open(full_path, "wb") as f:
                                f.write(create_dds_header(w, h, True))
                                f.write(sub_bytes)
                        elif fmt == "tif":
                            save_tiff_pure(full_path, w, h, sub_bytes)
                        else:  # png
                            save_png_pure(full_path, w, h, sub_bytes)

        except Exception as e:
            if args.verbose:
                print(f"[ERROR] Parsing error at {found_index}: {e}")
            search_offset = found_index + 4
            continue

    if args.list:
        print(f"Found {len(unique_folders)} unique folders:")
        for folder in sorted(unique_folders):
            print(folder)

    print(f"Done. Processed {page_count} pages.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract textures from Der Clou! 2 (The Sting!) game file."
    )
    parser.add_argument("input", help="Input game file (e.g. data.bin)")
    parser.add_argument(
        "-o", "--output", default="output_textures", help="Output directory"
    )
    parser.add_argument(
        "-l", "--list", action="store_true", help="List unique folders found in file"
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["dds", "png", "tif", "all", "both"],
        default="tif",
        help="Output image format (default: tif)",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=["atlas", "extract", "both"],
        default="both",
        help="Extraction mode",
    )
    parser.add_argument(
        "-k",
        "--keep-paths",
        type=int,
        default=0,
        help="Folder depth to preserve in output paths",
    )
    parser.add_argument(
        "--naming",
        choices=["overwrite", "if_exists", "always"],
        default="overwrite",
        help="Naming strategy",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose debug output"
    )

    args = parser.parse_args()
    process_file(args)
