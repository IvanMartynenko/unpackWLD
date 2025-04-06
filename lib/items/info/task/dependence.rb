require_relative '../../base'
require_relative 'acod'

module Wld
  module Items
    module Info
      module Task
        class Dependence < Base
          def initialize(file_or_hash, marker = 'DPND')
            @acod_list = []
            super
          end

          def unpack(file)
            token, _size = file.token_with_size
            raise_token(token, @marker) if token != @marker

            @nodes = {}
            @nodes[:unknown1] = file.int
            @nodes[:acod] = Acod.new(file).to_hash
            @nodes[:unknown2] = 4.times.map { |_| file.int }

            @task_list = List.new(file)
            @nodes[:tali] = @task_list.to_hash
            @nodes[:unknown3] = 9.times.map { |_| file.int }
            type = file.int
            @nodes[:type] = type
            @nodes[:unknown4] = file.ints(2) if type == 1
            @nodes[:unknown4] = file.ints(4) if type == 2
          end

          def pack
            bindata = BinaryDataBuffer.new
            tmp_bindata = BinaryDataBuffer.new

            tmp_bindata.push_int @nodes[:unknown1]
            tmp_bindata.concat Acod.new(@nodes[:acod]).to_binary
            tmp_bindata.push_ints @nodes[:unknown2]
            tmp_bindata.concat List.new(@nodes[:tali]).to_binary
            tmp_bindata.push_ints @nodes[:unknown3]
            tmp_bindata.push_int @nodes[:type]
            tmp_bindata.push_ints @nodes[:unknown4] if @nodes[:unknown4]

            data = tmp_bindata.data
            bindata.push_word @marker
            bindata.push_size data.size
            bindata.concat data
            @binary = bindata.data
          end
        end
      end
    end
  end
end
