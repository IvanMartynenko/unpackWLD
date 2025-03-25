class SystemFolderManager
  attr_reader :paths, :files

  def initialize(filepath)
    if File.directory?(filepath)
      @unpack_dir = filepath
      @filename = "#{File.split(filepath).last.gsub(/_unpack$/, '')}.wld"
    else
      @filename = File.basename(filepath)
      filename_without_ext = File.basename(filepath, File.extname(filepath))
      @unpack_dir = "#{filename_without_ext}_unpack"
    end

    @paths = {
      base: @unpack_dir,
      output: create_filepath('output'),
      pack: create_filepath('pack'),
      texture_pages: create_filepath('pack/texture_pages'),
      models: create_filepath('pack/models'),
      texture_files: create_filepath('output/texture_files'),
      single_texture_files: create_filepath('output/texture_files/single'),
      multiply_texture_files: create_filepath('output/texture_files/multiply')
    }

    @files = {
      model_list_tree: create_filepath('pack/model_list_tree.yml'),
      object_list_tree: create_filepath('pack/object_list_tree.yml'),
      texture_pages: create_filepath('pack/texture_pages.yml'),
      object_list: create_filepath('pack/object_list.bin'),
      macro_list: create_filepath('pack/macro_list.bin'),
      world_tree: create_filepath('pack/world_tree.bin'),
      models_info: create_filepath('pack/models_info.yml')
    }
  end

  def create_directories
    # Create the nested directories
    @paths.each_value do |value|
      FileUtils.mkdir_p(value)
      puts "Directories '#{value}' created successfully."
    end
  rescue StandardError => e
    puts "An error occurred: #{e.message}"
    exit 1
  end

  def texture_page_path(index)
    name = "#{index}.dds"
    File.join(@paths[:texture_pages], name)
  end

  def model_path(name, index, parent_folder_id)
    fullname = "#{name}_#{index}.yml"
    File.join(@models_tree[parent_folder_id - 1], fullname)
  end

  def pack_file_path
    File.join(@paths[:base], @filename)
  end

  def push_model_directories(yaml)
    @models_tree = convert_folder(yaml)
  end

  def create_model_directories
    @models_tree.each do |value|
      FileUtils.mkdir_p(value)
      puts "Directories '#{value}' created successfully."
    end
  end

  private

  def create_filepath(path)
    path.split('/').reduce(@unpack_dir) { |accumulator, element| File.join(accumulator, element) }
  end

  def convert_folder(yaml)
    res = [@paths[:models]]
    res += yaml.map do |a|
      path = @paths[:models]
      tree = [a[:name]]
      while a[:parent] != 1
        a = yaml[a[:parent] - 2]
        tree.push(a[:name])
      end
      tree.reverse.each do |item|
        path = File.join(path, item)
      end
      path
    end
    res
  end
end
