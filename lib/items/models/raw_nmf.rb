module Wld
  module Items
    class RawNmf
      def unpack(file)
        current_position = file.current
        token = file.token # read const char[4] and int = zero
        raise StandardError, "Bad end of ModelList. Expected 'NMF ' but got '#{token}'" unless token == 'NMF '

        file_size = 0
        loop do
          token, size = file.token_with_size
          break if token == 'END '

          file_size += size + 8
          file.next(size)
        end
        file.set_position(current_position)
        file.raw(file_size + 16)
      end

      def pack(node)
        node
        # File.binread(model_filepath(node, folder_manager))
      end

      protected

      def model_filepath(info, folder_manager)
        folder_manager.model_path(info[:name], info[:index], info[:parent_folder_iid])
      end
    end
  end
end
