#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
FPS = 24.0
DEG2RAD = Math::PI / 180.0

def fmt_f(x)
  format('%.9f', x.to_f).sub(/\.?0+$/, '') # компактно без лишних нулей
end

class NmfJsonToMaya
  def initialize(nodes)
    @result = []
    nodes.each do |node|
      unpacked_node = node[:data]
      node_name = node[:name]

      # Find the parent item based on its index
      parent_node = nodes.find { |t| t[:index] == node[:parent_iid] }
      parent_name = parent_node ? parent_node[:name] : nil
      # parent_name = nil if node[:parent_iid] == 1

      case node[:word]
      when 'ROOT'
        @result.push MayaFrameObject.new(unpacked_node, node_name, parent_name)
      when 'FRAM'
        @result.push MayaFrameObject.new(unpacked_node, node_name, parent_name)
      when 'JOIN'
        @result.push MayaJoinObject.new(unpacked_node, node_name, parent_name)
      when 'MESH'
        @result.push MayaMeshObject.new(unpacked_node, node_name, parent_name)
      when 'LOCA'
        @result.push MayaLocatorObject.new(unpacked_node, node_name, parent_name)
      end
    end
  end

  def nodes
    @result
  end
end

class MayaBaseObject
  def to_s
    ''
  end
end

class MayaFrameBaseObject < MayaBaseObject
  def initialize(fram_data, node_name = 'transformNode', parent_node_name)
    @node_name = node_name
    @parent_node_name = parent_node_name
    @translation = fram_data[:translation] || [0, 0, 0]
    @scaling     = fram_data[:scaling]     || [1, 1, 1]
    @rotation    = fram_data[:rotation]    || [0, 0, 0] # radians в базовом значении

    @anim        = fram_data[:anim] || {}

    rad2deg = ->(a) { a * 180.0 / Math::PI }
    @rot_deg = @rotation.map { |r| rad2deg.call(r) }
  end

  protected

  # -------- Анимация TRS из @anim --------
  def emit_trs_animation
    return '' if @anim.nil? || @anim.empty?

    out = +''
    # ожидаем структуру как в твоём примере:
    # @anim[:translation][:values][:x] = [v0, v1,...]
    # @anim[:translation][:keys][:x]   = [t0, t1,...]  (секунды)
    {
      translation: { curve: 'animCurveTL', attrs: %w[translateX translateY translateZ], axes: %i[x y z] },
      rotation: { curve: 'animCurveTA', attrs: %w[rotateX rotateY rotateZ], axes: %i[x y z] },
      scaling: { curve: 'animCurveTU', attrs: %w[scaleX scaleY scaleZ], axes: %i[x y z] }
    }.each do |track, spec|
      next unless @anim[track]

      values = @anim[track][:values] || {}
      keys   = @anim[track][:keys]   || {}

      spec[:axes].each_with_index do |ax, i|
        vlist = values[ax] || values[ax.to_s] || []
        tlist = keys[ax]   || keys[ax.to_s]   || []
        next if vlist.nil? || tlist.nil? || vlist.empty? || tlist.empty?

        # перевод секунд -> кадры
        frames = tlist.map { |t| (t.to_f * FPS) }
        vlist.map! { |v| v / DEG2RAD } if track == :rotation

        curve_name = "#{@node_name}_#{spec[:attrs][i]}"
        out << build_anim_curve(spec[:curve], curve_name, frames, vlist)
        out << connect_curve(curve_name, "#{@node_name}.#{spec[:attrs][i]}")
      end
    end

    # необязательно, но если будет явный visibility
    if @anim[:visibility].is_a?(Hash)
      vis_vals = @anim[:visibility][:values] || []
      vis_keys = @anim[:visibility][:keys]   || []
      if !vis_vals.empty? && !vis_keys.empty?
        frames = vis_keys.map { |t| (t.to_f * FPS).round }
        cname  = "#{@node_name}_visibility"
        out << build_anim_curve('animCurveTU', cname, frames, vis_vals)
        out << connect_curve(cname, "#{@node_name}.visibility")
      end
    end

    out
  end

  def build_anim_curve(curve_type, curve_name, frames, values)
    n = [frames.length, values.length].min
    return '' if n == 0

    pairs = (0...n).map { |i| "#{fmt_f(frames[i])} #{fmt_f(values[i])}" }.join(' ')
    s  = "\ncreateNode #{curve_type} -name \"#{curve_name}\";"
    s << "\n\tsetAttr \".tangentType\" 9;"
    s << "\n\tsetAttr \".weightedTangents\" no;"
    s << "\n\tsetAttr -size #{n} \".keyTimeValue[0:#{n - 1}]\" #{pairs};"
    # при желании можно задать выходные типы тангенсов:
    # s << "\n\tsetAttr -size #{n} \".keyTanOutType[0:#{n-1}]\" #{Array.new(n, 5).join(' ')};"
    s
  end

  def connect_curve(curve_name, dst_attr)
    "\nconnectAttr \"#{curve_name}.output\" \"#{dst_attr}\";"
  end
