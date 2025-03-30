require 'fileutils'
require 'json'
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

def pack_anim(item)
  accumulator = BindataStorer.new
  accumulator.push_word 'ANIM'
  accumulator.push_bool item[:unknown]

  keys = %i[translation scaling rotation]
  keys.each do |key|
    %i[x y z].each do |coord|
      accumulator.push_int item[key][:values][coord] ? item[key][:values][coord].size : 0
    end
  end

  keys.each do |key|
    %i[x y z].each do |coord|
      accumulator.push_floats item[key][:values][coord] if item[key][:values][coord]
    end
    %i[x y z].each do |coord|
      accumulator.push_ints item[key][:keys][coord] if item[key][:keys][coord]
    end
  end

  accumulator.data
end

# Write the INFO structure, which includes:
#   bigendian_int -> info[:size]
#   info[:unknow1], info[:unknow2], info[:unknow3]
#   "OPTS" block, "COND" block, "TALI" block
#
def pack_info(acc, info_hash)
  info_accumulator = BindataStorer.new
  info = info_hash[:info]
  # acc.push_bigendian_int info[:size]
  info_accumulator.push_int info[:unknow1]
  info_accumulator.push_int info[:unknow2]
  info_accumulator.push_int info[:unknow3]

  # Next the "OPTS" block
  opts_accumulator = BindataStorer.new
  opts = info_hash[:opts]
  # opts_accumulator.push_word 'OPTS'
  # acc.push_bigendian_int opts[:size]
  opts_accumulator.push_int opts[:unknow1]
  opts_accumulator.push_name opts[:id]
  opts_accumulator.push_int opts[:type]
  opts_accumulator.push_int opts[:story]
  opts_accumulator.push_negative_bool opts[:clickable]
  opts_accumulator.push_negative_bool opts[:process_when_visible]
  opts_accumulator.push_negative_bool opts[:process_always]

  # The parser calls parse_item(type) here, so we do the “reverse” and push the item fields:
  pack_item_for_type(opts_accumulator, opts[:type], opts[:info])
  opts_data = opts_accumulator.data
  info_accumulator.push_word 'OPTS'
  info_accumulator.push_size opts_data.size
  info_accumulator.push opts_data

  # After we finish "OPTS", we should see "COND" block
  cond = info_hash[:cond]
  info_accumulator.push_word 'COND'
  d = cond[:data].pack('H*')
  info_accumulator.push_size d.size
  info_accumulator.push d

  # Next "TALI"
  tali = info_hash[:tali]
  info_accumulator.push_word 'TALI'
  d = tali[:data].pack('H*')
  info_accumulator.push_size d.size
  info_accumulator.push d

  # Finally the parser expects 'END ' after TALI in InfoParser
  info_accumulator.push 'END '
  info_accumulator.push_int 0
  data = info_accumulator.data
  acc.push_word 'INFO'
  acc.push_size data.size
  acc.push data
end

#
# Pack the :info sub-block from parse_item(type). See InfoParser#parse_item
#
def pack_item_for_type(acc, type, item_info)
  case type
  when 0
    # type=0 (Item) => weight only
    acc.push_float item_info[:weight]
  when 1
    # type=1 => weight, value
    acc.push_float item_info[:weight]
    acc.push_float item_info[:value]
  when 2
    # type=2 => weight, value, strength, pick_locks, pick_safes, alarm_systems, volume, damaging
    #          applicability floats, noise floats
    acc.push_float item_info[:weight]
    acc.push_float item_info[:value]
    acc.push_float item_info[:strength]
    acc.push_float item_info[:pick_locks]
    acc.push_float item_info[:pick_safes]
    acc.push_float item_info[:alarm_systems]
    acc.push_float item_info[:volume]
    acc.push_negative_bool item_info[:damaging]

    acc.push_float item_info[:applicability][:glas]
    acc.push_float item_info[:applicability][:wood]
    acc.push_float item_info[:applicability][:steel]
    acc.push_float item_info[:applicability][:hightech]

    acc.push_float item_info[:noise][:glas]
    acc.push_float item_info[:noise][:wood]
    acc.push_float item_info[:noise][:steel]
    acc.push_float item_info[:noise][:hightech]
  when 3, 7, 8
    # 3 => Immobilie, or 7 => Tuer, or 8 => Fenster
    # all have: working_time, material, crack_type
    acc.push_float item_info[:working_time]
    acc.push_int   item_info[:material]
    acc.push_int   item_info[:crack_type]
  when 4
    # type=4 => Character A => speed (float), occupation (string)
    acc.push_float item_info[:speed]
    acc.push_name  item_info[:occupation]
    # If you also store skillfulness, push it here if needed
  when 5, 6
    # type=5 => Character B, or type=6 => Character C => speed
    acc.push_float item_info[:speed]
  when 9
    # type=9 => Car => transp_space, max_speed, acceleration, value, driving
    acc.push_float item_info[:transp_space]
    acc.push_float item_info[:max_speed]
    acc.push_float item_info[:acceleration]
    acc.push_float item_info[:value]
    acc.push_float item_info[:driving]
  else
    raise "Unknown type: #{type}"
  end
