require_relative '../base'
require_relative 'opts'
require_relative 'task/list'

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

          @opts = Opts.new(file)
          @nodes[:opts] = @opts.to_hash

          word, cond_size = file.token_with_size # COND
          raise "not COND. find #{word} token. #{item[:opts]}" if word != 'COND'

          @nodes[:cond] = file.hex(cond_size)

          tasks = Task::List.new(file)
          @nodes[:task_list] = tasks.to_hash

          token = file.token
          raise_token(token) unless token == 'END '
        end

        def pack
          bindata = BinaryDataBuffer.new
          tmp_bindata = BinaryDataBuffer.new

          tmp_bindata.add INFO_FIELDS[:unknown], @nodes
          tmp_bindata.concat Opts.new(@nodes[:opts]).to_binary

          tmp_bindata.push_word 'COND'
          tmp_bindata.push_size @nodes[:cond].pack('H*').size
          tmp_bindata.concat @nodes[:cond].pack('H*')

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
