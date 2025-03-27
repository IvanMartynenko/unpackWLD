require 'fileutils'
require 'yaml'
require_relative '../lib/system_folder_manager'

def deep_symbolize_keys(hash)
  if hash.is_a?(Hash)
    hash.each_with_object({}) do |(key, value), result|
      new_key = key.is_a?(Symbol) ? key : key.to_sym
      result[new_key] = value.is_a?(Array) ? value.map { |t| deep_symbolize_keys(t) } : deep_symbolize_keys(value)
    end
  elsif hash.is_a?(Array)
    hash.map { |v| deep_symbolize_keys(v) }
  else
    hash
  end
end

def pack(filepath)
  folder_manager = SystemFolderManager.new(filepath)
  model_list_tree = deep_symbolize_keys(YAML.load_file(folder_manager.files[:model_list_tree]))
  folder_manager.push_model_directories(model_list_tree)

  models_info = deep_symbolize_keys(YAML.load_file(folder_manager.files[:models_info]))

  # uniq_names = []
  # models_info.each do |info|
  #   model_file = deep_symbolize_keys YAML.load_file(folder_manager.model_path(info[:name], info[:index],
  #                                                                             info[:parent_folder]))
  #   materials = model_file.select { |t| t[:word] == 'MESH' }.flat_map { |t| t[:data][:materials] }.compact
  #   tmp_names = materials.map { |t| t[:texture] || t[:text] || nil }.compact
  #   names = tmp_names.map { |t| t[:name] }
  #   uniq_names.push names.uniq
  # end

  # uniq_names.flatten!
  # uniq_filenames = uniq_names.map { |t| File.basename(t).encode('Windows-1252') }
  # a = uniq_filenames.flat_map { |t| t.scan(/[^\x00-\x7F]/) }
  # puts a.sort.uniq.join.encode('utf-8')

  uniq_names = []
  models_info.each do |info|
    model_file = deep_symbolize_keys YAML.load_file(folder_manager.model_path(info[:name], info[:index],
                                                                              info[:parent_folder]))
    materials = model_file.select { |t| t[:word] == 'MESH' }.flat_map { |t| t[:data][:materials] }.compact
    tmp_names = materials.map { |t| t[:texture] || nil }.compact
    names = tmp_names.map { |t| t[:texture_page] }
    uniq_names.push names.uniq
  end

  uniq_names.flatten!
  # uniq_filenames = uniq_names.map { |t| File.basename(t).encode('Windows-1252') }
  # a = uniq_filenames.flat_map { |t| t.scan(/[^\x00-\x7F]/) }
  a = uniq_names.sort.uniq
  b = a.size.times.map { |i| i + 1}
  puts b - a 
  puts 'AAAAAAAAA'
  puts a - b
end

script_location = File.dirname(File.expand_path(__FILE__))
filepaths = Dir.glob(File.join(File.join(script_location, '..'), '*_unpack'))
filepaths.each do |f|
  pack(f)
end
