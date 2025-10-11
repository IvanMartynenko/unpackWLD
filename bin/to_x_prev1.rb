#!/usr/bin/env ruby
# frozen_string_literal: true
require 'json'

STRIP_TEX_PATHS = true     # обрезать директории у путей
FORCE_PNG_EXT   = false     # .tif -> .png в TextureFilename
FLIP_V          = true     # инвертировать V
USE_UV_FROM_VBUF = true    # брать uv из хвоста vbuf (как у тебя)

DEFAULT_POWER    = 10.0
DEFAULT_SPECULAR = [0.2, 0.2, 0.2]
DEFAULT_EMISSIVE = [0.0, 0.0, 0.0]

def fmt_f(x) = ('%.6f' % x.to_f).sub(/-0\.000000/, '0.000000').to_f

def write_matrix(io, m)
  io.puts "    FrameTransformMatrix {"
  m.each_with_index do |row, i|
    line = row.map { |v| fmt_f(v) }.join(', ')
    io.puts "      #{line}#{i == 3 ? ';;' : ','}"
  end
  io.puts "    }"
end

# --- Animation export --------------------------------------------------------

TICKS_PER_SECOND = 4800

def mat_identity
  [[1,0,0,0],
   [0,1,0,0],
   [0,0,1,0],
   [0,0,0,1]]
end

def mat_mul(a, b)
  m = Array.new(4) { Array.new(4, 0.0) }
  4.times do |i|
    4.times do |j|
      s = 0.0
      4.times { |k| s += a[i][k] * b[k][j] }
      m[i][j] = fmt_f(s)
    end
  end
  m
end

def mat_translation(tx, ty, tz)
  [[1,0,0,0],
   [0,1,0,0],
   [0,0,1,0],
   [tx,ty,tz,1]]
end

def mat_scale(sx, sy, sz)
  [[sx,0,0,0],
   [0,sy,0,0],
   [0,0,sz,0],
   [0,0,0,1]]
end

def mat_from_euler_xyz(rx, ry, rz)
  cx, sx = Math.cos(rx), Math.sin(rx)
  cy, sy = Math.cos(ry), Math.sin(ry)
  cz, sz = Math.cos(rz), Math.sin(rz)

  # R = Rz * Ry * Rx (XYZ intrinsic == Z*Y*X extrinsic)
  rz_m = [[cz,  sz, 0,0],
          [-sz, cz, 0,0],
          [0,   0,  1,0],
          [0,   0,  0,1]]
  ry_m = [[cy, 0, -sy,0],
          [0,  1, 0,  0],
          [sy, 0, cy, 0],
          [0,  0, 0,  1]]
  rx_m = [[1, 0,  0, 0],
          [0, cx, sx,0],
          [0,-sx, cx,0],
          [0, 0,  0, 1]]

  mat_mul(mat_mul(rz_m, ry_m), rx_m)
end

def flatten_row_major_16(m)
  # .x AnimationKey matrix expects 16 floats row-major
  m.flatten
end

def find_time_array(values_hash)
  # Возвращает массив времени t[], если находит монотонно возрастающий [0..] массив
  candidates = values_hash.values.select { |arr| arr.is_a?(Array) && arr.length > 1 }
  mono = candidates.select do |arr|
    increasing = true
    prev = -Float::INFINITY
    arr.each { |v| (increasing &&= v.to_f >= prev + 1e-12); prev = v.to_f }
    increasing
  end
  # Выбираем самый длинный монотонный
  (mono.max_by { |arr| arr.length } || [])
end

def collect_anim_nodes(items)
  items.select { |it| it.dig('data','anim') }
end

def to_ticks(seconds)
  (seconds.to_f * TICKS_PER_SECOND).round
end

