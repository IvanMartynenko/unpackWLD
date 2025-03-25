require 'yaml'

info = YAML.load_file 'VaBank_unpack/pack/models_info.yml'

# puts info.map { |t| t['name'] }.uniq - info.map { |t| t['name'] }
# puts info.map { |t| t['name'] }.size

puts info.group_by { |t| t['name'] }.select {|k,v| v.size != 1}.map {|k,v| k}
