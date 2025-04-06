class BinaryDataBuffer
  class << self
    def pack_item_no_size(marker:, data:)
      accumulator = new
      accumulator.push_word marker
      accumulator.push_int 0
      accumulator.concat data
      accumulator.push_word 'END '
      accumulator.push_int 0

      accumulator.data
    end

    def pack_item_with_size(marker:, data:)
      accumulator = new
      accumulator.push_word marker
      accumulator.push_size data.size
      accumulator.concat data
      accumulator.data
    end
  end

  def initialize
    @data = []
  end

  def push_name(string)
    name = "#{string.encode('Windows-1252')}\0"
    name += "\0" while name.size % 4 != 0
    res = [name.bytes.map { |byte| byte.to_s(16).rjust(2, '0') }.join].pack('H*')
    @data.push res
  end

  def push_token_with_zero(name)
    push_word name
    push_zero
  end

  def push_end_token
    push_end_word
    push_zero
  end

  def push_int(value)
    @data.push [value].pack('i')
  end

  def push_ints(values)
    values.each { |v| push_int(v) }
  end

  def push_float(value)
    if value.is_a? Array
      raise StandardError, 'bad size of float' if value.size > 1

      return push_float(value.first)
    end

    v = if value.is_a? String
          [value].pack('H*')
        else
          [value].pack('e')
        end
    @data.push v
  end

  def push_floats(values)
    values.each { |v| push_float(v) }
  end

  def push_word(value)
    @data.push value
  end

  def push_bool(value)
    v = if value
          [-1].pack('i')
        else
          [0].pack('i')
        end
    @data.push v
  end

  def push_negative_bool(value)
    push_bool value
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

  def push(value)
    @data.push  value
  end

  def push_end_word
    @data.push  [0x454E4420].pack('N')
  end

  def push_eof_word
    @data.push  [0x454F4620].pack('N')
  end

  def push_zero
    @data.push [0].pack('i')
  end

  def data
    @data.flatten.join
  end

  def concat(new_data)
    if new_data.is_a?(Array)
      @data.concat new_data
    else
      @data.push new_data
    end
  end

  def add(types_array, object)
    types_array.each do |field|
      send("push_#{field[:type]}", object[field[:key]])
    end
  end
end
