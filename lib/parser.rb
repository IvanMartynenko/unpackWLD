require_relative 'file_reader'
require 'logger'

MATRIX_SIZE = 16

# Parses the texture pages section.
class TexturePageParser
  def initialize(file, logger)
    @file = file
    @logger = logger
  end

  def parse
    pages = []
    token = @file.token
    return pages if token == 'END '

    while token == 'PAGE'
      page = {
        type: @file.int,
        width: @file.int,
        height: @file.int,
        index: @file.int,
        textures_count: textures_count = @file.int,
        textures: textures_count.times.map { parse_texture }
      }

      token = @file.word
      raise StandardError, "Not found TXPG separator (got '#{token}')" unless token == 'TXPG'

      page[:is_alpha] = @file.negative_bool
      page[:binary_data] = @file.hex(page[:width] * page[:height] * 2)

      pages << page
      token = @file.token
    end

    raise StandardError, "Bad end of TexturePage, expected 'END ' but got '#{token}'" unless token == 'END '

    pages
  end

  def parse_texture
    {
      filepath: @file.read_filename,
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
  def initialize(file, logger, tree_name)
    @file = file
    @logger = logger
    @tree_name = tree_name
  end

  def parse
    nodes = []
    token = @file.token
    return nodes if token == 'END '

    index = 2
    while token == 'ENTR'
      nodes << {
        type: @file.int,
        name: @file.name,
        index:,
        parent: @file.int
      }
      index += 1
      token = @file.token
    end

    raise StandardError, "Bad end of #{@tree_name}, expected 'END ' but got '#{token}'" unless token == 'END '

    nodes
  end
end

# Parses models, including sub-elements like animations, meshes, and materials.
class ModelParser
  def initialize(file, logger)
    @file = file
    @logger = logger
  end

  def parse
    models = []
    index = 0
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
    model_info = {
      type: @file.int,
      id: @file.int,
      name: @file.name,
      influences_camera: @file.negative_bool,
      no_camera_check: @file.negative_bool,
      anti_ground: @file.negative_bool,
      default_skeleton: @file.int,
      use_skeleton: @file.int
    }

    camera_token = @file.word
    model_info[:camera] = camera_token == 'RMAC' ? parse_camera : nil

    model_info[:parent_folder] = @file.int
    model_info[:count_of_attack_points] = @file.int
    model_info[:attack_points] = model_info[:count_of_attack_points].times.map do
      { x: @file.float, y: @file.float, z: @file.float, radius: @file.float }
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
    token = @file.token
    raise StandardError, "Bad end of ModelList. Expected 'NMF ' but got '#{token}'" unless token == 'NMF '

    model = []
    index = 1
    loop do
      token = @file.word
      size = @file.bigendian_int
      break if token == 'END '

      type   = @file.int
      parent = @file.int
      name   = @file.name

      data = case token
             when 'ROOT' then parse_root
             when 'LOCA' then parse_loca
             when 'FRAM' then parse_fram
             when 'JOIN' then parse_join
             when 'MESH' then parse_mesh
             else
               raise StandardError, "Unexpected token in MODEL: #{token}"
             end

      model << { word: token, size: size, name: name, type: type, parent: parent, data: data, index: index }
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
    res[:unknown] = @file.bool
    keys = %i[translation scaling rotation]
    keys.each { |key| res[key] = {} }
    keys.each { |key| res[key][:sizes] = @file.ints(3) }
    keys.each { |key| res[key].merge!(parse_curve(res[key][:sizes])) }
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
    res[:material_count] = @file.int

    if res[:material_count] > 0
      res[:materials] = []
      res[:material_count].times { res[:materials] << parse_mtrl }
    end

    a = @file.word == 'ANIM' ? parse_anim_mesh : nil
    res[:mesh_anim] = a if a

    res[:unknown_count_of_floats] = @file.int
    res[:unknown_floats] = @file.floats(res[:unknown_count_of_floats] * 3) if res[:unknown_count_of_floats] > 0

    res[:unknown_count_of_ints] = @file.int
    res[:unknown_ints] = @file.ints(res[:unknown_count_of_ints]) if res[:unknown_count_of_ints] > 0

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
        name: @file.read_filename,
        texture_page: @file.int,
        index_texture_on_page: @file.int,
        x0: @file.int,
        y0: @file.int,
        x2: @file.int,
        y2: @file.int
      }
    elsif token.to_s == 'TEXT'
      res[:text] = { name: @file.read_filename }
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

class Parser
  attr_reader :file, :texture_pages, :model_list_tree, :object_list_tree, :models, :objects, :macros, :word_tree

  def initialize(filepath, logger = nil)
    @file = FileReader.new(filepath)
    @texture_pages = []
    @model_list_tree = []
    @object_list_tree = []
    @models = []
    if logger
      @logger = logger
    else
      @logger = Logger.new($stdout)
      @logger.level = Logger::INFO
    end
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
        @logger.info "Texture Pages\t\treading..."
        @texture_pages = TexturePageParser.new(@file, @logger).parse
        @logger.info "Texture Pages\t\tend reading"
      when 'GROU'
        @logger.info "Model List Tree\t\treading..."
        @model_list_tree = TreeParser.new(@file, @logger, 'Model List Tree').parse
        @logger.info "Model List Tree\t\tend reading"
      when 'OBGR'
        @logger.info "Object List Tree\treading..."
        @object_list_tree = TreeParser.new(@file, @logger, 'Object List Tree').parse
        @logger.info "Object List Tree\t\tend reading"
      when 'LIST'
        @logger.info "Model List\t\treading..."
        @models = ModelParser.new(@file, @logger).parse
        @logger.info "Model List\t\tend reading"
      when 'OBJS'
        @logger.info "Object List\t\treading..."
        @objects = parse_obj
        @logger.info "Object List\t\tend reading"
      when 'MAKL'
        @logger.info "Makro List\t\treading..."
        @macros = parse_obj
        @logger.info "Makro List\t\tend reading"
      when 'TREE'
        @logger.info "World Tree\t\treading..."
        @word_tree = parse_dummy
        @logger.info "World Tree\t\tend reading"
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
