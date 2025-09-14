#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'

def joint_orient_to_matrix(joint_orient)
  # Step 1: Convert degrees to radians
  radian_orient = joint_orient.map { |angle| angle * Math::PI / 180.0 }

  # Extract angles
  x, y, z = radian_orient

  # Step 2: Compute cosines and sines of the angles
  cx = Math.cos(x)
  cy = Math.cos(y)
  cz = Math.cos(z)
  sx = Math.sin(x)
  sy = Math.sin(y)
  sz = Math.sin(z)

  # Step 3: Compute the rotation matrix components
  [
    [
      cy * cz,
      cy * sz,
      -sy,
      0
    ],
    [
      (sx * sy * cz) + (-cx * sz),
      (sx * sy * sz) + (cx * cz),
      sx * cy,
      0
    ],
    [
      (cx * sy * cz) + (sx * sz),
      (cx * sy * sz) + (-sx * cz),
      cx * cy,
      0
    ],
    [0, 0, 0, 1]
  ]
end

def add_edges(edge)
  a, b = edge
  return if a == b

  @edges ||= []
  rev = [b, a]

  # не добавляем дубликаты ни в прямом, ни в обратном направлении
  unless @edges.include?(edge) || @edges.include?(rev)
    @edges << edge.dup
  end
end

def generate_edges_from_ibuf(ibuf)
  @edges = []
  ibuf.each do |tri|
    buf = tri.dup
    # УДАЛИ это:
    # buf[1], buf[2] = buf[2], buf[1]

    # Рёбра по исходной ориентации треугольника
    buf.each_cons(2) { |a, b| add_edges([a, b]) }
    add_edges([buf.last, buf.first])
  end
  @edges
end

def find_edges_index(edges, value)
  # сначала ищем точное совпадение (та же ориентация)
  edges.each_with_index do |edge, index|
    return index if edge == value
  end
  # затем ищем обратную ориентацию и возвращаем отрицательный индекс
  rev = value.reverse
  edges.each_with_index do |edge, index|
    return -(index + 1) if edge == rev
  end
  nil
end

def generate_faces_from_edges_an_ibuf(edges, ibuf)
  ibuf.map do |tri|
    v1, v2, v3 = tri
    i1 = find_edges_index(edges, [v1, v2])
    i2 = find_edges_index(edges, [v2, v3])
    i3 = find_edges_index(edges, [v3, v1])
    [i1, i2, i3]
  end
end

# ---------- helpers ----------
def deg(rad)
  rad.to_f * 180.0 / Math::PI
end

def fmt(x)
  x
  # Короче и стабильнее: без экспоненты, до 9 знаков
  # ('%.9f' % x.to_f).sub(/0+$/,'').sub(/\.$/,'.0')
end

