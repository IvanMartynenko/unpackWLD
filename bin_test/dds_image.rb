require 'yaml'
require 'fileutils'
require 'mini_magick'
require_relative '../lib/system_folder_manager'

DDS_MAGIC = 0x20534444

def deep_symbolize_keys(hash)
  if hash.is_a?(Hash)
    hash.each_with_object({}) do |(key, value), result|
      new_key = key.is_a?(Symbol) ? key : key.to_sym
      result[new_key] = value.is_a?(Array) ? value.map { |t| deep_symbolize_keys(t) } : deep_symbolize_keys(value)
    end
  elsif hash.is_a?(Array)
    hash.map { |v| deep_symbolize_keys(v) }
  else
    hash
  end
end

# TEXTURES
def init_dds_header(width, height, is_alpha)
  header = {}
  header[:magic] = DDS_MAGIC
  header[:size] = 124
  header[:flags] = 4111
  header[:height] = height
  header[:width] = width
  header[:pitch_or_linear_size] = width * 2
  header[:depth] = 0
  header[:mip_map_count] = 1
  header[:reserved1] = Array.new(11, 0)

  header[:pixel_format] = {
    dw_size: 32,
    dw_flags: 65,
    dw_four_cc: 0,
    dw_rgb_bit_count: 16,
    dw_r_bit_mask: 31_744,
    dw_g_bit_mask: 992,
    dw_b_bit_mask: 31,
    dw_a_bit_mask: is_alpha ? 32_768 : 0
  }

  header[:caps] = 4096
  header[:caps2] = 0
  header[:caps3] = 0
  header[:caps4] = 0
  header[:reserved2] = 0

  header
end

def save_to_binary_file(header)
  # Prepare binary data
  binary_data = []
  binary_data << [header[:magic]].pack('L')
  binary_data << [header[:size]].pack('L')
  binary_data << [header[:flags]].pack('L')
  binary_data << [header[:height]].pack('L')
  binary_data << [header[:width]].pack('L')
  binary_data << [header[:pitch_or_linear_size]].pack('L')
  binary_data << [header[:depth]].pack('L')
  binary_data << [header[:mip_map_count]].pack('L')
  binary_data << header[:reserved1].pack('L*')

  pixel_format = header[:pixel_format]
  binary_data << [pixel_format[:dw_size]].pack('L')
  binary_data << [pixel_format[:dw_flags]].pack('L')
  binary_data << [pixel_format[:dw_four_cc]].pack('L')
  binary_data << [pixel_format[:dw_rgb_bit_count]].pack('L')
  binary_data << [pixel_format[:dw_r_bit_mask]].pack('L')
  binary_data << [pixel_format[:dw_g_bit_mask]].pack('L')
  binary_data << [pixel_format[:dw_b_bit_mask]].pack('L')
  binary_data << [pixel_format[:dw_a_bit_mask]].pack('L')

  binary_data << [header[:caps]].pack('L')
  binary_data << [header[:caps2]].pack('L')
  binary_data << [header[:caps3]].pack('L')
  binary_data << [header[:caps4]].pack('L')
  binary_data << [header[:reserved2]].pack('L')

  binary_data
end

def extract(filepath)
  folder_manager = SystemFolderManager.new(filepath)
  # Load YAML file
  data = deep_symbolize_keys YAML.load_file(folder_manager.files[:texture_pages])

  images = []
  data.each do |page|
    page[:textures].each do |info|
      filepath = info[:filepath]
      filepath.gsub!(/ß/, 'b')
      filepath.gsub!(/ä/, 'a')
      filepath.gsub!(/ö/, 'o')
      filepath.gsub!(/ü/, 'u')
      filepath.gsub!(/ÿ/, 'y')

      item = {
        filepath:,
        box: info[:box],
        source_box: info[:source_box],
        page_width: page[:width],
        page_height: page[:height],
        is_alpha: page[:is_alpha]
      }
      exists = images.select { |t| item == [t[:filepath], t[:box], t[:source_box]] }.first
      if exists
        exists[:pages_index].push(page[:index])
      else
        item[:pages_index] = [page[:index]]
        images.push(item)
      end
    end
  end

  images.each do |image|
    page_index = image[:pages_index].first
    texture_file_path = folder_manager.texture_page_path page_index
    texture_file = File.binread texture_file_path
    texture_file_pixels = texture_file[128..]

    # puts texture_file_pixels.class
    binary_data = ''
    width = image[:box][:x2] - image[:box][:x0]
    height = image[:box][:y2] - image[:box][:y0]
    texture_line_size = width * 2
    line = image[:box][:y0]
    while line < image[:box][:y2]
      offset = (image[:box][:x0] + (line * image[:page_width])) * 2

      end_offset = offset + texture_line_size - 1
      binary_data += texture_file_pixels[offset..end_offset]
      line += 1
    end

    ext = File.extname(image[:filepath])
    filename = image[:filepath].split('\\').last
    filename_without_ext = File.basename(filename, ext)
    image[:pages_index].each do |i|
      filename_without_ext += "_#{i}"
    end
    file = File.open folder_manager.texture_file("#{filename_without_ext}.dds"), 'wb'

    dds_header = save_to_binary_file(init_dds_header(width, height, image[:is_alpha])).join
    file.write(dds_header)
    file.write binary_data
    file.close
  end
end

script_location = File.dirname(File.expand_path(__FILE__))
filepaths = Dir.glob(File.join(File.join(script_location, '..'), '*_unpack'))
filepaths.each do |f|
  extract(f)
end