end

def pack(filepath)
  folder_manager = SystemFolderManager.new(filepath)
  file = BindataStorer.new
  # FileSaver.new(folder_manager.pack_file_path)

  file.push_word('WRLD')
  file.push_zero

  # SAVE TEXTURES
  file.push_word('TEXP')
  file.push_zero
  start_time = Time.now

  textures_info = JSON.parse(File.read(folder_manager.files[:texture_pages]))
  textures_info.each do |info|
    data = BindataStorer.new

    texture_file_path = folder_manager.texture_page_path info['iid']
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

    file.push_word 'PAGE'
    file.push_size header.size + texture_file_pixels.size + 20
    file.push_int 2
    file.push_int info['width'] * scale
    file.push_int info['height'] * scale
    file.push_int info['iid']
    file.push_int info['textures'].size
    file.push(header)
    file.push(texture_file_pixels)
  end
  file.push_end_word # END
  file.push_zero

  # SAVE ModelListTree, ObjectListTree
  model_list_items = [
    ['GROU', :model_list_tree],
    ['OBGR', :object_list_tree]
  ]
  model_list_items.each do |marker, file_key|
    file.push_word marker
    file.push_zero

    model_list_tree = JSON.parse(File.read(folder_manager.files[file_key]), symbolize_names: true)
    folder_manager.push_model_directories(model_list_tree) if file_key == :model_list_tree
    model_list_tree.sort_by { |t| t[:index] }.each do |item|
      accumulator = BindataStorer.new

      accumulator.push_int 0
      accumulator.push_name item[:name]
      # accumulator.push_int item['index']
      accumulator.push_int item[:parent_iid]
      data = accumulator.data

      file.push_word 'ENTR'
      file.push_size data.size
      file.push data
    end
    file.push_end_word
    file.push_zero
  end

  # SAVE MODELS
  file.push_word 'LIST'
  file.push_zero

  models_info = JSON.parse(File.read(folder_manager.files[:models_info]), symbolize_names: true)
  models_info.each do |info|
    accumulator = BindataStorer.new
    accumulator.push_int 9
    accumulator.push_int 1
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

    accumulator.push_int info[:parent_folder_iid]
    if info[:attack_points]
      accumulator.push_int info[:attack_points].size
      info[:attack_points].each do |val|
        accumulator.push_float val[:x]
        accumulator.push_float val[:y]
        accumulator.push_float val[:z]
        accumulator.push_float val[:radius]
      end
    else
      accumulator.push_int 0
    end

    accumulator.push 'NMF '
    accumulator.push_int 0
    model_file = JSON.parse(File.read(folder_manager.model_path(info[:name], info[:index],
                                                                info[:parent_folder_iid])), symbolize_names: true)
    model_file.sort_by { |t| t[:index] }.each do |value|
      item_accumulator = BindataStorer.new
      # item_accumulator.push_word value[:word]
      case value[:word]
      when 'ROOT'
        item_accumulator.push_int 2
        item_accumulator.push_int value[:parent_iid]
        item_accumulator.push_name value[:name]
        item_accumulator.push value[:data][:data].pack('H*')
      when 'LOCA'
        item_accumulator.push_int 0
        item_accumulator.push_int value[:parent_iid]
        item_accumulator.push_name value[:name]
      when 'FRAM'
        item_accumulator.push_int 2
        item_accumulator.push_int value[:parent_iid]
        item_accumulator.push_name value[:name]
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
        item_accumulator.push_int 2
        item_accumulator.push_int value[:parent_iid]
        item_accumulator.push_name value[:name]
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
        item_accumulator.push_int 14
        item_accumulator.push_int value[:parent_iid]
        item_accumulator.push_name value[:name]
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
          # item_accumulator.push_int value[:data][:unknown_count_of_floats]
          item_accumulator.push_int value[:data][:unknown_floats].size / 3
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
    file.push_word 'MODL'
    file.push_size data.size
    file.push data
  end

  file.push_end_word
  file.push_zero

  # SAVE Objects
  file.push_word 'OBJS'
  file.push_zero

  objects_info = JSON.parse(File.read(folder_manager.files[:object_list]), symbolize_names: true)
  # For each object in the data
  objects_info.each do |object|
    accumulator = BindataStorer.new

    # Object header fields
    accumulator.push_int object[:type]
    accumulator.push_name object[:name]
    accumulator.push_int object[:parent_folder]       # parser reads parent_folder directly
    accumulator.push_int object[:unknow2].size        # count_of_unknow2

    # Write each :unknow2 entry
    object[:unknow2].each do |u2|
      accumulator.push_name u2[:name]
      accumulator.push_int  u2[:unknow1]
      accumulator.push_float u2[:unknow2]
      accumulator.push_float u2[:unknow3]
      accumulator.push_int   u2[:unknow4]
      accumulator.push_float u2[:alway_negative100]
      accumulator.push_negative_bool u2[:unknow5]
      accumulator.push_negative_bool u2[:unknow6]

      accumulator.push_int u2[:unknow7].size
      u2[:unknow7].each do |u7|
        accumulator.push_name u7[:name]
        accumulator.push_float u7[:unknow1]
      end
    end

    # Write INFO block
    # accumulator.push_word 'INFO'
    pack_info(accumulator, object[:info])

    # Write 'END ' block for each object is done by the parser after 'INFO' -> 'COND' -> 'TALI'
    data = accumulator.data
    file.push_word 'OBJ '
    file.push_size data.size
    file.push data
  end

  file.push_end_word
  file.push_zero

  # SAVE MAKL
  file.push_word 'MAKL'
  file.push_zero
  file.push_end_word
  file.push_zero

  # SAVE World
  file.push_word 'TREE'
  file.push_zero

  world_nodes = JSON.parse(File.read(folder_manager.files[:world_tree]), symbolize_names: true)
  tmp_shadows = JSON.parse(File.read(folder_manager.files[:shadows]), symbolize_names: true)
  shadow = Array.new(tmp_shadows.last[:index].to_i + 1)
  tmp_shadows.each { |t| shadow[t[:index].to_i] = t }
  world_nodes.each do |k, node|
    accumulator = BindataStorer.new
    # accumulator.push_word 'NODE'
    accumulator.push_int 15
    accumulator.push_int node[:parent_iid].to_i
    accumulator.push_name node[:folder_name]
    # Если в ноде уже задан ключ :index – используем его, иначе подставляем порядковый номер.
    # accumulator.push_int(node[:index])
    accumulator.push_float node[:x]
    accumulator.push_float node[:y]
    accumulator.push_float node[:z]
    accumulator.push_float node[:w]
    accumulator.push_float node[:n]
    accumulator.push_float node[:u]
    accumulator.push_int node[:unknow1]
    accumulator.push_int node[:type]

    case node[:type]
    when 0 # folder
      # Ожидается массив из 4 целых чисел
      accumulator.push_ints([0, 0, 0, 0])
    when 1 # ground
      ground = node[:ground]
      accumulator.push_int node[:model_id]
      if ground[:connections]
        accumulator.push_int ground[:connections].size
        ground[:connections].each do |conn|
          accumulator.push_int conn[0]
          accumulator.push_int conn[1]
        end
      else
        accumulator.push_int 0
      end
      accumulator.push_int 0
      shad = shadow[k.to_s.to_i]
      if shad
        accumulator.push_word 'SHAD'
        accumulator.push_int shad[:shad][:size1]
        accumulator.push_int shad[:shad][:size2]
        shad[:shad][:data].each do |f|
          accumulator.push_float f
        end
      else
        accumulator.push_int 0
      end
    when 2 # item
      item_block = node[:item]
      accumulator.push_int node[:object_id]
      accumulator.push_int item_block[:unknow_zero]
      if item_block.key?(:info)
        # accumulator.push_word 'INFO'
        info_accumulator = BindataStorer.new
        pack_info(info_accumulator, item_block[:info])
        accumulator.push info_accumulator.data
        # accumulator.push_size info_accumulator.data.size
        # accumulator.push info_accumulator.data
      else
        accumulator.push_int 0
      end
      accumulator.push_int item_block[:unknow_zero2]
    when 3 # sun
      light = node[:light]
      accumulator.push_int light[:unknow1]
      light[:unknow_floats11].each { |f| accumulator.push_float f }
      accumulator.push_int light[:unknow2]
      light[:unknow_floats13].each { |f| accumulator.push_float f }
      accumulator.push_int light[:unknow3]
      accumulator.push_int light[:unknow4]
      accumulator.push_int light[:unknow5]
      accumulator.push_int light[:unknow6]
    else
      raise "Unknown node type: #{node[:type]}"
    end

    data = accumulator.data
    file.push_word 'NODE'
    file.push_size data.size
    file.push data
  end

  file.push_end_word
  file.push_zero

  file.push_eof_word
  file.push_zero
  puts "Pack end. Time: #{Time.now - start_time}"

  File.open(folder_manager.pack_file_path, 'wb') do |f|
    f << file.data
  end
end

script_location = File.dirname(File.expand_path(__FILE__))
filepaths = Dir.glob(File.join(File.join(script_location, '..'), '*_unpack'))
filepaths.each do |f|
  pack(f)
end
