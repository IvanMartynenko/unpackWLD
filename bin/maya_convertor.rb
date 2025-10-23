#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
FPS = 24.0
DEG2RAD = Math::PI / 180.0
RAD2DEG = 180.0 / Math::PI

def fmt_f(x)
  format('%.9f', x.to_f).sub(/\.?0+$/, '')
end

class NmfJsonToMaya
  def initialize(nodes)
    @result = []
    nodes.each do |node|
      unpacked_node = node[:data]
      node_name = node[:name]

      parent_node = nodes.find { |t| t[:index] == node[:parent_iid] }
      parent_name = parent_node ? parent_node[:name] : nil
      parent_name = nil if node[:parent_iid] == 1

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
    @rotation    = fram_data[:rotation]    || [0, 0, 0] # radians

    @anim        = fram_data[:anim] || {}

    rad2deg = ->(a) { a * 180.0 / Math::PI }
    @rot_deg = @rotation.map { |r| rad2deg.call(r) }
  end

  protected

  def emit_trs_animation
    return '' if @anim.nil? || @anim.empty?

    out = +''
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

        frames = tlist.map { |t| (t.to_f * FPS) }
        vlist.map! { |v| v / DEG2RAD } if track == :rotation

        curve_name = "#{@node_name}_#{spec[:attrs][i]}"
        out << build_anim_curve(spec[:curve], curve_name, frames, vlist)
        out << connect_curve(curve_name, "#{@node_name}.#{spec[:attrs][i]}")
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
    @rotation    = fram_data[:rotation]    || [0, 0, 0]

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

    str << "\n\tsetAttr \".translate\" -type \"double3\" #{@translation.join(' ')};"
    str << "\n\tsetAttr \".rotate\" -type \"double3\" #{@rot_deg.join(' ')};"
    str << "\n\tsetAttr \".scale\" -type \"double3\" #{@scaling.join(' ')};"
    str << "\n\tsetAttr \".rotatePivotTranslate\" -type \"double3\" #{@rpv_t.join(' ')};"
    str << "\n\tsetAttr \".rotatePivot\" -type \"double3\" #{@rpv.join(' ')};"
    str << "\n\tsetAttr \".scalePivotTranslate\" -type \"double3\" #{@spv_t.join(' ')};"
    str << "\n\tsetAttr \".scalePivot\" -type \"double3\" #{@spv.join(' ')};"
    str << "\n\tsetAttr \".shear\" -type \"double3\" #{@shear.join(' ')};"

    str << emit_trs_animation

    str
  end
end

class MayaJoinObject < MayaFrameBaseObject
  def initialize(fram_data, node_name = 'transformNode', parent_node_name)
    super

    @matrix          = fram_data[:matrix]          # 16 float (row-major)
    @rotation_matrix = fram_data[:rotation_matrix] # 16 float (row-major)

    @min_rot_limit   = fram_data[:min_rot_limit]   # [rx, ry, rz] (rad)
    @max_rot_limit   = fram_data[:max_rot_limit]   # [rx, ry, rz] (rad)

    m3 = extract_3x3(@rotation_matrix)
    @joint_orient = matrix_rowmajor_to_euler_xyz_standard(m3)
  end

  def extract_3x3(m4)
    return nil unless m4

    a = m4.flatten
    [
      [a[0], a[1], a[2]],
      [a[4], a[5], a[6]],
      [a[8], a[9], a[10]]
    ]
  end

  def matrix_rowmajor_to_euler_xyz_standard(m)
    m00, m01, m02 = m[0]
    m10, m11, m12 = m[1]
    m20, m21, m22 = m[2]

    r00 = m00
    r01 = m10
    r02 = m20
    r10 = m01
    r11 = m11
    r12 = m21
    r20 = m02
    r21 = m12
    r22 = m22

    if r20.abs < 0.999999
      y = Math.asin(-r20)
      x = Math.atan2(r21, r22)
      z = Math.atan2(r10, r00)
    else
      y = Math.asin(-r20)
      x = Math.atan2(-r12, r11)
      z = 0.0
    end

    [x, y, z].map { |v| v * RAD2DEG }
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

    str << "\n\tsetAttr \".translate\" -type \"double3\" #{@translation.join(' ')};"
    str << "\n\tsetAttr \".rotate\" -type \"double3\" #{@rot_deg.join(' ')};"
    str << "\n\tsetAttr \".scale\" -type \"double3\" #{@scaling.join(' ')};"

    str << "\n\tsetAttr \".jointOrient\" -type \"double3\" #{@joint_orient.map { |d| ('%.6f' % d) }.join(' ')};"
    str << "\n\tsetAttr \".minRotLimit\" -type \"double3\" #{@min_rot_limit.join(' ')};"
    str << "\n\tsetAttr \".maxRotLimit\" -type \"double3\" #{@max_rot_limit.join(' ')};"

    str << emit_trs_animation
    str
  end
