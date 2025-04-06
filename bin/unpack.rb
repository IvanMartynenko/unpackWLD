#!/usr/bin/env ruby
# This script processes a WLD game file by parsing it and saving various extracted assets.

require_relative '../lib/system_folder_manager'
require_relative '../lib/file_reader'
require_relative '../lib/items/texture_pages'
require_relative '../lib/items/folders'
require_relative '../lib/items/models/models'
require_relative '../lib/items/objects'
require_relative '../lib/items/world_items'
require_relative '../lib/items/makl'
# require_relative '../lib/parsers/wld_parser'
require_relative '../lib/file_savers/json_file_saver'
require_relative '../lib/file_savers/dds_file_saver'
require_relative '../lib/file_savers/binary_file_saver'
require_relative '../lib/file_savers/shadows_file_saver'
require_relative '../lib/file_savers/world_file_saver'
require_relative '../lib/file_savers/model_file_saver'

class WldFile
  attr_reader :texture_pages, :model_folders, :object_folders, :models, :objects, :world_items

  def initialize(filepath)
    @file = FileReader.new(filepath)
    @folder_manager = SystemFolderManager.new(filepath)
  end

  def parse
    token = @file.token
    if token != 'WRLD'
      raise StandardError, "Opened file is not a 'The Sting!' game file. Expected 'WRLD', got '#{token}'"
    end

    @texture_pages = Wld::Items::TexturePages.new(@file)
    @model_folders = Wld::Items::Folders.new(@file, 'GROU')
    @object_folders = Wld::Items::Folders.new(@file, 'OBGR')
    @models = Wld::Items::Models.new(@file)
    @objects = Wld::Items::Objects.new(@file)
    Wld::Items::Makl.new(@file)
    @world_items = Wld::Items::WorldItems.new(@file)

    # raise StandardError, "Bad token in game file. Got '#{token}'"
  end
end

# Returns texture page data without the binary image content.
# This is useful for saving lightweight JSON info about each texture page.
def get_texture_pages_info(data)
  data.map { |page| page.except(:image_binary) }
end

# Main function that orchestrates the file parsing and asset saving.
def main
  filepath = ARGV[0]
  if filepath.nil?
    puts 'Usage: Specify the path to the WLD game file as the first parameter.'
    exit 1
  end

  start_time = Time.now
  folder_manager = SystemFolderManager.new(filepath)
  folder_manager.create_directories

  wld = WldFile.new(filepath)
  wld.parse

  # parser = WldParser.new(filepath)
  # parser.processed
  JsonFileSaver.save(folder_manager.files[:model_list_tree], wld.model_folders.to_hash)
  JsonFileSaver.save(folder_manager.files[:object_list_tree], wld.object_folders.to_hash)
  JsonFileSaver.save(folder_manager.files[:object_list], wld.objects.to_hash)

  # # save shadows
  ShadowsFileSaver.save(folder_manager.files[:shadows], wld.world_items.to_hash)
  # # save world
  WorldFileSaver.save(folder_manager.files[:world_tree], wld.world_items.to_hash, wld.objects.to_hash,
                      wld.models.to_hash)

  # SAVE TEXTURES
  a = wld.texture_pages.to_hash
  JsonFileSaver.save(folder_manager.files[:texture_pages], get_texture_pages_info(a))
  a.each do |page|
    filepath = folder_manager.texture_page_path(page[:id])
    DdsFileSaver.save(filepath, page)
  end

  # MODELS
  folder_manager.push_model_directories(wld.model_folders.to_hash)
  folder_manager.create_model_directories
  wld.models.to_hash.each do |model|
    model[:system_filepath] = folder_manager.model_path(model[:name], model[:index], model[:parent_folder_iid])
  end
  ModelFileSaver.save(folder_manager.files[:models_info], wld.models.to_hash)

  puts "Total times: #{Time.now - start_time}"
end

main if __FILE__ == $PROGRAM_NAME
