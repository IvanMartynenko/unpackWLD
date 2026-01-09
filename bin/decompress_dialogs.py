#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) Dialog Decompressor

Description:
    This script processes compressed dialog files (e.g. Dialogs_*.txt) of "Der Clou! 2".
    It handles the specific binary format which includes a signature, decompressed size,
    and a custom bitmask-driven LZ compressed stream.

    Features:
    - Verifies file signature (00 00 07 00).
    - Decompresses data using the game's custom algorithm.
    - Decrypts the output via bitwise inversion.
    - Automatically strips "Bad Food" (0xBAADF00D) debug memory padding from the end.
    - Single file processing via command line arguments.

License: MIT License

Usage:
    python decompress_dialogs.py <input_file> <output_file>
"""

import struct
import sys
import argparse


def decompress_data(data):
    """
    Decompresses the data using a custom bitmask-driven algorithm.
    """
    if len(data) < 8:
        raise ValueError("Data too short for header")

    # Parse block header
    block_size = struct.unpack("<I", data[0:4])[0]
    flag = data[4]

    src_index = 8
    src_end_index = 4 + block_size
    output = bytearray()

    if flag == 1:
        length = block_size - 4
        output.extend(data[src_index : src_index + length])
        return output

    bit_mask = 0
    bit_count = 0

    while src_index < src_end_index and src_index < len(data):
        if bit_count == 0:
            if src_index + 2 > len(data):
                break
            bit_mask = struct.unpack("<H", data[src_index : src_index + 2])[0]
            src_index += 2
            bit_count = 16

        if (bit_mask & 1) == 0:
            if src_index >= len(data):
                break
            output.append(data[src_index])
            src_index += 1
        else:
            if src_index + 1 >= len(data):
                break

            token = data[src_index]
            src_index += 1

            offset_low = data[src_index]
            src_index += 1

            offset = ((token & 0xF0) << 4) + offset_low
            copy_length = (token & 0x0F) + 1

            copy_source_index = len(output) - offset
            if copy_source_index < 0:
                # Ignore invalid offsets that might occur near corrupted ends
                break

            for i in range(copy_length):
                output.append(output[copy_source_index + i])

        bit_mask >>= 1
        bit_count -= 1

    return output


def remove_garbage(data):
    """
    Removes specific debug patterns (Bad Food) from the end of the file.
    Pattern: 0D F0 AD BA (Little Endian for 0xBAADF00D)
    """
    # Pattern: 0d f0 ad ba
    bad_food = b"\x0d\xf0\xad\xba"

    # Strip repeating patterns of BadFood
    while data.endswith(bad_food):
        data = data[:-4]

    # Also strip null terminators if any
    data = data.rstrip(b"\x00")

    return data


def process_compressed_file(filename):
    """
    Reads, verifies, decompresses, inverts, and cleans the file data.
    """
    try:
        with open(filename, "rb") as f:
            file_data = f.read()
    except IOError as e:
        print(f"Error reading file {filename}: {e}")
        return None

    if len(file_data) < 8:
        print(f"File too short: {filename}")
        return None

    signature = file_data[0:4]
    if signature != b"\x00\x00\x07\x00":
        print(f"Invalid signature in {filename}")
        return None

    decompressed_size = struct.unpack("<I", file_data[4:8])[0]
    compressed_data = file_data[8:]

    try:
        decompressed_bytes = decompress_data(compressed_data)
    except Exception as e:
        print(f"Decompression error in {filename}: {e}")
        return None

    # Invert bytes
    actual_size = len(decompressed_bytes)
    process_limit = min(decompressed_size, actual_size)

    for i in range(process_limit):
        decompressed_bytes[i] = (~decompressed_bytes[i]) & 0xFF

    # Cut off at the header's declared size first
    result = decompressed_bytes[:process_limit]

    # Clean up the specific debug garbage
    result = remove_garbage(result)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Decompress a single game dialog file."
    )
    parser.add_argument("input_file", help="Path to the source .txt file")
    parser.add_argument("output_file", help="Path where to save the decompressed file")

    args = parser.parse_args()

    result = process_compressed_file(args.input_file)

    if result is not None:
        try:
            with open(args.output_file, "wb") as f:
                f.write(result)
            print(f"Successfully processed: {args.input_file} -> {args.output_file}")
        except IOError as e:
            print(f"Error writing output file: {e}")
            sys.exit(1)
    else:
        print("Processing failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
