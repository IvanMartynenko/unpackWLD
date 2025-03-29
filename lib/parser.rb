require_relative 'file_reader'
require 'logger'

MATRIX_SIZE = 16

# Parses the texture pages section.
class TexturePageParser
  def initialize(file)
    @file = file
  end

  def parse
    pages = []
    token, _page_size = @file.token_with_size
    return pages if token == 'END '

    while token == 'PAGE'
      @file.int # always 2, skip
      page = {
        width: @file.int,
        height: @file.int,
        iid: @file.int # id of texture page. for id using page index, start from 1
      }
      textures_count = @file.int
      page[:textures] = textures_count.times.map { parse_texture }

      txpg = @file.word
      raise StandardError, "Not found TXPG separator (got '#{txpg}')" unless txpg == 'TXPG'

      page[:is_alpha] = @file.negative_bool
      page[:image_binary] = @file.hex(page[:width] * page[:height] * 2) # the dds image binary data

      pages << page
      token, _page_size = @file.token_with_size
    end

    raise StandardError, "Bad end of TexturePage, expected 'END ' but got '#{token}'" unless token == 'END '

    pages
  end

  def parse_texture
    {
      filepath: @file.filename,
      box: {
        x0: @file.int,
        y0: @file.int,
        x2: @file.int,
        y2: @file.int
      },
      source_box: {
        x0: @file.int,
        y0: @file.int,
        x2: @file.int,
        y2: @file.int
      }
    }
  end
end

# Parses a tree structure (used for both model list trees and object list trees).
class TreeParser
  def initialize(file, tree_name)
    @file = file
    @tree_name = tree_name
  end

  def parse
    nodes = []
    token, _entry_size = @file.token_with_size
    return nodes if token == 'END '

    index = 2
    while token == 'ENTR'
      @file.int # always zero. skip
      nodes << {
        name: @file.name,
        index:,
        parent_iid: @file.int
      }
      index += 1
      token, _entry_size = @file.token_with_size
    end

    raise StandardError, "Bad end of #{@tree_name}, expected 'END ' but got '#{token}'" unless token == 'END '

    nodes
  end
end

