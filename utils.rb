DDS_MAGIC = 0x20534444

def create_directories(filepath, system_paths)
  directory_path = "#{File.dirname(filepath)}/#{File.basename(filepath, File.extname(filepath))}_unpack"
  # Create the nested directories

  system_paths.each do |key, value|
    system_paths[key] = "#{directory_path}/#{system_paths[key]}"
    FileUtils.mkdir_p(system_paths[key])
    puts "Directories '#{system_paths[key]}' created successfully."
  end
rescue StandardError => e
  puts "An error occurred: #{e.message}"
  exit 1
end

def read_wld_file(filepath, items)
  file = File.open(filepath, 'rb')
  raise StandardError, 'Can not open file' unless file

  value = read_word_and_size(file)

  if value[:word] != 'WRLD'
    file.close
    raise StandardError, "Opened file is not a 'The Sting!' game file"
  end

  loop do
    value = read_word_and_size(file)
    word = value[:word]
    break if word == 'EOF'

    item = items[value[:word].to_sym]
    raise StandardError, "Unknow props: #{word}" unless item

    reading_wld_item(file, item)
  end

  file.close
end

def read_word_and_size(file)
  bytes = file.read(8)
  if bytes.size != 8
    file.close
    raise StandardError, 'Bad end of WLD file'
  end

  { word: bytes[0..3].to_s.strip, size: bytes[4..7].unpack1('NN') }
end

def reading_wld_item(file, item)
  value = read_word_and_size(file)

  while value[:word] == item[:separator]
    item[:items].push file.read(value[:size])
    value = read_word_and_size(file)
  end

  raise StandardError, "Not found END marker for: #{value[:word]}" if value[:word] != 'END'
end

# TEXTURES
def init_dds_header(width, height, is_alpha)
  header = {}
  header[:magic] = DDS_MAGIC
  header[:size] = 124
  header[:flags] = 4111
  header[:height] = height
  header[:width] = width
  header[:pitch_or_linear_size] = width * 2
  header[:depth] = 0
  header[:mip_map_count] = 1
  header[:reserved1] = Array.new(11, 0)

  header[:pixel_format] = {
    dw_size: 32,
    dw_flags: 65,
    dw_four_cc: 0,
    dw_rgb_bit_count: 16,
    dw_r_bit_mask: 31744,
    dw_g_bit_mask: 992,
    dw_b_bit_mask: 31,
    dw_a_bit_mask: is_alpha ? 32768 : 0
  }

  header[:caps] = 4096
  header[:caps2] = 0
  header[:caps3] = 0
  header[:caps4] = 0
  header[:reserved2] = 0
  
  header
end

def save_to_binary_file(header)
  # Prepare binary data
  binary_data = []
  binary_data << [header[:magic]].pack("L")
  binary_data << [header[:size]].pack("L")
  binary_data << [header[:flags]].pack("L")
  binary_data << [header[:height]].pack("L")
  binary_data << [header[:width]].pack("L")
  binary_data << [header[:pitch_or_linear_size]].pack("L")
  binary_data << [header[:depth]].pack("L")
  binary_data << [header[:mip_map_count]].pack("L")
  binary_data << header[:reserved1].pack("L*")

  pixel_format = header[:pixel_format]
  binary_data << [pixel_format[:dw_size]].pack("L")
  binary_data << [pixel_format[:dw_flags]].pack("L")
  binary_data << [pixel_format[:dw_four_cc]].pack("L")
  binary_data << [pixel_format[:dw_rgb_bit_count]].pack("L")
  binary_data << [pixel_format[:dw_r_bit_mask]].pack("L")
  binary_data << [pixel_format[:dw_g_bit_mask]].pack("L")
  binary_data << [pixel_format[:dw_b_bit_mask]].pack("L")
  binary_data << [pixel_format[:dw_a_bit_mask]].pack("L")

  binary_data << [header[:caps]].pack("L")
  binary_data << [header[:caps2]].pack("L")
  binary_data << [header[:caps3]].pack("L")
  binary_data << [header[:caps4]].pack("L")
  binary_data << [header[:reserved2]].pack("L")

  binary_data
end


def get_txpg_offset(data)
  (data.size/4).times.each do |i|
    return i if data[i..i+3].to_s.strip == 'TXPG'
  end
  return -1
end

def parse_textures(data, textures_count, texture_page_number)
  textures = []
  offset = 0
  textures_count.times.each do |_index|
    name = find_end_of_name(data, offset)
    offset = name[:offset]
    info = {
      filepath: name[:name],
      box: {
        x0: data[offset..offset + 3].unpack1('V'),
        y0: data[offset + 4..offset + 3 + 4].unpack1('V'),
        x2: data[offset + 8..offset + 3 + 8].unpack1('V'),
        y2: data[offset + 12..offset + 3 + 12].unpack1('V')
      },
      source_box: {
        x0: data[offset + 16..offset + 3 + 16].unpack1('V'),
        y0: data[offset + 20..offset + 3 + 20].unpack1('V'),
        x2: data[offset + 24..offset + 3 + 24].unpack1('V'),
        y2: data[offset + 28..offset + 3 + 28].unpack1('V')
      }
    }
    info[:width] = info[:box][:x2] - info[:box][:x0]
    info[:height] = info[:box][:y2] - info[:box][:y0]
    info[:name] = File.basename(info[:filepath].gsub('\\', '/'))
    info[:ext] = File.extname(info[:name].gsub('\\', '/'))
    info[:texture_page_number] = texture_page_number
    textures.push(info)
    offset += 32
  end
  textures
end

def find_end_of_name(data, offset = 0)
  j = offset
  word = []
  while true
    tmp = data[j].force_encoding('Windows-1252').encode('UTF-8')
    j += 1
    break if tmp == "\0"

    word.push tmp
  end
  j += 1 while j % 4 != 0

  { offset: j, name: word.join.strip }
end

def deep_stringify_keys(hash)
  return hash unless hash.is_a?(Hash)
  
  hash.each_with_object({}) do |(key, value), result|
    new_key = key.is_a?(Symbol) ? key.to_s : key
    result[new_key] = value.is_a?(Array) ? value.map {|t| deep_stringify_keys(t) } : deep_stringify_keys(value)
  end
end
