#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
FPS = 24.0
DEG2RAD = Math::PI / 180.0
RAD2DEG = 180.0 / Math::PI

module MeshGeom
  EPS = 1e-8

  module_function

  # private
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

  # public
  def mesh_right_handed?(ibuf, mesh_data)
    vbuf = mesh_data[:vbuf]

    pos  = vbuf.map { |r| pos_of(r) }
    nrm  = vbuf.map { |r| nrm_of(r) }

    pos_cnt = 0
    neg_cnt = 0

    ibuf.each do |tri|
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
end

def convert_nodes(nodes)
  result = []
  nodes.each do |node|
    unpacked_node = node[:data]
    node_name = node[:name]

    parent_node = nodes.find { |t| t[:index] == node[:parent_iid] }
    parent_name = parent_node ? parent_node[:name] : nil
    parent_name = nil if node[:parent_iid] == 1

    case node[:word]
    when 'ROOT'
      result.push create_fram(unpacked_node, node_name: node_name, parent_node_name: parent_name)
    when 'FRAM'
      result.push create_fram(unpacked_node, node_name: node_name, parent_node_name: parent_name)
    when 'JOIN'
      result.push create_joint(unpacked_node, node_name: node_name, parent_node_name: parent_name)
    when 'LOCA'
      result.push create_locator(unpacked_node, node_name: node_name, parent_node_name: parent_name)
    when 'MESH'
      result.push create_mesh(unpacked_node, node_name: node_name, parent_node_name: parent_name)
    end
  end

  result
end

# HELPER FUNCTION
def animation_build_tracks_by_axis(raw_values)
  axes = %i[x y z]
  result = {}

  %i[translation rotation scaling].each do |track|
    anim = raw_values[track]
    next unless anim

    keys   = anim[:keys]
    values = anim[:values]
    next unless keys && values

    track_hash = {}

    axes.each do |ax|
      tlist = keys[ax]
      vlist = values[ax]
      next unless tlist
      next unless vlist
      next if tlist.empty? || vlist.empty?

      frames = tlist.map { |t| t.to_f * FPS } # from second to FPS
      vals   = vlist.map { |v| v.to_f }

      # rotation: радианы -> градусы
      vals = vals.map { |v| v / DEG2RAD } if track == :rotation

      track_hash[ax] = { frames: frames, values: vals }
    end

    result[track] = track_hash unless track_hash.empty?
  end

  result
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

# CONVERT FUNCTION
def create_fram(fram_data, parent_node_name:, node_name:)
  result = {}
  result[:node_name] = node_name
  result[:parent_node_name] = parent_node_name
  result[:translation] = fram_data[:translation]
  result[:scaling]     = fram_data[:scaling]
  result[:rotation] = fram_data[:rotation].map { |r| r * RAD2DEG }

  result[:node_type] = 'fram'

  result[:matrix] = fram_data[:matrix] # 16 float (row-major)
  result[:rotate_pivot_translate] = fram_data[:rotate_pivot_translate]
  result[:rotate_pivot] = fram_data[:rotate_pivot]
  result[:scale_pivot_translate] = fram_data[:scale_pivot_translate]
  result[:scale_pivot] = fram_data[:scale_pivot]
  result[:shear] = fram_data[:shear]

  anim = animation_build_tracks_by_axis(fram_data[:anim] || {})
  result[:with_animation] = !anim.empty?
  result[:animations] = anim

  result
end

def create_joint(fram_data, parent_node_name:, node_name: 'transformNode')
  result = {}
  result[:node_name] = node_name
  result[:parent_node_name] = parent_node_name
  result[:translation] = fram_data[:translation]
  result[:scaling]     = fram_data[:scaling]
  result[:rotation] = fram_data[:rotation].map { |r| r * RAD2DEG }

  result[:node_type] = 'joint'
  result[:matrix]          = fram_data[:matrix]          # 16 float (row-major)
  result[:rotation_matrix] = fram_data[:rotation_matrix] # 16 float (row-major)

  result[:min_rot_limit]   = fram_data[:min_rot_limit]   # [rx, ry, rz] (rad)
  result[:max_rot_limit]   = fram_data[:max_rot_limit]   # [rx, ry, rz] (rad)

  m3 = extract_3x3(result[:rotation_matrix])
  result[:joint_orient] = matrix_rowmajor_to_euler_xyz_standard(m3)

  anim = animation_build_tracks_by_axis(fram_data[:anim] || {})
  result[:with_animation] = !anim.empty?
  result[:animations] = anim

  result
end

def create_locator(_, node_name:, parent_node_name:)
  result = { node_type: 'locator' }
  result[:node_name] = node_name
  result[:parent_node_name] = parent_node_name
  result
end

