require_relative '../../base'
require_relative 'task'
require_relative 'dependence'

module Wld
  module Items
    module Info
      module Task
        class List < Base
          def initialize(file_or_hash, marker = 'TALI')
            # @list = []
            super
          end

          def unpack(file)
            token, _size = file.token_with_size
            raise_token(token, @marker) if token != @marker

            file.skip # skip zero
            unpack_tasks(file)
            # @nodes = @list.map(&:to_hash)

            token = file.token
            raise_token(token) unless token == 'END '
          end

          def pack
            bindata = BinaryDataBuffer.new
            tmp_bindata = BinaryDataBuffer.new

            tmp_bindata.push_zero

            @nodes.each do |node|
              tmp_bindata.concat Task.new(node[:task]).to_binary if node[:task]
              tmp_bindata.concat Dependence.new(node[:dependence]).to_binary if node[:dependence]
            end

            data = tmp_bindata.data
            bindata.push_word @marker
            bindata.push_size data.size + 8
            bindata.concat data
            bindata.push_word 'END '
            bindata.push_zero
            @binary = bindata.data
          end

          def unpack_tasks(file)
            type = file.word
            file.back

            case type
            when 'END '
              return
            when 'TASK'
              @nodes.push({ task: Task.new(file).to_hash })
            when 'DPND'
              @nodes.push({ dependence: Dependence.new(file).to_hash })
            else
              raise "Unknown type: #{type}"
            end
            unpack_tasks(file)
          end
        end
      end
    end
  end
end
