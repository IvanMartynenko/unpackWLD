require_relative '../../base'

module Wld
  module Items
    module Info
      module Task
        class Acod < Base
          def initialize(file_or_hash, marker = 'ACOD')
            @acod_list = []
            super
          end

          def unpack(file)
            token, _size = file.token_with_size
            raise_token(token, @marker) if token != @marker

            @nodes = file.ints(4)
          end

          def pack
            accumulator = BinaryDataBuffer.new
            tmp_accumulator = BinaryDataBuffer.new
            tmp_accumulator.push_ints(@nodes)

            accumulator.push @marker
            accumulator.push_size tmp_accumulator.data.size
            accumulator.concat tmp_accumulator.data
            @binary = accumulator.data
          end
        end
      end
    end
  end
end
