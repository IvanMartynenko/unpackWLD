require 'json'
require_relative 'base_file_saver'

class JsonFileSaver < BaseFileSaver
  def save(data)
    @file.write JSON.pretty_generate(data)
  end
end
