#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'

# ----------------------------- Константы/настройки ----------------------------

STRIP_TEX_PATHS  = true
FORCE_PNG_EXT    = false
FLIP_V           = true
USE_UV_FROM_VBUF = true

DEFAULT_POWER    = 10.0
DEFAULT_SPECULAR = [0.2, 0.2, 0.2]
DEFAULT_EMISSIVE = [0.0, 0.0, 0.0]

# Анимация/время
TICKS_PER_SECOND  = 4800
ANIM_FPS_DEFAULT  = 24.0
CLIP_START_FRAME  = 0.0
CLIP_END_FRAME    = 24.0

# ------------------------------- Вспомогательные ------------------------------

module MathX
  module_function

  def mat_identity
    [[1, 0, 0, 0],
     [0, 1, 0, 0],
     [0, 0, 1, 0],
     [0, 0, 0, 1]]
  end

  def extract_3x3(m) = (m || mat_identity)[0, 3].map { |row| row[0, 3] }
  def extract_t(m)   = (m || mat_identity)[3][0, 3]

  def build_rt(r3, t)
    [
      [r3[0][0], r3[0][1], r3[0][2], 0.0],
      [r3[1][0], r3[1][1], r3[1][2], 0.0],
      [r3[2][0], r3[2][1], r3[2][2], 0.0],
      [t[0],     t[1],     t[2],     1.0]
    ]
  end
end

# ----------------------------- 1) Подготовка данных ---------------------------

class XDataPreparer
  include MathX

  # Публичная точка входа
  def prepare(input_path)
    raw   = JSON.parse(File.read(input_path))
    items = raw.is_a?(Array) ? raw : [raw]

    scene = {
      root_index: nil,
      frames: {}, # index => { name:, matrix_local:, children:[frame_i], meshes:[mesh_i], is_joint:bool, anim:{} }
      meshes: {} # index => { name:, pos:, nrm:, uv:, tris:, materials:[] }
    }

    by_parent = collect_tree(items)
    root = items.find { |it| it['word'] == 'ROOT' } || items.first
    scene[:root_index] = root['index']

    # Построение кадров (FRAM/ROOT/JOIN) и мешей
    items.each do |it|
      case it['word']
      when 'ROOT', 'FRAM', 'JOIN'
        scene[:frames][it['index']] = build_frame(it, by_parent)
      when 'MESH'
        scene[:meshes][it['index']] = build_mesh(it)
      end
    end

    # Привязка мешей к фреймам-родителям
    items.each do |it|
      next unless it['word'] == 'MESH'

      parent = it['parent_iid']
      next unless scene[:frames][parent]

      scene[:frames][parent][:meshes] << it['index']
    end

    scene
  end

  # -------------------------- Построение узлов/мешей -------------------------

  def collect_tree(items)
    by_parent = Hash.new { |h, k| h[k] = [] }
    items.each { |it| by_parent[it['parent_iid']] << it }
    by_parent
  end

  def build_frame(node, children)
    d = node['data'] || {}

    # «Печка» локальной матрицы как в Maya-экспортёре:
    # если у узла есть rotation_matrix (4x4) и matrix (4x4 с трансляцией в m[3][0..2]),
    # то локальная = R(из rotation_matrix) + T(из matrix)
    r3 = MathX.extract_3x3(d['rotation_matrix'])
    t  = MathX.extract_t(d['matrix'])
    baked_local = d['rotation_matrix'] && d['matrix'] ? MathX.build_rt(r3, t) : (d['matrix'] || MathX.mat_identity)

    {
      name: node['name'].to_s.strip.empty? ? 'Root' : node['name'].to_s.strip,
      matrix_local: baked_local,
      children: (children[node['index']] || []).filter do |c|
        %w[FRAM ROOT JOIN].include?(c['word'])
      end.map { |c| c['index'] },
      meshes: [],
      is_joint: node['word'] == 'JOIN'
    }
  end

  def build_mesh(mesh)
    d    = mesh['data'] || {}
    name = mesh['name'].to_s.empty? ? 'Mesh' : mesh['name']

    vbuf = d['vbuf'] || []
    tris = (d['ibuf'] || []).flatten.each_slice(3).to_a

    pos = vbuf.map { |v| [v[0].to_f, v[1].to_f, v[2].to_f] }
    nrm = if vbuf.first && vbuf.first.size >= 6
            vbuf.map { |v| [v[3].to_f, v[4].to_f, v[5].to_f] }
          else
            Array.new(pos.length, [0.0, 1.0, 0.0])
          end

    uv = if USE_UV_FROM_VBUF && vbuf.first && vbuf.first.size >= 8
           vbuf.map do |v|
             u = v[-2].to_f
             vv = v[-1].to_f
             vv = 1.0 - vv if FLIP_V
             [u, vv]
           end
         else
           (d['uvpt'] || Array.new(pos.length, [0.0, 0.0])).map do |uv0|
             u = uv0[0].to_f
             vv = uv0[1].to_f
             vv = 1.0 - vv if FLIP_V
             [u, vv]
           end
         end

    mats = d['materials'] || []
    mats = [{ 'name' => 'DefaultWhite', 'red' => 1, 'green' => 1, 'blue' => 1, 'alpha' => 1 }] if mats.empty?

    {
      name: name,
      pos: pos,
      nrm: nrm,
      uv: uv,
      tris: tris,
      materials: mats
    }
  end