end

class MayaRootObject < MayaBaseObject
  def initialize(fram_data, node_name = 'transformNode', parent_node_name)
    @node_name = node_name
    @parent_node_name = parent_node_name
    @matrix = fram_data[:matrix]

    @translation = fram_data[:translation] || [0, 0, 0]
    @scaling     = fram_data[:scaling]     || [1, 1, 1]
    @rotation    = fram_data[:rotation]    || [0, 0, 0] # radians в базовом значении

    rad2deg = ->(a) { a * 180.0 / Math::PI }
    @rot_deg = @rotation.map { |r| rad2deg.call(r) }
  end

  def to_s
    str = +"\n"
    header = if @parent_node_name
               "createNode transform -name \"#{@node_name}\" -parent \"#{@parent_node_name}\";"
             else
               "createNode transform -name \"#{@node_name}\";"
             end
    str << header

    rows = @matrix
    str << "\n\tsetAttr \".matrix\" -type \"matrix\"\n"
    rows.each { |row| str << "\t\t#{row.map { |v| format('%.6f', v.to_f) }.join(' ')}\n" }
    str << "\t;\n"

    # базовые TRS (статические значения узла)
    str << "\n\tsetAttr \".translate\" -type \"double3\" #{@translation.join(' ')};"
    str << "\n\tsetAttr \".rotate\" -type \"double3\" #{@rot_deg.join(' ')};"
    str << "\n\tsetAttr \".scale\" -type \"double3\" #{@scaling.join(' ')};"

    str
  end
end

class MayaFrameObject < MayaFrameBaseObject
  def initialize(fram_data, node_name = 'transformNode', parent_node_name)
    super

    @rpv_t       = fram_data[:rotate_pivot_translate] || [0, 0, 0]
    @rpv         = fram_data[:rotate_pivot]           || [0, 0, 0]
    @spv_t       = fram_data[:scale_pivot_translate]  || [0, 0, 0]
    @spv         = fram_data[:scale_pivot]            || [0, 0, 0]
    @shear       = fram_data[:shear]                  || [0, 0, 0]
  end

  def to_s
    str = +"\n"
    header = if @parent_node_name
               "createNode transform -name \"#{@node_name}\" -parent \"#{@parent_node_name}\";"
             else
               "createNode transform -name \"#{@node_name}\";"
             end
    str << header
    # базовые TRS (статические значения узла)
    str << "\n\tsetAttr \".translate\" -type \"double3\" #{@translation.join(' ')};"
    str << "\n\tsetAttr \".rotate\" -type \"double3\" #{@rot_deg.join(' ')};"
    str << "\n\tsetAttr \".scale\" -type \"double3\" #{@scaling.join(' ')};"
    str << "\n\tsetAttr \".rotatePivotTranslate\" -type \"double3\" #{@rpv_t.join(' ')};"
    str << "\n\tsetAttr \".rotatePivot\" -type \"double3\" #{@rpv.join(' ')};"
    str << "\n\tsetAttr \".scalePivotTranslate\" -type \"double3\" #{@spv_t.join(' ')};"
    str << "\n\tsetAttr \".scalePivot\" -type \"double3\" #{@spv.join(' ')};"
    str << "\n\tsetAttr \".shear\" -type \"double3\" #{@shear.join(' ')};"
    # str << "\n\tsetAttr \".rotateOrder\" 0;"

    # анимация (если есть)
    str << emit_trs_animation

    str
  end
