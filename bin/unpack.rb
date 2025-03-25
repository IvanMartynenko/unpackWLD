require 'fileutils'
require 'yaml'
# require_relative '../utils'
require_relative '../lib/system_folder_manager'
require_relative '../lib/parser'

DDS_MAGIC = 0x20534444

def convert_folder(yaml)
  yaml.map do |a|
    str = a[:name]

    while a[:parent] != 1
      a = yaml[a[:parent] - 2]
      str = a[:name] + '/' + str
    end
    str
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

def deep_stringify_keys(hash)
  if hash.is_a?(Hash)
    hash.each_with_object({}) do |(key, value), result|
      new_key = key.is_a?(Symbol) ? key.to_s : key
      result[new_key] = value.is_a?(Array) ? value.map { |t| deep_stringify_keys(t) } : deep_stringify_keys(value)
    end
  elsif hash.is_a?(Array)
    hash.map { |v| deep_stringify_keys(v) }
  else
    hash
  end
end

def write_binary(filepath, items, separator)
  file = File.open(filepath, 'wb')
  items.each do |item|
    file&.write(separator)
    file&.write([item.size].pack('N'))
    file&.write(item)
  end
  file.close
end

def unpack(filepath)
  folder_manager = SystemFolderManager.new(filepath)
  folder_manager.create_directories
  parser = Parser.new(filepath)
  parser.processed

  folder_manager.push_model_directories(parser.model_list_tree)
  folder_manager.create_model_directories

  file = File.open(folder_manager.files[:model_list_tree], 'w')
  file&.write deep_stringify_keys(parser.model_list_tree).to_yaml
  file.close

  file = File.open(folder_manager.files[:object_list_tree], 'w')
  file&.write deep_stringify_keys(parser.object_list_tree).to_yaml
  file.close

  write_binary(folder_manager.files[:object_list], parser.objects, 'OBJ ')
  write_binary(folder_manager.files[:macro_list], parser.macros, 'OBJ ')
  write_binary(folder_manager.files[:world_tree], parser.word_tree, 'NODE')

  # SAVE TEXTURES
  file = File.open(folder_manager.files[:texture_pages], 'w')
  if file
    hash = parser.texture_pages.map do |p|
      {
        index: p[:index],
        width: p[:width],
        height: p[:height],
        is_alpha: p[:is_alpha],
        textures: p[:textures].map do |t|
          {
            filepath: t[:filepath],
            box: t[:box],
            source_box: t[:source_box]
          }
        end
      }
    end
    file.write(deep_stringify_keys(hash).to_yaml)
  end
  file.close

  parser.texture_pages.each do |page|
    file = File.open(folder_manager.texture_page_path(page[:index]), 'wb')
    if file
      dds_header = save_to_binary_file(init_dds_header(page[:width], page[:height], page[:is_alpha])).join
      file.write(dds_header)
      file.write(page[:binary_data].pack('H*'))
    end
    file.close
  end

  # MODELS
  file = File.open(folder_manager.files[:models_info], 'w')
  if file
    hash = parser.models.map do |p|
      p.except(:nmf)
    end
    file.write(deep_stringify_keys(hash).to_yaml)
  end
  file.close

  parser.models.each do |model|
    file = File.open(folder_manager.model_path(model[:name], model[:index], model[:parent_folder]), 'w')
    file&.write(deep_stringify_keys(model[:nmf]).to_yaml)
    file.close
  end
end

script_location = File.dirname(File.expand_path(__FILE__))
# filepaths = Dir.glob(File.join(script_location, '*.wld'))
filepaths = Dir.glob(File.join(File.join(script_location, '..'), '*.wld'))
filepaths.each do |f|
  unpack(f)
end
