#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
require 'matrix'  # для упрощённой работы с матрицами

# Пример запуска:
#   ruby nmf_to_obj.rb model.json output.obj

INPUT_JSON  = ARGV[0] || 'model.json'
OUTPUT_FILE = ARGV[1] || 'output.obj'

unless File.exist?(INPUT_JSON)
  puts "Не найден входной JSON-файл: #{INPUT_JSON}"
  exit 1
end

nmf_data = JSON.parse(File.read(INPUT_JSON))

################################################################################
# Простейшие вспомогательные функции для матриц transform/scale/rotate/translate
################################################################################

def matrix_identity
  Matrix.identity(4)
end

# Упрощённая функция создания матрицы трансляции
def matrix_translate(tx, ty, tz)
  Matrix[
    [1, 0, 0, tx],
    [0, 1, 0, ty],
    [0, 0, 1, tz],
    [0, 0, 0, 1]
  ]
end

# Упрощённая функция создания матрицы масштабирования
def matrix_scale(sx, sy, sz)
  Matrix[
    [sx,  0,  0, 0],
    [0,  sy,  0, 0],
    [0,   0, sz, 0],
    [0,   0,  0, 1]
  ]
end

# Повороты по осям (Эйлеровы углы) — в градусах или радианах?
# Предположим, что в NMF rotation лежит в градусах. Тогда переводим в радианы.
def matrix_rotate_x(angle_deg)
  a = angle_deg * Math::PI / 180.0
  Matrix[
    [1,        0,         0, 0],
    [0,  Math.cos(a), -Math.sin(a), 0],
    [0,  Math.sin(a),  Math.cos(a), 0],
    [0,        0,         0, 1]
  ]
end

def matrix_rotate_y(angle_deg)
  a = angle_deg * Math::PI / 180.0
  Matrix[
    [ Math.cos(a), 0, Math.sin(a), 0],
    [           0, 1,           0, 0],
    [-Math.sin(a), 0, Math.cos(a), 0],
    [           0, 0,           0, 1]
  ]
end

def matrix_rotate_z(angle_deg)
  a = angle_deg * Math::PI / 180.0
  Matrix[
    [Math.cos(a), -Math.sin(a), 0, 0],
    [Math.sin(a),  Math.cos(a), 0, 0],
    [          0,            0, 1, 0],
    [          0,            0, 0, 1]
  ]
end

def matrix_euler_rotation(rx, ry, rz)
  # Порядок вращений может отличаться в зависимости от движка.
  # Допустим, делаем Rz * Ry * Rx (или в другом порядке).
  matrix_rotate_z(rz) * matrix_rotate_y(ry) * matrix_rotate_x(rx)
end

# Применение 4x4 матрицы к вектору (x, y, z)
def apply_matrix(mat, x, y, z)
  v = mat * Matrix[[x], [y], [z], [1]]
  [v[0,0], v[1,0], v[2,0]]  # извлекаем x,y,z
end

################################################################################
# Рекурсивный сбор всей иерархии, включая анимации
################################################################################

# Узлы могут быть ROOT/LOCA/FRAM/JOIN/MESH и т.д.
# Предположим, что каждый узел описывается так:
# {
#   "type": "FRAM",
#   "name": "frame1",
#   "children": [...],
#   "anim": {
#       # Внутри - структуры с keyframes (translation_curve_values_x/y/z и т.д.)
#   },
#   "translation": [Tx,Ty,Tz],
#   "rotation": [Rx,Ry,Rz],
#   "scaling": [Sx,Sy,Sz],
#   ...
# }
#
# В "mesh" узлах - vbuf, ibuf и т.п.

def collect_nodes_recursive(node, parent = nil)
  result = []
  children = node['children'] || []

  current = {
    'type'        => node['type'],
    'name'        => node['name'],
    'parent'      => parent,
    'translation' => node['translation'] || [0,0,0],
    'rotation'    => node['rotation'] || [0,0,0],
    'scaling'     => node['scaling'] || [1,1,1],
    'anim'        => node['anim'],  # может быть nil
    'vbuf'        => node['vbuf'],
    'ibuf'        => node['ibuf'],
    'uvpt'        => node['uvpt'],
    'vnum'        => node['vnum'],
    'inum'        => node['inum'],
  }

  result << current

  children.each do |ch|
    result.concat( collect_nodes_recursive(ch, current) )
  end
  result
end

all_nodes = collect_nodes_recursive(nmf_data, nil)

# Выделим отдельно все меши
meshes = all_nodes.select { |n| n['type'] == 'MESH' }

