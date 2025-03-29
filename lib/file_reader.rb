class FileReader
  attr_reader :file

  def initialize(filepath)
    @file = File.open(filepath, 'rb')
    raise StandardError, 'Can not open file' unless @file
  end

  def name
    res = ''
    loop do
      tmp = word
      res += tmp
      break if tmp.include? "\0"
    end
    res.gsub(/\0/, '').force_encoding('Windows-1252').encode('UTF-8')
  end

  def filename
    res = ''
    loop do
      tmp = word
      res += tmp
      break if tmp.include? "\0"
    end
    res.gsub(/\0/, '').force_encoding('Windows-1252').encode('UTF-8')
  end

  def word
    read_raw_bytes(1).to_s
  end

  def floats(size)
    # read_raw_bytes(size).unpack('e*')
    # read_raw_bytes(size).unpack('H*')
    size.times.map do |_|
      v = read_raw_bytes(1)
      value = v.unpack1('e*')
      value.nan? ? v.unpack('H*') : value
    end
  end

  def ints(size)
    read_raw_bytes(size).unpack('V*')
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

  def float
    floats(1).first
  end

  def int
    ints(1).first
  end

  def int16
    ints16(1).first
  end

  def bigendian_int
    bigendian_ints(1).first
  end

  def bool
    int == 1
  end

  def negative_bool
    int == 4_294_967_295
    # 4294967295
  end

  def skip
    read_raw_bytes(1)
  end

  def token
    val = word
    skip
    val
  end

  def token_with_size
    [word, bigendian_int]
  end

  def close
    file.close
  end

  def eof?
    file.eof?
  end

  def back
    file.seek(-4, IO::SEEK_CUR)
  end

  def pos
    file.pos
  end

  private

  def read_raw_bytes(count, data_size = 4)
    size = count * data_size
    return '' if size.zero?

    file.read(size)
  end
end