def create_mesh(mesh_data, node_name:, parent_node_name:)
  result = { node_type: 'mesh' }
  result[:node_name] = node_name
  result[:parent_node_name] = parent_node_name

  result[:vrts] = mesh_data[:vbuf].map { |t| [t[0], t[1], t[2]] }
  ibuf = mesh_data[:ibuf].map { |tri| [tri[0], tri[1], tri[2]] }
  ibuf = if MeshGeom.mesh_right_handed?(ibuf, mesh_data)
           mesh_data[:ibuf].map { |tri| [tri[0], tri[2], tri[1]] }
         else
           mesh_data[:ibuf].map { |tri| [tri[0], tri[1], tri[2]] }
         end
  result[:ibuf] = ibuf

  edge, face = build_edges_and_faces_signed(ibuf)
  result[:edge] = edge
  result[:face] = face
  result[:edge].map! { |e| e.length == 2 ? e + [0] : e }

  result[:materials] = mesh_data[:materials]

  result[:uvpt] = mesh_data[:vbuf].map do |t|
    u = (t[6] || 0.0).to_f
    v = (t[7] || 0.0).to_f
    [u, v]
  end

  result[:uv_index_of_vertex] = (0...result[:vrts].length).to_a

  result[:materials] = mesh_data[:materials].map do |m|
    mat_name = m[:name]
    mat_name = 'lambert' if mat_name == '' || mat_name.empty?
    mat_name = "#{mat_name}_#{result[:node_name]}"
    a = m[:alpha].to_f

    tex_path = m.dig(:texture, :name)
    tex_path = tex_path&.tr('\\', '/') # Maya отлично ест forward-slash
    {
      mat_name:,
      sg_name: "#{mat_name}SG",
      r: m[:red].to_f,
      g: m[:green].to_f,
      b: m[:blue].to_f,
      a:,
      t: a,
      repeatU: m[:horizontal_stretch].to_i,
      repeatV: m[:vertical_stretch].to_i,
      mirrorU: m[:uv_mapping_flip_horizontal].to_i,
      mirrorV: m[:uv_mapping_flip_vertical].to_i,
      rotateUV: m[:rotate].to_i,
      tex_path: tex_path,
      has_tex: !tex_path.nil? && !tex_path.empty?,
      place2d_name: "#{mat_name}_place2d",
      file_name: "#{mat_name}_file"
    }
  end

  result
end

# OUTPUT FUNCTION
def fmt_f(x)
  format('%.9f', x.to_f).sub(/\.?0+$/, '')
end

