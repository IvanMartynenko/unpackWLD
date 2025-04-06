require_relative 'base'
require_relative 'info/info'

WORLD_FIELDS = {
  base: [
    { key: :parent_id, type: :int },
    { key: :folder_name, type: :name },
    { key: :x, type: :float },
    { key: :y, type: :float },
    { key: :z, type: :float },
    { key: :w, type: :float },
    { key: :n, type: :float },
    { key: :u, type: :float },
    { key: :unknown1, type: :int },
    { key: :type, type: :int }
  ]
}.freeze

module Wld
  module Items
    class WorldItems < Base
      def initialize(file_or_hash, marker = 'TREE')
        @separator = 'NODE'
        super
      end

      protected

      def unpack_node(file, index)
        file.skip # skip value 15
        item = file.read WORLD_FIELDS[:base]
        item[:index] = index + 2
        unpack_by_type(file, item)

        item
      end

      def pack_node(node)
        accumulator = BinaryDataBuffer.new
        accumulator.push_int 15
        accumulator.add WORLD_FIELDS[:base], node
        accumulator.concat pack_by_type(node)

        accumulator.data
      end

      def unpack_by_type(file, item)
        case item[:type]
        when 0
          file.ints(4) # skip 4 zero int
        when 1
          unpack_model(file, item)
        when 2
          unpack_object(file, item)
        when 3
          unpack_light(file, item)
        end
      end

      def pack_by_type(item)
        accumulator = BinaryDataBuffer.new

        case item[:type]
        when 0
          accumulator.push_ints [0, 0, 0, 0] # skip 4 zero int
        when 1
          accumulator.concat pack_model(item)
        when 2
          accumulator.concat pack_object(item)
        when 3
          accumulator.concat pack_light(item)
        end

        accumulator.data
      end

      def unpack_model(file, item)
        item[:model_id] = file.int
        item[:model_name] = nil
        connections_count = file.int
        if connections_count.positive?
          item[:connections] = connections_count.times.map do |_|
            [file.int, file.int]
          end
        end
        file.int # skip zero
        shad = file.word
        item[:shad] = unpack_shadows(file) if shad == 'SHAD'
      end

      def pack_model(item)
        accumulator = BinaryDataBuffer.new

        accumulator.push_int item[:model_id]
        if item[:connections]
          accumulator.push_int item[:connections].size
          item[:connections].each do |conn|
            accumulator.push_ints conn
          end
        else
          accumulator.push_zero
        end
        accumulator.push_zero # skip zero
        if item[:shad]
          accumulator.concat pack_shadows(item[:shad])
        else
          accumulator.push_zero # skip zero
        end

        accumulator.data
      end

      def unpack_shadows(file)
        shad = {}
        shad[:size1] = file.int
        shad[:size2] = file.int

        additional_offset = shad[:size1].odd? && shad[:size2].odd? ? 1 : 0
        size = (shad[:size1] * shad[:size2] / 2) + additional_offset
        shad[:data] = file.floats(size)
        shad
      end

      def pack_shadows(shad)
        accumulator = BinaryDataBuffer.new

        accumulator.push_word 'SHAD'
        accumulator.push_int shad[:size1]
        accumulator.push_int shad[:size2]
        accumulator.push_floats shad[:data]

        accumulator.data
      end

      def unpack_object(file, item)
        item[:object_id] = file.int
        item[:object_name] = nil
        item[:item] = {}
        item[:item][:unknown_zero] = file.int
        if file.word == 'INFO'
          file.back
          item[:item][:info] = Info::Info.new(file).to_hash
        end
        item[:item][:unknown_zero2] = file.int
      end

      def pack_object(item)
        accumulator = BinaryDataBuffer.new

        accumulator.push_int item[:object_id]
        accumulator.push_int item[:item][:unknown_zero]
        if item[:item][:info]
          accumulator.concat Info::Info.new(item[:item][:info]).to_binary
        else
          accumulator.push_zero
        end
        accumulator.push_int item[:item][:unknown_zero2]

        accumulator.data
      end

      def unpack_light(file, item)
        item[:light] = {}
        item[:light][:unknown1] = file.int
        item[:light][:unknown_floats11] = file.floats(11)
        item[:light][:unknown2] = file.int
        item[:light][:unknown_floats13] = file.floats(13)
        item[:light][:unknown3] = file.ints(4)
      end

      def pack_light(item)
        accumulator = BinaryDataBuffer.new

        accumulator.push_int item[:light][:unknown1]
        accumulator.push_floats item[:light][:unknown_floats11]
        accumulator.push_int item[:light][:unknown2]
        accumulator.push_floats item[:light][:unknown_floats13]
        accumulator.push_ints item[:light][:unknown3]

        accumulator.data
      end
    end
  end
end
