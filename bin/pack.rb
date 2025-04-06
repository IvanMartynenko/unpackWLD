require 'fileutils'
require 'json'
require_relative '../lib/system_folder_manager'
require_relative '../lib/file_reader'
require_relative '../lib/items/texture_pages'
require_relative '../lib/items/folders'
require_relative '../lib/items/models/models'
require_relative '../lib/items/objects'
require_relative '../lib/items/world_items'
require_relative '../lib/items/makl'
require_relative '../lib/shadows_binary_parser'

def model_filepath(info, folder_manager)
  folder_manager.model_path(info[:name], info[:index], info[:parent_folder_iid])
end

def open_texture_dds_file(id, folder_manager)
  texture_file_path = folder_manager.texture_page_path id
  File.binread texture_file_path
end

def main
  filepath = ARGV[0]
  if filepath.nil?
    puts 'Usage: Specify the path to the unpacked WLD game folder as the first parameter.'
    exit 1
  end
  start_time = Time.now
  folder_manager = SystemFolderManager.new(filepath)
  file = BinaryDataBuffer.new

  file.push_token_with_zero 'WRLD'

  textures_info = JSON.parse(File.read(folder_manager.files[:texture_pages]), symbolize_names: true)
  textures_info.each do |node|
    texture_file = open_texture_dds_file(node[:id], folder_manager)
    node[:image_binary] = texture_file[128..]
    image_height = texture_file[(4 * 4)..(4 * 4) + 3].unpack1('i')
    scale = image_height / node[:width].to_i
    node[:width] = node[:width] * scale
    node[:height] = node[:height] * scale
    node[:textures].each do |texture|
      texture[:box].each { |k, v| texture[:box][k] = v * scale }
    end
    # header = pack_texture_list(info[:textures], info[:is_alpha], scale)
  end
  file.concat Wld::Items::TexturePages.new(textures_info).to_binary

  model_folders = JSON.parse(File.read(folder_manager.files[:model_list_tree]), symbolize_names: true)
  file.concat Wld::Items::Folders.new(model_folders, 'GROU').to_binary

  object_folders = JSON.parse(File.read(folder_manager.files[:object_list_tree]), symbolize_names: true)
  file.concat Wld::Items::Folders.new(object_folders, 'OBGR').to_binary

  folder_manager.push_model_directories(model_folders)
  models_info = JSON.parse(File.read(folder_manager.files[:models_info]), symbolize_names: true)
  models_info.each do |node|
    # node[:nmf] = JSON.parse(File.read(model_filepath(node, folder_manager)), symbolize_names: true)
    node[:nmf] = File.binread(model_filepath(node, folder_manager))
  end
  file.concat Wld::Items::Models.new(models_info).to_binary

  objects = JSON.parse(File.read(folder_manager.files[:object_list]), symbolize_names: true)
  file.concat Wld::Items::Objects.new(objects).to_binary

  file.concat Wld::Items::Makl.new({}).to_binary

  shadows = ShadowsBinaryParser.new(folder_manager.files[:shadows]).parse
  world = JSON.parse(File.read(folder_manager.files[:world_tree]), symbolize_names: true)

  tmp_shadows = Array.new(shadows.last[:index].to_i + 1)
  shadows.each do |t|
    tmp_shadows[t[:index].to_i] = t
  end
  world.each do |w|
    w[:shad] = tmp_shadows[w[:index]] if w[:type] == 1 && tmp_shadows[w[:index]]
  end
  file.concat Wld::Items::WorldItems.new(world).to_binary

  file.push_eof_word
  file.push_zero

  File.open(folder_manager.pack_file_path, 'wb') do |f|
    f << file.data
  end
  puts "Pack end. Time: #{Time.now - start_time}"
end

main if __FILE__ == $PROGRAM_NAME
