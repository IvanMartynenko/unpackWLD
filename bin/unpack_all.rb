#!/usr/bin/env ruby
# This script processes WLD game files by parsing them and saving various extracted assets.

require 'pathname'

def main
  # Define the script directory and the unpack script path using Pathname for clarity.
  script_dir    = Pathname.new(__FILE__).expand_path.dirname
  unpack_script = script_dir.join('unpack.rb')

  # Glob all .wld files in the parent directory of the script.
  wld_files = script_dir.parent.glob('*.wld')

  # Process each WLD file by calling the unpack script with the file path.
  wld_files.each do |wld_file|
    system('ruby', unpack_script.to_s, wld_file.to_s)
  end
end

# Execute main if this file is run directly.
main if __FILE__ == $PROGRAM_NAME
