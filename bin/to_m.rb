#!/usr/bin/env ruby
# frozen_string_literal: true
# Конвертер: JSON сцена -> Maya ASCII (.ma)
# Использует полные имена атрибутов и длинные флаги команд

require 'json'
require 'pathname'

STRIP_TEX_PATHS   = true
FORCE_PNG_EXT     = false
FLIP_V            = true
USE_UV_FROM_VBUF  = true

DEFAULT_MAT_NAME  = 'DefaultWhite'
DEFAULT_COLOR     = [1.0, 1.0, 1.0, 1.0]

ATTRS = {
  transform: {
    visibility: 'visibility',
    translate:  'translate',
    rotate:     'rotate',
    scale:      'scale'
  },
  mesh: {
    vrts:       'vrts',
    face:       'face',
    uvSet:      'uvSet',
    uvSetName:  'uvSetName',
    uvSetArr:   'uvSet'
  },
  shadingEngine: {
    surfaceShader: 'surfaceShader'
  },
  lambert: {
    color:       'color',
    diffuse:     'diffuse',
    transparency:'transparency'
  },
  file: {
    fileTextureName: 'fileTextureName',
    outColor:        'outColor'
  },
  place2d: {
    coverage: 'coverage',
    translateFrame:'translateFrame',
    rotateFrame:'rotateFrame',
    mirrorU: 'mirrorU',
    mirrorV: 'mirrorV',
    stagger: 'stagger',
    wrapU: 'wrapU',
    wrapV: 'wrapV',
    repeatUV: 'repeatUV',
    offset: 'offset',
    rotateUV: 'rotateUV',
    noiseUV: 'noiseUV',
    vertexUvOne:'vertexUvOne',
    vertexUvTwo:'vertexUvTwo',
    vertexUvThree:'vertexUvThree',
    vertexCameraOne:'vertexCameraOne',
    outUV: 'outUV',
    outUvFilterSize: 'outUvFilterSize'
  }
}

def f3(x,y,z) = "#{fmt(x)} #{fmt(y)} #{fmt(z)}"
def fmt(x) = ('%.6f' % x.to_f).sub(/-0\.000000/, '0.000000')

def texture_name(mat)
  t = mat.dig('texture','name')
  return nil unless t && !t.empty?
  t = STRIP_TEX_PATHS ? File.basename(t) : t.tr('\\','/')
  t = t.sub(/\.(tif|tiff)\z/i, '.png') if FORCE_PNG_EXT
  t.tr('\\','/')
end

def collect_tree(items)
  by_parent = Hash.new { |h,k| h[k] = [] }
  items.each { |it| by_parent[it['parent_iid']] << it }
  by_parent
end

def decompose_trs(m)
  tx, ty, tz = m[3][0], m[3][1], m[3][2]
  sx = Math.sqrt(m[0][0]**2 + m[0][1]**2 + m[0][2]**2)
  sy = Math.sqrt(m[1][0]**2 + m[1][1]**2 + m[1][2]**2)
  sz = Math.sqrt(m[2][0]**2 + m[2][1]**2 + m[2][2]**2)
  r = [
    [m[0][0]/sx, m[0][1]/sx, m[0][2]/sx],
    [m[1][0]/sy, m[1][1]/sy, m[1][2]/sy],
    [m[2][0]/sz, m[2][1]/sz, m[2][2]/sz]
  ]
  if r[0][2] < 1
    if r[0][2] > -1
      ry = Math.asin(r[0][2])
      rx = Math.atan2(-r[1][2], r[2][2])
      rz = Math.atan2(-r[0][1], r[0][0])
    else
      ry = -Math::PI/2
      rx = -Math.atan2(r[1][0], r[1][1])
      rz = 0
    end
  else
    ry = Math::PI/2
    rx = Math.atan2(r[1][0], r[1][1])
    rz = 0
  end
  [ [tx,ty,tz], [rx*180/Math::PI, ry*180/Math::PI, rz*180/Math::PI], [sx,sy,sz] ]
end

def write_header(io)
  io.puts '//Maya ASCII 2020 scene'
  io.puts 'requires maya "2020";'
  io.puts 'currentUnit -linear centimeter -angle degree -time film;'
  io.puts 'fileInfo "application" "json2maya_ascii_full";'
  io.puts
end

def safe_name(s, fallback)
  n = s.to_s.strip
  n.empty? ? fallback : n.gsub(/[^\w\-\.]/,'_')
end

