require 'yaml'
require_relative '../lib/simulated_binary_file'

def convert_folder(yaml)
  yaml.map do |a|
    str = a['name']

    while a['parent_iid'] != 1
      a = yaml[a['parent_iid'] - 2]
      str = a['name'] + '/' + str
    end
    str
  end
end

objects = YAML.load_file('VaBank_unpack/pack/object_list.yml').select { |t| t['info'] }
@folders = convert_folder YAML.load_file('VaBank_unpack/pack/object_list_tree.yml')

objects = objects.uniq { |t| t['info']['tali'] }
objects = objects.map do |t|
  {
    name: @folders[t['parent_folder'] - 2] + '/' + t['name'],
    tali: t['info']['tali']['data'].pack("H*")
  }
end
objects = objects.sort_by { |t| t[:tali].size }

# objects.each do |object|
#   puts object[:cond].size
# end
index = 1
puts objects[index][:name]
puts objects[index][:tali][12..15].unpack1('e*')
puts objects[index][:tali].size
