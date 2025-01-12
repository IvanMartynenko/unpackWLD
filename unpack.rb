# encoding: utf-8
Encoding.default_external = Encoding::UTF_8
Encoding.default_internal = Encoding::UTF_8

require 'fileutils'
require "yaml"
require File.expand_path("utils")

# PAGE
# FileSize (big endian)
# 0x02000000
# width
# height
# index + 1. 1,2,3,4,...
# countOfTextures

def unpack(filepath)
system_paths = {
  output: "output",
  pack: "pack",
  texture_pages: File.join("pack", "texture_pages"),
  texture_files: File.join("output", "texture_files"),
  single_texture_files: File.join(File.join("output","texture_files"),"single"),
  multiply_texture_files: File.join(File.join("output","texture_files"),"multiply")
}

wld_items = {
  TREE: { separator: 'NODE', name: 'WorldTree', items: [] },
  TEXP: { separator: 'PAGE', name: 'TexturePages', items: [] },
  GROU: { separator: 'ENTR', name: 'ModelListTree', items: [] },
  OBGR: { separator: 'ENTR', name: 'ObjectListTree', items: [] },
  LIST: { separator: 'MODL', name: 'ModelList', items: [] },
  OBJS: { separator: 'OBJ', name: 'ObjectList', items: [] },
  MAKL: { separator: 'OBJ', name: 'MakroList', items: [] }
}

# if ARGV.length < 1
#   puts 'Usage: ruby unpack.rb filename.wld'
#   exit 1
# end

read_wld_file(filepath, wld_items)
create_directories(filepath, system_paths)


texture_pages = []
wld_items[:TEXP][:items].each do |data|
  image_data_offset = get_txpg_offset(data)
  index = data[12..15].unpack1('V')
  textures_count = data[16..19].unpack1('V')
  texture_pages.push({
    image_data_offset:,
    width: data[4..7].unpack1('V'),
    height: data[8..11].unpack1('V'),
    is_alpha: data[image_data_offset+4..image_data_offset+7].unpack1("V") == 4294967295,
    index:,
    textures_count:,
    data: data[image_data_offset+8..-1],
    textures: parse_textures(data[20..image_data_offset-1], textures_count, index)
  })
end

# SAVE
wld_items.each do |key, value|
  next if key == :TEXP

  file = File.open(File.join(system_paths[:pack], key.downcase.to_s), "wb")
  value[:items].each do |item|
    file.write(value[:separator].size == 4 ? value[:separator] : value[:separator] + ' ')
    file.write([item.size].pack("N"))
    file.write(item)
  end
  file.close
end

# SAVE TEXTURES
file = File.open(File.join(system_paths[:pack], "texture_pages.yml"), "w")
if file
  file.write(texture_pages.map {|p| deep_stringify_keys(p.except(:data))}.to_yaml)
end
file.close

texture_pages.each do |page|
  file = File.open(File.join(system_paths[:texture_pages], "#{page[:index]}.dds"), "wb")
  if file
    file.write(save_to_binary_file(init_dds_header(page[:width], page[:height], page[:is_alpha])).join)
    file.write(page[:data])
  end
  file.close
end

end

script_location = File.dirname(File.expand_path(__FILE__))
filepaths = Dir.glob(File.join(script_location, '*.wld'))
filepaths.each do |f|
  unpack(f)
end