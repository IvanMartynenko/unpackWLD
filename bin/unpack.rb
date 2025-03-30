require 'fileutils'
require 'json'
require_relative '../lib/system_folder_manager'
require_relative '../lib/parser'

DDS_MAGIC = 0x20534444
@threads = []

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

def write_binary(filepath, items, separator)
  file = File.open(filepath, 'wb')
  items.each do |item|
    file&.write(separator)
    file&.write([item.size].pack('N'))
    file&.write(item)
  end
  file.close
end

def write_json_file(filepath, data)
  @threads << Thread.new do
    time = Time.now
    file = File.open(filepath, 'w')
    file&.write JSON.pretty_generate(data)
    file.close
    puts "End save #{filepath}. Times: #{Time.now - time}"
  end
end

def get_texture_pages_info(data)
  data.map do |p|
    p.reject { |key, _| key == :image_binary }
  end
end

def save_dds_texture_page(folder_manager, page)
  file = File.open(folder_manager.texture_page_path(page[:iid]), 'wb')
  if file
    dds_header = save_to_binary_file(init_dds_header(page[:width], page[:height], page[:is_alpha])).join
    file.write(dds_header)
    file.write(page[:image_binary].pack('H*'))
  end
  file.close
end

def world_withot_shadows(old_world, objects, models)
  world = old_world.dup
  world.each do |_key, new_hash|
    new_hash.delete(:shad)
    new_hash[:object_name] = objects[new_hash[:object_id] - 1][:name] if new_hash[:object_id]
    new_hash[:model_name] = models[new_hash[:model_id] - 2][:name] if new_hash[:model_id]
  end
  world
end

def world_to_shadow(word)
  word.filter_map do |key, hash|
    { index: key, shad: hash[:shad] } if hash[:shad]
  end
end

# A small helper to build a node with the appropriate name and an empty :child hash
def build_node(value)
  res = {}
  %i[folder_name object_name model_name].each do |k|
    res[:name] = value[k] if value[k]
  end
  res[:child] = {}
  res
  # # Pick the first of :folder_name, :object_name, :model_name that isn't nil
  # name_key = %i[folder_name object_name model_name].find { |key| v[key] }
  # {
  #   name: name_key ? v[name_key] : nil,
  #   child: {}
  # }
end

def save_world_view(filepath, world)
  res  = {}
  path = {}

  world.each do |k, v|
    node = build_node(v)

    if v[:parent_iid] == '1'
      res[k.to_sym] = node
    else
      parent_id = v[:parent_iid].to_sym
      # Attach this node to its parent's :child hash
      path[parent_id][:child][k.to_sym] = node
    end
    path[k.to_sym] = node
  end

  write_json_file(filepath, res)
end

def unpack(filepath)
  start_time = Time.now
  folder_manager = SystemFolderManager.new(filepath)
  folder_manager.create_directories
  time = Time.now
  parser = Parser.new(filepath)
  parser.processed
  puts "End parse file. Time: #{Time.now - time}"

  folder_manager.push_model_directories(parser.model_list_tree)
  folder_manager.create_model_directories

  write_json_file(folder_manager.files[:model_list_tree], parser.model_list_tree)
  write_json_file(folder_manager.files[:object_list_tree], parser.object_list_tree)
  write_json_file(folder_manager.files[:object_list], parser.objects)

  # save shadows
  write_json_file(folder_manager.files[:shadows], world_to_shadow(parser.word_tree))
  # save world
  write_json_file(folder_manager.files[:world_tree],
                  world_withot_shadows(parser.word_tree, parser.objects, parser.models))
  save_world_view(folder_manager.files[:world_view], parser.word_tree)

  # SAVE TEXTURES
  @threads << Thread.new do
    write_json_file(folder_manager.files[:texture_pages], get_texture_pages_info(parser.texture_pages))
    parser.texture_pages.each { |page| save_dds_texture_page(folder_manager, page) }
  end

  # MODELS
  @threads << Thread.new do
    hash = parser.models.map { |p| p.except(:nmf) }
    write_json_file(folder_manager.files[:models_info], hash)
  end

  # save models files
  time = Time.now
  @threads << Thread.new do
    parser.models.each do |model|
      file = File.open(folder_manager.model_path(model[:name], model[:index], model[:parent_folder_iid]), 'w')
      file&.write(JSON.pretty_generate(model[:nmf]))
      file.close
    end
  end
  @threads.each(&:join)
  puts "End save model files. Times: #{Time.now - time}"
  puts "Total times: #{Time.now - start_time}"
end

script_location = File.dirname(File.expand_path(__FILE__))
# filepaths = Dir.glob(File.join(script_location, '*.wld'))
filepaths = Dir.glob(File.join(File.join(script_location, '..'), '*.wld'))
filepaths.each do |f|
  unpack(f)
end
