require 'yaml'
require_relative '../lib/simulated_binary_file'

data = []
file_system = File.new('VaBank_unpack/pack/world_tree.bin')

until file_system.eof?
  file_system.read(4).to_s
  size = file_system.read(4).unpack1('N')
  data.push SimulatedBinaryFile.from_data(file_system.read(size))
end

ii = 1
data.map do |file|
  ii += 1
  file.read_int # 15
  a = file.read_int # 1-65220 parent
  b = file.read_name # folder name
  z = file.read_float
  file.read_float # -12.0 - 3.4
  file.read_float # -38 - 42
  file.read_float # -5.02920389175415 - 103.72408294677734 123456.0, 123457.4296875
  file.read_float # -10.170000076293945 - 45.243621826171875
  file.read_float # 1.0
  b2 = file.read_int # ffffffff || f7ffffff
  c = file.read_int # 0-3 type. 0 is folder.
  c1 = file.read_int # 0-2861
  c2 = file.read_int
  w = file.read_int # if  c==2 && b.nil? &&  c1 == 0
  
  next if c != 1
  # puts c2

  q2 = c2.times.map do |e|
    [file.read_int, file.read_int]
  end
  if file.data.size - file.offset == 0
    # puts q1
  end
  q1 = file.read_word
  # puts "#{ii} #{q2} #{c1}"
  puts "#{q2.last}"
  # puts "#{c2} #{q1}, #{file.data.size - file.offset}"
  # file.read_int
  # a2 = file.read_hex(4).unpack("H*")
  # puts "#{w} #{a2}"
  # next if a2 == 1145129043
  # next if a2 != 0
  # file.read_int
  # file.read_int
  # file.read_int
  # puts file.read_word

  # puts "end size: #{file.data.size - file.offset}"
end


# 15
# parent
# folder_name
# unknow_float1
# unknow_float2
# unknow_float3
# unknow_float4
# unknow_float5
# unknow_float6 1.0
# unknow_int f7ffffff
# type 0 is folder, 1 is shadow map, 2 is, 3 is
# next if object id

# if fodler type
# 0
# 0
# 0
# 0