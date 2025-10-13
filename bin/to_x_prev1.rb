#!/usr/bin/env ruby
# frozen_string_literal: true
require 'json'

STRIP_TEX_PATHS  = true
FORCE_PNG_EXT    = false
FLIP_V           = true
USE_UV_FROM_VBUF = true

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

# Нормализация времени: по умолчанию 0..24 кадров @ 24 fps => 1.0 сек.
ANIM_FPS          = 24.0
CLIP_START_FRAME  = 0.0
CLIP_END_FRAME    = 24.0

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
  m.flatten
end

# Линейная интерполяция по нормализованному времени [0..1]
def lerp(a, b, t)
  a + (b - a) * t
end

def sample_channel(keys_norm, values, t_norm)
  return nil if keys_norm.nil? || values.nil? || keys_norm.empty? || values.empty?
  # граничные случаи
  return values.first.to_f if t_norm <= keys_norm.first.to_f + 1e-8
  return values.last.to_f  if t_norm >= keys_norm.last.to_f  - 1e-8

  # двоичный поиск сегмента
  lo = 0
  hi = keys_norm.length - 1
  while hi - lo > 1
    mid = (lo + hi) / 2
    if t_norm < keys_norm[mid].to_f
      hi = mid
    else
      lo = mid
    end
  end
  t0 = keys_norm[lo].to_f
  t1 = keys_norm[hi].to_f
  v0 = values[lo].to_f
  v1 = values[hi].to_f
  alpha = (t_norm - t0) / (t1 - t0 + 1e-12)
  lerp(v0, v1, alpha)
end

# Собираем уникальный отсортированный список ВСЕХ ключей (нормализованных)
def gather_all_key_times(anim)
  times = []

  %w[translation rotation scaling].each do |grp|
    h = anim[grp] || {}
    k = (h['keys'] || {})
    %w[x y z].each do |axis|
      arr = k[axis]
      times.concat(arr) if arr.is_a?(Array)
    end
  end

  times = times.map(&:to_f).uniq.sort
  times
end

def to_ticks(seconds)
  (seconds.to_f * TICKS_PER_SECOND).round
end

def write_animation_for_node(io, node)
  anim = node.dig('data','anim')
  return false unless anim && anim.is_a?(Hash)

  # Базовые TRS (если канал пуст или нет анимации)
  base_t = node.dig('data','translation') || [0.0,0.0,0.0]
  base_s = node.dig('data','scaling')     || [1.0,1.0,1.0]
  base_r = node.dig('data','rotation')    || [0.0,0.0,0.0]

  tr   = anim['translation'] || {'values'=>{},'keys'=>{}}
  sc   = anim['scaling']     || {'values'=>{},'keys'=>{}}
  rot  = anim['rotation']    || {'values'=>{},'keys'=>{}}

  # Если когда-то добавите метаданные клипа — используйте их тут:
  # meta = anim['meta'] || {}
  # fps  = (meta['fps'] || ANIM_FPS).to_f
  # f0   = (meta['startFrame'] || CLIP_START_FRAME).to_f
  # f1   = (meta['endFrame']   || CLIP_END_FRAME).to_f
  fps = ANIM_FPS
  f0  = CLIP_START_FRAME
  f1  = CLIP_END_FRAME

  duration_sec = (f1 - f0) / fps

  # Список всех нормализованных ключей [0..1]
  times_norm = gather_all_key_times(anim)
  return false if times_norm.nil? || times_norm.empty?

  # Подготовим ссылки на ключи/значения по каналам
  t_keys = tr['keys']   || {}
  t_vals = tr['values'] || {}
  r_keys = rot['keys']  || {}
  r_vals = rot['values']|| {}
  s_keys = sc['keys']   || {}
  s_vals = sc['values'] || {}

  frame_name = node['name'].to_s.strip
  frame_name = 'Root' if frame_name.empty?

  io.puts "  Animation {"
  io.puts "    {#{frame_name}}"
  io.puts "    AnimationKey {"
  io.puts "      4;"  # 4 == matrix keys

  io.puts "      #{times_norm.length};"

  times_norm.each_with_index do |t_norm, i|
    # значения по каналам с интерполяцией
    tx = sample_channel(t_keys['x'], t_vals['x'], t_norm) || base_t[0].to_f
    ty = sample_channel(t_keys['y'], t_vals['y'], t_norm) || base_t[1].to_f
    tz = sample_channel(t_keys['z'], t_vals['z'], t_norm) || base_t[2].to_f

    sx = sample_channel(s_keys['x'], s_vals['x'], t_norm) || base_s[0].to_f
    sy = sample_channel(s_keys['y'], s_vals['y'], t_norm) || base_s[1].to_f
    sz = sample_channel(s_keys['z'], s_vals['z'], t_norm) || base_s[2].to_f

    rx = sample_channel(r_keys['x'], r_vals['x'], t_norm) || base_r[0].to_f
    ry = sample_channel(r_keys['y'], r_vals['y'], t_norm) || base_r[1].to_f
    rz = sample_channel(r_keys['z'], r_vals['z'], t_norm) || base_r[2].to_f

    # Построение матрицы TRS
    m = mat_identity
    m = mat_mul(m, mat_scale(sx, sy, sz))
    m = mat_mul(m, mat_from_euler_xyz(rx, ry, rz))
    m = mat_mul(m, mat_translation(tx, ty, tz))

    flat = flatten_row_major_16(m).map { |v| fmt_f(v) }

    t_sec  = t_norm.to_f * duration_sec
    tick   = to_ticks(t_sec)

    io.puts "      #{tick};16;" + flat.join(', ') + ";;#{i + 1 == times_norm.size ? ';' : ','}"
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

  # --- Material list ---
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

  # --- Vertex colors ---
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