# Parses models, including sub-elements like animations, meshes, and materials.
class ModelParser
  def initialize(file)
    @file = file
  end

  def parse
    models = []
    index = 2
    loop do
      token = @file.token
      break if token == 'END '
      raise StandardError, "Bad parse MODELS. Expected 'MODL', got '#{token}'" unless token == 'MODL'

      res = parse_model
      res[:index] = index
      models << res
      index += 1
    end
    models
  end

  def parse_model
    @file.int # always 9. skip
    @file.int # always 1. skip
    model_info = {
      name: @file.name,
      influences_camera: @file.negative_bool,
      no_camera_check: @file.negative_bool,
      anti_ground: @file.negative_bool,
      default_skeleton: @file.int,
      use_skeleton: @file.int
    }

    camera_token = @file.word
    model_info[:camera] = camera_token == 'RMAC' ? parse_camera : nil

    model_info[:parent_folder_iid] = @file.int
    count_of_attack_points = @file.int
    if count_of_attack_points > 0
      model_info[:attack_points] = count_of_attack_points.times.map do
        { x: @file.float, y: @file.float, z: @file.float, radius: @file.float }
      end
    end
    model_info[:nmf] = parse_nmf

    model_info
  end

  def parse_camera
    {
      camera: {
        x: @file.float,
        y: @file.float,
        z: @file.float,
        pitch: @file.float,
        yaw: @file.float
      },
      item: {
        x: @file.float,
        y: @file.float,
        z: @file.float,
        pitch: @file.float,
        yaw: @file.float
      }
    }
  end

  def parse_nmf
    token = @file.token # read const char[4] and int = zero
    raise StandardError, "Bad end of ModelList. Expected 'NMF ' but got '#{token}'" unless token == 'NMF '

    model = []
    index = 1
    loop do
      token, _size = @file.token_with_size
      break if token == 'END '

      @file.int # 0 from LOCA, 14 from MESH, other 2. skip
      parent_iid = @file.int # start from 0. 0 for ROOT
      name = @file.name

      data = case token
             when 'ROOT' then parse_root
             when 'LOCA' then parse_loca
             when 'FRAM' then parse_fram
             when 'JOIN' then parse_join
             when 'MESH' then parse_mesh
             else
               raise StandardError, "Unexpected token in MODEL: #{token}"
             end

      model << { word: token, name:, parent_iid:, data:, index: }
      index += 1
    end
    model
  end

  def parse_root
    { data: @file.hex(41 * 4) }
  end

  def parse_loca
    {}
  end

  def parse_fram
    res = {}
    keys = %i[translation scaling rotation rotate_pivot_translate rotate_pivot scale_pivot_translate
              scale_pivot shear]
    res[:matrix] = @file.floats(MATRIX_SIZE).each_slice(4).to_a
    keys.each { |key| res[key] = @file.floats(3) }
    a = @file.word == 'ANIM' ? parse_anim : nil
    res[:anim] = a if a
    res
  end

  def parse_join
    res = {}
    keys = %i[translation scaling rotation]
    res[:matrix] = @file.floats(MATRIX_SIZE).each_slice(4).to_a
    keys.each { |key| res[key] = @file.floats(3) }
    res[:rotation_matrix] = @file.floats(MATRIX_SIZE).each_slice(4).to_a
    res[:min_rot_limit] = @file.floats(3)
    res[:max_rot_limit] = @file.floats(3)
    a = @file.word == 'ANIM' ? parse_anim : nil
    res[:anim] = a if a
    res
  end

  def parse_anim
    res = {}
    sizes = {}
    res[:unknown] = @file.bool
    keys = %i[translation scaling rotation]
    keys.each { |key| res[key] = {} }
    keys.each { |key| sizes[key] = {} }
    keys.each { |key| sizes[key][:sizes] = @file.ints(3) }
    keys.each { |key| res[key].merge!(parse_curve(sizes[key][:sizes])) }
    res
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

  def parse_mesh
    res = {}
    res[:tnum] = @file.int
    res[:vnum] = @file.int

    vbuf_count = 10
    uvbuf_count = 2
    vbuf_count_float = res[:vnum] * vbuf_count
    uvbuf_count_float = res[:vnum] * uvbuf_count

    res[:vbuf] = @file.floats(vbuf_count_float).each_slice(vbuf_count).to_a
    res[:uvpt] = @file.floats(uvbuf_count_float).each_slice(uvbuf_count).to_a

    res[:inum] = @file.int
    ibuf = @file.ints16(res[:inum])
    res[:ibuf] = ibuf.each_slice(3).to_a
    @file.int16 if res[:inum].odd?
    res[:backface_culling] = @file.int
    res[:complex] = @file.int
    res[:inside] = @file.int
    res[:smooth] = @file.int
    res[:light_flare] = @file.int
    material_count = @file.int

    if material_count > 0
      res[:materials] = []
      material_count.times { res[:materials] << parse_mtrl }
    end

    a = @file.word == 'ANIM' ? parse_anim_mesh : nil
    res[:mesh_anim] = a if a

    unknown_count_of_floats = @file.int
    res[:unknown_floats] = @file.floats(unknown_count_of_floats * 3) if unknown_count_of_floats > 0

    unknown_count_of_ints = @file.int
    res[:unknown_ints] = @file.ints(unknown_count_of_ints) if unknown_count_of_ints > 0

    res
  end

  def parse_mtrl
    res = {}
    token = @file.word
    raise StandardError, "Expected 'MTRL' but got '#{token}'" unless token == 'MTRL'

    res[:name] = @file.name
    res[:blend_mode] = @file.int
    res[:unknown_ints] = @file.ints(4)
    res[:uv_mapping_flip_horizontal] = @file.int
    res[:uv_mapping_flip_vertical] = @file.int
    res[:rotate] = @file.int
    res[:horizontal_stretch] = @file.int
    res[:vertical_stretch] = @file.int
    res[:red] = @file.float
    res[:green] = @file.float
    res[:blue] = @file.float
    res[:alpha] = @file.float
    res[:red2] = @file.float
    res[:green2] = @file.float
    res[:blue2] = @file.float
    res[:alpha2] = @file.float
    res[:unknown_zero_ints] = @file.ints(9)

    token = @file.word
    if token.to_s == 'TXPG'
      res[:texture] = {
        name: @file.filename,
        texture_page: @file.int,
        index_texture_on_page: @file.int,
        x0: @file.int,
        y0: @file.int,
        x2: @file.int,
        y2: @file.int
      }
    elsif token.to_s == 'TEXT'
      res[:text] = { name: @file.filename }
    end

    res
  end

  def parse_anim_mesh
    anim_meshes = []
    anim_meshes << parse_single_anim_mesh
    anim_meshes << parse_single_anim_mesh while @file.word == 'ANIM'
    anim_meshes.flatten
  end

  def parse_single_anim_mesh
    {
      unknown_bool: @file.bool,
      unknown_size_of_ints: size = @file.int,
      unknown_ints: @file.ints(size),
      unknown_floats: @file.floats(3),
      unknown_size1: s1 = @file.int,
      unknown_size2: s2 = @file.int,
      unknown_size3: s3 = @file.int,
      unknown_floats1: @file.floats(s1 * 2),
      unknown_floats2: @file.floats(s2 * 2),
      unknown_floats3: @file.floats(s3 * 2)
    }
  end
