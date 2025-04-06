require_relative 'base'
require_relative 'info/info'

OBJECT_FIELDS = {
  base: [
    { key: :type,          type: :int },
    { key: :name,          type: :name },
    { key: :parent_folder, type: :int }
  ],
  animation: [
    { key: :name, type: :name },
    { key: :unknown1,          type: :int   },
    { key: :unknown2,          type: :float },
    { key: :unknown3,          type: :float },
    { key: :unknown4,          type: :int   },
    { key: :alway_negative100, type: :float },
    { key: :unknown5,          type: :bool  },
    { key: :unknown6,          type: :bool  }
  ],
  animation_unknown: [
    { key: :name, type: :name },
    { key: :unknown1, type: :float }

  ]
}.freeze

module Wld
  module Items
    class Objects < Base
      def initialize(file_or_hash, marker = 'OBJS')
        @separator = 'OBJ '
        super
      end

      protected

      def unpack_node(file, index)
        item = { index: index + 1 }

        file.read OBJECT_FIELDS[:base], item
        item[:animations] = unpack_animations(file)
        item[:info] = Info::Info.new(file).to_hash

        item
      end

      def pack_node(node)
        bindata = BinaryDataBuffer.new
        bindata.add OBJECT_FIELDS[:base], node
        bindata.concat pack_animations(node[:animations])
        bindata.concat Info::Info.new(node[:info]).to_binary

        bindata.data
      end

      def unpack_animations(file)
        count_of_animations = file.int
        count_of_animations.times.map do
          animation_item = {}
          file.read OBJECT_FIELDS[:animation], animation_item
          count_of_unknown7 = file.int
          animation_item[:unknown7] = count_of_unknown7.times.map do
            file.read OBJECT_FIELDS[:animation_unknown]
          end
          animation_item
        end
      end

      def pack_animations(animations)
        bindata = BinaryDataBuffer.new

        bindata.push_int animations.size
        animations.each do |animation_item|
          bindata.add OBJECT_FIELDS[:animation], animation_item
          bindata.push_int animation_item[:unknown7].size
          animation_item[:unknown7].each do |unknown|
            bindata.add OBJECT_FIELDS[:animation_unknown], unknown
          end
        end
        bindata.data
      end
    end
  end
end