end

class XFileWriter
  INDENT = '  ' # 2 пробела на уровень

  def write(scene, output_path)
    File.open(output_path, 'w') do |io|
      io.puts 'xof 0303txt 0032'
      write_frame_recursive(io, scene, scene[:root_index], 1)
    end
  end

  private

  def iputs(io, level, line = '')
    io.puts("#{INDENT * level}#{line}")
  end

  def fmt_f(val)
    format('%.6f', val.to_f).sub('-0.000000', '0.000000').to_f
  end

  def write_frame_recursive(io, scene, frame_index, level)
    frame = scene[:frames][frame_index]
    name  = frame[:name]

    iputs io, level, "Frame #{name} {"

    # FrameTransformMatrix
    iputs io, level + 1, 'FrameTransformMatrix {'
    rows = frame[:matrix_local].map do |row|
      "#{INDENT * (level + 2)}#{row.map { |v| fmt_f(v) }.join(', ')}"
    end
    # Каждая строка уже предвосхищена отступом; между строками — запятые, в конце — ";;"
    io.puts rows.join(",\n") + ';;'
    iputs io, level + 1, '}'

    # Дочерние фреймы
    frame[:children].each do |child_idx|
      write_frame_recursive(io, scene, child_idx, level + 1)
    end

    # Меши
    frame[:meshes].each do |mesh_idx|
      write_mesh(io, scene[:meshes][mesh_idx], level + 1)
    end

    iputs io, level, '}'
  end

  def write_mesh(io, mesh, level)
    name = mesh[:name]
    pos  = mesh[:pos]
    nrm  = mesh[:nrm]
    uv   = mesh[:uv]
    tris = mesh[:tris]
    mats = mesh[:materials]
    if mats.nil? || mats.empty?
      mats = [{ 'name' => 'DefaultWhite', 'red' => 1, 'green' => 1, 'blue' => 1, 'alpha' => 1 }]
    end

    iputs io, level, "Mesh #{name} {"

    # vertices
    iputs io, level + 1, "#{pos.length};"
    vertex_lines = pos.map do |p|
      "#{INDENT * (level + 2)}#{fmt_f(p[0])}; #{fmt_f(p[1])}; #{fmt_f(p[2])};"
    end
    io.puts vertex_lines.join(",\n") + ';' # завершаем списком с ";;" на последней строке

    # faces (triangles)
    iputs io, level + 1, "#{tris.length};"
    face_lines = tris.map do |t|
      "#{INDENT * (level + 2)}3; #{t[0]},#{t[1]},#{t[2]};"
    end
    io.puts face_lines.join(",\n") + ';'

    # materials
    mat_indices = tris.length > 0 ? Array.new(tris.length, 0).join(',') : ''
    iputs io, level + 1, 'MeshMaterialList {'
    iputs io, level + 2, "#{mats.length};"
    iputs io, level + 2, "#{tris.length};"
    iputs io, level + 2, "#{mat_indices};;"
    mats.each { |m| write_material(io, m, level + 2) }
    iputs io, level + 1, '}'

    # normals
    if nrm.any?
      iputs io, level + 1, 'MeshNormals {'
      iputs io, level + 2, "#{nrm.length};"
      nrm.each_with_index do |n, i|
        tail = (i == nrm.length - 1) ? ';;' : ';,'
        iputs io, level + 2, "#{fmt_f(n[0])}; #{fmt_f(n[1])}; #{fmt_f(n[2])}#{tail}"
      end
      iputs io, level + 2, "#{tris.length};"
      tris.each_with_index do |t, i|
        tail = (i == tris.length - 1) ? ';;' : ';,'
        iputs io, level + 2, "3; #{t[0]},#{t[1]},#{t[2]}#{tail}"
      end
      iputs io, level + 1, '}'
    end

    # uv (texcoords)
    if uv.any?
      iputs io, level + 1, 'MeshTextureCoords {'
      iputs io, level + 2, "#{uv.length};"
      uv.each_with_index do |tc, i|
        tail = (i == uv.length - 1) ? ';;' : ';,'
        iputs io, level + 2, "#{fmt_f(tc[0])}; #{fmt_f(tc[1])}#{tail}"
      end
      iputs io, level + 1, '}'
    end

    # vertex colors (из первого материала — как fallback)
    m0 = mats.first
    cr = m0['red']   || 1
    cg = m0['green'] || 1
    cb = m0['blue']  || 1
    ca = m0['alpha'] || 1
    iputs io, level + 1, 'MeshVertexColors {'
    iputs io, level + 2, "#{pos.length};"
    pos.each_with_index do |_, i|
      tail = (i == pos.length - 1) ? ';;' : ';,'
      iputs io, level + 2, "#{i}; #{fmt_f(cr)}; #{fmt_f(cg)}; #{fmt_f(cb)}; #{fmt_f(ca)}#{tail}"
    end
    iputs io, level + 1, '}'

    iputs io, level, '}'
  end

  def texture_name(mat)
    t = mat.dig('texture', 'name')
    return nil unless t && !t.empty?

    t = STRIP_TEX_PATHS ? File.basename(t) : t.tr('\\', '/')
    t = t.sub(/\.(tif|tiff)\z/i, '.png') if FORCE_PNG_EXT
    t.tr('\\', '/')
  end

  def write_material(io, mat, level)
    r = (mat['red']   || 1.0).to_f
    g = (mat['green'] || 1.0).to_f
    b = (mat['blue']  || 1.0).to_f
    a = (mat['alpha'] || 1.0).to_f
    name = mat['name'].to_s.empty? ? 'Material' : mat['name']

    iputs io, level, "Material #{name} {"
    iputs io, level + 1, "#{fmt_f(r)}; #{fmt_f(g)}; #{fmt_f(b)}; #{fmt_f(a)};;"
    iputs io, level + 1, "#{fmt_f(DEFAULT_POWER)};"
    iputs io, level + 1, "#{fmt_f(DEFAULT_SPECULAR[0])}; #{fmt_f(DEFAULT_SPECULAR[1])}; #{fmt_f(DEFAULT_SPECULAR[2])};;"
    iputs io, level + 1, "#{fmt_f(DEFAULT_EMISSIVE[0])}; #{fmt_f(DEFAULT_EMISSIVE[1])}; #{fmt_f(DEFAULT_EMISSIVE[2])};;"
    tex = texture_name(mat)
    iputs io, level + 1, "TextureFilename { \"#{tex}\"; }" if tex
    iputs io, level, '}'
  end
