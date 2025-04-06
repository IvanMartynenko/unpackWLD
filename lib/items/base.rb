require_relative '../binary_data_buffer'

module Wld
  module Items
    class Base
      def initialize(file_or_hash, marker)
        @binary = nil
        @nodes = []
        @marker = marker

        if file_or_hash.is_a?(Hash) || file_or_hash.is_a?(Array)
          @nodes = file_or_hash
          pack
        else
          unpack(file_or_hash)
        end
      end

      def to_binary
        pack if @binary.nil?

        @binary
      end

      def to_hash
        @nodes
      end

      protected

      def unpack(file)
        @token = file.token
        raise_token(@token, @marker) if @token != @marker

        @token, _entry_size = file.token_with_size
        return if @token == 'END '

        unpack_nodes(file)

        raise_token(@token) unless @token == 'END '
      end

      def unpack_nodes(file)
        index = 0
        while @token == @separator
          @nodes << unpack_node(file, index)
          index += 1
          @token, _entry_size = file.token_with_size
        end
      end

      def unpack_node(file)
        raise NotImplementedError, 'This method must be implemented in a subclass'
      end

      def pack
        @binary = BinaryDataBuffer.pack_item_no_size(marker: @marker, data: pack_nodes)
      end

      def pack_nodes
        @nodes.flat_map do |node|
          BinaryDataBuffer.pack_item_with_size marker: @separator, data: pack_node(node)
        end
      end

      def pack_node
        raise NotImplementedError, 'This method must be implemented in a subclass'
      end

      def raise_token(token, marker = 'END')
        raise TokenError.new(token, marker)
      end
    end

    class TokenError < StandardError
      attr_reader :error_message

      def initialize(token, expected_marker)
        @error_message = 'Unexpected token encountered in the game file. ' \
                         "Received '#{token}', but expected '#{expected_marker}'. " \
                         "Please check the file's format and token sequence for any discrepancies."
        super(error_message)
      end
    end
  end
end
