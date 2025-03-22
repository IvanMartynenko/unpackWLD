#!/usr/bin/env ruby

# Copies 'length' bytes from the source (using slicing).
def copy_data(src, length)
  src[0, length]
end

# Decompresses the data using a custom bitmask-driven algorithm.
#
# The data parameter is a binary string containing the block header:
#   - Bytes 0-3: block_size (unsigned 32-bit little-endian).
#   - Bytes 4-7: flag field (only the first byte is used).
#   - Bytes 8-end: compressed data stream.
#
# When flag == 1, the block is uncompressed (raw copy, size = block_size - 4).
# Otherwise, for each 16-bit bitmask loaded from the stream:
#   - A 0 bit means copy one literal byte.
#   - A 1 bit means read a token and an offset low byte.
#     The token's high nibble (shifted left by 4) plus the offset low byte
#     give the offset into the already decompressed output.
#     The low nibble plus one is the number of bytes to copy.
#
# Returns an array of decompressed bytes (integers 0–255).
def decompress_data(data)
  # Parse block header.
  block_size = data[0, 4].unpack("L").first  # unsigned 32-bit little-endian
  flag = data[4, 4].unpack("C").first          # only the first byte matters

  src_index = 8
  src_end_index = 4 + block_size
  output = []

  # If flag equals 1, perform a raw copy.
  if flag == 1
    literal_data = data[src_index, block_size - 4]
    output.concat(literal_data.bytes)
    return output
  end

  bit_mask = 0
  bit_count = 0

  while src_index < src_end_index && src_index < data.bytesize
    # Refill the bitmask when exhausted.
    if bit_count == 0
      break if src_index + 2 > data.bytesize
      bit_mask = data[src_index, 2].unpack("v").first  # little-endian unsigned short
      src_index += 2
      bit_count = 16
    end

    if (bit_mask & 1) == 0
      # Literal: copy one byte directly.
      byte_val = data.getbyte(src_index)
      break if byte_val.nil?
      output << byte_val
      src_index += 1
    else
      # Compressed token: read token and offset low byte.
      token = data.getbyte(src_index)
      raise "Unexpected end of data: token missing" if token.nil?
      src_index += 1

      offset_low = data.getbyte(src_index)
      raise "Unexpected end of data: offset_low missing" if offset_low.nil?
      src_index += 1

      # Compute the offset: the high nibble of token shifted left by 4 plus offset_low.
      offset = ((token & 0xF0) << 4) + offset_low
      copy_length = (token & 0x0F) + 1

      copy_source_index = output.size - offset
      raise "Invalid offset: #{offset} is too large" if copy_source_index < 0

      copy_length.times do |i|
        output << output[copy_source_index + i]
      end
    end

    bit_mask >>= 1
    bit_count -= 1
  end

  output
end

# Processes a compressed file.
#
# The file is expected to have the following layout:
#   - Bytes 0-3: signature (should be 0, 0, 7, 0).
#   - Bytes 4-7: decompressed size (unsigned 32-bit little-endian).
#   - Bytes 8-end: compressed block header and data.
#
# After decompression, the first 'decompressed_size' bytes of the output are
# inverted (each byte bitwise negated).
#
# Returns the final processed data as a binary string.
def process_compressed_file(filename)
  file_data = File.binread(filename)
  if file_data.bytesize < 8
    puts "File too short"
    return nil
  end

  signature = file_data[0, 4].bytes
  unless signature == [0, 0, 7, 0]
    puts "Invalid signature"
    return nil
  end

  # Read decompressed size from bytes 4-7.
  decompressed_size = file_data[4, 4].unpack("L").first
  # The compressed block header begins at byte 8.
  compressed_data = file_data[8..-1]

  # Decompress the data.
  decompressed_bytes = decompress_data(compressed_data)

  # Invert the first decompressed_size bytes.
  decompressed_bytes[0...decompressed_size] = decompressed_bytes[0...decompressed_size].map do |b|
    (~b) & 0xFF
  end

  # Return the processed data as a binary string.
  decompressed_bytes.pack("C*")
end

files = Dir.glob("Dialogs_*.txt")
files.each do |filename|
  next if filename.include?("decompressed")

  result = process_compressed_file(filename)
  if result
    # Replace the .txt extension with _decompressed.txt
    output_filename = filename.sub(/\.txt$/, '_decompressed.txt')
    File.binwrite(output_filename, result)
    puts "Decompression and processing completed for #{filename} -> #{output_filename}"
  else
    puts "Failed processing file: #{filename}"
  end
end