def puts_matrix(io, plug, v)
  io.puts %Q{    setAttr "#{plug}" -type "matrix" #{v};}
end

def puts_attr_vec3(io, plug, v)
  io.puts %Q{    setAttr "#{plug}" -type "double3" #{fmt(v[0])} #{fmt(v[1])} #{fmt(v[2])};}
end

def sanitize_name(name)
  # Maya не любит пробелы и спецсимволы в именах узлов
  name.to_s.gsub(/[^A-Za-z0-9_]/, '_')
end

def convert_root_to_maya_ascii(fram_data, node_name = 'transformNode', parent_node_name)
  line = parent_node_name ? "createNode transform -name \"#{node_name}\" -parent \"#{parent_node_name}\";" : "createNode transform -name \"#{node_name}\";"
  # Extract transformation attributes
  translation = fram_data[:translation]
  scaling = fram_data[:scaling]
  rotation = fram_data[:rotation]
  # rotate_pivot_translate = fram_data[:rotate_pivot_translate]
  # rotate_pivot = fram_data[:rotate_pivot]
  # scale_pivot_translate = fram_data[:scale_pivot_translate]
  # scale_pivot = fram_data[:scale_pivot]
  # shear = fram_data[:shear]

  # Flatten the matrix for Maya's attribute
  matrix_flat = fram_data[:matrix].flatten.map(&:to_s).join(' ')

  # Maya ASCII body
  str = ''
  str += line
  str += "\n\tsetAttr \".matrix\" -type \"matrix\" #{matrix_flat};"
  str += "\n\tsetAttr \".translate\" -type \"double3\" #{translation.join(' ')};"
  str += "\n\tsetAttr \".scale\" -type \"double3\" #{scaling.join(' ')};"
  str += "\n\tsetAttr \".rotate\" -type \"double3\" #{rotation.join(' ')};"
  # str += "\n\tsetAttr \".rotatePivotTranslate\" -type \"double3\" #{rotate_pivot_translate.join(' ')};"
  # str += "\n\tsetAttr \".rotatePivot\" -type \"double3\" #{rotate_pivot.join(' ')};"
  # str += "\n\tsetAttr \".scalePivotTranslate\" -type \"double3\" #{scale_pivot_translate.join(' ')};"
  # str += "\n\tsetAttr \".scalePivot\" -type \"double3\" #{scale_pivot.join(' ')};"
  # str += "\n\tsetAttr \".shear\" -type \"double3\" #{shear.join(' ')};"

  str
end

def convert_fram_to_maya_ascii(fram_data, node_name = 'transformNode', parent_node_name, as_joint: true)
  line = parent_node_name ?
    "createNode transform -name \"#{node_name}\" -parent \"#{parent_node_name}\";" :
    "createNode transform -name \"#{node_name}\";"

  translation = fram_data[:translation] || [0,0,0]
  scaling     = fram_data[:scaling]     || [1,1,1]
  rotation    = fram_data[:rotation]    || [0,0,0] # radians
  rpv_t       = fram_data[:rotate_pivot_translate] || [0,0,0]
  rpv         = fram_data[:rotate_pivot]           || [0,0,0]
  spv_t       = fram_data[:scale_pivot_translate]  || [0,0,0]
  spv         = fram_data[:scale_pivot]            || [0,0,0]
  shear       = fram_data[:shear]                  || [0,0,0]

  rad2deg = ->(a){ a * 180.0 / Math::PI }
  rot_deg = rotation.map { |r| rad2deg.call(r) }

  str  = +""
  str << line
  # Важно: не пишем .matrix — только компоненты
  # matrix_flat = fram_data[:matrix].flatten.map(&:to_s).join(' ')
  # str += "\n\tsetAttr \".matrix\" -type \"matrix\" #{matrix_flat};"
  str << "\n\tsetAttr \".translate\" -type \"double3\" #{translation.join(' ')};"
  str << "\n\tsetAttr \".rotate\" -type \"double3\" #{rot_deg.join(' ')};"
  str << "\n\tsetAttr \".scale\" -type \"double3\" #{scaling.join(' ')};"
  str << "\n\tsetAttr \".rotatePivotTranslate\" -type \"double3\" #{rpv_t.join(' ')};"
  str << "\n\tsetAttr \".rotatePivot\" -type \"double3\" #{rpv.join(' ')};"
  str << "\n\tsetAttr \".scalePivotTranslate\" -type \"double3\" #{spv_t.join(' ')};"
  str << "\n\tsetAttr \".scalePivot\" -type \"double3\" #{spv.join(' ')};"
  str << "\n\tsetAttr \".shear\" -type \"double3\" #{shear.join(' ')};"
  # На всякий случай зафиксируем порядок вращения (если у тебя в данных он всегда XYZ)
  str << "\n\tsetAttr \".rotateOrder\" 0;"

  str
end

def euler_xyz_from_matrix3(m)
  r00, r01, r02 = m[0]
  r10, r11, r12 = m[1]
  r20, r21, r22 = m[2]

  # Небо/гимбал-safe разбор на углы для порядка XYZ
  if r20 < 1.0
    if r20 > -1.0
      y = Math.asin(-r20)
      x = Math.atan2(r21, r22)
      z = Math.atan2(r10, r00)
    else
      # r20 == -1 -> y = +90°
      y =  Math::PI / 2.0
      x = -Math.atan2(-r12, r11)
      z = 0.0
    end
  else
    # r20 == +1 -> y = -90°
    y = -Math::PI / 2.0
    x =  Math.atan2(-r12, r11)
    z = 0.0
  end

  [x, y, z].map { |rad| rad * 180.0 / Math::PI }
end

def matrix_to_joint_orient(matrix)
  # Извлекаем только первые 3 строки и 3 столбца (вращение)
  m = matrix[0..2].map { |row| row[0..2] }

  # Эйлеровы углы (XYZ порядок, как в твоём коде)
  # формулы обратного преобразования из rotation matrix:
  #
  # y = atan2(-m[0][2], sqrt(m[0][0]^2 + m[0][1]^2))
  # x = atan2(m[1][2], m[2][2])
  # z = atan2(m[0][1], m[0][0])

  if (m[0][2].abs - 1.0).abs < 1e-8
    # особый случай: gimbal lock
    y = m[0][2] > 0 ? -Math::PI/2 : Math::PI/2
    x = Math.atan2(m[2][1], m[1][1])
    z = 0.0
  else
    y = Math.asin(-m[0][2])
    x = Math.atan2(m[1][2], m[2][2])
    z = Math.atan2(m[0][1], m[0][0])
  end

  # конвертируем в градусы
  [x, y, z].map { |r| r * 180.0 / Math::PI }
end

# tg(a) = sin(a) / cos(a)
# x = tg(y) -> y = arctg(x)

def convert_join_to_maya_ascii(join_data, node_name = 'joint1', parent_node_name = nil, as_joint: true)
  translation = join_data[:translation] || [0,0,0]
  scaling     = join_data[:scaling]     || [1,1,1]
  rotation    = join_data[:rotation]    || [0,0,0] # radians
  rpv_t       = join_data[:rotate_pivot_translate] || [0,0,0]
  rpv         = join_data[:rotate_pivot]           || [0,0,0]
  spv_t       = join_data[:scale_pivot_translate]  || [0,0,0]
  spv         = join_data[:scale_pivot]            || [0,0,0]
  shear       = join_data[:shear]                  || [0,0,0]

  rad2deg = ->(a){ a * 180.0 / Math::PI }
  rot_deg = rotation.map { |r| rad2deg.call(r) }

  node_type = as_joint ? 'joint' : 'transform'
  # node_type = 'transform'
  header = parent_node_name ?
    "createNode #{node_type} -name \"#{node_name}\" -parent \"#{parent_node_name}\";" :
    "createNode #{node_type} -name \"#{node_name}\";"

  str  = +""
  str << header
  matrix_flat = join_data[:matrix].flatten.map(&:to_s).join(' ')
  str << "\n\tsetAttr \".matrix\" -type \"matrix\" #{matrix_flat};"
  # str << "\n\tsetAttr -keyable off \".visibility\";"
  str << "\n\tsetAttr \".translate\" -type \"double3\" #{translation.join(' ')};"
  str << "\n\tsetAttr \".rotate\" -type \"double3\" #{rot_deg.join(' ')};"
  str << "\n\tsetAttr \".scale\" -type \"double3\" #{scaling.join(' ')};"

  unless as_joint
    str << "\n\tsetAttr \".rotatePivotTranslate\" -type \"double3\" #{rpv_t.join(' ')};"
    str << "\n\tsetAttr \".rotatePivot\" -type \"double3\" #{rpv.join(' ')};"
    str << "\n\tsetAttr \".scalePivotTranslate\" -type \"double3\" #{spv_t.join(' ')};"
    str << "\n\tsetAttr \".scalePivot\" -type \"double3\" #{spv.join(' ')};"
    str << "\n\tsetAttr \".shear\" -type \"double3\" #{shear.join(' ')};"
  end
  # порядок вращения: 0 = xyz
  str << "\n\tsetAttr \".rotateOrder\" 0;"

  if as_joint
      matrix_flat = matrix_to_joint_orient join_data[:rotation_matrix]
      str << "\n\tsetAttr \".jointOrient\" -type \"double3\" #{matrix_flat.join(' ')};"
    # При желании можно приблизительно маппить rotation_matrix -> jointOrient,
    # но без точного соглашения (pre/post) лучше не трогать. Оставим коммент.
    # def build_maya_joint_ma(name:, rotation_matrix:, min_rot_limit:, max_rot_limit:, use_joint_orient: true, radius: 1.0)
    # берём верхний левый 3x3
    # m3 = join_data[:rotation_matrix][0..2].map { |row| row[0..2] }
    # ex, ey, ez = euler_xyz_from_matrix3(m3)
    # str << %(\n\tsetAttr ".rotateX" #{ex};)
    # str << %(\n\tsetAttr ".rotateY" #{ey};)
    # str << %(\n\tsetAttr ".rotateZ" #{ez};)
  end

  # Ограничения поворота (если нужны) — ВНИМАНИЕ: в Maya надо включать флаги enable.
  # Если хочешь активировать — раскомментируй блок ниже.
  if join_data[:min_rot_limit] && join_data[:max_rot_limit]
    min_deg = join_data[:min_rot_limit] #.map(&rad2deg)
    max_deg = join_data[:max_rot_limit] #.map(&rad2deg)
    str << "\n\tsetAttr \".minRotLimit\" -type \"double3\" #{min_deg.join(' ')};"
    str << "\n\tsetAttr \".maxRotLimit\" -type \"double3\" #{max_deg.join(' ')};"
    str << "\n\tsetAttr \".rotationLimitEnable\" -type \"bool3\" yes yes yes;"
    # setAttr ".maxRotLimit" -type "double3"  45  90 0;
    # setAttr ".rotationLimitEnable" -type "bool3" yes no no;
  #   # В Maya есть атрибуты minRotLimitX/Y/Z, maxRotLimitX/Y/Z и enable-флаги.
    # %w[X Y Z].each_with_index do |axis, i|
    #   str << "\n\tsetAttr \".minRotLimit#{axis}\" #{min_deg[i]};"
    #   str << "\n\tsetAttr \".maxRotLimit#{axis}\" #{max_deg[i]};"
    #   str << "\n\tsetAttr \".minRot#{axis}LimitEnable\" yes;"
    #   str << "\n\tsetAttr \".maxRot#{axis}LimitEnable\" yes;"
    # end
  end

  # Если в JOIN была вложенная анимация — сразу допишем её.
  if join_data[:anim]
    str << "\n" << append_anim_to_maya_ascii(join_data[:anim], node_name)
  end

  str
end

# Конвертор анимации → Maya ASCII (с длинными именами и корректными коннектами)
def append_anim_to_maya_ascii(anim_data, node_name, opts = {})
  # Суффиксы атрибутов ноды
  attr_prefixes = {
    translation: 'translate',
    rotation:    'rotate',
    scaling:     'scale'
  }.merge(opts[:attr_prefixes] || {})

  # Настройки кривых
  weighted = opts.key?(:weighted) ? !!opts[:weighted] : false
  # Общий тип тангента кривой (целое enum). 18 = auto (как в новых Maya).
  tangent_type = opts[:tangent_type] || 18
  # Infinity режимы (enum целые), по умолчанию 0 = constant
  pre_inf  = opts[:pre_infinity]  || 0
  post_inf = opts[:post_infinity] || 0

  # Если подаёшь углы в радианах — конвертируем в градусы для animCurveTA
  rad2deg = ->(a){ a * 180.0 / Math::PI }

  # Хелпер: создать animCurve и записать keyTimeValue
  # curve_type: 'animCurveTL' | 'animCurveTA' | 'animCurveTU'
  # attr: 'translateX' | 'rotateY' | 'scaleZ' и т.п.
  # keys: [t0, t1, ...] (кадры/время)
  # vals: [v0, v1, ...]
  # key_tans (опц.): массив enum для per-key tangent (если нужен единый — можно не задавать)
  build_curve = lambda do |curve_type, attr, keys, vals, key_tans = nil|
    return "" if keys.nil? || vals.nil? || keys.empty? || vals.empty?

    n = [keys.size, vals.size].min
    curve_name = "#{node_name}_#{attr}_curve"

    s = +"createNode #{curve_type} -name \"#{curve_name}\";"
    # Общие настройки кривой — длинные имена
    s << "\n\tsetAttr \".tangentType\" #{tangent_type};"
    s << "\n\tsetAttr \".weightedTangents\" #{weighted ? 'yes' : 'no'};"
    s << "\n\tsetAttr \".preInfinity\"  #{pre_inf};"
    s << "\n\tsetAttr \".postInfinity\" #{post_inf};"

    # Ключи: используем длинное имя .keyTimeValue
    flat = []
    n.times { |i| flat << keys[i] << vals[i] }
    s << "\n\tsetAttr -s #{n} \".keyTimeValue[0:#{n-1}]\" #{flat.join(' ')};"

    # (опц.) per-key tangent тип, если передан (смотри список enum’ов Maya)
    if key_tans && key_tans.is_a?(Array) && key_tans.size >= n
      # .keyTan — длинное имя сводного массива per-key tangent’ов (если нужен единый, можно не задавать)
      # Если хочешь отдельно In/Out: .keyInTan / .keyOutTan (аналог .kit/.kot)
      s << "\n\tsetAttr -s #{n} \".keyTan[0:#{n-1}]\" #{key_tans.first(n).join(' ')};"
    end

    # Подключения: time → curve.input, curve.output → node.attr
    # time1 обычно существует в сцене; это безопасное подключение
    s << "\nconnectAttr \"time1.outTime\" \"#{curve_name}.input\";"
    s << "\nconnectAttr \"#{curve_name}.output\" \"#{node_name}.#{attr}\";"

    s
  end

  axes = { x: 'X', y: 'Y', z: 'Z' }
  out  = +""

  # Translation: анимируется кривыми линейной величины → animCurveTL
  if t = anim_data[:translation]
    axes.each do |ax_sym, ax_up|
      keys = t.dig(:keys, ax_sym)   || []
      vals = t.dig(:values, ax_sym) || []
      out << "\n" << build_curve.call('animCurveTL', "#{attr_prefixes[:translation]}#{ax_up}", keys, vals)
    end
  end

  # Rotation: углы → animCurveTA (градусы)
  if r = anim_data[:rotation]
    axes.each do |ax_sym, ax_up|
      keys = r.dig(:keys, ax_sym)   || []
      vals = (r.dig(:values, ax_sym) || []).map { |v| rad2deg.call(v) }
      out << "\n" << build_curve.call('animCurveTA', "#{attr_prefixes[:rotation]}#{ax_up}", keys, vals)
    end
  end

  # Scale: unitless → animCurveTU (самый безопасный вариант)
  if s = anim_data[:scaling]
    axes.each do |ax_sym, ax_up|
      keys = s.dig(:keys, ax_sym)   || []
      vals = s.dig(:values, ax_sym) || []
      out << "\n" << build_curve.call('animCurveTU', "#{attr_prefixes[:scaling]}#{ax_up}", keys, vals)
    end
  end

  out
end


# Ожидает mesh_data формата парсера:
# {
#   vbuf: [[x,y,z, ...ещё 7...], ...],
#   uvpt: [[u,v], ...],
#   ibuf: [[i0,i1,i2], ...]
# }
P2D_TO_FILE = [
  %w[coverage        coverage],
  %w[translateFrame  translateFrame],
  %w[rotateFrame     rotateFrame],
  %w[mirrorU         mirrorU],
  %w[mirrorV         mirrorV],
  %w[stagger         stagger],
  %w[wrapU           wrapU],
  %w[wrapV           wrapV],
  %w[repeatUV        repeatUV],
  %w[offset          offset],
  %w[rotateUV        rotateUV],
  %w[noiseUV         noiseUV],
  %w[vertexUvOne     vertexUvOne],
  %w[vertexUvTwo     vertexUvTwo],
  %w[vertexUvThree   vertexUvThree],
  %w[vertexCameraOne vertexCameraOne],
]

# Выходы place2dTexture -> входы file
P2D_OUTPUTS_TO_FILE = [
  %w[outUV           uvCoord],
  %w[outUvFilterSize uvFilterSize],
]

def convert_mesh_to_maya_ascii(mesh_data, node_name, parent_node_name = 'meshTransform')
  vbuf  = mesh_data[:vbuf] || []
  uvpt  = mesh_data[:uvpt] || []
  ibuf  = mesh_data[:ibuf] || [] # треугольники как индексы вершин
  mtrls = mesh_data[:materials] || []

  # построим уникальные рёбра (с учётом ориентации) и грани в индексах рёбер
  edges_oriented = generate_edges_from_ibuf(ibuf) # массив пар [a,b] в той ориентации, в которой встретились
  faces_by_edges = generate_faces_from_edges_an_ibuf(edges_oriented, ibuf)

  # утилита: сжать список индексов фейсов в "f[a:b] f[c] ..."
  compress_face_indices = lambda do |ids|
    return '' if ids.nil? || ids.empty?
    ids = ids.uniq.sort
    runs = []
    run_start = ids.first
    prev = ids.first
    ids[1..-1].each do |x|
      if x == prev + 1
        prev = x
      else
        runs << (run_start == prev ? "#{run_start}" : "#{run_start}:#{prev}")
        run_start = prev = x
      end
    end
    runs << (run_start == prev ? "#{run_start}" : "#{run_start}:#{prev}")
    ' ' + runs.map { |r| "\"f[#{r}]\"" }.join(' ')
  end

  # форматтер чисел
  fmt_f = ->(f) { ('%.6f' % f).sub(/\.?0+$/, '') }

  # вершины "x y z"
  vrts = vbuf.map { |row| x, y, z = row[0, 3]; "#{fmt_f[x]} #{fmt_f[y]} #{fmt_f[z]}" }

  # для .edge требуется "i j 0" (жёсткость = 0)
  edges_for_attr = edges_oriented.map { |i, j| "#{i} #{j} 0" }

  # UV "u v"
  uv_list = uvpt.map { |u, v| "#{fmt_f[u]} #{fmt_f[v]}" }

  # собрать группы по материалам: ожидаем что в каждом материале может быть :faces => [индексы граней]
  # если ни у кого нет :faces — применим первый материал ко всем фейсам
  faces_total = ibuf.size
  material_groups =
    if mtrls.any? { |m| m[:faces] && !m[:faces].empty? }
      mtrls.map { |m| (m[:faces] || []).select { |i| i.is_a?(Integer) && i >= 0 && i < faces_total } }
    else
      mtrls.empty? ? [] : [Array(0...(faces_total))]
    end

  # заголовок createNode
  line = parent_node_name ?
    "createNode mesh -name \"#{node_name}\" -parent \"#{parent_node_name}\";" :
    "createNode transform -name \"#{node_name}\";"

  str = +""
  str << line
  str << "\n\tsetAttr -keyable off \".visibility\";"

  # instObjGroups/objectGroups:
  # 0-й og оставим пустым (как у вас), далее — по числу материалов/групп
  groups_count = [material_groups.size + 1, 1].max
  str << "\n\tsetAttr -size #{groups_count} \".instObjGroups[0].objectGroups\";"
  str << "\n\tsetAttr \".instObjGroups[0].objectGroups[0].objectGrpCompList\" -type \"componentList\" 0;"

  # Если нет материалов — положим во 2-ю группу все фейсы (как было).
  if material_groups.empty?
    if faces_total > 0
      str << "\n\tsetAttr \".instObjGroups[0].objectGroups[1].objectGrpCompList\" -type \"componentList\" 1 \"f[0:#{faces_total - 1}]\";"
    else
      str << "\n\tsetAttr \".instObjGroups[0].objectGroups[1].objectGrpCompList\" -type \"componentList\" 0;"
    end
  else
    # Для каждой материал-группы создаём свой componentList
    material_groups.each_with_index do |faces, idx|
      comp = faces.empty? ? "0" : "1#{compress_face_indices.call(faces)}"
      # componentList в .ma: сначала число списков, затем сами списки.
      # Мы кладём один список на группу.
      if faces.empty?
        str << "\n\tsetAttr \".instObjGroups[0].objectGroups[#{idx + 1}].objectGrpCompList\" -type \"componentList\" 0;"
      else
        str << "\n\tsetAttr \".instObjGroups[0].objectGroups[#{idx + 1}].objectGrpCompList\" -type \"componentList\" 1#{compress_face_indices.call(faces)};"
      end
    end
  end

  # .vrts
  if vrts.any?
    str << "\n\tsetAttr -size #{vrts.size} \".vrts[0:#{vrts.size - 1}]\"  #{vrts.join(' ')};"
  else
    str << "\n\tsetAttr -size 0 \".vrts\";"
  end

  # .edge (по индексам вершин, как ориентированные пары)
  if edges_for_attr.any?
    str << "\n\tsetAttr -size #{edges_for_attr.size} \".edge[0:#{edges_for_attr.size - 1}]\"  #{edges_for_attr.join(' ')};"
  else
    str << "\n\tsetAttr -size 0 \".edge\";"
  end

  # .uvpt
  if uv_list.any?
    str << "\n\tsetAttr -size #{uv_list.size} \".uvpt[0:#{uv_list.size - 1}]\"  #{uv_list.join(' ')};"
  else
    str << "\n\tsetAttr -size 0 \".uvpt\";"
  end

  # .face: polyFaces по индексам рёбер (как у вас)
  if faces_by_edges.any?
    face_string = faces_by_edges.map { |f| "\t\tf 3 #{f.join(' ')} " }.join(" \n")
    str << "\n\tsetAttr -size #{faces_by_edges.size} \".face[0:#{faces_by_edges.size - 1}]\" -type \"polyFaces\"\n#{face_string};"
  else
    str << "\n\tsetAttr -size 0 \".face\" -type \"polyFaces\";"
  end

  # ===== Материалы / шейдинг =====
  # Для каждого материала создаём: lambert, shadingEngine, (опционально) file + place2dTexture.
  # Затем коннектим og[k] -> SG.dagSetMembers.
  mtrls.each_with_index do |m, idx|
    base_name = (m[:name] || "mat#{idx}").gsub(/\s+/, '_')
    mat_name  = "#{base_name}_lambert"
    sg_name   = "#{base_name}SG"
    file_name = "#{base_name}_tex"
    p2d_name  = "#{base_name}_p2d"

    # lambert
    str << "\ncreateNode lambert -name \"#{mat_name}\";"
    # Цвет/альфа (если заданы), возьмём первые из пары [red,green,blue], alpha
    if m[:red] && m[:green] && m[:blue]
      str << "\n\tsetAttr \".color\" -type \"float3\" #{fmt_f[m[:red]]} #{fmt_f[m[:green]]} #{fmt_f[m[:blue]]};"
    end
    str << "\n\tsetAttr \".transparency\" -type \"float3\" #{fmt_f[1.0 - (m[:alpha] || 1.0)]} #{fmt_f[1.0 - (m[:alpha] || 1.0)]} #{fmt_f[1.0 - (m[:alpha] || 1.0)]};" if m.key?(:alpha)

    # shadingEngine
    str << "\ncreateNode shadingEngine -name \"#{sg_name}\";"
    str << "\n\tsetAttr \".ihi\" 0;"
    str << "\n\tsetAttr \".ro\" yes;"
    str << "\nconnectAttr \"#{mat_name}.outColor\" \"#{sg_name}.surfaceShader\";"

    # Текстура (по желанию)
    if m[:texture] && m[:texture][:name] && !m[:texture][:name].to_s.empty?
      tex_path = m[:texture][:name]
      str << "\ncreateNode place2dTexture -name \"#{p2d_name}\";"
      str << "\ncreateNode file -name \"#{file_name}\";"
      str << "\n\tsetAttr -type \"string\" \"#{file_name}.fileTextureName\" \"#{tex_path}\";"

      # стандартные коннекты place2d -> file
      %w[coverage translateFrame rotateFrame mirrorU mirrorV
         stagger wrapU wrapV repeatUV offset rotate noiseUV vertexCameraOne].each do |a|
        str << "\nconnectAttr \"#{p2d_name}.#{a}\" \"#{file_name}.#{a}\";"
      end
      %w[outUV outUvFilterSize].each do |a|
        str << "\nconnectAttr \"#{p2d_name}.#{a}\" \"#{file_name}.#{a}\";"
      end

      # file.outColor -> lambert.color (перекрываем цвет)
      str << "\nconnectAttr \"#{file_name}.outColor\" \"#{mat_name}.color\";"
    end

    # assign: og[k] -> SG.dagSetMembers (если групп нет — пропустим, позже свяжем весь меш)
    if material_groups.any?
      og_index = idx + 1 # мы положили материалы начиная с og[1]
      str << "\nconnectAttr -na \"#{node_name}.instObjGroups[0].objectGroups[#{og_index}]\" \"#{sg_name}.dagSetMembers\";"
    end
  end

  # Если материалов нет, или мы не заполнили группы — свяжем весь меш с первым SG (если он есть)
  if mtrls.any? && material_groups.empty?
    base_name = (mtrls.first[:name] || "mat0").gsub(/\s+/, '_')
    sg_name   = "#{base_name}SG"
    # создавали objectGroups[1] как "все фейсы"
    str << "\nconnectAttr -na \"#{node_name}.instObjGroups[0].objectGroups[1]\" \"#{sg_name}.dagSetMembers\";"
  end

  str
end

def generate_edges_from_ibuf(ibuf)
  # puts "#{ibuf}"
  edges = []  # Use a set to avoid duplicates
  ibuf.each do |buf2|
    buf = buf2
    tmp = buf[1]
    buf[1] = buf[2]
    buf[2] = tmp
    # puts "buf #{buf}"
    # if find_edges_index(edges.to_a, )
    buf.each_cons(2) do |a, b|
      edges.push([a,b]) if find_edges_index(edges,[a,b]).nil?
    end  # Add edges between consecutive vertices
    edges.push([buf.last, buf.first]) if find_edges_index(edges,[buf.last, buf.first]).nil? # Add the edge between the first and last vertex
  end
  edges # Convert to an array
end

def generate_faces_from_edges_an_ibuf(edges, ibuf)
  result = []
  ibuf.each do |buf|
    v1 = buf[0]
    v2 = buf[1]
    v3 = buf[2]
    i1 = find_edges_index(edges, [v1, v2])
    i2 = find_edges_index(edges, [v2, v3])
    i3 = find_edges_index(edges, [v3, v1])
    # puts "#{i1} #{i2} #{i3} #{[v1, v2]} | #{[v2, v3]} | #{[v3, v1]} ||| #{edges}"
    # next if i1.nil? || i2.nil? || i3.nil?

    result.push([i1, i2, i3])
  end
  result
end

def find_edges_index(edges, value)
  v1 = nil
  v2 = nil
  edges.each_with_index do |edge, index|
    if edge == value
      v1 = index
      break
    end
  end

  reverse_value = value.reverse
  edges.each_with_index do |edge, index|
    if edge == reverse_value
      # v2 = index
      # break
      return -(index+1)
    end
    # return index - edges.size
  end

  return nil if v1.nil? && v2.nil?
  return v2 if v1.nil?
  return v1 if v2.nil?

  if v2 <= v1
    # return v2 - edges.size
    return -(v2 + 1)
  end

  return v1
end

# def add_edges(value)
#   edges.push(value) if find_edges_index(edges,value).nil?
# end

def convert_mesh_to_maya_ascii22(mesh_data, node_name = 'meshShape', parent_node_name = 'meshTransform')
  line = parent_node_name ? "createNode mesh -name \"#{node_name}\" -parent \"#{parent_node_name}\";" : "createNode transform -name \"#{node_name}\";"

  vrts = mesh_data[:vbuf].map { |t| [t[0], t[1], t[2]] }
  # uvpt = mesh_data[:vbuf].map { |t| [t[6], t[7]] }
  uvpt = (mesh_data[:uvpt] || []).map { |u, v| [u, v] }
  edge = generate_edges_from_ibuf(mesh_data[:ibuf])
  face = generate_faces_from_edges_an_ibuf(edge, mesh_data[:ibuf])
  edge.map! { |e| e.push(0) }

  # puts "#{edge}"
  # Maya ASCII body
  str = ''
  str += line
  str += "\n\tsetAttr -keyable off \".visibility\";"
  str += "\n\tsetAttr -size 2 \".instObjGroups[0].objectGroups\";"
  str += "\n\tsetAttr \".instObjGroups[0].objectGroups[0].objectGrpCompList\" -type \"componentList\" 0;"
  str += "\n\tsetAttr \".instObjGroups[0].objectGroups[1].objectGrpCompList\" -type \"componentList\" 1 \"f[0:#{face.size - 1}]\";"
  str += "\n\tsetAttr -size #{vrts.size} \".vrts[0:#{vrts.size - 1}]\"  #{vrts.join(' ')};"
  str += "\n\tsetAttr -size #{edge.size} \".edge[0:#{edge.size - 1}]\"  #{edge.join(' ')};"
  str += "\n\tsetAttr -size #{uvpt.size} \".uvpt[0:#{uvpt.size - 1}]\"  #{uvpt.join(' ')};"
  face_string = face.map { |f| "\t\tf 3 #{f.join(' ')} " }.join(" \n")
  str += "\n\tsetAttr -size #{face.size} \".face[0:#{face.size - 1}]\" -type \"polyFaces\"\n#{face_string};"
  str
end

def model_to_maya(items)
  str = "//Maya ASCII 2.5 scene"
  # str += '\n//Name: BasketballKorbout.ma'
  # str += '\n//Last modified: Sun, Jan 19, 2025 06:42:36 AM'
  str += "\nrequires maya \"2.5\";"
  str += "\ncurrentUnit -linear centimeter -angle degree -time film;"
  items.each do |item|
    # Extract the necessary values from the item
    unpacked_item = item[:data]
    item_name = item[:name]

    # Find the parent item based on its index
    parent_item = items.find { |t| t[:index] == item[:parent_iid] }
    parent_name = parent_item ? parent_item[:name] : nil
    parent_name = nil if item[:parent_iid] == 1

    # puts item
    case item[:word]
    when 'ROOT'
      # str += "\n" + convert_root_to_maya_ascii(unpacked_item, item_name, parent_name)
    when 'JOIN'
      str += "\n" + convert_join_to_maya_ascii(unpacked_item, item_name, parent_name, as_joint: true)
    when 'FRAM'
      str += "\n" + convert_join_to_maya_ascii(unpacked_item, item_name, parent_name, as_joint: false)
    when 'MESH'
      str += "\n" + convert_mesh_to_maya_ascii(unpacked_item, item_name, parent_name)
    end
  end
  str
end


# ---------- main ----------
if ARGV.length < 2
  warn "Usage: ruby #{File.basename(__FILE__)} input.json output.ma"
  exit 1
end

input_path, output_path = ARGV
nodes = JSON.parse(File.read(input_path),  symbolize_names: true)
scene = model_to_maya(nodes)

File.open(output_path, 'w:utf-8') do |io|
  io << scene
end

puts "Wrote #{output_path}"