def write_animation_for_node(io, node)
  anim = node.dig('data','anim')
  return false unless anim && anim.is_a?(Hash)

  base_t = node.dig('data','translation') || [0.0,0.0,0.0]
  base_s = node.dig('data','scaling')     || [1.0,1.0,1.0]
  base_r = node.dig('data','rotation')    || [0.0,0.0,0.0]

  tr   = anim['translation'] || {'values'=>{},'keys'=>{}}
  sc   = anim['scaling']     || {'values'=>{},'keys'=>{}}
  rot  = anim['rotation']    || {'values'=>{},'keys'=>{}}

  t_times  = find_time_array(tr['values'] || {})
  s_times  = find_time_array(sc['values'] || {})
  r_times  = find_time_array(rot['values']|| {})

  # Набор всех времён (в секундах)
  times = [t_times, s_times, r_times].max_by(&:length)
  times = t_times if times.nil? || times.empty?
  times = s_times if (times.nil? || times.empty?) && !s_times.empty?
  times = r_times if (times.nil? || times.empty?) && !r_times.empty?
  return false if times.nil? || times.empty?

  # Подготовим массивы значений (заполняем базовыми, если канал пуст)
  tv = {
    'x' => tr.dig('values','x') && (tr['values']['x'].length == (tr['values']['z']||[]).length) ? nil : nil, # не используем как значения
    'y' => tr.dig('values','y'),
    'z' => tr.dig('values','z')
  }
  sv = {
    'x' => sc.dig('values','x'),
    'y' => sc.dig('values','y'),
    'z' => sc.dig('values','z')
  }
  rv = {
    'x' => rot.dig('values','x'),
    'y' => rot.dig('values','y'),
    'z' => rot.dig('values','z')
  }

  frame_name = node['name'].to_s.strip
  frame_name = 'Root' if frame_name.empty?

  io.puts "  Animation {"
  io.puts "    {#{frame_name}}"
  io.puts "    AnimationKey {"
  io.puts "      4;"  # 4 == matrix keys

  io.puts "      #{times.length};"

  times.each_with_index do |tsec, i|
    tx = tv['x'] && tv['x'][i] || base_t[0].to_f
    ty = tv['y'] && tv['y'][i] || base_t[1].to_f
    tz = tv['z'] && tv['z'][i] || base_t[2].to_f

    sx = sv['x'] && sv['x'][i] || base_s[0].to_f
    sy = sv['y'] && sv['y'][i] || base_s[1].to_f
    sz = sv['z'] && sv['z'][i] || base_s[2].to_f

    rx = rv['x'] && rv['x'][i] || base_r[0].to_f
    ry = rv['y'] && rv['y'][i] || base_r[1].to_f
    rz = rv['z'] && rv['z'][i] || base_r[2].to_f

    m = mat_identity
    m = mat_mul(m, mat_scale(sx, sy, sz))
    m = mat_mul(m, mat_from_euler_xyz(rx, ry, rz))
    m = mat_mul(m, mat_translation(tx, ty, tz))

    flat = flatten_row_major_16(m).map { |v| fmt_f(v) }
    tick = to_ticks(tsec)

    io.puts "      #{tick};16;" + flat.join(', ') + ";;#{i + 1 === times.size ? ';' : ','}"
  end

  io.puts "    }"
  io.puts "  }"
  true
end

def any_animations?(items)
  items.any? { |it| it.dig('data','anim') }
end

def write_animation_set(io, items)
  return unless any_animations?(items)
  io.puts "AnimationSet Anim_0 {"
  items.each do |node|
    write_animation_for_node(io, node)
  end
  io.puts "}"
end

def collect_tree(items)
  by_parent = Hash.new { |h,k| h[k] = [] }
  items.each { |it| by_parent[it['parent_iid']] << it }
  by_parent
end

def texture_name(mat)
  t = mat.dig('texture','name')
  return nil unless t && !t.empty?
  t = STRIP_TEX_PATHS ? File.basename(t) : t.tr('\\','/')
  if FORCE_PNG_EXT
    t = t.sub(/\.(tif|tiff)\z/i, '.png')
  end
  t.tr('\\','/')
end

def write_material(io, mat)
  r = (mat['red']   || 1.0).to_f
  g = (mat['green'] || 1.0).to_f
  b = (mat['blue']  || 1.0).to_f
  a = (mat['alpha'] || 1.0).to_f
  name = mat['name'].to_s.empty? ? 'Material' : mat['name']
  io.puts "        Material #{name} {"
  io.puts "          #{fmt_f(r)}; #{fmt_f(g)}; #{fmt_f(b)}; #{fmt_f(a)};;"
  io.puts "          #{fmt_f(DEFAULT_POWER)};"
  io.puts "          #{fmt_f(DEFAULT_SPECULAR[0])}; #{fmt_f(DEFAULT_SPECULAR[1])}; #{fmt_f(DEFAULT_SPECULAR[2])};;"
  io.puts "          #{fmt_f(DEFAULT_EMISSIVE[0])}; #{fmt_f(DEFAULT_EMISSIVE[1])}; #{fmt_f(DEFAULT_EMISSIVE[2])};;"
  tex = texture_name(mat)
  io.puts "          TextureFilename { \"#{tex}\"; }" if tex
  io.puts "        }"
end

