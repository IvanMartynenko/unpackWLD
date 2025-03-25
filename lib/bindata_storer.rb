class BindataStorer
  def initialize
    @data = []
  end

  # data_to_write.push([0x54585047].pack('N')) # TXPG
  def push_name(string)
    name = "#{string.encode('Windows-1252')}\0"
    name += "\0" while name.size % 4 != 0
    res = [name.bytes.map { |byte| byte.to_s(16).rjust(2, '0') }.join].pack('H*')
    @data.push res
  end

  def push_int(value)
    @data.push [value].pack('V')
  end

  def push_ints(values)
    values.each { |v| push_int(v) }
  end

  def push_float(value)
    if value.is_a? String
      @data.push [value].pack('H*')
    else
      @data.push [value].pack('e')
    end
    # @data.push [value].pack('e')
    # @data.push [value].pack('H*')
  end

  def push_floats(values)
    values.each { |v| push_float(v) }
    # @data.push [value].pack('e')
  end

  def push_word(value)
    @data.push value
  end

  def push_negative_bool(value)
    if value
      @data.push [-1].pack('V')
    else
      @data.push [0].pack('V')
    end
  end

  def push_bigendian_int(value)
    @data.push [value].pack('N')
  end

  def push_size(value)
    push_bigendian_int(value)
  end

  def push_int16(value)
    @data.push [value].pack('s<')
  end

  def push_ints16(values)
    values.each { |v| push_int16(v) }
  end

  def push_bool(value)
    push_int(value ? 1 : 0)
  end

  def push(value)
    @data.push value
  end

  def data
    @data.flatten.join
  end
end
