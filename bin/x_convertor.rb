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

  def fmt_f(x)
    format('%.6f', x.to_f).sub('-0.000000', '0.000000').to_f
  end

  def mat_identity
    [[1, 0, 0, 0],
     [0, 1, 0, 0],
     [0, 0, 1, 0],
     [0, 0, 0, 1]]
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
    [[1, 0, 0, 0],
     [0, 1, 0, 0],
     [0, 0, 1, 0],
     [tx, ty, tz, 1]]
  end

  def mat_scale(sx, sy, sz)
    [[sx, 0, 0, 0],
     [0, sy, 0, 0],
     [0, 0, sz, 0],
     [0, 0, 0, 1]]
  end

  def mat_from_euler_xyz(rx, ry, rz)
    cx = Math.cos(rx)
    sx = Math.sin(rx)
    cy = Math.cos(ry)
    sy = Math.sin(ry)
    cz = Math.cos(rz)
    sz = Math.sin(rz)

    rz_m = [[cz,  sz, 0, 0],
            [-sz, cz, 0, 0],
            [0,   0,  1, 0],
            [0,   0,  0, 1]]
    ry_m = [[cy, 0, -sy, 0],
            [0,  1, 0,  0],
            [sy, 0, cy, 0],
            [0,  0, 0,  1]]
    rx_m = [[1, 0,  0, 0],
            [0, cx, sx, 0],
            [0, -sx, cx, 0],
            [0, 0, 0, 1]]

    mat_mul(mat_mul(rz_m, ry_m), rx_m)
  end

  def flatten_row_major_16(m)
    m.flatten
  end

  def lerp(a, b, t)
    a + ((b - a) * t)
  end

  # def to_ticks(seconds)
  #   (seconds.to_f * TICKS_PER_SECOND).round
  # end
  def to_ticks(seconds)
    ((seconds.to_f * TICKS_PER_SECOND) + 1e-6).round # небольшая подложка против -0.0000001
  end

  # ----- из Maya-скрипта: печка локальной матрицы из rotation_matrix + translate -----

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
      frames: {},     # index => { name:, matrix_local:, children:[frame_i], meshes:[mesh_i], is_joint:bool, anim:{} }
      meshes: {},     # index => { name:, pos:, nrm:, uv:, tris:, materials:[] }
      animation_set: nil
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

    # Анимация — готовим клипы для всех узлов с anim
    scene[:animation_set] = build_animation_set(items)

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
      is_joint: node['word'] == 'JOIN',
      anim: d['anim']
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

  # ------------------------------- Анимация -----------------------------------

  # собираем уникальные времена (могут быть секунды или 0..1)
  def gather_all_key_times(anim)
    times = []
    %w[translation rotation scaling visibility].each do |grp|
      h = anim[grp] || {}
      k = h['keys'] || {}
      # спец-случай visibility: keys — одномерный массив
      if grp == 'visibility'
        arr = h['keys']
        times.concat(arr) if arr.is_a?(Array)
      else
        %w[x y z].each do |axis|
          arr = k[axis]
          times.concat(arr) if arr.is_a?(Array)
        end
      end
    end
    times = times.map(&:to_f).uniq.sort
    unit = detect_time_unit(times) # :seconds или :normalized
    [times, unit]
  end

  def detect_time_unit(times)
    return :normalized if times.empty?

    # если есть ключи > 1.0 — вероятнее секунды
    times.max > 1.000001 ? :seconds : :normalized
  end

  def sample_channel(keys, values, t)
    return nil if keys.nil? || values.nil? || keys.empty? || values.empty?
    return values.first.to_f if t <= keys.first.to_f + 1e-8
    return values.last.to_f  if t >= keys.last.to_f - 1e-8

    lo = 0
    hi = keys.length - 1
    while hi - lo > 1
      mid = (lo + hi) / 2
      if t < keys[mid].to_f
        hi = mid
      else
        lo = mid
      end
    end
    t0 = keys[lo].to_f
    t1 = keys[hi].to_f
    v0 = values[lo].to_f
    v1 = values[hi].to_f
    alpha = (t - t0) / (t1 - t0 + 1e-12)
    MathX.lerp(v0, v1, alpha)
  end

  def build_animation_for_node(node)
    anim = node.dig('data', 'anim')
    return nil unless anim.is_a?(Hash)

    base_t = node.dig('data', 'translation') || [0.0, 0.0, 0.0]
    base_s = node.dig('data', 'scaling')     || [1.0, 1.0, 1.0]
    base_r = node.dig('data', 'rotation')    || [0.0, 0.0, 0.0] # радианы

    tr  = anim['translation'] || { 'values' => {}, 'keys' => {} }
    sc  = anim['scaling']     || { 'values' => {}, 'keys' => {} }
    rot = anim['rotation']    || { 'values' => {}, 'keys' => {} }

    # meta fps/clip если вдруг есть
    fps = (anim.dig('meta', 'fps') || ANIM_FPS_DEFAULT).to_f
    f0  = (anim.dig('meta', 'startFrame') || CLIP_START_FRAME).to_f
    f1  = (anim.dig('meta', 'endFrame')   || CLIP_END_FRAME).to_f
    duration_sec_default = (f1 - f0) / (fps <= 0 ? ANIM_FPS_DEFAULT : fps)

    times_all, unit = gather_all_key_times(anim)
    return nil if times_all.empty?

    # нормализуем время в секундах для t→ticks
    times_sec =
      if unit == :seconds
        times_all
      else
        # нормализованные ключи 0..1 → растягиваем на duration_sec_default
        times_all.map { |u| u * duration_sec_default }
      end

    # подготовим удобные ссылки
    t_keys = tr['keys'] || {}
    t_vals = tr['values'] || {}
    s_keys = sc['keys'] || {}
    s_vals = sc['values'] || {}
    r_keys = rot['keys'] || {}
    r_vals = rot['values'] || {}

    # для сэмплинга используем оригинальные единицы времени, чтобы не копить ошибку интерполяции
    keys_time_for = ->(h) { unit == :seconds ? h : (h || []).map(&:to_f) }

    txk = keys_time_for.call(t_keys['x'])
    tyyk = keys_time_for.call(t_keys['y'])
    tzk = keys_time_for.call(t_keys['z'])
    sxk = keys_time_for.call(s_keys['x'])
    syk = keys_time_for.call(s_keys['y'])
    szk = keys_time_for.call(s_keys['z'])
    rxk = keys_time_for.call(r_keys['x'])
    ryk = keys_time_for.call(r_keys['y'])
    rzk = keys_time_for.call(r_keys['z'])

    samples = []
    times_all.each_with_index do |t_raw, i|
      # t_raw в единицах unit; для вывода ticks используем times_sec[i]
      tx = sample_channel(txk, t_vals['x'], t_raw) || base_t[0].to_f
      ty = sample_channel(tyyk, t_vals['y'], t_raw) || base_t[1].to_f
      tz = sample_channel(tzk, t_vals['z'], t_raw) || base_t[2].to_f

      sx = sample_channel(sxk, s_vals['x'], t_raw) || base_s[0].to_f
      sy = sample_channel(syk, s_vals['y'], t_raw) || base_s[1].to_f
      sz = sample_channel(szk, s_vals['z'], t_raw) || base_s[2].to_f

      rx = sample_channel(rxk, r_vals['x'], t_raw) || base_r[0].to_f
      ry = sample_channel(ryk, r_vals['y'], t_raw) || base_r[1].to_f
      rz = sample_channel(rzk, r_vals['z'], t_raw) || base_r[2].to_f

      m = MathX.mat_identity
      m = MathX.mat_mul(m, MathX.mat_scale(sx, sy, sz))
      m = MathX.mat_mul(m, MathX.mat_from_euler_xyz(rx, ry, rz))
      m = MathX.mat_mul(m, MathX.mat_translation(tx, ty, tz))

      flat = MathX.flatten_row_major_16(m).map { |v| MathX.fmt_f(v) }
      samples << { tick: MathX.to_ticks(times_sec[i]), matrix16: flat }
    end

    # --- НОРМАЛИЗАЦИЯ ВРЕМЕНИ КЛЮЧЕЙ (важно для Assimp) ---
    # 1) Сдвигаем так, чтобы первый тик был >= 0
    min_tick = samples.map { |s| s[:tick] }.min || 0
    if min_tick < 0
      shift = -min_tick
      samples.each { |s| s[:tick] += shift }
    end

    # 2) Удаляем дубликаты по тику (последний выигрывает), сортируем по времени
    samples = samples
              .group_by { |s| s[:tick] }
              .map { |tick, arr| arr.last } # если несколько попало в один тик, берём последний
              .sort_by { |s| s[:tick] }

    # 3) Форсируем строгую монотонность тиков, если надо
    (1...samples.length).each do |i|
      samples[i][:tick] = samples[i - 1][:tick] + 1 if samples[i][:tick] <= samples[i - 1][:tick]
    end

    {
      frame_name: node['name'].to_s.strip.empty? ? 'Root' : node['name'].to_s.strip,
      frame_index: node['index'],
      times_count: times_all.length,
      samples: samples
    }
  end

  def build_animation_set(items)
    clips = []
    items.each do |node|
      next unless node.dig('data', 'anim')

      if (clip = build_animation_for_node(node))
        clips << clip
      end
    end
    return nil if clips.empty?

    { name: 'Anim_0', clips: clips }
  end
