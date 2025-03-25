require 'fileutils'
require 'yaml'
# require File.expand_path('utils')
require_relative '../lib/system_folder_manager'
require_relative '../lib/file_saver'
require_relative '../lib/bindata_storer'

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

def pack_anim(yaml)
  accumulator = BindataStorer.new
  accumulator.push_word 'ANIM'
  accumulator.push_bool yaml[:unknown]

  keys = %i[translation scaling rotation]
  keys.each { |key| accumulator.push_ints yaml[key][:sizes] }

  keys.each do |key|
    %i[x y z].each do |coord|
      accumulator.push_floats yaml[key][:values][coord] if yaml[key][:values][coord]
    end
    %i[x y z].each do |coord|
      accumulator.push_ints yaml[key][:keys][coord] if yaml[key][:keys][coord]
    end
  end

  accumulator.data
end

def parse_curve(sizes)
  res = { values: {}, keys: {} }
  coordinates = %i[x y z]
  coordinates.each_with_index do |coord, idx|
    res[:values][coord] = @file.floats(sizes[idx]) if sizes[idx] > 0
  end
  coordinates.each_with_index do |coord, idx|
    res[:keys][coord] = @file.ints(sizes[idx]) if sizes[idx] > 0
  end
  res
end

def pack(filepath)
  folder_manager = SystemFolderManager.new(filepath)
  file = FileSaver.new(folder_manager.pack_file_path)

  file.write_word('WRLD')
  file.write_zero

  # SAVE TEXTURES
  file.write_word('TEXP')
  file.write_zero

  textures_info = YAML.load_file(folder_manager.files[:texture_pages])
  textures_info.each do |info|
    data = BindataStorer.new

    texture_file_path = folder_manager.texture_page_path info['index']
    texture_file = File.binread texture_file_path
    texture_file_pixels = texture_file[128..]
    image_height = texture_file[(4 * 4)..(4 * 4) + 3].unpack1('V')
    scale = image_height / info['width'].to_i

    info['textures'].each do |texture|
      data.push_name texture['filepath']

      box = texture['box']
      data.push_int(box['x0'] * scale)
      data.push_int(box['y0'] * scale)
      data.push_int(box['x2'] * scale)
      data.push_int(box['y2'] * scale)

      box = texture['source_box']
      data.push_int(box['x0'])
      data.push_int(box['y0'])
      data.push_int(box['x2'])
      data.push_int(box['y2'])
    end
    data.push_word('TXPG')
    data.push_negative_bool(info['is_alpha'])

    header = data.data

    file.write_word 'PAGE'
    file.write_size header.size + texture_file_pixels.size + 20
    file.write_int 2
    file.write_int info['width'] * scale
    file.write_int info['height'] * scale
    file.write_int info['index']
    file.write_int info['textures'].size
    file.write(header)
    file.write(texture_file_pixels)
  end
  file.write_end_word # END
  file.write_zero

  # SAVE ModelListTree, ObjectListTree
  model_list_items = [
    ['GROU', :model_list_tree],
    ['OBGR', :object_list_tree]
  ]
  model_list_items.each do |marker, file_key|
    file.write_word marker
    file.write_zero

    model_list_tree = deep_symbolize_keys(YAML.load_file(folder_manager.files[file_key]))
    folder_manager.push_model_directories(model_list_tree) if file_key == :model_list_tree
    model_list_tree.sort_by { |t| t[:index] }.each do |item|
      accumulator = BindataStorer.new

      accumulator.push_int 0
      accumulator.push_name item[:name]
      # accumulator.push_int item['index']
      accumulator.push_int item[:parent]
      data = accumulator.data

      file.write_word 'ENTR'
      file.write_size data.size
      file.write data
    end
    file.write_end_word
    file.write_zero
  end

  # SAVE MODELS
  file.write_word 'LIST'
  file.write_zero

  models_info = deep_symbolize_keys(YAML.load_file(folder_manager.files[:models_info]))
  models_info.each do |info|
    accumulator = BindataStorer.new
    accumulator.push_int 9
    accumulator.push_int info[:id]
    accumulator.push_name info[:name]
    accumulator.push_negative_bool info[:influences_camera]
    accumulator.push_negative_bool info[:no_camera_check]
    accumulator.push_negative_bool info[:anti_ground]
    accumulator.push_int info[:default_skeleton]
    accumulator.push_int info[:use_skeleton]
    if info[:camera]
      accumulator.push_word 'RMAC'
      [info[:camera][:camera], info[:camera][:item]].each do |val|
        accumulator.push_float val[:x]
        accumulator.push_float val[:y]
        accumulator.push_float val[:z]
        accumulator.push_float val[:pitch]
        accumulator.push_float val[:yaw]
      end
    else
      accumulator.push_int 0
    end

    accumulator.push_int info[:parent_folder]
    accumulator.push_int info[:attack_points].size
    info[:attack_points].each do |val|
      accumulator.push_float val[:x]
      accumulator.push_float val[:y]
      accumulator.push_float val[:z]
      accumulator.push_float val[:radius]
    end

    accumulator.push 'NMF '
    accumulator.push_int 0
    model_file = deep_symbolize_keys YAML.load_file(folder_manager.model_path(info[:name], info[:index],
                                                                              info[:parent_folder]))
    model_file.sort_by { |t| t[:index] }.each do |value|
      item_accumulator = BindataStorer.new
      # item_accumulator.push_word value[:word]
      item_accumulator.push_int value[:type]
      item_accumulator.push_int value[:parent]
      item_accumulator.push_name value[:name]
      case value[:word]
      when 'ROOT'
        item_accumulator.push value[:data][:data].pack('H*')
      when 'LOCA'
      when 'FRAM'
        item_accumulator.push_floats value[:data][:matrix].flatten
        keys = %i[translation scaling rotation rotate_pivot_translate rotate_pivot scale_pivot_translate
                  scale_pivot shear]
        keys.each { |key| item_accumulator.push_floats value[:data][key] }
        if value[:data][:anim]
          item_accumulator.push pack_anim(value[:data][:anim])
        else
          item_accumulator.push_int 0
        end
      when 'JOIN'
        item_accumulator.push_floats value[:data][:matrix].flatten
        keys = %i[translation scaling rotation]
        keys.each { |key| item_accumulator.push_floats value[:data][key] }
        item_accumulator.push_floats value[:data][:rotation_matrix].flatten
        item_accumulator.push_floats value[:data][:min_rot_limit]
        item_accumulator.push_floats value[:data][:max_rot_limit]
        if value[:data][:anim]
          item_accumulator.push pack_anim(value[:data][:anim])
        else
          item_accumulator.push_int 0
        end
      when 'MESH'
        item_accumulator.push_int value[:data][:tnum]
        item_accumulator.push_int value[:data][:vnum]
        item_accumulator.push_floats value[:data][:vbuf].flatten
        item_accumulator.push_floats value[:data][:uvpt].flatten
        item_accumulator.push_int value[:data][:inum]
        item_accumulator.push_ints16 value[:data][:ibuf].flatten
        item_accumulator.push_int16(0) if value[:data][:inum].odd?
        item_accumulator.push_int value[:data][:backface_culling]
        item_accumulator.push_int value[:data][:complex]
        item_accumulator.push_int value[:data][:inside]
        item_accumulator.push_int value[:data][:smooth]
        item_accumulator.push_int value[:data][:light_flare]
        if value[:data][:materials]
          item_accumulator.push_int value[:data][:materials].size
          value[:data][:materials].each do |mt|
            item_accumulator.push_word 'MTRL'
            item_accumulator.push_name mt[:name]
            item_accumulator.push_int mt[:blend_mode]
            item_accumulator.push_ints mt[:unknown_ints]
            item_accumulator.push_int mt[:uv_mapping_flip_horizontal]
            item_accumulator.push_int mt[:uv_mapping_flip_vertical]
            item_accumulator.push_int mt[:rotate]
            item_accumulator.push_int mt[:horizontal_stretch]
            item_accumulator.push_int mt[:vertical_stretch]
            item_accumulator.push_float mt[:red]
            item_accumulator.push_float mt[:green]
            item_accumulator.push_float mt[:blue]
            item_accumulator.push_float mt[:alpha]
            item_accumulator.push_float mt[:red2]
            item_accumulator.push_float mt[:green2]
            item_accumulator.push_float mt[:blue2]
            item_accumulator.push_float mt[:alpha2]
            item_accumulator.push_ints mt[:unknown_zero_ints]

            if mt[:texture]
              item_accumulator.push_word 'TXPG'
              item_accumulator.push_name mt[:texture][:name]
              item_accumulator.push_int mt[:texture][:texture_page]
              item_accumulator.push_int mt[:texture][:index_texture_on_page]
              item_accumulator.push_int mt[:texture][:x0]
              item_accumulator.push_int mt[:texture][:y0]
              item_accumulator.push_int mt[:texture][:x2]
              item_accumulator.push_int mt[:texture][:y2]
            elsif mt[:text]
              item_accumulator.push_word 'TEXT'
              item_accumulator.push_name mt[:text][:name]
            else
              item_accumulator.push_int 0
            end
          end
        else
          item_accumulator.push_int 0
        end

        if value[:data][:mesh_anim]
          value[:data][:mesh_anim].each do |anim|
            item_accumulator.push_word 'ANIM'
            item_accumulator.push_bool anim[:unknown_bool]
            item_accumulator.push_int anim[:unknown_ints].size
            item_accumulator.push_ints anim[:unknown_ints]
            item_accumulator.push_floats anim[:unknown_floats]
            item_accumulator.push_int anim[:unknown_size1]
            item_accumulator.push_int anim[:unknown_size2]
            item_accumulator.push_int anim[:unknown_size3]
            item_accumulator.push_floats anim[:unknown_floats1]
            item_accumulator.push_floats anim[:unknown_floats2]
            item_accumulator.push_floats anim[:unknown_floats3]
          end
        end
        item_accumulator.push_int 0

        if value[:data][:unknown_floats]
          item_accumulator.push_int value[:data][:unknown_count_of_floats]
          item_accumulator.push_floats value[:data][:unknown_floats]
        else
          item_accumulator.push_int 0
        end
        if value[:data][:unknown_ints]
          item_accumulator.push_int value[:data][:unknown_ints].size
          item_accumulator.push_ints value[:data][:unknown_ints]
        else
          item_accumulator.push_int 0
        end
      end

      data = item_accumulator.data
      accumulator.push value[:word]
      accumulator.push_size data.size
      accumulator.push data
    end
    accumulator.push 'END '
    accumulator.push_int 0

    data = accumulator.data
    file.write_word 'MODL'
    file.write_size data.size
    file.write data
  end

  file.write_end_word
  file.write_zero

  # SAVE Objects
  file.write_word 'OBJS'
  file.write_zero

  f = File.binread(folder_manager.files[:object_list])
  file.write(f)

  file.write_end_word
  file.write_zero

  # SAVE MAKL
  file.write_word 'MAKL'
  file.write_zero
  file.write_end_word
  file.write_zero

  # SAVE World
  file.write_word 'TREE'
  file.write_zero

  f = File.binread(folder_manager.files[:world_tree])
  file.write(f)

  file.write_end_word
  file.write_zero

  file.write_eof_word
  file.write_zero

  file.close
end

script_location = File.dirname(File.expand_path(__FILE__))
filepaths = Dir.glob(File.join(File.join(script_location, '..'), '*_unpack'))
filepaths.each do |f|
  pack(f)
end
