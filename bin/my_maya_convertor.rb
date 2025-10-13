#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'

class NmfJsonToMaya
  def initialize(nodes)
    @result = []
    nodes.each do |node|
      unpacked_node = node[:data]
      node_name = node[:name]

      # Find the parent item based on its index
      parent_node = nodes.find { |t| t[:index] == node[:parent_iid] }
      parent_name = parent_node ? parent_node[:name] : nil
      parent_name = nil if node[:parent_iid] == 1

    case node[:word]
      when 'JOIN'
        @result.push MayaFrameObject.new(unpacked_node, node_name, parent_name, as_joint: true)
      when 'FRAM'
        @result.push MayaFrameObject.new(unpacked_node, node_name, parent_name, as_joint: true)
      when 'MESH'
        @result.push MayaMeshObject.new(unpacked_node, node_name, parent_name)
      end
    end
  end

  def nodes
    @result
  end
end

class MayaBaseObject
end

class MayaFrameObject < MayaBaseObject
  def initialize(fram_data, node_name = 'transformNode', parent_node_name, as_joint: true)
    @node_name = node_name
    @parent_node_name = parent_node_name
    @translation = fram_data[:translation] || [0,0,0]
    @scaling     = fram_data[:scaling]     || [1,1,1]
    @rotation    = fram_data[:rotation]    || [0,0,0] # radians
    @rpv_t       = fram_data[:rotate_pivot_translate] || [0,0,0]
    @rpv         = fram_data[:rotate_pivot]           || [0,0,0]
    @spv_t       = fram_data[:scale_pivot_translate]  || [0,0,0]
    @spv         = fram_data[:scale_pivot]            || [0,0,0]
    @shear       = fram_data[:shear]                  || [0,0,0]

    rad2deg = ->(a){ a * 180.0 / Math::PI }
    @rot_deg = @rotation.map { |r| rad2deg.call(r) }
  end

  def to_s
    str  = +"\n"
    line = @parent_node_name ?
      "createNode transform -name \"#{@node_name}\" -parent \"#{@parent_node_name}\";" :
      "createNode transform -name \"#{@node_name}\";"
    str << line
    # Важно: не пишем .matrix — только компоненты
    # matrix_flat = fram_data[:matrix].flatten.map(&:to_s).join(' ')
    # str += "\n\tsetAttr \".matrix\" -type \"matrix\" #{matrix_flat};"
    str << "\n\tsetAttr \".translate\" -type \"double3\" #{@translation.join(' ')};"
    str << "\n\tsetAttr \".rotate\" -type \"double3\" #{@rot_deg.join(' ')};"
    str << "\n\tsetAttr \".scale\" -type \"double3\" #{@scaling.join(' ')};"
    str << "\n\tsetAttr \".rotatePivotTranslate\" -type \"double3\" #{@rpv_t.join(' ')};"
    str << "\n\tsetAttr \".rotatePivot\" -type \"double3\" #{@rpv.join(' ')};"
    str << "\n\tsetAttr \".scalePivotTranslate\" -type \"double3\" #{@spv_t.join(' ')};"
    str << "\n\tsetAttr \".scalePivot\" -type \"double3\" #{@spv.join(' ')};"
    str << "\n\tsetAttr \".shear\" -type \"double3\" #{@shear.join(' ')};"
    str << "\n\tsetAttr \".rotateOrder\" 0;"

    str
  end
end

class MayaMeshObject < MayaBaseObject
  def initialize(mesh_data, node_name = 'meshShape', parent_node_name = 'meshTransform')
    @node_name = node_name
    @parent_node_name = parent_node_name

    # Вершины (xyz)
    @vrts = mesh_data[:vbuf].map { |t| [t[0], t[1], t[2]] }

    # Исходные треугольники (по вершинам) — пригодятся для mf
    @ibuf = mesh_data[:ibuf].map { |tri| [tri[0], tri[2], tri[1]] } # [v1,v2,v3]

    # Сгенерим рёбра и индексы рёбер для polyFaces::f
    # @edge = generate_edges_from_ibuf(@ibuf)
    # @face = generate_faces_from_edges_an_ibuf(@edge, @ibuf)
    @edge, @face = build_edges_and_faces_signed(@ibuf)
     @edge.map! { |e| e.length == 2 ? e + [0] : e }

    # ---------- UV: строим пул uvpt и соответствие вершина->uv-индекс ----------
    # Приоритет: mesh_data[:uvpt] если длина == числу вершин; иначе берём из vbuf[6,7]; иначе 0,0
    uv_source_per_vertex =
      if mesh_data[:uvpt].is_a?(Array) && mesh_data[:uvpt].length == @vrts.length
        mesh_data[:uvpt].map { |u| [u[0].to_f, u[1].to_f] }
      else
        mesh_data[:vbuf].map { |t| [(t[6] || 0.0).to_f, (t[7] || 0.0).to_f] }
      end

    # В этой сборке лоадер отлично работает, когда uvpt идёт "по-вершинно":
    # uv-индекс == индекс вершины. Это же сильно упрощает mf.
    @uvpt = uv_source_per_vertex
    @uv_index_of_vertex = (0...@vrts.length).to_a
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

  # 2) Для каждого треугольника считаем ПОДПИСАННЫЕ индексы рёбер (для f)
  faces_signed = tris.map do |(a, b, c)|
    e0 = signed_edge_index(edge_map, a, b) # (a→b)
    e1 = signed_edge_index(edge_map, b, c) # (b→c)
    e2 = signed_edge_index(edge_map, c, a) # (c→a)
    [e0, e1, e2]
  end

  [edges, faces_signed]
