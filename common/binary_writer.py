# -*- coding: utf-8 -*-

import struct

ENCODING = "cp1252"  # Windows-1252 for strings


class BinaryWriter:
    """
    Class for sequential data writing to a binary buffer.
    """

    def __init__(self):
        self.data = bytearray()

    def push_bytes(self, b):
        self.data.extend(b)

    def push_int(self, val):
        self.data.extend(struct.pack("<i", int(val)))

    def push_ints(self, vals):
        for v in vals:
            self.push_int(v)

    def push_float(self, val):
        self.data.extend(struct.pack("<f", float(val)))

    def push_floats(self, vals):
        for v in vals:
            self.push_float(v)

    def push_bool(self, val):
        self.push_int(-1 if val else 0)

    def push_word(self, val):
        if len(val) != 4:
            raise ValueError(f"Word must be 4 chars: {val}")
        self.data.extend(val.encode("ascii"))

    def push_string(self, val):
        encoded = val.encode(ENCODING) + b"\x00"
        self.data.extend(encoded)
        while len(self.data) % 4 != 0:
            self.data.extend(b"\x00")

    def push_hex(self, hex_str):
        self.data.extend(bytes.fromhex(hex_str))

    def push_big_endian_int(self, size):
        # Block sizes are written as Big-Endian
        self.data.extend(struct.pack(">I", size))

    def push_uint16(self, val):
        # Write as unsigned short (2 bytes) little-endian
        self.data.extend(struct.pack("<H", int(val)))

    def push_uints16(self, vals):
        for v in vals:
            self.push_uint16(v)

    def get_data(self):
        return self.data
