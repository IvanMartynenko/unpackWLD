require 'json'
require_relative 'base_file_saver'

DDS_MAGIC = 0x20534444

class DdsFileSaver < BaseFileSaver
  def save(data)
    @file.write dds_header(data[:width], data[:height], data[:is_alpha])
    @file.write(data[:image_binary].pack('H*'))
  end

  private

  # TEXTURES
  def dds_header(width, height, is_alpha)
    # Reserved array of 11 integers (DWORDs)
    reserved1 = Array.new(11, 0)

    # Pixel format as an array with the following order:
    # [dw_size, dw_flags, dw_four_cc, dw_rgb_bit_count, dw_r_bit_mask, dw_g_bit_mask, dw_b_bit_mask, dw_a_bit_mask]
    pixel_format = [
      32,            # dw_size
      65,            # dw_flags
      0,             # dw_four_cc
      16,            # dw_rgb_bit_count
      31_744,        # dw_r_bit_mask
      992,           # dw_g_bit_mask
      31,            # dw_b_bit_mask
      (is_alpha ? 32_768 : 0) # dw_a_bit_mask
    ]

    # Construct the header array according to DDS specification order:
    # magic, size, flags, height, width, pitch_or_linear_size, depth, mip_map_count,
    # reserved1 (11 values), pixel_format (8 values), caps, caps2, caps3, caps4, reserved2
    header_array = [
      DDS_MAGIC,          # magic
      124,                # size
      4111,               # flags
      height,             # height
      width,              # width
      width * 2,          # pitch_or_linear_size
      0,                  # depth
      1,                  # mip_map_count
      *reserved1,        # reserved1 (11 DWORDs)
      *pixel_format,     # pixel_format (8 DWORDs)
      4096,              # caps
      0,                 # caps2
      0,                 # caps3
      0,                 # caps4
      0                  # reserved2
    ]

    header_array.pack('L*')
  end
end