end

# Parses a info from objects
class InfoParser
  def initialize(file)
    @file = file
  end

  def parse
    item = {}
    @file.bigendian_int # skip size
    item[:info] = {
      unknow1: @file.int,
      unknow2: @file.int,
      unknow3: @file.int
    }

    word = @file.word
    raise 'not opts' if word != 'OPTS'

    @file.bigendian_int # skip size
    item[:opts] = {
      unknow1: @file.int,
      id: @file.name,
      type: object_type = @file.int,
      story: @file.int,
      clickable: @file.negative_bool,
      process_when_visible: @file.negative_bool,
      process_always: @file.negative_bool,
      info: parse_item(object_type)
    }

    word = @file.word # COND
    raise "not COND. find #{word} token. #{item[:opts]}" if word != 'COND'

    z = @file.bigendian_int # skip size
    item[:cond] = {
      data: @file.hex(z)
    }

    word = @file.word # TALI
    raise 'not TALI' if word != 'TALI'

    z = @file.bigendian_int # skip size
    item[:tali] = {
      data: @file.hex(z)
      # data: parse_tali(file, z)
    }

    word = @file.token # END
    raise 'Parse Object Error. Not found END.' if word != 'END '

    item
  end

  def parse_item(type)
    case type
    when 0
      # type = 0 Item
      # Weight float always 0
      { weight: @file.float }
    when 1
      # type = 1 Item - Beute
      # Weight float, Value float
      {
        weight: @file.float,
        value: @file.float
      }
    when 2
      # type = 2 Item - Tool
      # Weight float, Value float,
      # Strength float (0.0 or 1.0), PickLocks float, PickSafes float,
      # AlarmSystems float (0.0 always), Volume float (0.0 always),
      # Damaging negative boolean,
      # Applicability: { Glas, Wood, Steel, HighTech } all floats,
      # Noise: { Glas, Wood, Steel, HighTech } all floats.
      {
        weight: @file.float,
        value: @file.float,
        strength: @file.float,
        pick_locks: @file.float,
        pick_safes: @file.float,
        alarm_systems: @file.float,
        volume: @file.float,
        damaging: @file.negative_bool,
        applicability: {
          glas: @file.float,
          wood: @file.float,
          steel: @file.float,
          hightech: @file.float
        },
        noise: {
          glas: @file.float,
          wood: @file.float,
          steel: @file.float,
          hightech: @file.float
        }
      }
    when 3
      # type = 3 Immobilie
      # WorkingTime float, Material int, CrackType int
      {
        working_time: @file.float,
        material: @file.int,
        crack_type: @file.int
      }
    when 4
      # type = 4 Character A
      # Speed float, Skillfulness (0.0 always)
      {
        speed: @file.float,
        occupation: @file.name
        # skillfulness: @file.float
      }
    when 5
      # type = 5 Character B
      # Speed float
      { speed: @file.float }
    when 6
      # type = 6 Character C
      # Speed float
      { speed: @file.float }
    when 7
      # type = 7 Durchgang - Tuer
      # WorkingTime float, Material int, CrackType int
      {
        working_time: @file.float,
        material: @file.int,
        crack_type: @file.int
      }
    when 8
      # type = 8 Durchgang - Fenster
      # WorkingTime float, Material int, CrackType int
      {
        working_time: @file.float,
        material: @file.int,
        crack_type: @file.int
      }
    when 9
      # type = 9 Car
      # Transp. Space float, MaxSpeed float, Acceleration float,
      # Value float (cost), Driving float
      {
        transp_space: @file.float,
        max_speed: @file.float,
        acceleration: @file.float,
        value: @file.float,
        driving: @file.float
      }
    else
      raise "Unknown type: #{type}"
    end
  end