end

class MayaLocatorObject
  def initialize(_, node_name, parent_node_name)
    @node_name = node_name
    @parent_node_name = parent_node_name
  end

  def to_s
    str = +"\n"
    str << "createNode locator -name \"#{@node_name}\" -parent \"#{@parent_node_name}\";\n"
    str
  end
end

class MayaMeshObject < MayaBaseObject
  def initialize(mesh_data, node_name = 'meshShape', parent_node_name = 'meshTransform')
    @node_name = node_name
    @parent_node_name = parent_node_name

    @vrts = mesh_data[:vbuf].map { |t| [t[0], t[1], t[2]] }
    @ibuf = mesh_data[:ibuf].map { |tri| [tri[0], tri[1], tri[2]] }
    @have_meterial_name = mesh_right_handed?(mesh_data)
    @ibuf = if @have_meterial_name
              mesh_data[:ibuf].map { |tri| [tri[0], tri[2], tri[1]] }
            else
              mesh_data[:ibuf].map { |tri| [tri[0], tri[1], tri[2]] }
            end

    @edge, @face = build_edges_and_faces_signed(@ibuf)
    @edge.map! { |e| e.length == 2 ? e + [0] : e }

    @materials = mesh_data[:materials]

    @uvpt = mesh_data[:vbuf].map do |t|
      u = (t[6] || 0.0).to_f
      v = (t[7] || 0.0).to_f
      [u, v]
    end

    @uv_index_of_vertex = (0...@vrts.length).to_a

    @materials = mesh_data[:materials].map do |m|
      mat_name = m[:name]
      mat_name = 'lambert' if mat_name == '' || mat_name.empty?
      mat_name = "#{mat_name}_#{@node_name}"
      a = (m[:alpha] || 1.0).to_f

      tex_path = m.dig(:texture, :name)
      tex_path = tex_path&.tr('\\', '/') # Maya отлично ест forward-slash
      {
        mat_name:,
        sg_name: "#{mat_name}SG",
        r: (m[:red]   || 1).to_f,
        g: (m[:green] || 1).to_f,
        b: (m[:blue]  || 1).to_f,
        a:,
        t: a,
        repeatU: (m[:horizontal_stretch] || 1).to_i,
        repeatV: (m[:vertical_stretch]   || 1).to_i,
        mirrorU: (m[:uv_mapping_flip_horizontal] || 0).to_i == 1 ? 1 : 0,
        mirrorV: (m[:uv_mapping_flip_vertical]   || 0).to_i == 1 ? 1 : 0,
        rotateUV: (m[:rotate] || 0).to_i,
        tex_path: tex_path,
        has_tex: !tex_path.nil? && !tex_path.empty?,
        place2d_name: "#{mat_name}_place2d",
        file_name: "#{mat_name}_file"
      }
    end
  end

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
  def pos_of(row) = row[0, 3]
  def nrm_of(row) = row[3, 3]

  def mesh_right_handed?(mesh_data)
    vbuf = mesh_data[:vbuf]

    pos  = vbuf.map { |r| pos_of(r) }
    nrm  = vbuf.map { |r| nrm_of(r) }

    pos_cnt = 0
    neg_cnt = 0

    @ibuf.each do |tri|
      i0, i1, i2 = tri
      p0 = pos[i0]
      p1 = pos[i1]
      p2 = pos[i2]
      n_geom = normalize(cross(sub(p1, p0), sub(p2, p0)))
      n_avg  = normalize([nrm[i0][0] + nrm[i1][0] + nrm[i2][0],
                          nrm[i0][1] + nrm[i1][1] + nrm[i2][1],
                          nrm[i0][2] + nrm[i1][2] + nrm[i2][2]])
      s = dot(n_geom, n_avg)
      s >= 0 ? (pos_cnt += 1) : (neg_cnt += 1)
    end

    pos_cnt >= neg_cnt # true => праворукий; false => леворукий
  end

  def build_edges_and_faces_signed(tris)
    edge_map = {}
    edges    = []

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

    faces_signed = tris.map do |(a, b, c)|
      e0 = signed_edge_index(edge_map, a, b)
      e1 = signed_edge_index(edge_map, b, c)
      e2 = signed_edge_index(edge_map, c, a)
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
    str += "\n\tsetAttr -keyable off \".visibility\";"
    str += "\n\tsetAttr -size 2 \".instObjGroups[0].objectGroups\";"
    str += "\n\tsetAttr \".opposite\" yes;"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[0].objectGrpCompList\" -type \"componentList\" 0;"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[1].objectGrpCompList\" -type \"componentList\" 1 \"f[0:#{@face.size - 1}]\";"

    str += "\n\tsetAttr -size #{@vrts.size} \".vrts[0:#{@vrts.size - 1}]\"  \t\t#{@vrts.map do |x, y, z|
      "#{x.to_f} #{y.to_f} #{z.to_f}"
    end.join("\t")};"

    str += "\n\tsetAttr -size #{@edge.size} \".edge[0:#{@edge.size - 1}]\"  \t\t#{@edge.map do |x, y, z|
      "#{x} #{y} #{z}"
    end.join("\t")};"

    str += "\n\tsetAttr -size #{@uvpt.size} \".uvpt[0:#{@uvpt.size - 1}]\" -type \"float2\"\t\t" \
           "#{@uvpt.map { |u, v| "#{u} #{v}" }.each_slice(6).map { |chunk| chunk.join('   ') }.join("\t")};"

    face_lines = []
    @face.each_with_index do |edges_triplet, i|
      f_part = "f 3 #{edges_triplet.join(' ')}"
      tri = @ibuf[i]
      uv_idx = tri.map { |v| @uv_index_of_vertex[v] }
      mf_part = "mf 3 #{uv_idx.join(' ')}"
      face_lines << "\t\t#{f_part}   #{mf_part}"
    end

    str += "\n\tsetAttr -size #{@face.size} \".face[0:#{@face.size - 1}]\" -type \"polyFaces\"\n#{face_lines.join(" \n")};"

    str << "\n"
    @materials.each do |material|
      str << %(createNode lambert -name "#{material[:mat_name]}";\n)
      str << %(\tsetAttr ".color" -type "float3" #{material[:r]} #{material[:g]} #{material[:b]} ;\n)
      str << %(\tsetAttr ".transparency" -type "float3" #{material[:t]} #{material[:t]} #{material[:t]} ;\n)
      str << %(\tsetAttr ".diffuse" 1;\n)
      str << %(\tsetAttr ".translucence" 0;\n)
      str << %(\tsetAttr ".ambientColor" -type "float3" 0 0 0;\n)

      str << %(createNode shadingEngine -name "#{material[:sg_name]}";\n)
      str << %(\tsetAttr ".ihi" 0;\n)
      str << %(connectAttr "#{material[:mat_name]}.outColor" "#{material[:sg_name]}.surfaceShader";\n)

      if material[:has_tex]
        str << %(createNode place2dTexture -name "#{material[:place2d_name]}";\n)
        str << %(\tsetAttr ".repeatU" #{material[:repeatU]};\n)
        str << %(\tsetAttr ".repeatV" #{material[:repeatV]};\n)
        str << %(\tsetAttr ".rotateUV" #{material[:rotateUV]};\n)

        str << %(createNode file -name "#{material[:file_name]}";\n)
        str << %(\tsetAttr ".fileTextureName" -type "string" "#{material[:tex_path]}";\n)


        str << %(connectAttr "#{material[:place2d_name]}.coverage"           "#{material[:file_name]}.coverage";\n)
        str << %(connectAttr "#{material[:place2d_name]}.translateFrame"     "#{material[:file_name]}.translateFrame";\n)
        str << %(connectAttr "#{material[:place2d_name]}.rotateFrame"        "#{material[:file_name]}.rotateFrame";\n)
        str << %(connectAttr "#{material[:place2d_name]}.repeatUV"           "#{material[:file_name]}.repeatUV";\n)
        str << %(connectAttr "#{material[:place2d_name]}.offset"             "#{material[:file_name]}.offset";\n)
        str << %(connectAttr "#{material[:place2d_name]}.rotateUV"           "#{material[:file_name]}.rotateUV";\n)
        str << %(connectAttr "#{material[:place2d_name]}.outUV"              "#{material[:file_name]}.uvCoord";\n)

        str << %(connectAttr "#{material[:file_name]}.outColor"         "#{material[:mat_name]}.color";\n)
      end

      str << %(connectAttr "#{@node_name}.instObjGroups" "#{material[:sg_name]}.dagSetMembers" -nextAvailable;\n)
    end
    str
  end
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
