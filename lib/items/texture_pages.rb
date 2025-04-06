require_relative 'base'

TEXTURE_PAGE_FIELDS = {
  base: [
    { key: :width, type: :int },
    { key: :height, type: :int },
    { key: :id, type: :int }
  ],
  box: [
    { key: :x0, type: :int },
    { key: :y0, type: :int },
    { key: :x2, type: :int },
    { key: :y2, type: :int }
  ]
}.freeze

module Wld
  module Items
    class TexturePages < Base
      def initialize(file_or_hash, marker = 'TEXP')
        @separator = 'PAGE'
        super
      end

      protected

      def unpack_node(file, _index)
        file.skip # always 2, skip
        page = file.read TEXTURE_PAGE_FIELDS[:base]
        textures_count = file.int
        page[:textures] = textures_count.times.map { unpack_texture(file) }

        token = file.word
        raise StandardError, "Not found TXPG separator (got '#{token}')" unless token == 'TXPG'

        page[:is_alpha] = file.bool
        page[:image_binary] = file.hex(page[:width] * page[:height] * 2) # the dds image binary data

        page
      end

      def pack_node(info)
        accumulator = BinaryDataBuffer.new

        accumulator.push_int 2
        accumulator.add TEXTURE_PAGE_FIELDS[:base], info
        accumulator.push_int info[:textures].size
        accumulator.concat pack_texture_list(info[:textures])
        accumulator.push_word('TXPG')
        accumulator.push_bool(info[:is_alpha])
        accumulator.concat info[:image_binary]

        accumulator.data
      end

      def unpack_texture(file)
        {
          filepath: file.filename,
          box: file.read(TEXTURE_PAGE_FIELDS[:box]),
          source_box: file.read(TEXTURE_PAGE_FIELDS[:box])
        }
      end

      def pack_texture_list(textures)
        accumulator = BinaryDataBuffer.new
        textures.each do |texture|
          accumulator.push_name texture[:filepath]
          accumulator.add TEXTURE_PAGE_FIELDS[:box], texture[:box]
          accumulator.add TEXTURE_PAGE_FIELDS[:box], texture[:source_box]
        end
        accumulator.data
      end
    end
  end
end