end

# Parses a objects
class ObjectParser
  def initialize(file)
    @file = file
  end

  def parse
    nodes = []
    token, _data_size = @file.token_with_size
    return nodes if token == 'END '
    raise StandardError, "Bad parse OBJECTS. Expected 'OBJ ', got '#{token}'" unless token == 'OBJ '

    index = 1
    while token == 'OBJ '
      item = {
        type: @file.int,
        name: @file.name,
        index:,
        parent_folder: @file.int
      }
      count_of_unknow2 = @file.int
      item[:unknow2] = parse_unknow2(count_of_unknow2)

      word = @file.word # info
      raise 'not info' if word != 'INFO'

      item[:info] = InfoParser.new(@file).parse
      nodes << item

      index += 1
      token, _data_size = @file.token_with_size
    end

    raise StandardError, "Bad end of Objects, expected 'END ' but got '#{token}'" unless token == 'END '

    nodes
  end

  def parse_unknow2(count)
    count.times.map do
      item = {
        name: @file.name,
        unknow1: @file.int,
        unknow2: @file.float,
        unknow3: @file.float,
        unknow4: @file.int,
        alway_negative100: @file.float, # -100.0
        unknow5: @file.negative_bool,
        unknow6: @file.negative_bool
      }
      count_of_unknow7 = @file.int
      item[:unknow7] = count_of_unknow7.times.map do
        {
          name: @file.name,
          unknow1: @file.float
        }
      end
      item
    end
  end
end

