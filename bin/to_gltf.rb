#!/usr/bin/env ruby
# frozen_string_literal: true
require 'json'

# ---- ПОВЕДЕНЧЕСКИЕ ФЛАГИ (совместимы с твоими) ----
STRIP_TEX_PATHS   = true   # обрезать директории у путей
FORCE_PNG_EXT     = false  # .tif -> .png для image.uri
FLIP_V            = true   # инвертировать V
USE_UV_FROM_VBUF  = true   # брать UV из хвоста vbuf

DEFAULT_BASECOLOR = [1.0, 1.0, 1.0, 1.0]
DEFAULT_METALLIC  = 0.0
DEFAULT_ROUGHNESS = 0.9

# ---- УТИЛИТЫ ----
def fmt_f(x) = ('%.6f' % x.to_f).sub(/-0\.000000/, '0.000000').to_f

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

def transpose4x4(m) # row-major -> column-major
  [
    m[0][0], m[1][0], m[2][0], m[3][0],
    m[0][1], m[1][1], m[2][1], m[3][1],
    m[0][2], m[1][2], m[2][2], m[3][2],
    m[0][3], m[1][3], m[2][3], m[3][3]
  ].map { |v| v.to_f }
end

def default_matrix
  [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
end

def minmax_per_component(arr, comps)
  mins = Array.new(comps, Float::INFINITY)
  maxs = Array.new(comps, -Float::INFINITY)
  arr.each_slice(comps) do |t|
    comps.times do |i|
      v = t[i].to_f
      mins[i] = v if v < mins[i]
      maxs[i] = v if v > maxs[i]
    end
  end
  [mins, maxs]
end

def pad_to4!(bin)
  pad = (4 - (bin.bytesize % 4)) % 4
  bin << ("\x00" * pad) if pad != 0
end

# ---- СБОРКА glTF ----
class GltfBuilder
  attr_reader :gltf, :bin

  def initialize
    @bin  = ''.b
    @gltf = {
      'asset' => { 'version' => '2.0', 'generator' => 'ruby-gltf-converter' },
      'scenes' => [ { 'nodes' => [] } ],
      'nodes' => [],
      'meshes' => [],
      'buffers' => [],
      'bufferViews' => [],
      'accessors' => [],
      'materials' => [],
      'images' => [],
      'textures' => [],
      'samplers' => []
    }
    @sampler_idx = add_default_sampler
    @material_cache = {} # key by material hash -> index
    @image_cache = {}    # uri -> image index
    @texture_cache = {}  # image index -> texture index
  end

  def add_default_sampler
    @gltf['samplers'] << { 'magFilter'=>9729, 'minFilter'=>9987, 'wrapS'=>10497, 'wrapT'=>10497 }
    @gltf['samplers'].length - 1
  end

  def add_buffer(uri=nil)
    @gltf['buffers'] << { 'byteLength'=>0, 'uri'=>uri }.compact
    @gltf['buffers'].length - 1
  end

def push_blob(bytes, align = 4)
  # гарантируем, что следующий кусок начнётся с кратного 4 офсета
  pad = (@bin.bytesize % align)
  if pad != 0
    @bin << ("\x00" * (align - pad))
  end
  offset = @bin.bytesize
  @bin << bytes
  offset
end

def add_buffer_view(buffer_idx, byte_offset, byte_length, target=nil)
  bv = { 'buffer'=>buffer_idx, 'byteOffset'=>byte_offset, 'byteLength'=>byte_length }
  bv['target'] = target if target
  @gltf['bufferViews'] << bv
  @gltf['bufferViews'].length - 1
end

  def add_accessor(bv_idx, component_type, count, type_str, min_vals=nil, max_vals=nil, normalized=false)
    acc = {
      'bufferView'=>bv_idx,
      'componentType'=>component_type,
      'count'=>count,
      'type'=>type_str
    }
    acc['min'] = min_vals if min_vals
    acc['max'] = max_vals if max_vals
    acc['normalized'] = true if normalized
    @gltf['accessors'] << acc
    @gltf['accessors'].length - 1
  end

  def ensure_image(uri)
    return @image_cache[uri] if @image_cache.key?(uri)
    @gltf['images'] << { 'uri'=>uri }
    idx = @gltf['images'].length - 1
    @image_cache[uri] = idx
    idx
  end

  def ensure_texture_for_image(img_idx)
    return @texture_cache[img_idx] if @texture_cache.key?(img_idx)
    @gltf['textures'] << { 'sampler'=>@sampler_idx, 'source'=>img_idx }
    idx = @gltf['textures'].length - 1
    @texture_cache[img_idx] = idx
    idx
  end

  def ensure_material(mat_hash)
    # mat_hash: {baseColor:[r,g,b,a], tex_uri:nil|str, metallic, roughness}
    key = mat_hash.to_a.sort_by(&:first)
    return @material_cache[key] if @material_cache.key?(key)

    pbr = {
      'baseColorFactor' => mat_hash[:baseColor],
      'metallicFactor'  => mat_hash[:metallic],
      'roughnessFactor' => mat_hash[:roughness]
    }
    if mat_hash[:tex_uri]
      img_idx = ensure_image(mat_hash[:tex_uri])
      tex_idx = ensure_texture_for_image(img_idx)
      pbr['baseColorTexture'] = { 'index'=>tex_idx }
    end
    @gltf['materials'] << { 'pbrMetallicRoughness'=>pbr, 'alphaMode'=>'OPAQUE' }
    idx = @gltf['materials'].length - 1
    @material_cache[key] = idx
    idx
  end

  def add_mesh_primitive(positions, indices, normals=nil, uvs=nil, material_idx=nil)
    # choose index component type
    max_idx = indices.max || 0
    idx_type = (max_idx < 65536) ? 5123 : 5125 # UNSIGNED_SHORT / UNSIGNED_INT
    pack_code = (idx_type == 5123) ? 'S<' : 'L<'
    idx_bytes = indices.pack(pack_code*indices.length)
    idx_offset = push_blob(idx_bytes)
    idx_bv = add_buffer_view(0, idx_offset, idx_bytes.bytesize, 34963) # ELEMENT_ARRAY_BUFFER
    idx_acc = add_accessor(idx_bv, idx_type, indices.length, 'SCALAR', [indices.min || 0], [max_idx])

    # positions
    pos_bytes = positions.pack('e*') # little-endian float16? No; use 32-bit: 'e' is Float16 in Ruby 3.2+, safer 'e' not universal. Use 'e'?? Better 'e' is half. Use 'e' wrong.
  end
end

# ---- main build converted ----
# We’ll implement pack for Float32 safely across Ruby versions.
def pack_f32(arr)
  arr.pack('e*') # NOTE: On modern Ruby 'e' = little-endian float. If not supported, fallback:
rescue StandardError
  # portable: pack native then force little-endian per float
  arr.pack('f*').bytes.each_slice(4).map(&:reverse).flatten.pack('C*')
end

def build_gltf_from_items(items)
  builder = GltfBuilder.new
  # single external buffer
  buf_idx = builder.add_buffer('') # uri will be set by caller; byteLength filled later

  by_parent = collect_tree(items)
  root = items.find { |it| it['word']=='ROOT' } || items.first

  # maps for created nodes
  def add_frame_node_recursive(builder, node, by_parent)
    name = node['name'].to_s.strip
    name = 'Root' if name.empty?
    mat = node.dig('data','matrix') || default_matrix
    gltf_node = { 'name'=>name, 'matrix'=>transpose4x4(mat) }
    parent_idx = builder.gltf['nodes'].length
    builder.gltf['nodes'] << gltf_node

    # children
    kids = []
    (by_parent[node['index']] || []).each do |ch|
      case ch['word']
      when 'FRAM'
        child_idx = add_frame_node_recursive(builder, ch, by_parent)
        kids << child_idx
      when 'MESH'
        mesh_idx, mesh_node_idx = add_mesh_node(builder, ch)
        kids << mesh_node_idx
      end
    end
    gltf_node['children'] = kids unless kids.empty?
    parent_idx
  end

  def add_mesh_node(builder, mesh_node)
    d    = mesh_node['data'] || {}
    name = mesh_node['name'].to_s.empty? ? 'Mesh' : mesh_node['name']

    vbuf = d['vbuf'] || []
    tris = (d['ibuf'] || []).flatten.each_slice(3).to_a
    indices = tris.flatten

    pos = vbuf.map { |v| [v[0].to_f, v[1].to_f, v[2].to_f] }.flatten
    has_nrm = vbuf.first && vbuf.first.size >= 6
    nrm = has_nrm ? vbuf.map { |v| [v[3].to_f, v[4].to_f, v[5].to_f] }.flatten : nil

    uvs_raw =
      if USE_UV_FROM_VBUF && vbuf.first && vbuf.first.size >= 8
        vbuf.map { |v| [v[-2].to_f, v[-1].to_f] }
      else
        (d['uvpt'] || Array.new(vbuf.length, [0.0,0.0])).map { |uv| [uv[0].to_f, uv[1].to_f] }
      end
    if FLIP_V
      uvs_raw = uvs_raw.map { |u,v| [u, 1.0 - v] }
    end
    uvs = uvs_raw.flatten

    # material (берём первый, как делал твой .x-экспорт)
    mats = d['materials'] || []
    mats = [ { 'name'=>'DefaultWhite', 'red'=>1, 'green'=>1, 'blue'=>1, 'alpha'=>1 } ] if mats.empty?
    m0 = mats.first
    base = [
      (m0['red']   || 1.0).to_f,
      (m0['green'] || 1.0).to_f,
      (m0['blue']  || 1.0).to_f,
      (m0['alpha'] || 1.0).to_f
    ]
    tex_uri = texture_name(m0)
    mat_idx = builder.ensure_material(baseColor: base, tex_uri: tex_uri,
                                      metallic: DEFAULT_METALLIC, roughness: DEFAULT_ROUGHNESS)

    # ---- pack indices
    max_idx = indices.max || 0
idx_type   = (max_idx < 65536) ? 5123 : 5125
idx_bytes  = indices.pack(idx_type == 5123 ? 'S<*' : 'L<*')  # <-- фикс
idx_offset = builder.push_blob(idx_bytes)                     # уже выровнено
idx_bv     = builder.add_buffer_view(0, idx_offset, idx_bytes.bytesize, 34963)
idx_acc    = builder.add_accessor(idx_bv, idx_type, indices.length, 'SCALAR', [indices.min || 0], [max_idx])

    # ---- positions
    pos_bytes = pack_f32(pos)
    pos_offset = builder.push_blob(pos_bytes)
    pos_bv = builder.add_buffer_view(0, pos_offset, pos_bytes.bytesize, 34962) # ARRAY_BUFFER
    pmins, pmaxs = minmax_per_component(pos, 3)
    pos_acc = builder.add_accessor(pos_bv, 5126, pos.length/3, 'VEC3', pmins, pmaxs) # FLOAT

    # ---- normals
    nrm_acc = nil
    if nrm && !nrm.empty?
      nrm_bytes = pack_f32(nrm)
      nrm_offset = builder.push_blob(nrm_bytes)
      nrm_bv = builder.add_buffer_view(0, nrm_offset, nrm_bytes.bytesize, 34962)
      nmins, nmaxs = minmax_per_component(nrm, 3)
      nrm_acc = builder.add_accessor(nrm_bv, 5126, nrm.length/3, 'VEC3', nmins, nmaxs)
    end

    # ---- texcoords
    uv_acc = nil
    if uvs && !uvs.empty?
      uv_bytes = pack_f32(uvs)
      uv_offset = builder.push_blob(uv_bytes)
      uv_bv = builder.add_buffer_view(0, uv_offset, uv_bytes.bytesize, 34962)
      umins, umaxs = minmax_per_component(uvs, 2)
      uv_acc = builder.add_accessor(uv_bv, 5126, uvs.length/2, 'VEC2', umins, umaxs)
    end

    prim = { 'mode'=>4, 'indices'=>idx_acc, 'attributes'=>{ 'POSITION'=>pos_acc } } # TRIANGLES
    prim['attributes']['NORMAL'] = nrm_acc if nrm_acc
    prim['attributes']['TEXCOORD_0'] = uv_acc if uv_acc
    prim['material'] = mat_idx if mat_idx

    builder.gltf['meshes'] << { 'name'=>name, 'primitives'=>[prim] }
    mesh_index = builder.gltf['meshes'].length - 1

    # node that holds mesh (без собственной матрицы; наследует от кадра)
    node = { 'name'=>name, 'mesh'=>mesh_index }
    node_idx = builder.gltf['nodes'].length
    builder.gltf['nodes'] << node
    [mesh_index, node_idx]
  end

  root_idx = add_frame_node_recursive(builder, root, by_parent)
  builder.gltf['scenes'][0]['nodes'] << root_idx

  # finalize buffer
  pad_to4!(builder.bin)
  builder.gltf['buffers'][0]['byteLength'] = builder.bin.bytesize
  builder
end

def main(inp, outp)
  data = JSON.parse(File.read(inp))
  items = data.is_a?(Array) ? data : [data]

  builder = build_gltf_from_items(items)

  # write .bin
  bin_path = File.join(File.dirname(outp), File.basename(outp, File.extname(outp)) + '.bin')
  File.binwrite(bin_path, builder.bin)
  # set relative uri
  builder.gltf['buffers'][0]['uri'] = File.basename(bin_path)

  # write .gltf
  File.write(outp, JSON.pretty_generate(builder.gltf))
end

if ARGV.length != 2
  warn "Usage: ruby #{File.basename($0)} input.json output.gltf"
  exit 1
end
main(ARGV[0], ARGV[1])