# Функция, которая вычисляет финальную (world) матрицу для узла
# (аккумулируя родительскую). Если у узла нет анимации, просто
# используем translation/rotation/scaling. Если есть, нужно взять
# значения из keyframes. Ниже — упрощённо, для одного кадра:
def compute_local_matrix_for_frame(node, frame_index)
  # Если есть анимация (anim) и в ней ключи — достаём оттуда
  # Для упрощения предполагаем, что rotation_curve_values_x — это
  # массив float, а rotation_curve_keys_x — это массив int, где
  # индекс ключа = номеру кадра. То есть никакой интерполяции,
  # просто "берём кадр 0,1,2...".
  # Если кадра нет — fallback на базовое значение.

  tx, ty, tz = node['translation']
  rx, ry, rz = node['rotation']
  sx, sy, sz = node['scaling']

  anim = node['anim']

  if anim
    # Пример извлечения:
    # Для оси X (translation):
    #   - anim["translation_curve_values_x"] = [...float...]
    #   - anim["translation_curve_keys_x"]   = [...int...]
    #
    # Мы ищем элемент, у которого anim["translation_curve_keys_x"][i] == frame_index
    # Либо, если хотим просто "i-й элемент" = "i-й кадр".
    # Ниже — упрощённый вариант "если i < size, берём i-й элемент".
    tx_arr = anim["translation_curve_values_x"] || []
    ty_arr = anim["translation_curve_values_y"] || []
    tz_arr = anim["translation_curve_values_z"] || []
    if frame_index < tx_arr.size
      tx = tx_arr[frame_index]
    end
    if frame_index < ty_arr.size
      ty = ty_arr[frame_index]
    end
    if frame_index < tz_arr.size
      tz = tz_arr[frame_index]
    end

    sx_arr = anim["scaling_curve_values_x"] || []
    sy_arr = anim["scaling_curve_values_y"] || []
    sz_arr = anim["scaling_curve_values_z"] || []
    if frame_index < sx_arr.size
      sx = sx_arr[frame_index]
    end
    if frame_index < sy_arr.size
      sy = sy_arr[frame_index]
    end
    if frame_index < sz_arr.size
      sz = sz_arr[frame_index]
    end

    rx_arr = anim["rotation_curve_values_x"] || []
    ry_arr = anim["rotation_curve_values_y"] || []
    rz_arr = anim["rotation_curve_values_z"] || []
    if frame_index < rx_arr.size
      rx = rx_arr[frame_index]
    end
    if frame_index < ry_arr.size
      ry = ry_arr[frame_index]
    end
    if frame_index < rz_arr.size
      rz = rz_arr[frame_index]
    end
  end

  # Теперь собираем матрицу: M = T * R * S (или другой порядок).
  # Часто делают M = T * RzRyRx * S. Ниже выберем некий порядок:
  mat_s = matrix_scale(sx, sy, sz)
  mat_r = matrix_euler_rotation(rx, ry, rz)
  mat_t = matrix_translate(tx, ty, tz)

  mat_t * mat_r * mat_s
end

# Функция для прохода от корня к узлу, собирая все матрицы (parent->...->child),
# чтобы получить итоговую world-матрицу для конкретного кадра
def compute_world_matrix(node, frame_index)
  m_local = compute_local_matrix_for_frame(node, frame_index)

  # поднимаемся к parent
  parent = node['parent']
  if parent
    # рекурсия
    m_parent = compute_world_matrix(parent, frame_index)
    return m_parent * m_local
  else
    return m_local
  end
end

################################################################################
# Основная логика экспорта
################################################################################

# 1. Определим, сколько всего кадров у нас есть. Для простоты возьмём
#    максимальное кол-во ключей среди всех anim-каналов во всех узлах.
max_frames = 1  # минимум один "кадр" (статический)
all_nodes.each do |node|
  anim = node['anim']
  next unless anim
  # Посмотрим на translation_curve_values_x / y / z и т.д.
  %w[
    translation_curve_values_x translation_curve_values_y translation_curve_values_z
    scaling_curve_values_x scaling_curve_values_y scaling_curve_values_z
    rotation_curve_values_x rotation_curve_values_y rotation_curve_values_z
  ].each do |key|
    arr = anim[key]
    max_frames = [max_frames, arr.size].max if arr.is_a?(Array)
  end
end

# 2. Готовим общий список строк для OBJ
obj_output = []
obj_output << "# OBJ file exported from custom NMF JSON with naive 'frame-by-frame' animation"
obj_output << "# Total frames: #{max_frames}"

vertex_offset = 0
normal_offset = 0
uv_offset     = 0

