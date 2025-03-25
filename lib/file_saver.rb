class FileSaver
  attr_reader :file

  class << self
    def name_to_binary(string)
      name = string.encode('Windows-1252') + "\0"
      name += "\0" while name.size % 4 != 0
      [name.bytes.map { |byte| byte.to_s(16).rjust(2, '0') }.join].pack('H*')
    end
  end

  def initialize(filepath)
    @file = File.open(filepath, 'wb')
    raise StandardError, 'Can not open file' unless @file
  end

  def write(value)
    file.write value
  end

  def write_end_word
    file.write [0x454E4420].pack('N')
  end

  def write_eof_word
    file.write [0x454F4620].pack('N')
  end

  def write_zero
    file.write [0].pack('N')
  end

  def write_word(string)
    file.write string
  end

  def write_int(value)
    file.write [value].pack('V')
  end

  def write_bigendian_int(value)
    file.write [value].pack('N')
  end

  def write_size(value)
    write_bigendian_int(value)
  end

  def close
    file.close
  end

  def eof?
    file.eof?
  end
end
