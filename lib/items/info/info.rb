require_relative '../base'
require_relative 'opts'
require_relative 'task/list'
require_relative 'dialog'

INFO_FIELDS = {
  unknown: [
    { key: :unknown1,          type: :int },
    { key: :unknown2,          type: :int },
    { key: :unknown3, type: :int }
  ]
}.freeze

module Wld
  module Items
    module Info
      class Info < Base
        def initialize(file_or_hash, marker = 'INFO')
          super
        end

        def unpack(file)
          token, _size = file.token_with_size # skip size
          raise_token(token, @marker) if token != @marker

          @nodes = file.read INFO_FIELDS[:unknown]

          @nodes[:opts] = Opts.new(file).to_hash
          @nodes[:dialog] = Dialog.new.unpack(file, @nodes)
          case @nodes[:opts][:type]
          when 7, 8
            @nodes[:opts][:custom] = {}
            @nodes[:opts][:custom][:open] = file.int
            @nodes[:opts][:custom][:locked] = file.int
          when 3
            @nodes[:opts][:custom] = {}
            @nodes[:opts][:custom][:open] = file.int
            @nodes[:opts][:custom][:locked] = file.int
            @nodes[:opts][:custom][:active] = file.int
          when 4
            @nodes[:opts][:custom] = {}
            @nodes[:opts][:custom][:open] = file.int
            @nodes[:opts][:custom][:locked] = file.int
            @nodes[:opts][:custom][:values] = file.floats(8)
          end
          @nodes[:task_list] = Task::List.new(file).to_hash

          token = file.token
          raise_token(token) unless token == 'END '
        end

        def pack
          bindata = BinaryDataBuffer.new
          tmp_bindata = BinaryDataBuffer.new

          tmp_bindata.add INFO_FIELDS[:unknown], @nodes
          tmp_bindata.concat Opts.new(@nodes[:opts]).to_binary
          tmp_bindata.concat Dialog.new.pack(@nodes[:dialog], @nodes[:opts])

          tmp_bindata.concat Task::List.new(@nodes[:task_list]).to_binary

          data = tmp_bindata.data
          bindata.push_word @marker
          bindata.push_size data.size + 8
          bindata.concat data
          bindata.push_word 'END '
          bindata.push_zero
          @binary = bindata.data
        end
      end
    end
  end
end
