require_relative 'base'

module Wld
  module Items
    class Makl < Base
      def initialize(file_or_hash, marker = 'MAKL')
        @separator = 'OBJ '
        super
      end

      protected

      def unpack_node(file, _index); end

      def pack_node; end
    end
  end
end
