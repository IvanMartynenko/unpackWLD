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
    str  = +""
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
    @vrts = mesh_data[:vbuf].map { |t| [t[0], t[1], t[2]] }
    # uvpt = mesh_data[:vbuf].map { |t| [t[6], t[7]] }
    # uvpt = (mesh_data[:uvpt] || []).map { |u, v| [u, v] }
    @edge = generate_edges_from_ibuf(mesh_data[:ibuf])
    @face = generate_faces_from_edges_an_ibuf(@edge, mesh_data[:ibuf])
    @edge.map! { |e| e.push(0) }
  end

  def to_s
    line = @parent_node_name ? "createNode mesh -name \"#{@node_name}\" -parent \"#{@parent_node_name}\";" : "createNode transform -name \"#{@node_name}\";"
    str = ''
    str += line
    str += "\n\tsetAttr -keyable off \".visibility\";"
    str += "\n\tsetAttr -size 2 \".instObjGroups[0].objectGroups\";"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[0].objectGrpCompList\" -type \"componentList\" 0;"
    str += "\n\tsetAttr \".instObjGroups[0].objectGroups[1].objectGrpCompList\" -type \"componentList\" 1 \"f[0:#{@face.size - 1}]\";"
    str += "\n\tsetAttr -size #{@vrts.size} \".vrts[0:#{@vrts.size - 1}]\"  \n\t\t#{@vrts.map { |x, y, z| "#{x} #{y} #{z}" }.join("\n\t\t")};"
    str += "\n\tsetAttr -size #{@edge.size} \".edge[0:#{@edge.size - 1}]\"  \n\t\t#{@edge.map { |x, y, z| "#{x} #{y} #{z}" }.join("\n\t\t")};"
    # str += "\n\tsetAttr -size #{uvpt.size} \".uvpt[0:#{uvpt.size - 1}]\"  #{uvpt.join(' ')};"
    face_string = @face.map { |f| "\t\tf 3 #{f.join(' ')} " }.join(" \n")
    str += "\n\tsetAttr -size #{@face.size} \".face[0:#{@face.size - 1}]\" -type \"polyFaces\"\n#{face_string};"
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
