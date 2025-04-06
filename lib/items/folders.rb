require_relative 'base'

FOLDER_FIELDS = {
  base: [
    { key: :name, type: :name },
    { key: :parent_folder_id, type: :int }
  ]
}.freeze

module Wld
  module Items
    class Folders < Base
      def initialize(file_or_hash, marker)
        @separator = 'ENTR'
        super
      end

      protected

      def unpack_node(file, index)
        folder = { index: index + 2 }
        file.skip # always zero. skip
        file.read FOLDER_FIELDS[:base], folder
        folder
      end

      def pack_node(node)
        bindata = BinaryDataBuffer.new

        bindata.push_int 0
        bindata.add FOLDER_FIELDS[:base], node

        bindata.data
      end
    end
  end
end
