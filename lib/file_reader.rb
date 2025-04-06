class FileReader
  def initialize(filepath)
    @file = File.binread(filepath)
    raise StandardError, 'Can not open file' unless @file

    @offset = 0
  end

  def name
    null_index = @file.index("\0", @offset)
    raise StandardError, 'Null terminator not found' if null_index.nil?

    name_bytes = @file[@offset...null_index]
    @offset = null_index + 1
    # Align the offset to the next 4-byte boundary
    remainder = @offset % 4
    @offset += (4 - remainder) unless remainder.zero?
    name_bytes.force_encoding('Windows-1252').encode('UTF-8')
  end

  alias filename name

  def word
    read_raw_bytes(1).to_s
  end

  def floats(size)
    # Read all bytes at once (each float is 4 bytes by default)
    bytes = read_raw_bytes(size)
    values = bytes.unpack('e*')
    values.each_with_index.map do |value, i|
      value.nan? ? bytes[i * 4, 4].unpack1('H*') : value
    end
  end

  def ints(size)
    read_raw_bytes(size).unpack('i*')
  end

  def ints16(size)
    read_raw_bytes(size, 2).unpack('v*')
  end

  def bigendian_ints(size)
    read_raw_bytes(size).unpack('N*')
  end

  def hex(size)
    read_raw_bytes(size, 1).unpack('H*')
  end

  def raw(size)
    read_raw_bytes(size, 1)
  end

  def float
    bytes = read_raw_bytes(1)
    value = bytes.unpack1('e')
    value.nan? ? bytes[0, 4].unpack1('H*') : value
  end

  def int
    read_raw_bytes(1).unpack1('i')
  end

  def int16
    read_raw_bytes(1, 2).unpack1('v')
  end

  def bigendian_int
    read_raw_bytes(1).unpack1('N')
  end

  def bool
    int == -1
  end

  def token
    val = word
    skip
    val
  end

  def token_with_size
    [word, bigendian_int]
  end

  def eof?
    @offset >= @file.size
  end

  def skip
    @offset += 4
  end

  def back
    @offset -= 4
  end

  def next(size)
    @offset += size
  end

  def current
    @offset
  end

  def set_position(offset)
    @offset = offset
  end


  def current_size
    (@file.size - @offset) / 4
  end

  def read(params, exists_item = nil)
    item = exists_item || {}
    params.each do |field|
      item[field[:key]] = send(field[:type])
    end
    item
  end

  private

  def read_raw_bytes(count, data_size = 4)
    size = count * data_size
    start_pos = @offset
    @offset += size
    @file[start_pos, size]
  end
end
