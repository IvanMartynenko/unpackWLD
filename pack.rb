require 'fileutils'
require 'yaml'
require_relative 'utils'

wld_items = {

  TEXP: { separator: 'PAGE', name: 'TexturePages', items: [] },
  GROU: { separator: 'ENTR', name: 'ModelListTree', items: [] },
  OBGR: { separator: 'ENTR', name: 'ObjectListTree', items: [] },
  LIST: { separator: 'MODL', name: 'ModelList', items: [] },
  OBJS: { separator: 'OBJ ', name: 'ObjectList', items: [] },
  MAKL: { separator: 'OBJ ', name: 'MakroList', items: [] },
  TREE: { separator: 'NODE', name: 'WorldTree', items: [] }
}

if ARGV.length < 1
  puts 'Usage: ruby pack.rb path'
  exit 1
end

filepath = ARGV[0]

unless File.directory?(filepath)
  puts "#{filepath} is not a directory."
  exit 1
end

basefilepath = filepath
filepath = "#{filepath}/pack"
unless File.directory?(filepath)
  puts "#{filepath} is not a directory."
  exit 1
end

pack_info_filepath = "#{basefilepath}/pack_info.yml"
scale_info = File.exist?(pack_info_filepath) ? YAML.load_file(pack_info_filepath) : {}
scale_info['textures'] = [] if scale_info['textures'].nil? 

zero = [0].pack('N')
end_word = [0x454E4420].pack('N')

file = File.open("#{basefilepath}/output.wld", 'wb')
file.write('WRLD')
file.write(zero)

# SAVE TEXTURES
file.write('TEXP')
file.write(zero)

textures_info = YAML.load_file("#{filepath}/texture_pages.yml")
textures_info.each do |info|
  data_to_write = []

  tmp_scale = scale_info['textures'].select { |t| t['page_index'] == info['index'] }.first
  scale = tmp_scale ? tmp_scale['scale'].to_i : 1

  info['textures'].each do |texture|
    name = texture['filepath'].encode('Windows-1252') + "\0"
    name += "\0" while name.size % 4 != 0
    data_to_write.push [name.bytes.map { |byte| byte.to_s(16).rjust(2, '0') }.join].pack('H*')

    box = texture['box']

    data_to_write.push([box['x0'] * scale].pack('V'))
    data_to_write.push([box['y0'] * scale].pack('V'))
    data_to_write.push([box['x2'] * scale].pack('V'))
    data_to_write.push([box['y2'] * scale].pack('V'))

    box = texture['source_box']

    data_to_write.push([box['x0']].pack('V'))
    data_to_write.push([box['y0']].pack('V'))
    data_to_write.push([box['x2']].pack('V'))
    data_to_write.push([box['y2']].pack('V'))
  end
  data_to_write.push([0x54585047].pack('N')) # TXPG
  # data_to_write.push([0xFFFFFFFF].pack("V"))
  data_to_write.push([info['is_alpha'] ? 4294967295 : 0].pack('V'))

  header = data_to_write.flatten.join
  texture_file = File.binread("#{filepath}/texture_pages/#{info['index']}.dds")[128..-1]

  file.write('PAGE')
  file.write([header.size + texture_file.size + 20].pack('N'))
  file.write([2].pack('V'))
  file.write([info['width'] * scale].pack('V'))
  file.write([info['height'] * scale].pack('V'))
  file.write([info['index']].pack('V'))
  file.write([info['textures'].size].pack('V'))
  file.write(header)
  file.write(texture_file)
end

file.write(end_word) # END
file.write(zero)
# texture_pages.each do |page|
#   file = File.open("#{system_paths[:texture_pages]}/#{page[:index]}.dds", "wb")
#   if file
#     file.write(save_to_binary_file(init_dds_header(page[:width], page[:height])).join)
#     file.write(page[:data])
#   end
#   file.close
# end

# SAVE
wld_items.each do |key, _value|
  next if key == :TEXP

  item_file = File.open("#{filepath}/#{key.downcase}", 'rb')

  file.write(key)
  file.write(zero)

  file.write(item_file.read)
  file.write(end_word) # END
  file.write(zero)

  item_file.close
end

file.write([0x454F4620].pack('N')) # EOF
file.write(zero)

file.close