class WorldParser
  def initialize(file)
    @file = file
  end

  def parse
    nodes = []
    token = @file.token
    return nodes if token == 'END '
    raise StandardError, "Bad parse WORLD. Expected 'NODE', got '#{token}'" unless token == 'NODE'

    index = 2
    while token == 'NODE'
      item = {
        type15: @file.int,
        parent_iid: @file.int,
        folder_name: @file.name,
        index:,
        x: @file.float,
        y: @file.float,
        z: @file.float,
        w: @file.float,
        n: @file.float,
        u: @file.float,
        unknow1: @file.int,
        type: @file.int
      }

      case item[:type]
      when 0 # folder
        item[:folder] = []
        item[:folder].push @file.int
        item[:folder].push @file.int
        item[:folder].push @file.int
        item[:folder].push @file.int
      when 1 # ground
        item[:model_id] = @file.int
        item[:model_name] = nil
        item[:ground] = {}
        connections_count = @file.int
        if connections_count > 0
          item[:ground][:connections] = []
          connections_count.times.each do |_|
            item[:ground][:connections].push [@file.int, @file.int]
          end
        end
        item[:ground][:unknow2] = @file.int
        shad = @file.word
        if shad == 'SHAD'
          item[:shad] = {}
          item[:shad][:size1] = @file.int
          item[:shad][:size2] = @file.int

          item[:shad][:data] = []
          shad_word = @file.word
          while shad_word != 'NODE' && shad_word != 'END '
            @file.back
            item[:shad][:data].push @file.float
            shad_word = @file.word
          end
          @file.back
        end
      when 2
        item[:object_id] = @file.int
        item[:object_name] = nil
        item[:item] = {}
        item[:item][:unknow_zero] = @file.int
        item[:item][:info] = InfoParser.new(@file).parse if @file.word == 'INFO'
        item[:item][:unknow_zero2] = @file.int
      when 3
        item[:light] = {}
        item[:light][:unknow1] = @file.int
        item[:light][:unknow_floats11] = []
        11.times.each do |_|
          item[:light][:unknow_floats11].push @file.float
        end
        item[:light][:unknow2] = @file.int
        item[:light][:unknow_floats13] = []
        13.times.each do |_|
          item[:light][:unknow_floats13].push @file.float
        end
        item[:light][:unknow3] = @file.int
        item[:light][:unknow4] = @file.int
        item[:light][:unknow5] = @file.int
        item[:light][:unknow6] = @file.int
      end

      nodes << item

      index += 1
      token = @file.token
    end

    raise StandardError, "Bad end of World, expected 'END ' but got '#{token}'" unless token == 'END '

    nodes
  end
end

class Parser
  attr_reader :file, :texture_pages, :model_list_tree, :object_list_tree, :models, :objects, :macros, :word_tree

  def initialize(filepath)
    @file = FileReader.new(filepath)
    @texture_pages = []
    @model_list_tree = []
    @object_list_tree = []
    @models = []
  end

  def processed
    if @file.token != 'WRLD'
      @file.close
      raise StandardError, "Opened file is not a 'The Sting!' game file. Expected 'WRLD', got '#{token}'"
    end

    until file.eof?
      token = file.token

      case token
      when 'TEXP'
        # puts "Texture Pages\t\treading..."
        @texture_pages = TexturePageParser.new(@file).parse
        # puts "Texture Pages\t\tend reading"
      when 'GROU'
        # puts "Model List Tree\t\treading..."
        @model_list_tree = TreeParser.new(@file, 'Model List Tree').parse
        # puts "Model List Tree\t\tend reading"
      when 'OBGR'
        # puts "Object List Tree\treading..."
        @object_list_tree = TreeParser.new(@file, 'Object List Tree').parse
        # puts "Object List Tree\t\tend reading"
      when 'LIST'
        # puts "Model List\t\treading..."
        @models = ModelParser.new(@file).parse
        # puts "Model List\t\tend reading"
      when 'OBJS'
        # puts "Object List\t\treading..."
        @objects = ObjectParser.new(@file).parse
        # parse_obj
        # puts "Object List\t\tend reading"
      when 'MAKL'
        # puts "Makro List\t\treading..."
        @macros = parse_obj
        # puts "Makro List\t\tend reading"
      when 'TREE'
        # puts "World Tree\t\treading..."
        @word_tree = WorldParser.new(@file).parse
        # puts "World Tree\t\tend reading"
      when 'EOF '
        @file.close
        return
      else
        raise StandardError, "Bad token in game file. Got '#{token}'"
      end
    end
    raise StandardError, "Bad end of file for 'The Sting!' game file"
  end

  def parse_obj
    token = @file.word
    size = @file.bigendian_int
    return [] if token == 'END '

    res = []
    while token == 'OBJ '
      res << file.hex(size).pack('H*')
      token = @file.word
      size = @file.bigendian_int
    end
    res
  end

  def parse_dummy
    token = @file.word
    size = @file.bigendian_int
    return [] if token == 'END '

    res = []
    while token == 'NODE'
      res << file.hex(size).pack('H*')
      token = @file.word
      size = @file.bigendian_int
    end
    res
  end
end
