require 'yaml'
require 'fileutils'
require_relative '../lib/system_folder_manager'

GLOBAL_EXT = '.tif'

def deep_stringify_keys(hash)
  if hash.is_a?(Hash)
    hash.each_with_object({}) do |(key, value), result|
      new_key = key.is_a?(Symbol) ? key.to_s : key
      result[new_key] = value.is_a?(Array) ? value.map { |t| deep_stringify_keys(t) } : deep_stringify_keys(value)
    end
  elsif hash.is_a?(Array)
    hash.map { |v| deep_stringify_keys(v) }
  else
    hash
  end
end

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

def normalize_filepath_without_ext(path)
  ext = File.extname(path)
  filename = path.split('\\').last
  filename.gsub!(/ß/, 'b')
  filename.gsub!(/ä/, 'a')
  filename.gsub!(/ö/, 'o')
  filename.gsub!(/ü/, 'u')
  filename.gsub!(/ÿ/, 'y')
  filename_without_ext = File.basename(filename, ext)

  base = 'C:\\TheSting\\textures'
  base += '\\NEW_TEXTURES' if path.downcase.include? '\\NEW_TEXTURES\\'.downcase
  "#{base}\\#{filename_without_ext}"
end

filepath = ARGV[0]
exit 0 if filepath.nil?

folder_manager = SystemFolderManager.new(filepath)
model_list_tree = deep_symbolize_keys(YAML.load_file(folder_manager.files[:model_list_tree]))
folder_manager.push_model_directories(model_list_tree)
# Load YAML file
data = deep_symbolize_keys YAML.load_file(folder_manager.files[:texture_pages])
data = data.sort_by { |t| t[:index] }

images = []
data.each_with_index do |page, page_index|
  page[:textures].each_with_index do |info, texture_index|
    exists = images.select { |i| info[:filepath] == i[:filepath] }.first
    if exists
      img = exists[:items].select { |i| [info[:box], info[:source_box]] == [i[:box], i[:source_box]] }.first
      if img
        img[:texture_index].push([page_index, texture_index])
        img[:pages_index].push(page[:index])
      else
        exists[:items].push({
                              box: info[:box],
                              source_box: info[:source_box],
                              page_width: page[:width],
                              page_height: page[:height],
                              is_alpha: page[:is_alpha],
                              texture_index: [[page_index, texture_index]],
                              pages_index: [page[:index]]
                            })
      end
    else
      images.push({
                    filepath: info[:filepath],
                    new_filepath: normalize_filepath_without_ext(info[:filepath]),
                    items: [
                      {
                        box: info[:box],
                        source_box: info[:source_box],
                        page_width: page[:width],
                        page_height: page[:height],
                        is_alpha: page[:is_alpha],
                        texture_index: [[page_index, texture_index]],
                        pages_index: [page[:index]]
                      }
                    ]
                  })
    end
  end
end

images.each do |image|
  if image[:items].size == 1
    item = image[:items].first
    item[:texture_index].each do |p|
      data[p[0]][:textures][p[1]][:filepath] = image[:new_filepath] + GLOBAL_EXT
    end
  else
    image[:items].each do  |item|
      filename_without_ext = image[:new_filepath]
      unless image[:new_filepath].include? '\\NEW_TEXTURES\\'
        item[:pages_index].each do |i|
          filename_without_ext += "__#{i}"
        end
      end
      item[:texture_index].each do |p|
        data[p[0]][:textures][p[1]][:filepath] = filename_without_ext + GLOBAL_EXT
      end
    end
  end
end

# data.each_with_index do |page, _page_index|
#   page[:textures].each_with_index do |info, _texture_index|
#     info[:source_box][:x0] = 0
#     info[:source_box][:y0] = 0
#     info[:source_box][:x2] = info[:box][:x2] - info[:box][:x0]
#     info[:source_box][:y2] = info[:box][:y2] - info[:box][:y0]
#   end
# end

models_info = deep_symbolize_keys YAML.load_file(folder_manager.files[:models_info])
models_info.each do |info|
  model_file = deep_symbolize_keys YAML.load_file(folder_manager.model_path(info[:name], info[:index],
                                                                            info[:parent_folder]))
  model_file.each do |word|
    next if word[:word] != 'MESH'

    word[:data][:materials].each do |mt|
      mt[:text][:name] = normalize_filepath_without_ext(mt[:text][:name]) + GLOBAL_EXT if mt[:text]
      next unless mt[:texture]

      page_index = mt[:texture][:texture_page]
      texture_index = mt[:texture][:index_texture_on_page]
      page = data.select { |t| t[:index] == page_index }.first
      tx = page[:textures][texture_index]
      mt[:texture][:name] = tx[:filepath]
    end
  end

  file = File.open(folder_manager.model_path(info[:name], info[:index],
                                             info[:parent_folder]), 'w')
  if file
    file.write(deep_stringify_keys(model_file).to_yaml)
    file.close
  end
end

file = File.open(folder_manager.files[:texture_pages], 'w')
if file
  file.write(deep_stringify_keys(data).to_yaml)
  file.close
end
