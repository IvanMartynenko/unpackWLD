require 'yaml'
require 'json'
require_relative '../lib/simulated_binary_file'

def get_connections(item)
  if item[:ground]
    if item[:ground][:connections]
      item[:ground][:connections].map { |c| c[1] == 0 ? c[0] : c }
    else
      []
    end
  else
    []
  end
end

def get_name(objects, item)
  path = []

  iterator = objects[item[:parent_iid].to_sym]

  while iterator[:parent_iid] != '1'
    path.push iterator[:folder_name][0..10]
    iterator = objects[iterator[:parent_iid].to_sym]
  end

  path.reverse.join('/') + "/#{item[:model_name]}"
end

objects = JSON.parse(File.read('VaBank_unpack/pack/world_tree.json'), symbolize_names: true)

res = {}
path = {}
objects.each do |k, v|
  if v[:parent_iid] == '1'
    res[k] = {}
    %i[folder_name object_name model_name].each do |new_k|
      res[k][:name] = v[new_k] if v[new_k]
    end
    res[k][:child] = {}
    path[k] = res[k]
    next
  end

  id = v[:parent_iid].to_sym
  path[id][:child][k] = {}
  %i[folder_name object_name model_name].each do |new_k|
    path[id][:child][k][:name] = v[new_k] if v[new_k]
  end
  path[id][:child][k][:child] = {}

  path[k] = path[id][:child][k]
end
# puts res
# res = { items: {}, connections: {} }
# objects.each do |key, item|
#   next if item[:type] != 1

#   res[:items][key] = get_name(objects, item)
#   connections = get_connections(item)
#   res[:connections][key] = connections if connections.size > 0
# end

file = File.open('tmp.json', 'w')
file&.write JSON.pretty_generate(res)
file.close
