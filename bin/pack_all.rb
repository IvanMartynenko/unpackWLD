#!/usr/bin/env ruby
# This script processes WLD game files by parsing them and saving various extracted assets.

require 'pathname'

def main
  # Define the script directory and the unpack script path using Pathname for clarity.
  script_dir  = Pathname.new(__FILE__).expand_path.dirname
  pack_script = script_dir.join('pack.rb')

  unpack_folders = script_dir.parent.glob('*_unpack')

  unpack_folders.each do |folder|
    system('ruby', pack_script.to_s, folder.to_s)
  end
end

# Execute main if this file is run directly.
main if __FILE__ == $PROGRAM_NAME