def write_transform(io, name, mat)
  t, r, s = decompose_trs(mat)
  io.puts %(createNode transform -name "#{name}";)
  io.puts %(setAttr "#{name}.#{ATTRS[:transform][:visibility]}" yes;)
  io.puts %(setAttr "#{name}.#{ATTRS[:transform][:translate]}" -type "double3" #{f3(*t)};)
  io.puts %(setAttr "#{name}.#{ATTRS[:transform][:rotate]}" -type "double3" #{f3(*r)};)
  io.puts %(setAttr "#{name}.#{ATTRS[:transform][:scale]}" -type "double3" #{f3(*s)};)
end

def write_mesh_node(io, xform_name, mesh_name, pos, tris, uv, mat_ref)
  shape = "#{mesh_name}Shape"
  io.puts %(createNode mesh -name "#{shape}" -parent "#{xform_name}";)
  io.puts %(setAttr "#{shape}.#{ATTRS[:transform][:visibility]}" yes;)

  io.puts %(setAttr -size #{pos.length} "#{shape}.#{ATTRS[:mesh][:vrts]}[0:#{pos.length-1}]" -type "float3")
  pos.each_with_index do |p, i|
    io.puts " #{fmt(p[0])} #{fmt(p[1])} #{fmt(p[2])}#{i==pos.length-1 ? ';' : ''}"
  end

  if uv && uv.any?
    io.puts %(setAttr "#{shape}.#{ATTRS[:mesh][:uvSet]}[0].#{ATTRS[:mesh][:uvSetName]}" -type "string" "map1";)
    io.puts %(setAttr -size #{uv.length} "#{shape}.#{ATTRS[:mesh][:uvSet]}[0].#{ATTRS[:mesh][:uvSetArr]}[0:#{uv.length-1}].uvSetU";)
    io.print " "
    uv.each_with_index { |u,i| io.print("#{fmt(u[0])}#{i==uv.length-1 ? ";\n" : ' '}" ) }
    io.puts %(setAttr -size #{uv.length} "#{shape}.#{ATTRS[:mesh][:uvSet]}[0].#{ATTRS[:mesh][:uvSetArr]}[0:#{uv.length-1}].uvSetV";)
    io.print " "
    uv.each_with_index do |u,i|
      v = FLIP_V ? (1.0 - u[1].to_f) : u[1].to_f
      io.print("#{fmt(v)}#{i==uv.length-1 ? ";\n" : ' '}")
    end
  end

  io.puts %(setAttr -size #{tris.length} "#{shape}.#{ATTRS[:mesh][:face]}[0:#{tris.length-1}]" -type "polyFaces")
  tris.each_with_index do |t, i|
    io.print " f 3 #{t[0]} #{t[1]} #{t[2]}"
    if uv && uv.any?
      io.print " mu 0 3 #{t[0]} #{t[1]} #{t[2]}"
    end
    io.puts(i==tris.length-1 ? ";" : "")
  end

  if mat_ref
    sg = "#{mat_ref}SG"
    io.puts %(sets -edit -forceElement "#{sg}" "#{shape}";)
  end
end

def write_lambert_with_file(io, base_name, color_rgba, tex_path)
  lam = "#{base_name}_lambert"
  sg  = "#{base_name}SG"

  io.puts %(createNode shadingEngine -name "#{sg}";)
  io.puts %(createNode lambert -name "#{lam}";)
  io.puts %(setAttr "#{lam}.#{ATTRS[:lambert][:diffuse]}" 0.8;)
  io.puts %(setAttr "#{lam}.#{ATTRS[:lambert][:transparency]}" -type "float3" 0 0 0;)

  if tex_path && !tex_path.empty?
    file_node  = "#{base_name}_file"
    p2d_node   = "#{base_name}_place2d"
    path = STRIP_TEX_PATHS ? File.basename(tex_path) : tex_path
    path = path.sub(/\.(tif|tiff)\z/i, '.png') if FORCE_PNG_EXT
    path = path.tr('\\','/')

    io.puts %(createNode place2dTexture -name "#{p2d_node}";)
    io.puts %(createNode file -name "#{file_node}";)
    io.puts %(setAttr -type "string" "#{file_node}.#{ATTRS[:file][:fileTextureName]}" "#{path}";)

    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:coverage]}" "#{file_node}.coverage";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:translateFrame]}" "#{file_node}.translateFrame";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:rotateFrame]}" "#{file_node}.rotateFrame";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:mirrorU]}" "#{file_node}.mirrorU";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:mirrorV]}" "#{file_node}.mirrorV";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:stagger]}" "#{file_node}.stagger";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:wrapU]}" "#{file_node}.wrapU";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:wrapV]}" "#{file_node}.wrapV";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:repeatUV]}" "#{file_node}.repeatUV";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:offset]}" "#{file_node}.offset";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:rotateUV]}" "#{file_node}.rotateUV";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:noiseUV]}" "#{file_node}.noiseUV";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:vertexUvOne]}" "#{file_node}.vertexUvOne";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:vertexUvTwo]}" "#{file_node}.vertexUvTwo";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:vertexUvThree]}" "#{file_node}.vertexUvThree";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:vertexCameraOne]}" "#{file_node}.vertexCameraOne";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:outUV]}" "#{file_node}.uvCoord";)
    io.puts %(connectAttr "#{p2d_node}.#{ATTRS[:place2d][:outUvFilterSize]}" "#{file_node}.uvFilterSize";)

    io.puts %(connectAttr "#{file_node}.#{ATTRS[:file][:outColor]}" "#{lam}.#{ATTRS[:lambert][:color]}";)
  else
    r,g,b,_a = color_rgba
    io.puts %(setAttr "#{lam}.#{ATTRS[:lambert][:color]}" -type "float3" #{fmt(r)} #{fmt(g)} #{fmt(b)};)
  end

  io.puts %(connectAttr "#{lam}.outColor" "#{sg}.#{ATTRS[:shadingEngine][:surfaceShader]}";)
  [lam, sg]
end

def write_scene(io, data)
  items     = data.is_a?(Array) ? data : [data]
  children  = collect_tree(items)
  root      = items.find { |it| it['word'] == 'ROOT' } || items.first
  write_header(io)

  stack = [root]
  until stack.empty?
    node = stack.shift
    name = safe_name(node['name'], node['word'] == 'ROOT' ? 'Root' : 'Node')
    mat  = node.dig('data','matrix') || [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

    if node['word'] == 'ROOT' || node['word'] == 'FRAM'
      write_transform(io, name, mat)
      (children[node['index']] || []).each do |ch|
        stack << ch
        if ch['word'] == 'FRAM'
          child_name = safe_name(ch['name'], 'Node')
          io.puts %(parent -relative -shape -world "#{child_name}" "#{name}";)
        end
      end
      next
    end

    if node['word'] == 'MESH'
      parent_name = safe_name(items.find { |it| it['index'] == node['parent_iid'] }&.dig('name'), 'Root')
      parent_name = 'Root' if parent_name.empty?

      d    = node['data'] || {}
      vbuf = d['vbuf'] || []
      ibuf = (d['ibuf'] || []).flatten
      tris = ibuf.each_slice(3).to_a
      pos  = vbuf.map { |v| [v[0].to_f, v[1].to_f, v[2].to_f] }
      uv   =
        if USE_UV_FROM_VBUF && vbuf.first && vbuf.first.size >= 8
          vbuf.map { |v| [v[-2].to_f, v[-1].to_f] }
        else
          (d['uvpt'] || Array.new(pos.length, [0.0,0.0])).map { |u| [u[0].to_f, u[1].to_f] }
        end

      mats = d['materials'] || []
      mats = [ { 'name'=>DEFAULT_MAT_NAME, 'red'=>1, 'green'=>1, 'blue'=>1, 'alpha'=>1 } ] if mats.empty?
      mat0 = mats.first
      rgba = [
        (mat0['red']||DEFAULT_COLOR[0]).to_f,
        (mat0['green']||DEFAULT_COLOR[1]).to_f,
        (mat0['blue']||DEFAULT_COLOR[2]).to_f,
        (mat0['alpha']||DEFAULT_COLOR[3]).to_f
      ]
      tex  = texture_name(mat0)
      base_mat_name = safe_name(mat0['name'], 'Mat')
      write_lambert_with_file(io, base_mat_name, rgba, tex)
      mesh_name = safe_name(node['name'], 'Mesh')
      io.puts %(createNode transform -name "#{mesh_name}" -parent "#{parent_name}";)
      io.puts %(setAttr "#{mesh_name}.#{ATTRS[:transform][:visibility]}" yes;)
      write_mesh_node(io, mesh_name, mesh_name, pos, tris, uv, base_mat_name)
    end
  end
end

def main(inp, outp)
  data = JSON.parse(File.read(inp))
  File.open(outp, 'w:utf-8') { |io| write_scene(io, data) }
end

if __FILE__ == $0
  if ARGV.length != 2
    warn "Usage: ruby #{File.basename($0)} input.json output.ma"
    exit 1
  end
  main(ARGV[0], ARGV[1])
end
