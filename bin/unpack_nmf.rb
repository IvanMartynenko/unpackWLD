#!/usr/bin/env ruby
require 'json'
require_relative '../lib/file_reader'
require_relative '../lib/items/models/nmf'

input_file =  ARGV[0]
output_file =  ARGV[0].sub(/.nmf/, '.json')

file_reader = FileReader.new(input_file)
data = Wld::Items::Nmf.new.unpack(file_reader)
File.open(output_file, "w").write(data.to_json)