end

class MayaJoinObject < MayaFrameBaseObject
  def initialize(fram_data, node_name = 'transformNode', parent_node_name)
    super

    @matrix           = fram_data[:matrix]               # 16 float (row-major), опционально
    @rotation_matrix  = fram_data[:rotation_matrix]      # 16 float (row-major), опционально

    # во входных данных лимиты приходят в радианах — конвертнём при выводе в градусы
    @min_rot_limit    = fram_data[:min_rot_limit]        # [rx, ry, rz] (rad) | nil
    @max_rot_limit    = fram_data[:max_rot_limit]        # [rx, ry, rz] (rad) | nil

    # jointOrient (в градусах) из rotation_matrix, если дана
    r3 = extract_3x3(@rotation_matrix)
    @joint_orient_deg =
      if r3
        x, y, z = euler_xyz_from_matrix_rowmajor(r3) # rad
        [rad2deg(x), rad2deg(y), rad2deg(z)]
      end
  end

  def rad2deg(a) = a.to_f * (180.0 / Math::PI)
  # def deg2rad(a) = a.to_f * Math::PI / 180.0

  # Принимает либо flat-16, либо [[..4],[..4],[..4],[..4]]
  def extract_3x3(m4)
    return nil unless m4

    a =
      if m4.is_a?(Array) && m4.size == 16
        m4
      elsif m4.is_a?(Array) && m4.size == 4 && m4.all? { |r| r.is_a?(Array) && r.size == 4 }
        m4.flatten
      else
        return nil
      end
    [
      [a[0], a[1], a[2]],
      [a[4], a[5], a[6]],
      [a[8], a[9], a[10]]
    ]
  end

  # Эйлеры для порядка XYZ, row-major (R = Rz * Ry * Rx в матричном умножении справа налево)
  # r:
  # [ r00 r01 r02
  #   r10 r11 r12
  #   r20 r21 r22 ]
  def euler_xyz_from_matrix_rowmajor(r)
    r00, r01, r02 = r[0]
    r10, r11, r12 = r[1]
    r20, r21, r22 = r[2]

    y = Math.asin(-[[r20, -1.0].max, 1.0].min) # clamp(-1..1)
    cy = Math.cos(y)

    if cy.abs > 1e-8
      x = Math.atan2(r21, r22)
      z = Math.atan2(r10, r00)
    else
      # gimbal lock
      x = Math.atan2(-r12, r11)
      z = 0.0
    end
    [x, y, z]
  end

  # эвристика: если значения похожи на градусы, не конвертируем
  def ensure_degrees(vec)
    return nil unless vec&.size == 3

    max_abs = vec.map(&:abs).max.to_f
    if max_abs <= ((2 * Math::PI) + 1e-4) # похоже на радианы
      vec.map { |v| rad2deg(v) }
    else
      vec.map(&:to_f) # уже градусы
    end
  end

  def to_s
    str = +"\n"
    header =
      if @parent_node_name
        "createNode joint -name \"#{@node_name}\" -parent \"#{@parent_node_name}\";"
      else
        "createNode joint -name \"#{@node_name}\";"
      end
    str << header

    rows = @matrix
    str << "\n\tsetAttr \".matrix\" -type \"matrix\"\n"
    rows.each { |row| str << "\t\t#{row.map { |v| format('%.6f', v.to_f) }.join(' ')}\n" }
    str << "\t;\n"

    str << "\n\tsetAttr \".translate\" -type \"double3\" #{@translation.join(' ')};"
    str << "\n\tsetAttr \".rotate\" -type \"double3\" #{@rot_deg.join(' ')};"
    str << "\n\tsetAttr \".scale\" -type \"double3\" #{@scaling.join(' ')};"

    # 2) jointOrient — из rotation_matrix (в градусах)
    if @joint_orient_deg
      str << "\n\tsetAttr \".jointOrient\" -type \"double3\" #{@joint_orient_deg.map { |d| ('%.6f' % d) }.join(' ')};"
    end

    str << "\n\tsetAttr \".minRotLimit\" -type \"double3\" #{@min_rot_limit.join(' ')};"
    str << "\n\tsetAttr \".maxRotLimit\" -type \"double3\" #{@max_rot_limit.join(' ')};"

    # 4) Анимация (если есть) — оставляем как было
    str << emit_trs_animation

    str
  end
