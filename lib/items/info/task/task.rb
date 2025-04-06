require_relative '../../base'

TASKS_FIELDS = {
  base: [
    { key: :unknown1, type: :int },
    { key: :unknown2, type: :int },
    { key: :task_id, type: :int },
    { key: :default, type: :bool },
    { key: :critical, type: :bool }
  ]
}.freeze

module Wld
  module Items
    module Info
      module Task
        class Task < Base
          def initialize(file_or_hash, marker = 'TASK')
            @acod_list = []
            super
          end

          def unpack(file)
            token, _size = file.token_with_size
            raise_token(token, @marker) if token != @marker

            @nodes = file.read TASKS_FIELDS[:base]
            count_of_params = file.int
            @nodes[:params] = count_of_params.times.map do |index|
              type = file.int
              values = unpack_task_by_type(file, type, @nodes[:task_id], index)
              { type:, values: }
            end
          end

          def pack
            bindata = BinaryDataBuffer.new
            tmp_bindata = BinaryDataBuffer.new

            tmp_bindata.add TASKS_FIELDS[:base], @nodes
            tmp_bindata.push_int @nodes[:params].size
            @nodes[:params].each do |param|
              tmp_bindata.push_int param[:type]
              tmp_bindata.concat pack_task_by_type(param)
            end

            data = tmp_bindata.data
            bindata.push_word @marker
            bindata.push_size data.size
            bindata.concat data
            @binary = bindata.data
          end

          def unpack_task_by_type(file, type, task_id, index)
            case type
            when 2
              file.floats(3)
            when 3
              file.float
            when 4, 5, 8, 9, 10
              file.int # 0,1,2
            when 6, 12, 16
              file.name
            when 7
              Acod.new(file).to_hash
            when 15
              file.hex(9 * 4).unpack1('H*').first
            else
              raise StandardError, "Error. Unknown type: #{type}. TaskId: #{task_id}. Params number: #{index + 1}"
            end
          end

          def pack_task_by_type(param)
            bindata = BinaryDataBuffer.new
            case param[:type]
            when 2
              bindata.push_floats param[:values]
            when 3
              bindata.push_float param[:values]
            when 4, 5, 8, 9, 10
              bindata.push_int param[:values]
            when 6, 12, 16
              bindata.push_name param[:values]
            when 7
              bindata.concat Acod.new(param[:values]).to_binary
            when 15
              bindata.push_hex param[:values]
            end
            bindata.data
          end
        end
      end
    end
  end
end
