#!/usr/bin/env ruby
# extract_textures.rb
#
# Usage:
#   extract_textures.rb [options] <model_root_folder>
#
# Description:
#   This script reads the model list and texture page data from the specified folder,
#   extracts individual textures from combined texture pages (DDS format), and
#   converts each to TIFF using ffmpeg or a chosen converter.
#
# Options:
#   -h, --help           Show this help message
#   -v, --verbose        Enable verbose logging
#   -o, --output DIR     Specify output base folder (default: <model_root>/output)
#   -f, --formats LIST   Comma-separated list of output formats (dds,tif)
#
# Example:
#   extract_textures.rb -v -o /tmp/out -f dds,tif "/path/to/models"

require 'json'
require 'fileutils'
require 'optparse'

options = {
  verbose: false,
  output: nil,
  formats: %w[dds tif]
}

parser = OptionParser.new do |opts|
  opts.banner = "Usage: #{File.basename($PROGRAM_NAME)} [options] <the_sting_unpack_root_folder>"

  opts.on('-v', '--verbose', 'Enable verbose logging') do
    options[:verbose] = true
  end

  opts.on('-oDIR', '--output=DIR', 'Output base directory') do |dir|
    options[:output] = dir
  end

  opts.on('-fLIST', '--formats=LIST', 'Comma-separated output formats (dds,tif)') do |list|
    options[:formats] = list.split(',').map(&:strip)
  end

  opts.on('-h', '--help', 'Prints this help') do
    puts opts
    exit
  end
end

begin
  parser.parse!
  root = ARGV.shift or raise OptionParser::MissingArgument, 'model_root_folder'
rescue OptionParser::ParseError => e
  STDERR.puts e.message
  STDERR.puts parser
  exit 1
end

output_base = options[:output] || File.join(File.join(root, 'output'), 'texture_files')
dds_output = File.join(output_base, 'dds')
tiff_output = File.join(output_base, 'tiff')
pack_path = File.join(root, 'pack')
texture_json_path = File.join(pack_path, 'texture_pages.json')
texture_pages_path = File.join(pack_path, 'texture_pages')

FileUtils.mkdir_p(output_base)
FileUtils.mkdir_p(dds_output)
FileUtils.mkdir_p(tiff_output)

log = ->(msg) { puts "[INFO] #{msg}" } if options[:verbose]
log ||= ->(*){}

texture_data = JSON.parse(File.read(texture_json_path))

# DDS constants
DDS_MAGIC = 0x20534444

# Helpers
def init_dds_header(width, height, alpha)
  {
    magic: DDS_MAGIC,
    size: 124,
    flags: 0x00001007,
    height: height,
    width: width,
    pitch_or_linear_size: width * 2,
    depth: 0,
    mip_map_count: 1,
    reserved1: [0] * 11,
    pixel_format: {
      dw_size: 32,
      dw_flags: 0x00000041,
      dw_four_cc: 0,
      dw_rgb_bit_count: 16,
      dw_r_bit_mask: 0x7C00,
      dw_g_bit_mask: 0x03E0,
      dw_b_bit_mask: 0x001F,
      dw_a_bit_mask: alpha ? 0x8000 : 0
    },
    caps: 0x00001000,
    caps2: 0,
    caps3: 0,
    caps4: 0,
    reserved2: 0
  }
end

def write_dds(file_path, header, pixel_bytes)
  binary = []
  %i[magic size flags height width pitch_or_linear_size depth mip_map_count].each { |k|
    binary << [header[k]].pack('L')
  }
  binary << header[:reserved1].pack('L*')
  pf = header[:pixel_format]
  %i[dw_size dw_flags dw_four_cc dw_rgb_bit_count dw_r_bit_mask dw_g_bit_mask dw_b_bit_mask dw_a_bit_mask].each { |k|
    binary << [pf[k]].pack('L')
  }
  %i[caps caps2 caps3 caps4 reserved2].each { |k|
    binary << [header[k]].pack('L')
  }
  File.binwrite(file_path, binary.join + pixel_bytes)
end

texture_data.each do |page|
  page_id = page['id']
  width = page['width']
  raw = File.binread(File.join(texture_pages_path, "#{page_id}.dds"))
  pixels = raw.byteslice(128, raw.bytesize - 128)

  page['textures'].each do |tex|
    path = tex['filepath']
    next if path.include?('\\NEW_TEXTURES\\')

    filename = path.split('\\').last
    ext = File.extname(path)
    name = File.basename(filename, ext)

    x0, y0 = tex['box'].values_at('x0','y0')
    x2, y2 = tex['box'].values_at('x2','y2')
    w, h = x2 - x0, y2 - y0
    alpha = true

    # Extract raw bytes
    data = ''.b
    y0.upto(y2 - 1) do |y|
      offset = (x0 + y * width) * 2
      data << pixels.byteslice(offset, w * 2)
    end

    if options[:formats].include?('dds')
      dds_out = File.join(dds_output, "#{name}.dds")
      log.call "Writing DDS: #{dds_out} (#{w}x#{h})"
      header = init_dds_header(w, h, alpha)
      write_dds(dds_out, header, data)
    end

    if options[:formats].include?('tif')
      tif_out = File.join(tiff_output, "#{name}.tif")
      log.call "Converting to TIFF: #{tif_out}"
      system('ffmpeg', '-y', '-v', 'error', '-i', "#{File.join(dds_output, "#{name}.dds")}", tif_out)
    end
  end
end

log.call "All done. Outputs are in #{output_base}"