end

class XFileWriterBin
  # ===== Tokens (WORD) =====
  TOKEN_NAME         = 1
  TOKEN_STRING       = 2
  TOKEN_INTEGER      = 3
  TOKEN_GUID         = 5
  TOKEN_INTEGER_LIST = 6
  TOKEN_FLOAT_LIST   = 7

  TOKEN_OBRACE    = 10
  TOKEN_CBRACE    = 11
  TOKEN_OBRACKET  = 14
  TOKEN_CBRACKET  = 15
  TOKEN_SEMICOLON = 20

  # ===== Header (DWORD) =====
  XOFFILE_FORMAT_MAGIC       = ('x'.ord) | ('o'.ord << 8) | ('f'.ord << 16) | (' '.ord << 24)
  XOFFILE_FORMAT_VERSION_0302= ('0'.ord) | ('3'.ord << 8) | ('0'.ord << 16) | ('2'.ord << 24)
  XOFFILE_FORMAT_BINARY      = ('b'.ord) | ('i'.ord << 8) | ('n'.ord << 16) | (' '.ord << 24)
  XOFFILE_FLOAT_32           = ('0'.ord) | ('0'.ord << 8) | ('3'.ord << 16) | ('2'.ord << 24)

  def write(scene, output_path)
    File.open(output_path, 'wb') do |io|
      write_header(io)
      write_frame_recursive(io, scene, scene[:root_index])
    end
  end

  private

  # ========= low-level ==========

  def w_word(io, v)  = io.write [v].pack('v')        # little-endian WORD
  def w_dword(io, v) = io.write [v].pack('V')        # little-endian DWORD
  def w_f32(io, f)   = io.write [f.to_f].pack('e')   # little-endian float

  def write_header(io)
    w_dword(io, XOFFILE_FORMAT_MAGIC)
    w_dword(io, XOFFILE_FORMAT_VERSION_0302)
    w_dword(io, XOFFILE_FORMAT_BINARY)
    w_dword(io, XOFFILE_FLOAT_32)
  end

  # token writers
  def t(io, token)          = w_word(io, token)
  def t_name(io, s)
    s = s.to_s
    t(io, TOKEN_NAME)
    w_dword(io, s.bytesize)
    io.write s
  end
  def t_string(io, s, terminator = TOKEN_SEMICOLON)
    s = s.to_s
    t(io, TOKEN_STRING)
    w_dword(io, s.bytesize)
    io.write s
    w_word(io, terminator)
  end
  def t_int_list(io, arr)
    t(io, TOKEN_INTEGER_LIST)
    w_dword(io, arr.length)
    arr.each { |v| w_dword(io, Integer(v)) }
  end
  def t_float_list(io, arr)
    t(io, TOKEN_FLOAT_LIST)
    w_dword(io, arr.length)
    arr.each { |f| w_f32(io, f.to_f) }
  end

  def begin_object(io, identifier, instance_name=nil)
    t_name(io, identifier)          # identifier (template name)
    t_name(io, instance_name) if instance_name && !instance_name.empty? # optional object name
    t(io, TOKEN_OBRACE)
  end
  def end_object(io) = t(io, TOKEN_CBRACE)

  # ========= domain helpers ==========

  def write_frame_recursive(io, scene, frame_index)
    f = scene[:frames][frame_index]
    begin_object(io, 'Frame', f[:name])

    # FrameTransformMatrix { float[16] }
    begin_object(io, 'FrameTransformMatrix')
    # matrix_local — 4x4 (row-major как в txt-выводе)
    flat = f[:matrix_local].flatten(1).map!(&:to_f)
    t_float_list(io, flat)
    end_object(io)

    # children
    f[:children].each { |idx| write_frame_recursive(io, scene, idx) }

    # meshes
    f[:meshes].each { |midx| write_mesh(io, scene[:meshes][midx]) }

    end_object(io)
  end

  def write_mesh(io, mesh)
    name = mesh[:name]
    pos  = mesh[:pos]  # [[x,y,z]...]
    tris = mesh[:tris] # [[i0,i1,i2]...]
    nrm  = mesh[:nrm]  # [[nx,ny,nz]...]
    uv   = mesh[:uv]   # [[u,v]...]
    mats = mesh[:materials]
    if mats.nil? || mats.empty?
      mats = [{ 'name'=>'DefaultWhite','red'=>1,'green'=>1,'blue'=>1,'alpha'=>1 }]
    end

    begin_object(io, 'Mesh', name)

    # nVertices; vertices[]
    t_int_list(io, [pos.length])
    t_float_list(io, pos.flat_map { |p| [p[0],p[1],p[2]] })

    # nFaces; face[i]: n; indices[n]
    t_int_list(io, [tris.length])
    tris.each do |t3|
      t_int_list(io, [3])               # MeshFace.nFaceVertexIndices
      t_int_list(io, [t3[0], t3[1], t3[2]]) # MeshFace.faceVertexIndices[]
    end

    # MeshMaterialList
    write_mesh_material_list(io, mats, tris.length)

    # MeshNormals (если есть)
    if nrm && !nrm.empty?
      begin_object(io, 'MeshNormals')
      t_int_list(io, [nrm.length])
      t_float_list(io, nrm.flat_map { |n| [n[0],n[1],n[2]] })
      t_int_list(io, [tris.length])
      tris.each do |t3|
        t_int_list(io, [3])
        t_int_list(io, [t3[0], t3[1], t3[2]])
      end
      end_object(io)
    end

    # MeshTextureCoords (если есть)
    if uv && !uv.empty?
      begin_object(io, 'MeshTextureCoords')
      t_int_list(io, [uv.length])
      t_float_list(io, uv.flat_map { |tc| [tc[0], tc[1]] })
      end_object(io)
    end

    # MeshVertexColors (по первому материалу — fallback)
    write_mesh_vertex_colors(io, pos.length, mats.first)

    end_object(io) # Mesh
  end

  def write_mesh_material_list(io, mats, face_count)
    begin_object(io, 'MeshMaterialList')
    # nMaterials; nFaceIndexes; faceIndexes[]  (всё в 0-й материал для простоты)
    t_int_list(io, [mats.length])
    t_int_list(io, [face_count])
    t_int_list(io, (face_count > 0 ? Array.new(face_count, 0) : []))
    # сами материалы
    mats.each { |m| write_material(io, m) }
    end_object(io)
  end

  def write_mesh_vertex_colors(io, vertex_count, m0)
    cr = (m0['red']   || 1).to_f
    cg = (m0['green'] || 1).to_f
    cb = (m0['blue']  || 1).to_f
    ca = (m0['alpha'] || 1).to_f

    begin_object(io, 'MeshVertexColors')
    t_int_list(io, [vertex_count])     # nVertexColors
    vertex_count.times do |i|
      # IndexedColor: index (DWORD), ColorRGBA (4 floats)
      t_int_list(io, [i])
      t_float_list(io, [cr, cg, cb, ca])
    end
    end_object(io)
  end

  def write_material(io, mat)
    name = (mat['name'].to_s.empty? ? 'Material' : mat['name'])
    r = (mat['red']   || 1.0).to_f
    g = (mat['green'] || 1.0).to_f
    b = (mat['blue']  || 1.0).to_f
    a = (mat['alpha'] || 1.0).to_f

    power     = DEFAULT_POWER
    specular  = DEFAULT_SPECULAR
    emissive  = DEFAULT_EMISSIVE
    tex       = texture_name(mat)

    begin_object(io, 'Material', name)
    t_float_list(io, [r, g, b, a])      # faceColor (ColorRGBA)
    t_float_list(io, [power])           # power
    t_float_list(io, specular)          # specularColor (ColorRGB)
    t_float_list(io, emissive)          # emissiveColor (ColorRGB)

    if tex
      begin_object(io, 'TextureFilename')
      t_string(io, tex)                 # строка с завершающим TOKEN_SEMICOLON
      end_object(io)
    end

    end_object(io)
  end

  # ==== те же утилиты из вашего кода ====

  def texture_name(mat)
    t = mat.dig('texture','name')
    return nil if t.nil? || t.empty?
    t = STRIP_TEX_PATHS ? File.basename(t) : t.tr('\\','/')
    t = t.sub(/\.(tif|tiff)\z/i, '.png') if FORCE_PNG_EXT
    t.tr('\\','/')
  end

  # Значения по умолчанию — как у вас
  DEFAULT_POWER     = 8.0
  DEFAULT_SPECULAR  = [0.0, 0.0, 0.0]
  DEFAULT_EMISSIVE  = [0.0, 0.0, 0.0]
end
# ----------------------------------- CLI -------------------------------------

def main(argv)
  if argv.length != 1
    warn "Usage: ruby #{File.basename($0)} input.json"
    exit 1
  end
  inp = argv.first
  outp = inp.sub('.json', '.x')
  data = XDataPreparer.new.prepare(inp)
  XFileWriter.new.write(data, outp)
end

main(ARGV)