end

class MayaLocatorObject
  def initialize(data, node_name, parent_node_name)
    @node_name = node_name
    @parent_node_name = parent_node_name
  end

  def to_s
    shape_name = "#{@node_name}Shape"
    str = +"\n"
    str << "createNode transform -name \"#{@node_name}\""
    str << " -parent \"#{@parent_node_name}\"" if @parent_node_name
    str << ";\n"
    str << "\tsetAttr \".translate\" -type \"double3\" 0 0 0;\n"
    str << "\tsetAttr \".rotate\" -type \"double3\" 0 0 0;\n"
    str << "\tsetAttr \".scale\" -type \"double3\" 1 1 1;\n"
    str << "createNode locator -name \"#{shape_name}\" -parent \"#{@node_name}\";\n"
    str << "\tsetAttr \".localScale\" -type \"double3\" 1 1 1;\n"
    str
  end
end

class MayaMeshObject < MayaBaseObject
  def initialize(mesh_data, node_name = 'meshShape', parent_node_name = 'meshTransform')
    @node_name = node_name
    @parent_node_name = parent_node_name

    # Вершины (xyz)
    @vrts = mesh_data[:vbuf].map { |t| [t[0], t[1], t[2]] }

    @ibuf = mesh_data[:ibuf].map { |tri| [tri[0], tri[1], tri[2]] }
    @have_meterial_name = mesh_right_handed?(mesh_data)
    # mesh_data[:materials].any? { |m| m[:name] != '' }
    # Исходные треугольники
    # @ibuf = mesh_data[:ibuf].map { |tri| [tri[0], tri[2], tri[1]] }
    # if @node_name == 'pPlaneShape74' || @node_name == 'pPlaneShape75' || @node_name == 'pPlaneShape76'
    @ibuf = if @have_meterial_name
              mesh_data[:ibuf].map { |tri| [tri[0], tri[2], tri[1]] }
            else
              mesh_data[:ibuf].map { |tri| [tri[0], tri[1], tri[2]] }
            end
    # end
    # puts @node_name

    # Рёбра и faces с подписанным направлением для polyFaces::f
    @edge, @face = build_edges_and_faces_signed(@ibuf)
    @edge.map! { |e| e.length == 2 ? e + [0] : e }

    @materials = mesh_data[:materials]

    # ---------- UV: используем ТОЛЬКО vbuf[6,7] (пер-вершинно), сохраняем >1.0 ----------
    # # FIX: приоритет vbuf, никаких замен на mesh_data[:uvpt]
    @uvpt = mesh_data[:vbuf].map do |t|
      u = (t[6] || 0.0).to_f
      v = (t[7] || 0.0).to_f
      [u, v]
    end

    # flip_v = FLIP_V
    # @uv0 = mesh_data[:vbuf].map { |t| uv0_of(t, flip_v) }
    # @uv1 = mesh_data[:vbuf].map { |t| uv1_of(t, flip_v) }.compact
    # @has_uv1 = @uv1.length == @vrts.length # все вершины имеют UV1

    # Индекс UV == индекс вершины (то, что ожидает обратный экспортёр)
    @uv_index_of_vertex = (0...@vrts.length).to_a

    @materials = mesh_data[:materials].map do |m|
      mat_name = m[:name]
      mat_name = 'lambert' if mat_name == '' || mat_name.empty?
      mat_name = "#{mat_name}_#{@node_name}"
      a = (m[:alpha] || 1.0).to_f
      {
        mat_name:,
        sg_name: "#{mat_name}SG",
        r: (m[:red]   || 1).to_f,
        g: (m[:green] || 1).to_f,
        b: (m[:blue]  || 1).to_f,
        a:,
        t: a, # прозрачность в Maya: 0..1, где 1 — полностью прозрачно
        # UV placement из твоих полей
        repeatU: (m[:horizontal_stretch] || 1).to_i,
        repeatV: (m[:vertical_stretch]   || 1).to_i,
        mirrorU: (m[:uv_mapping_flip_horizontal] || 0).to_i == 1 ? 1 : 0,
        mirrorV: (m[:uv_mapping_flip_vertical]   || 0).to_i == 1 ? 1 : 0,
        rotateUV: (m[:rotate] || 0).to_i # если у тебя это «четверть-обороты», умножь на 90
      }
    end

    # puts "mesh #{@node_name}"
    # ceckA(mesh_data[:vbuf])
  end

  # def ceckA(vbuf)
  #   cols = vbuf.map(&:length).min
  #   puts "min tuple length: #{cols}"
  #   if cols >= 10
  #     u2 = vbuf.map { |t| t[8] }.compact
  #     v2 = vbuf.map { |t| t[9] }.compact
  #     u2_range = u2.minmax.map { |x| x&.round(6) }
  #     v2_range = v2.minmax.map { |x| x&.round(6) }
  #     puts "UV2 ranges: u2=#{u2_range.inspect} v2=#{v2_range.inspect}"
  #     likely_uv2 = u2.all? && v2.all? && u2_range[0] && v2_range[0] &&
  #                  u2_range[0] >= -0.5 && u2_range[1] <= 2.0 &&
  #                  v2_range[0] >= -0.5 && v2_range[1] <= 2.0
  #     puts "Interpret t[8],t[9] as UV2? => #{likely_uv2}"
  #   else
  #     puts 'No columns 8–9 in vbuf.'
  #   end
  # end
  def uv0_of(t, flip_v)
    u = t[6].to_f
    v = t[7].to_f
    v = 1.0 - v if flip_v
    [u, v]
  end

  def uv1_of(t, flip_v)
    return nil unless t.length >= 10

    u = t[8].to_f
    v = t[9].to_f
    v = 1.0 - v if flip_v
    [u, v]
  end

  EPS = 1e-8

  def normalize(v)
    l = Math.sqrt((v[0] * v[0]) + (v[1] * v[1]) + (v[2] * v[2]))
    return [0.0, 0.0, 0.0] if l < EPS

    [v[0] / l, v[1] / l, v[2] / l]
  end

  def sub(a, b)  = [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
  def cross(a, b)= [(a[1] * b[2]) - (a[2] * b[1]), (a[2] * b[0]) - (a[0] * b[2]), (a[0] * b[1]) - (a[1] * b[0])]
  def dot(a, b)  = (a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2])

  # из vbuf-строки берём позицию и нормаль (формат: x,y,z,nx,ny,nz, ...):
  def pos_of(row) = row[0, 3]
  def nrm_of(row) = row[3, 3]

  def mesh_right_handed?(mesh_data)
    vbuf = mesh_data[:vbuf]
    # ibuf = mesh.dig( 'ibuf') || []
    # return true if vbuf.empty? || ibuf.empty? # по умолчанию считаем праворуким

    pos  = vbuf.map { |r| pos_of(r) }
    nrm  = vbuf.map { |r| nrm_of(r) }

    pos_cnt = 0
    neg_cnt = 0

    # puts "aa #{@ibuf}"
    @ibuf.each do |tri|
      i0, i1, i2 = tri
      p0 = pos[i0]
      p1 = pos[i1]
      p2 = pos[i2]
      n_geom = normalize(cross(sub(p1, p0), sub(p2, p0))) # по индексации
      n_avg  = normalize([nrm[i0][0] + nrm[i1][0] + nrm[i2][0],
                          nrm[i0][1] + nrm[i1][1] + nrm[i2][1],
                          nrm[i0][2] + nrm[i1][2] + nrm[i2][2]])
      s = dot(n_geom, n_avg)
      s >= 0 ? (pos_cnt += 1) : (neg_cnt += 1)
    end

    pos_cnt >= neg_cnt # true => праворукий; false => леворукий
  end

  # Построение неориентированных рёбер + ПОДПИСАННЫЕ индексы рёбер для f
  def build_edges_and_faces_signed(tris)
    edge_map = {}   # "va|vb" -> edge_index
    edges    = []   # [[va,vb], ...] с va < vb

    # 1) Собираем уникальные рёбра
    tris.each do |(a, b, c)|
      [[a, b], [b, c], [c, a]].each do |u, v|
        va, vb = [u, v].minmax
        key = "#{va}|#{vb}"
        unless edge_map.key?(key)
          edge_map[key] = edges.length
          edges << [va, vb]
        end
      end
    end

    # 2) Подписанные индексы рёбер для каждого треугольника
    faces_signed = tris.map do |(a, b, c)|
      e0 = signed_edge_index(edge_map, a, b) # (a→b)
      e1 = signed_edge_index(edge_map, b, c) # (b→c)
      e2 = signed_edge_index(edge_map, c, a) # (c→a)
      [e0, e1, e2]
    end

    [edges, faces_signed]
  end

  def signed_edge_index(edge_map, a, b)
    va, vb = [a, b].minmax
    idx = edge_map["#{va}|#{vb}"]
    raise "edge not found for #{a}-#{b}" unless idx

    same_dir = (a == va) && (b == vb)
    same_dir ? idx : -(idx + 1)
  end

  def to_s
    line = @parent_node_name ? "createNode mesh -name \"#{@node_name}\" -parent \"#{@parent_node_name}\";" : "createNode transform -name \"#{@node_name}\";"
    str = ''
    str += line
    # str += "\n\tsetAttr \".opposite\" yes;"
    str += "\n\tsetAttr -keyable off \".visibility\";"
    str += "\n\tsetAttr -size 2 \".instObjGroups[0].objectGroups\";"
    str += "\n\tsetAttr \".opposite\" yes;"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[0].objectGrpCompList\" -type \"componentList\" 0;"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[1].objectGrpCompList\" -type \"componentList\" 1 \"f[0:#{@face.size - 1}]\";"

    # Вершины
    str += "\n\tsetAttr -size #{@vrts.size} \".vrts[0:#{@vrts.size - 1}]\"  \t\t#{@vrts.map do |x, y, z|
      "#{x.to_f} #{y.to_f} #{z.to_f}"
    end.join("\t")};"

    # Рёбра
    str += "\n\tsetAttr -size #{@edge.size} \".edge[0:#{@edge.size - 1}]\"  \t\t#{@edge.map do |x, y, z|
      "#{x} #{y} #{z}"
    end.join("\t")};"

    # UV-пул (.uvpt) — ВАЖНО: пишем ровно по числу вершин; значения НЕ клампим (# FIX)
    str += "\n\tsetAttr -size #{@uvpt.size} \".uvpt[0:#{@uvpt.size - 1}]\" -type \"float2\"\t\t" \
           "#{@uvpt.map { |u, v| "#{u} #{v}" }.each_slice(6).map { |chunk| chunk.join('   ') }.join("\t")};"

    # # UV-пул (.uvpt) — ВАЖНО: пишем ровно по числу вершин; значения НЕ клампим (# FIX)
    # str += "\n\tsetAttr -size #{@uv0.size} \".uvpt[0].uvpt[0:#{@uv0.size - 1}]\" -type \"float2\"\t\t" \
    #        "#{@uv0.map { |u, v| "#{u} #{v}" }.each_slice(6).map { |chunk| chunk.join('   ') }.join("\t")};"

    # # UV-пул (.uvpt)
    # str += "\n\tsetAttr -size #{@uv1.size} \".uvpt[1].uvpt[0:#{@uv1.size - 1}]\" -type \"float2\"\t\t" \
    #        "#{@uv1.map { |u, v| "#{u} #{v}" }.each_slice(6).map { |chunk| chunk.join('   ') }.join("\t")};"

    # polyFaces: f ... и mf (uv-индексы совпадают с индексами вершин)
    face_lines = []
    @face.each_with_index do |edges_triplet, i|
      f_part = "f 3 #{edges_triplet.join(' ')}"
      tri = @ibuf[i] # [v0, v1, v2] — порядок НЕ меняли (# FIX)
      uv_idx = tri.map { |v| @uv_index_of_vertex[v] }
      mf_part = "mf 3 #{uv_idx.join(' ')}"
      face_lines << "\t\t#{f_part}   #{mf_part}"
    end

    str += "\n\tsetAttr -size #{@face.size} \".face[0:#{@face.size - 1}]\" -type \"polyFaces\"\n#{face_lines.join(" \n")};"

    str << "\n"
    @materials.each do |material|
      # === Материал ===
      str << %(createNode lambert -name "#{material[:mat_name]}";\n)
      str << %(\tsetAttr ".color" -type "float3" #{material[:r]} #{material[:g]} #{material[:b]} ;\n)
      str << %(\tsetAttr ".transparency" -type "float3" #{material[:t]} #{material[:t]} #{material[:t]} ;\n)
      str << %(\tsetAttr ".diffuse" 1;\n)
      str << %(\tsetAttr ".translucence" 0;\n)
      str << %(\tsetAttr ".ambientColor" -type "float3" 0 0 0;\n)

      # === shadingEngine ===
      str << %(createNode shadingEngine -name "#{material[:sg_name]}";\n)
      str << %(\tsetAttr ".ihi" 0;\n)
      str << %(\tsetAttr ".renderableOnly" yes;\n)
      str << %(connectAttr "#{material[:mat_name]}.outColor" "#{material[:sg_name]}.surfaceShader";\n)

      # === узел размещения UV ===
      # str << %(createNode place2dTexture -n "#{mat_name}_place2d";\n)
      # str << %(    setAttr "#{mat_name}_place2d.repeatU" #{repeatU};\n)
      # str << %(    setAttr "#{mat_name}_place2d.repeatV" #{repeatV};\n)
      # str << %(    setAttr "#{mat_name}_place2d.mirrorU" #{mirrorU};\n)
      # str << %(    setAttr "#{mat_name}_place2d.mirrorV" #{mirrorV};\n)
      # str << %(    setAttr "#{mat_name}_place2d.rotateUV" #{rotateUV};\n)

      # === назначаем shadingEngine на меш ===
      str << %(connectAttr "#{@node_name}.instObjGroups" "#{material[:sg_name]}.dagSetMembers" -nextAvailable;\n)
    end
    str
  end

  # --------- утилиты ---------

  # def generate_edges_from_ibuf(ibuf)
  #   edges = []
  #   ibuf.each do |buf|
  #     buf.each_cons(2) do |a, b|
  #       edges.push([a, b]) if find_edges_index(edges, [a, b]).nil?
  #     end
  #     edges.push([buf.last, buf.first]) if find_edges_index(edges, [buf.last, buf.first]).nil?
  #   end
  #   edges
  # end

  # def find_edges_index(edges, value)
  #   v1 = nil
  #   v2 = nil
  #   edges.each_with_index do |edge, index|
  #     if edge == value
  #       v1 = index
  #       break
  #     end
  #   end

  #   reverse_value = value.reverse
  #   edges.each_with_index do |edge, index|
  #     return -(index + 1) if edge == reverse_value
  #   end

  #   return nil if v1.nil? && v2.nil?
  #   return v1 unless v1.nil?

  #   v2
  # end

  # def generate_faces_from_edges_an_ibuf(edges, ibuf)
  #   result = []
  #   ibuf.each do |buf|
  #     v1, v2, v3 = buf
  #     i1 = find_edges_index(edges, [v1, v2])
  #     i2 = find_edges_index(edges, [v2, v3])
  #     i3 = find_edges_index(edges, [v3, v1])
  #     result << [i1, i2, i3]
  #   end
  #   result
  # end
end

def model_to_maya(items)
  str = '//Maya ASCII 2.5 scene'
  str += "\nrequires maya \"2.5\";"
  str += "\ncurrentUnit -linear centimeter -angle degree -time film;"
  str += NmfJsonToMaya.new(items).nodes.join("\n")
  str
end

# ---------- main ----------
if ARGV.length < 2
  warn "Usage: ruby #{File.basename(__FILE__)} input.json output.ma"
  exit 1
end

input_path, output_path = ARGV
nodes = JSON.parse(File.read(input_path), symbolize_names: true)
scene = model_to_maya(nodes)

File.open(output_path, 'w:utf-8') do |io|
  io << scene
end

puts "Wrote #{output_path}"
