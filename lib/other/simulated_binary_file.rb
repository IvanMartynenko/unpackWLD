class SimulatedBinaryFile
  attr_reader :data, :offset

  class << self
    def from_data(data)
      new(data)
    end
  end

  def initialize(data)
    @data = data
    @offset = 0
  end

  def read_name
    res = ''
    loop do
      word = read_word
      res += word
      break if word.include? "\0"
    end
    res.strip.force_encoding('Windows-1252').encode('UTF-8')
  end

  def read_raw(size)
    read_raw_bytes(size, 1)
  end

  def read_word
    read_raw_bytes(1).to_s
  end

  def read_floats(size)
    read_raw_bytes(size).unpack('e*')
  end

  def read_ints(size)
    read_raw_bytes(size).unpack('i<*')
  end

  def read_ints16(size)
    read_raw_bytes(size, 2).unpack('s*')
  end

  def read_unsigned_ints_big_endians(size)
    read_raw_bytes(size).unpack('N*')
  end

  def read_4hex(size)
    read_raw_bytes(size).unpack('H*')
  end

  def read_hex(size)
    read_raw_bytes(size, 1)
  end

  def read_float
    read_floats(1).first
  end

  def read_int
    read_ints(1).first
  end

  def read_int16
    read_ints16(1).first
  end

  def read_unsigned_int_big_endians
    read_unsigned_ints_big_endians(1).first
  end

  def read_boolean
    read_int == 1
  end

  def read_negative_bool
    read_int == 4_294_967_295
  end

  def end?
    (@data.size - @offset).zero?
  end

  def current_size
    (@data.size - @offset) / 4
  end

  def size
    @data.size
  end

  def back
    @offset -= 4
  end

  def read_by_task_type(task_id, index)
    type = read_int
    case type
    when 2
      read_floats(3)
    when 3
      read_float
    when 4
      read_int
    when 5
      read_int # 0,1,2
    when 6
      read_name
    when 7
      read_word
      read_ints(4)
    when 8
      read_int # 0,1,2
    when 9
      read_int
    when 10
      read_int # InvItem
    when 12
      read_name
    when 15
      read_hex(9*4).unpack("H*").first
    when 16
      read_name
    else
      puts "Error. Unknow type: #{type}. TaskId: #{task_id}. Params number: #{index + 1}"
      exit 0
    end
  end

  private

  def read_raw_bytes(count, data_size = 4)
    size = count * data_size
    return '' if size.zero?

    raise StandardError, 'bed end of file' if @offset + size > @data.size

    res = @data[@offset..@offset + size - 1]
    @offset += size
    res
  end
end