def model_to_maya(nodes)
  str = '//Maya ASCII 2.5 scene'
  str += "\nrequires maya \"2.5\";"
  str += "\ncurrentUnit -linear centimeter -angle degree -time film;"
  nodes.each do |node|
    if node[:node_type] == 'fram'
      str += "\n"
      header = if node[:parent_node_name]
                 "createNode transform -name \"#{node[:node_name]}\" -parent \"#{node[:parent_node_name]}\";"
               else
                 "createNode transform -name \"#{node[:node_name]}\";"
               end
      str << header

      str << "\n\tsetAttr \".translate\" -type \"double3\" #{node[:translation].join(' ')};"
      str << "\n\tsetAttr \".rotate\" -type \"double3\" #{node[:rotation].join(' ')};"
      str << "\n\tsetAttr \".scale\" -type \"double3\" #{node[:scaling].join(' ')};"
      str << "\n\tsetAttr \".rotatePivotTranslate\" -type \"double3\" #{node[:rotate_pivot_translate].join(' ')};"
      str << "\n\tsetAttr \".rotatePivot\" -type \"double3\" #{node[:rotate_pivot].join(' ')};"
      str << "\n\tsetAttr \".scalePivotTranslate\" -type \"double3\" #{node[:scale_pivot_translate].join(' ')};"
      str << "\n\tsetAttr \".scalePivot\" -type \"double3\" #{node[:scale_pivot].join(' ')};"
      str << "\n\tsetAttr \".shear\" -type \"double3\" #{node[:shear].join(' ')};"
    end
    if node[:node_type] == 'joint'
      str += "\n"
      header =
        if node[:parent_node_name]
          "createNode joint -name \"#{node[:node_name]}\" -parent \"#{node[:parent_node_name]}\";"
        else
          "createNode joint -name \"#{node[:node_name]}\";"
        end
      str << header

      str << "\n\tsetAttr \".translate\" -type \"double3\" #{node[:translation].join(' ')};"
      str << "\n\tsetAttr \".rotate\" -type \"double3\" #{node[:rotation].join(' ')};"
      str << "\n\tsetAttr \".scale\" -type \"double3\" #{node[:scaling].join(' ')};"

      str << "\n\tsetAttr \".jointOrient\" -type \"double3\" #{node[:joint_orient].map { |d| ('%.6f' % d) }.join(' ')};"
      str << "\n\tsetAttr \".minRotLimit\" -type \"double3\" #{node[:min_rot_limit].join(' ')};"
      str << "\n\tsetAttr \".maxRotLimit\" -type \"double3\" #{node[:max_rot_limit].join(' ')};"
    end
    if node[:with_animation]
      str += "\n"
      {
        translation: { curve: 'animCurveTL', attrs: %w[translateX translateY translateZ], axes: %i[x y z] },
        rotation: { curve: 'animCurveTA', attrs: %w[rotateX rotateY rotateZ], axes: %i[x y z] },
        scaling: { curve: 'animCurveTU', attrs: %w[scaleX scaleY scaleZ], axes: %i[x y z] }
      }.each do |track, spec|
        next unless node[:animations][track]

        spec[:axes].each_with_index do |ax, i|
          next if node[:animations][track][ax].nil? || node[:animations][track][ax].empty?

          curve_name = "#{node[:node_name]}_#{spec[:attrs][i]}"
          if node[:animations][track][ax][:frames]
            n = node[:animations][track][ax][:frames].size
            pairs = (0...n).map do |i|
              "#{fmt_f(node[:animations][track][ax][:frames][i])} #{fmt_f(node[:animations][track][ax][:values][i])}"
            end.join(' ')
            str << "\ncreateNode #{spec[:curve]} -name \"#{curve_name}\";"
            str << "\n\tsetAttr \".tangentType\" 9;"
            str << "\n\tsetAttr \".weightedTangents\" no;"
            str << "\n\tsetAttr -size #{n} \".keyTimeValue[0:#{n - 1}]\" #{pairs};"
          end
          str << "\nconnectAttr \"#{curve_name}.output\" \"#{node[:node_name]}.#{spec[:attrs][i]}\";"
        end
      end
    end
    if node[:node_type] == 'locator'
      str += "\n"
      str << "createNode locator -name \"#{node[:node_name]}\" -parent \"#{node[:parent_node_name]}\";\n"
    end
    next unless node[:node_type] == 'mesh'

    line = node[:parent_node_name] ? "createNode mesh -name \"#{node[:node_name]}\" -parent \"#{node[:parent_node_name]}\";" : "createNode mesh -name \"#{node[:node_name]}\";"
    str += "\n"
    str += line
    str += "\n\tsetAttr -keyable off \".visibility\";"
    str += "\n\tsetAttr -size 2 \".instObjGroups[0].objectGroups\";"
    str += "\n\tsetAttr \".opposite\" yes;"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[0].objectGrpCompList\" -type \"componentList\" 0;"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[1].objectGrpCompList\" -type \"componentList\" 1 \"f[0:#{node[:face].size - 1}]\";"

    str += "\n\tsetAttr -size #{node[:vrts].size} \".vrts[0:#{node[:vrts].size - 1}]\"  \t\t#{node[:vrts].map do |x, y, z|
      "#{x.to_f} #{y.to_f} #{z.to_f}"
    end.join("\t")};"

    str += "\n\tsetAttr -size #{node[:edge].size} \".edge[0:#{node[:edge].size - 1}]\"  \t\t#{node[:edge].map do |x, y, z|
      "#{x} #{y} #{z}"
    end.join("\t")};"

    str += "\n\tsetAttr -size #{node[:uvpt].size} \".uvpt[0:#{node[:uvpt].size - 1}]\" -type \"float2\"\t\t" \
           "#{node[:uvpt].map { |u, v| "#{u} #{v}" }.each_slice(6).map { |chunk| chunk.join('   ') }.join("\t")};"

    face_lines = []
    node[:face].each_with_index do |edges_triplet, i|
      f_part = "f 3 #{edges_triplet.join(' ')}"
      tri = node[:ibuf][i]
      uv_idx = tri.map { |v| node[:uv_index_of_vertex][v] }
      mf_part = "mf 3 #{uv_idx.join(' ')}"
      face_lines << "\t\t#{f_part}   #{mf_part}"
    end

    str += "\n\tsetAttr -size #{node[:face].size} \".face[0:#{node[:face].size - 1}]\" -type \"polyFaces\"\n#{face_lines.join(" \n")};"

    str << "\n"
    node[:materials].each do |material|
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

      str << %(connectAttr "#{node[:node_name]}.instObjGroups" "#{material[:sg_name]}.dagSetMembers" -nextAvailable;\n)
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
nodes = JSON.parse(File.read(input_path), symbolize_names: true)
scene = model_to_maya(convert_nodes(nodes))

File.open(output_path, 'w:utf-8') do |io|
  io << scene
end

puts "Wrote #{output_path}"
