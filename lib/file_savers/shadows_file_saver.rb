require 'json'
require_relative '../binary_data_buffer'

class ShadowsFileSaver < BaseFileSaver
  def save(world)
    accumulator = BinaryDataBuffer.new

    world.each do |hash|
      next unless hash[:shad]

      accumulator.push_int hash[:index]
      accumulator.push_int hash[:shad][:size1]
      accumulator.push_int hash[:shad][:size2]
      accumulator.push_floats hash[:shad][:data]
    end
    @file.write accumulator.data
  end
end
