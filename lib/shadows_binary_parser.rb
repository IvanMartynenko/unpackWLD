require_relative 'file_reader'

class ShadowsBinaryParser
  def initialize(filepath)
    @file = FileReader.new(filepath)
  end

  def parse
    shadows = []

    until @file.eof?
      shadows << {
        index: @file.int,
        size1: s1 = @file.int,
        size2: s2 = @file.int,
        data: @file.floats(shadow_size(s1, s2))
      }
    end

    shadows
  end

  def shadow_size(size1, size2)
    additional_offset = size1.odd? && size2.odd? ? 1 : 0
    (size1 * size2 / 2) + additional_offset
  end
end