(0...max_frames).each do |frame_index|
  # Для каждого кадра будем выводить геометрию всех мешей
  meshes.each_with_index do |mesh, mesh_idx|
    name  = mesh['name']  || "mesh_#{mesh_idx}"
    vnum  = mesh['vnum']  || 0
    inum  = mesh['inum']  || 0
    vbuf  = mesh['vbuf']  || []
    ibuf  = mesh['ibuf']  || []
    uvpt  = mesh['uvpt']  || []

    # Получаем world-матрицу для этого меша (с учётом родителей!)
    world_mat = compute_world_matrix(mesh, frame_index)

    # Разбираем vbuf на позиции (и нормали, если нужно).
    positions = []
    normals   = []

    (0...vnum).each do |i|
      base_idx = i * 10
      x, y, z   = vbuf[base_idx, 3]
      nx, ny, nz = vbuf[base_idx + 3, 3]
      # Применим world_mat к позиции
      wx, wy, wz = apply_matrix(world_mat, x, y, z)
      positions << [wx, wy, wz]

      # Для нормали (nx, ny, nz) в идеале нужно умножать
      # на "верхнюю левую 3x3" матрицы (без трансляции),
      # причём использовать обратную-транспонированную, если есть scale.
      # Здесь — упростим (чистое R). Если есть неединичный scale, получится неверно.
      # Для демонстрации сделаем упрощённо:
      nwx, nwy, nwz = apply_matrix(world_mat, nx, ny, nz)
      # Вычтем трансляцию (или просто игнорируем w=0). Для удобства вручную:
      #   mat*(nx,ny,nz,0) --> ...
      # но кратко покажем:
      # Пусть mat3 = world_mat без последнего ряда/столбца трансляции:
      mat3 = Matrix[
        [world_mat[0,0], world_mat[0,1], world_mat[0,2]],
        [world_mat[1,0], world_mat[1,1], world_mat[1,2]],
        [world_mat[2,0], world_mat[2,1], world_mat[2,2]]
      ]
      normal_v = mat3 * Vector[nx, ny, nz]
      # Нормируем:
      normal_vn = normal_v.normalize
      normals << [normal_vn[0], normal_vn[1], normal_vn[2]]
    end

    # Выясняем UV
    # Либо берём mesh['uvpt'], либо из vbuf[6..7] — в зависимости от того,
    # как именно хранятся UV в вашем NMF. Ниже — пример с uvpt:
    uvs = []
    if uvpt.size == vnum * 2
      (0...vnum).each do |i|
        base_uv_idx = i * 2
        u, v = uvpt[base_uv_idx, 2]
        uvs << [u, v]
      end
    else
      # fallback — пробуем из vbuf[6..7]
      (0...vnum).each do |i|
        base_idx = i * 10 + 6
        u, v = vbuf[base_idx, 2]
        uvs << [u, v]
      end
    end

    # Теперь записываем в OBJ
    # Название группы = имя_меша + _frame_X
    group_name = "#{name}_frame_#{frame_index}"
    obj_output << "g #{group_name}"

    # Пишем вершины
    positions.each do |vx, vy, vz|
      obj_output << "v #{vx} #{vy} #{vz}"
    end

    # Пишем нормали
    normals.each do |nx, ny, nz|
      obj_output << "vn #{nx} #{ny} #{nz}"
    end

    # Пишем UV
    uvs.each do |u, v|
      obj_output << "vt #{u} #{v}"
    end

    # Индексы. Предполагаем, что ibuf содержит треугольники
    # (по 3 индекса на треугольник).
    (0...(inum / 3)).each do |tri|
      i1 = ibuf[tri * 3 + 0].to_i
      i2 = ibuf[tri * 3 + 1].to_i
      i3 = ibuf[tri * 3 + 2].to_i
      # конвертим в 1-базовые, учитывая смещения
      v1  = vertex_offset + i1 + 1
      v2  = vertex_offset + i2 + 1
      v3  = vertex_offset + i3 + 1

      vt1 = uv_offset + i1 + 1
      vt2 = uv_offset + i2 + 1
      vt3 = uv_offset + i3 + 1

      vn1 = normal_offset + i1 + 1
      vn2 = normal_offset + i2 + 1
      vn3 = normal_offset + i3 + 1

      obj_output << "f #{v1}/#{vt1}/#{vn1} #{v2}/#{vt2}/#{vn2} #{v3}/#{vt3}/#{vn3}"
    end
  end

  # По завершении кадра сдвигаем смещения на число всех вершин этого кадра
  # (т.е. сумму vnum по всем мешам). Так как мы всё пишем подряд.
  meshes.each do |mesh|
    vnum = mesh['vnum'] || 0
    vertex_offset += vnum
    normal_offset += vnum
    uv_offset     += vnum
  end
end

# Записываем результат
File.open(OUTPUT_FILE, 'w') do |f|
  obj_output.each {|line| f.puts(line)}
end

puts "Готово! Экспортировано #{max_frames} кадров в #{OUTPUT_FILE}"