end

# Возвращает индекс ребра с направлением:
#   совпало с хранением (va<vb и (a,b)==(va,vb))  -> idx
#   обратное направление                          -> -(idx+1)
def signed_edge_index(edge_map, a, b)
  va, vb = [a, b].minmax
  idx = edge_map["#{va}|#{vb}"]
  raise "edge not found for #{a}-#{b}" unless idx
  same_dir = (a == va) && (b == vb)
  same_dir ? idx : -(idx + 1)
end

  def build_edges_and_faces(tris)
    edge_map = {}      # "va|vb" -> edge_index
    edges = []         # [[va,vb,0], ...]
    faces = []         # [[e0,e1,e2], ...]

    tris.each do |(a, b, c)|
      tri_edges = [[a, b], [b, c], [c, a]].map do |u, v|
        va, vb = [u, v].minmax
        key = "#{va}|#{vb}"
        idx = edge_map[key]
        unless idx
          idx = edges.length
          edge_map[key] = idx
          edges << [va, vb, 0]  # 3-й элемент — как у вас, флаг/сглаживание/и пр.
        end
        idx
      end
      faces << tri_edges
    end

    faces.map! { |t| [t[0], t[1], t[2]] }
    [edges, faces]
  end

  def to_s
    line = @parent_node_name ? "createNode mesh -name \"#{@node_name}\" -parent \"#{@parent_node_name}\";" : "createNode transform -name \"#{@node_name}\";"
    str = ''
    str += line
    str += "\n\tsetAttr -keyable off \".visibility\";"
    str += "\n\tsetAttr -size 2 \".instObjGroups[0].objectGroups\";"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[0].objectGrpCompList\" -type \"componentList\" 0;"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[1].objectGrpCompList\" -type \"componentList\" 1 \"f[0:#{@face.size - 1}]\";"

    # Вершины
    str += "\n\tsetAttr -size #{@vrts.size} \".vrts[0:#{@vrts.size - 1}]\"  \t\t#{@vrts.map { |x, y, z| "#{x} #{y} #{z}" }.join("\t")};"

    # Рёбра
    str += "\n\tsetAttr -size #{@edge.size} \".edge[0:#{@edge.size - 1}]\"  \t\t#{@edge.map { |x, y, z| "#{x} #{y} #{z}" }.join("\t")};"

    # UV-пул (.uvpt) — важно: -type "float2"
    str += "\n\tsetAttr -size #{@uvpt.size} \".uvpt[0:#{@uvpt.size - 1}]\" -type \"float2\"\t\t" \
           "#{@uvpt.map { |u, v| "#{u} #{v}" }.each_slice(6).map { |chunk| chunk.join('   ') }.join("\t")};"

    # polyFaces: f ... и mf <ровно N индексов>
    face_lines = []
    @face.each_with_index do |edges_triplet, i|
      # "f 3 e1 e2 e3"
      f_part = "f 3 #{edges_triplet.join(' ')}"

      # Для mf нам нужны uv-индексы уголков. Берём вершины из исходного ibuf[i] (порядок per-corner)
      tri = @ibuf[i]
      uv_idx = tri.map { |v| @uv_index_of_vertex[v] } # тут просто [v1, v2, v3]

      # "mf u1 u2 u3" (без uv-сета и без count — как у тебя)
      mf_part = "mf 3 #{uv_idx.join(' ')}"

      face_lines << "\t\t#{f_part}   #{mf_part}"
      # face_lines << "\t\t#{f_part}  "
    end

    str += "\n\tsetAttr -size #{@face.size} \".face[0:#{@face.size - 1}]\" -type \"polyFaces\"\n#{face_lines.join(" \n")};"
    str
  end

  # --------- твои утилиты без изменений ---------

  def generate_edges_from_ibuf(ibuf)
    edges = []
    ibuf.each do |buf|
      buf.each_cons(2) do |a, b|
        edges.push([a, b]) if find_edges_index(edges, [a, b]).nil?
      end
      edges.push([buf.last, buf.first]) if find_edges_index(edges, [buf.last, buf.first]).nil?
    end
    edges
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
        return -(index + 1)
      end
    end

    return nil if v1.nil? && v2.nil?
    return v1 unless v1.nil?
    v2
  end

  def generate_faces_from_edges_an_ibuf(edges, ibuf)
    result = []
    ibuf.each do |buf|
      v1, v2, v3 = buf
      i1 = find_edges_index(edges, [v1, v2])
      i2 = find_edges_index(edges, [v2, v3])
      i3 = find_edges_index(edges, [v3, v1])
      result << [i1, i2, i3]
    end
    result
  end


end

def model_to_maya(items)
  str = "//Maya ASCII 2.5 scene"
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
nodes = JSON.parse(File.read(input_path),  symbolize_names: true)
scene = model_to_maya(nodes)

File.open(output_path, 'w:utf-8') do |io|
  io << scene
end

puts "Wrote #{output_path}"