end

# ------------------------------- 2) Вывод в .x --------------------------------

class XFileWriter
  include MathX

  def write(scene, output_path)
    File.open(output_path, 'w') do |io|
      io.puts 'xof 0303txt 0032'
      write_frame_recursive(io, scene, scene[:root_index])
      write_animation_set(io, scene[:animation_set]) if scene[:animation_set]
    end
  end

  def write_frame_recursive(io, scene, frame_index)
    frame = scene[:frames][frame_index]
    name = frame[:name].to_s.strip.empty? ? 'Root' : frame[:name]

    io.puts "  Frame #{name} {"
    write_matrix(io, frame[:matrix_local])

    frame[:children].each do |child_idx|
      write_frame_recursive(io, scene, child_idx)
    end

    frame[:meshes].each do |mesh_idx|
      write_mesh(io, scene[:meshes][mesh_idx])
    end

    io.puts '  }'
  end

  def write_matrix(io, m)
    io.puts '    FrameTransformMatrix {'
    m.each_with_index do |row, i|
      line = row.map { |v| MathX.fmt_f(v) }.join(', ')
      io.puts "      #{line}#{i == 3 ? ';;' : ','}"
    end
    io.puts '    }'
  end

  def write_mesh(io, mesh)
    name = mesh[:name]
    pos  = mesh[:pos]
    nrm  = mesh[:nrm]
    uv   = mesh[:uv]
    tris = mesh[:tris]
    mats = mesh[:materials]
    if mats.nil? || mats.empty?
      mats = [{ 'name' => 'DefaultWhite', 'red' => 1, 'green' => 1, 'blue' => 1,
                'alpha' => 1 }]
    end

    io.puts "    Mesh #{name} {"
    # vertices
    io.puts "      #{pos.length};"
    pos.each_with_index do |p, i|
      io.puts "      #{fmt_f(p[0])}; #{fmt_f(p[1])}; #{fmt_f(p[2])}#{i == pos.length - 1 ? ';;' : ';,'}"
    end
    # faces
    io.puts "      #{tris.length};"
    tris.each_with_index do |t, i|
      io.puts "      3; #{t[0]},#{t[1]},#{t[2]}#{i == tris.length - 1 ? ';;' : ';,'}"
    end

    # materials
    io.puts '      MeshMaterialList {'
    io.puts "        #{mats.length};"
    io.puts "        #{tris.length};"
    io.puts '        ' + (tris.length > 0 ? Array.new(tris.length, 0).join(',') : '') + ';;'
    mats.each { |m| write_material(io, m) }
    io.puts '      }'

    # normals
    if nrm.any?
      io.puts '      MeshNormals {'
      io.puts "        #{nrm.length};"
      nrm.each_with_index do |n, i|
        io.puts "        #{fmt_f(n[0])}; #{fmt_f(n[1])}; #{fmt_f(n[2])}#{i == nrm.length - 1 ? ';;' : ';,'}"
      end
      io.puts "        #{tris.length};"
      tris.each_with_index do |t, i|
        io.puts "        3; #{t[0]},#{t[1]},#{t[2]}#{i == tris.length - 1 ? ';;' : ';,'}"
      end
      io.puts '      }'
    end

    # uv
    if uv.any?
      io.puts '      MeshTextureCoords {'
      io.puts "        #{uv.length};"
      uv.each_with_index do |tc, i|
        io.puts "        #{fmt_f(tc[0])}; #{fmt_f(tc[1])}#{i == uv.length - 1 ? ';;' : ';,'}"
      end
      io.puts '      }'
    end

    # vertex colors (из первого материала — как fallback)
    m0 = mats.first
    cr = m0['red'] || 1
    cg = m0['green'] || 1
    cb = m0['blue'] || 1
    ca = m0['alpha'] || 1
    io.puts '      MeshVertexColors {'
    io.puts "        #{pos.length};"
    pos.each_with_index do |_, i|
      io.puts "        #{i}; #{fmt_f(cr)}; #{fmt_f(cg)}; #{fmt_f(cb)}; #{fmt_f(ca)}#{i == pos.length - 1 ? ';;' : ';,'}"
    end
    io.puts '      }'

    io.puts '    }'
  end

  def texture_name(mat)
    t = mat.dig('texture', 'name')
    return nil unless t && !t.empty?

    t = STRIP_TEX_PATHS ? File.basename(t) : t.tr('\\', '/')
    t = t.sub(/\.(tif|tiff)\z/i, '.png') if FORCE_PNG_EXT
    t.tr('\\', '/')
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
    io.puts '        }'
  end

  def write_animation_set(io, anim_set)
    io.puts "AnimationSet #{anim_set[:name]} {"
    anim_set[:clips].each { |clip| write_animation_clip(io, clip) }
    io.puts '}'
  end

  def write_animation_clip(io, clip)
    frame_name = clip[:frame_name].to_s.strip
    frame_name = 'Root' if frame_name.empty?

    io.puts '  Animation {'
    io.puts "    {#{frame_name}}"
    io.puts '    AnimationKey {'
    io.puts '      4;'
    io.puts "      #{clip[:times_count]};"
    clip[:samples].each_with_index do |smp, i|
      line = "      #{smp[:tick]};16;" + smp[:matrix16].map { |v| fmt_f(v) }.join(', ')
      io.puts line + ";;#{i + 1 == clip[:samples].size ? ';' : ','}"
    end
    io.puts '    }'
    io.puts '  }'
  end
end

# ----------------------------------- CLI -------------------------------------

def main(argv)
  if argv.length != 2
    warn "Usage: ruby #{File.basename($0)} input.json output.x"
    exit 1
  end
  inp, outp = argv
  data = XDataPreparer.new.prepare(inp)
  XFileWriter.new.write(data, outp)
end

main(ARGV)
