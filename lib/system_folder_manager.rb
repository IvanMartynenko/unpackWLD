class SystemFolderManager
  attr_reader :paths, :files

  def initialize(filepath)
    if File.directory?(filepath)
      @unpack_dir = filepath
      @filename = "#{File.split(filepath).last.gsub(/_unpack$/, '')}.wld"
    else
      @filename = File.basename(filepath)
      filename_without_ext = File.basename(filepath, File.extname(filepath))
      @unpack_dir = File.join(File.dirname(filepath), "#{filename_without_ext}_unpack")
    end

    @paths = {
      base: @unpack_dir,
      output: create_filepath('output'),
      pack: create_filepath('pack'),
      texture_pages: create_filepath('pack/texture_pages'),
      models: create_filepath('pack/models'),
      texture_files: create_filepath('output/texture_files'),
      dds_texture_files: create_filepath('output/texture_files/dds'),
      tiff_texture_files: create_filepath('output/texture_files/tiff')
    }

    @files = {
      model_list_tree: create_filepath('pack/model_list_tree.json'),
      object_list_tree: create_filepath('pack/object_list_tree.json'),
      texture_pages: create_filepath('pack/texture_pages.json'),
      object_list: create_filepath('pack/object_list.json'),
      macro_list: create_filepath('pack/macro_list.bin'),
      world_tree: create_filepath('pack/world_tree.json'),
      models_info: create_filepath('pack/models_info.json'),
      shadows: create_filepath('pack/shadows.json'),
      world_view: create_filepath('world_view.json')
    }
  end

  def create_directories
    # Create the nested directories
    @paths.each_value do |value|
      FileUtils.mkdir_p(value)
      # puts "Directories '#{value}' created successfully."
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
    fullname = "#{name}_#{index}.json"
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
      # puts "Directories '#{value}' created successfully."
    end
  end

  def dds_texture_file(name)
    File.join(@paths[:dds_texture_files], name)
  end

  def tiff_texture_file(name)
    File.join(@paths[:tiff_texture_files], name)
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
      while a[:parent_iid] != 1
        a = yaml[a[:parent_iid] - 2]
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
