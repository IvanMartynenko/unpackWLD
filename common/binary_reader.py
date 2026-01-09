# -*- coding: utf-8 -*-

import struct

ENCODING = "cp1252"  # Windows-1252 for strings


class BinaryReader:
    """
    Class for reading binary data (needed for parsing shadows.bin and DDS headers).
    """

    def __init__(self, data):
        self.data = data
        self.offset = 0
        self.size = len(data)

    def read_bytes(self, length):
        if self.offset + length > self.size:
            raise EOFError("Unexpected end of data")
        chunk = self.data[self.offset : self.offset + length]
        self.offset += length
        return chunk

    def read_int(self):
        return struct.unpack("<i", self.read_bytes(4))[0]

    def read_uint(self):
        return struct.unpack("<I", self.read_bytes(4))[0]

    def read_uint16(self):
        return struct.unpack("<H", self.read_bytes(2))[0]

    def read_big_endian_int(self):
        return struct.unpack(">I", self.read_bytes(4))[0]

    def read_float(self):
        return struct.unpack("<f", self.read_bytes(4))[0]

    def read_ints(self, count):
        return list(struct.unpack(f"<{count}i", self.read_bytes(4 * count)))

    def read_uints16(self, count):
        return list(struct.unpack(f"<{count}H", self.read_bytes(2 * count)))

    def read_floats(self, count):
        return list(struct.unpack(f"<{count}f", self.read_bytes(4 * count)))

    def read_hex(self, length):
        return self.read_bytes(length).hex()

    def read_bool(self):
        val = self.read_int()
        return val != 0  # In original: -1 is true, 0 is false.

    def read_word(self):
        return self.read_bytes(4).decode(
            "ascii", errors="ignore"
        )  # Markers like 'WRLD'

    def read_string(self):
        """Reads a null-terminated string with 4-byte alignment."""
        start = self.offset
        try:
            null_index = self.data.index(b"\x00", start)
        except ValueError:
            raise ValueError("Null terminator not found for string")

        raw_str = self.data[start:null_index]
        string_val = raw_str.decode(ENCODING)

        # Calculate new offset accounting for alignment
        self.offset = null_index + 1
        remainder = self.offset % 4
        if remainder != 0:
            self.offset += 4 - remainder

        return string_val

    def peek_word(self):
        if self.offset + 4 > self.size:
            return None
        return self.data[self.offset : self.offset + 4].decode("ascii", errors="ignore")

    def skip(self, count=4):
        self.offset += count

    def back(self, count=4):
        self.offset -= count

    def eof(self):
        return self.offset >= self.size
