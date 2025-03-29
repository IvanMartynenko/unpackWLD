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
  file.read_float
  file.read_float # -12.0 - 3.4
  file.read_float # -38 - 42
  file.read_float # -5.02920389175415 - 103.72408294677734 123456.0, 123457.4296875
  file.read_float # -10.170000076293945 - 45.243621826171875
  file.read_float # 1.0
  b2 = file.read_int # ffffffff || f7ffffff
  c = file.read_int # 0-3 type. 0 is folder. 1 is ground.

  # puts b
  # puts 'item'
  next if c != 2
  s1 = file.read_int
  s2 = file.read_int # 0
  s3 = file.read_word # INFO
  next if s3 == 'INFO'
  puts s1
  # puts 'AAAAAAAA'
  # puts file.read_int

  # s4 = file.read_float
  # s5 = file.read_int # 3
  # s6 = file.read_int # 0-9
  # s7 = file.read_int # 
  # s8 = file.read_word # OPTS
  # s9 = file.read_unsigned_int_big_endians
  # s10 = file.read_int # 9
  # s11 = file.read_name
  # puts s8

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
# type 0 is folder, 1 is ground, 2 is, 3
# next if object id

# if fodler type
# 0
# 0
# 0
# 0

# if ground type
# int
# int count of connections
# int
# [item_id, 0] size of count of connections
# SHAD or 0
# if shad
# s1 int
# s2 int
# [float] size of s1*max(s2/2, 1)

# if is object

# if sun type
# int
# 11 floats
# int
# 13 floats
# int 
# 0
# 0
# 0