def write_mesh(io, mesh)
  d    = mesh['data'] || {}
  name = mesh['name'].to_s.empty? ? 'Mesh' : mesh['name']

  vbuf = d['vbuf'] || []
  tris = (d['ibuf'] || []).flatten.each_slice(3).to_a

  pos = vbuf.map { |v| [v[0].to_f, v[1].to_f, v[2].to_f] }
  nrm = if vbuf.first && vbuf.first.size >= 6
          vbuf.map { |v| [v[3].to_f, v[4].to_f, v[5].to_f] }
        else
          Array.new(pos.length, [0.0,1.0,0.0])
        end
  uv  = if USE_UV_FROM_VBUF && vbuf.first && vbuf.first.size >= 8
          vbuf.map { |v|
            u,vv = v[-2].to_f, v[-1].to_f
            vv = 1.0 - vv if FLIP_V
            [u, vv]
          }
        else
          (d['uvpt'] || Array.new(pos.length, [0.0,0.0])).map { |uv|
            u,vv = uv[0].to_f, uv[1].to_f
            vv = 1.0 - vv if FLIP_V
            [u, vv]
          }
        end

  mats = d['materials'] || []
  mats = [ { 'name'=>'DefaultWhite', 'red'=>1, 'green'=>1, 'blue'=>1, 'alpha'=>1 } ] if mats.empty?

  io.puts "    Mesh #{name} {"
  # vertices
  io.puts "      #{pos.length};"
  pos.each_with_index do |p,i|
    io.puts "      #{fmt_f(p[0])}; #{fmt_f(p[1])}; #{fmt_f(p[2])}#{i==pos.length-1 ? ';;' : ';,'}"
  end
  # faces
  io.puts "      #{tris.length};"
  tris.each_with_index do |t,i|
    io.puts "      3; #{t[0]},#{t[1]},#{t[2]}#{i==tris.length-1 ? ';;' : ';,'}"
  end

  # --- Material list (раньше всего, чтобы капризные лоадеры подхватили) ---
  io.puts "      MeshMaterialList {"
  io.puts "        #{mats.length};"
  io.puts "        #{tris.length};"
  io.puts "        " + (tris.length>0 ? Array.new(tris.length, 0).join(',') : "") + ";;"
  mats.each { |m| write_material(io, m) }
  io.puts "      }"

  # --- Normals ---
  if nrm.any?
    io.puts "      MeshNormals {"
    io.puts "        #{nrm.length};"
    nrm.each_with_index do |n,i|
      io.puts "        #{fmt_f(n[0])}; #{fmt_f(n[1])}; #{fmt_f(n[2])}#{i==nrm.length-1 ? ';;' : ';,'}"
    end
    io.puts "        #{tris.length};"
    tris.each_with_index do |t,i|
      io.puts "        3; #{t[0]},#{t[1]},#{t[2]}#{i==tris.length-1 ? ';;' : ';,'}"
    end
    io.puts "      }"
  end

  # --- UV ---
  if uv.any?
    io.puts "      MeshTextureCoords {"
    io.puts "        #{uv.length};"
    uv.each_with_index do |tc,i|
      io.puts "        #{fmt_f(tc[0])}; #{fmt_f(tc[1])}#{i==uv.length-1 ? ';;' : ';,'}"
    end
    io.puts "      }"
  end

  # --- Vertex colors (чтобы уж точно был цвет, даже без текстур) ---
  m0 = mats.first
  cr,cg,cb,ca = (m0['red']||1), (m0['green']||1), (m0['blue']||1), (m0['alpha']||1)
  io.puts "      MeshVertexColors {"
  io.puts "        #{pos.length};"
  pos.each_with_index do |_,i|
    io.puts "        #{i}; #{fmt_f(cr)}; #{fmt_f(cg)}; #{fmt_f(cb)}; #{fmt_f(ca)}#{i==pos.length-1 ? ';;' : ';,'}"
  end
  io.puts "      }"

  io.puts "    }"
end

def write_frame_recursive(io, node, children)
  name = node['name'].to_s.strip
  name = 'Root' if name.empty?
  io.puts "  Frame #{name} {"
  mat = node.dig('data','matrix') || [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
  write_matrix(io, mat)

  (children[node['index']] || []).each do |ch|
    case ch['word']
    when 'FRAM' then write_frame_recursive(io, ch, children)
    when 'MESH' then write_mesh(io, ch)
    end
  end

  io.puts "  }"
end

def main(inp, outp)
  data = JSON.parse(File.read(inp))
  items = data.is_a?(Array) ? data : [data]
  children = collect_tree(items)
  root = items.find { |it| it['word'] == 'ROOT' } || items.first

  File.open(outp, 'w') do |io|
    io.puts "xof 0303txt 0032"
    write_frame_recursive(io, root, children)
    write_animation_set(io, items)
  end
end

if ARGV.length != 2
  warn "Usage: ruby #{File.basename($0)} input.json output.x"
  exit 1
end
main(ARGV[0], ARGV[1])
