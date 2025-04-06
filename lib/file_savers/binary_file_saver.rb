require 'json'
require_relative 'base_file_saver'

class BinaryFileSaver < BaseFileSaver
  def save(data)
    @file.write data
  end
end
