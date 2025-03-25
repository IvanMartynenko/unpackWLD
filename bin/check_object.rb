require 'yaml'
require_relative '../lib/simulated_binary_file'

def convert_folder(yaml)
  yaml.map do |a|
    str = a['name']

    while a['parent'] != 1
      a = yaml[a['parent'] - 2]
      str = a['name'] + '/' + str
    end
    str
  end
end

def find_end_of_name(data, offset = 0)
  j = offset
  word = []
  while true
    tmp = data[j].force_encoding('Windows-1252').encode('UTF-8')
    j += 1
    break if tmp == "\0"

    word.push tmp
  end
  j += 1 while j % 4 != 0

  { offset: j, name: word.join.strip }
end

def parse_item(file, type)
  case type
  when 0
    # type = 0 Item
    # Weight float always 0
    { weight: file.read_float }
  when 1
    # type = 1 Item - Beute
    # Weight float, Value float
    {
      weight: file.read_float,
      value: file.read_float
    }
  when 2
    # type = 2 Item - Tool
    # Weight float, Value float,
    # Strength float (0.0 or 1.0), PickLocks float, PickSafes float,
    # AlarmSystems float (0.0 always), Volume float (0.0 always),
    # Damaging negative boolean,
    # Applicability: { Glas, Wood, Steel, HighTech } all floats,
    # Noise: { Glas, Wood, Steel, HighTech } all floats.
    {
      weight: file.read_float,
      value: file.read_float,
      strength: file.read_float,
      pick_locks: file.read_float,
      pick_safes: file.read_float,
      alarm_systems: file.read_float,
      volume: file.read_float,
      damaging: file.read_negative_bool,
      applicability: {
        glas: file.read_float,
        wood: file.read_float,
        steel: file.read_float,
        hightech: file.read_float
      },
      noise: {
        glas: file.read_float,
        wood: file.read_float,
        steel: file.read_float,
        hightech: file.read_float
      }
    }
  when 3
    # type = 3 Immobilie
    # WorkingTime float, Material int, CrackType int
    {
      working_time: file.read_float,
      material: file.read_int,
      crack_type: file.read_int
    }
  when 4
    # type = 4 Character A
    # Speed float, Skillfulness (0.0 always)
    {
      speed: file.read_float,
      skillfulness: file.read_float
    }
  when 5
    # type = 5 Character B
    # Speed float
    { speed: file.read_float }
  when 6
    # type = 6 Character C
    # Speed float
    { speed: file.read_float }
  when 7
    # type = 7 Durchgang - Tuer
    # WorkingTime float, Material int, CrackType int
    {
      working_time: file.read_float,
      material: file.read_int,
      crack_type: file.read_int
    }
  when 8
    # type = 8 Durchgang - Fenster
    # WorkingTime float, Material int, CrackType int
    {
      working_time: file.read_float,
      material: file.read_int,
      crack_type: file.read_int
    }
  when 9
    # type = 9 Car
    # Transp. Space float, MaxSpeed float, Acceleration float,
    # Value float (cost), Driving float
    {
      transp_space: file.read_float,
      max_speed: file.read_float,
      acceleration: file.read_float,
      value: file.read_float,
      driving: file.read_float
    }
  else
    raise "Unknown type: #{type}"
  end
end

def parse_unknow2(file, count)
  count.times.map do
    {
      name: file.read_name,
      unknow1: file.read_int,
      unknow2: file.read_float,
      unknow3: file.read_float,
      unknow4: file.read_int,
      alway_negative100: file.read_float, # -100.0
      unknow5: file.read_negative_bool,
      unknow6: file.read_negative_bool,
      count_of_unknow7: count_of_unknow7 = file.read_int,
      unknow7: count_of_unknow7.times.map do
        {
          name: file.read_name,
          unknow1: file.read_float
        }
      end
    }
  end
end

def parse_tali(file, tali_size)
  size = 4
  res = []
  file.read_int # zero
  while size < tali_size
    word = file.read_word
    s = file.read_unsigned_int_big_endians
    d = file.read_hex(s)
    if word == 'TASK' && d.size == 24
      # print "EWQ1:\t\t\t"
      # 24 - 256
      # puts d[0..3].unpack1('H*') # zero
      # puts d[4..7].unpack1('H*') # fffff
      # print d[8..11].unpack1('V*') # int TYPE_ID
      # puts d[12..15].unpack1('H*') # zero
      # puts d[16..19].unpack1('H*') # zero
      # puts d[20..23].unpack1('H*') # 0,1,2,3,19,22
      # puts "__________\n"
      # puts d[24..27].unpack1("V*") # 3,5,6,8
      # puts d[28..31].unpack1("H*")
      # puts d[32..35].unpack1("H*")
      # if d.size > 32
      #   puts d[28..31].to_s
      # end
    end
    res.push({
               size: s,
               word:,
               #  zero:,
               #  type:,
               data: d
             })
    size += s + 8
  end
  res
end

data = []
file_system = File.new('VaBank_unpack/pack/object_list.bin')
@folders = convert_folder YAML.load_file('VaBank_unpack/pack/object_list_tree.yml')

until file_system.eof?
  file_system.read(4).to_s
  size = file_system.read(4).unpack1('N')
  data.push SimulatedBinaryFile.from_data(file_system.read(size))
end

data.map do |file|
  result = {
    type: file.read_int, # 6
    name: file.read_name,
    parent_folder: file.read_int,
    count_of_unknow2: count_of_unknow2 = file.read_int,
    unknow2: parse_unknow2(file, count_of_unknow2)
  }
  result[:full_name] = @folders[result[:parent_folder] - 2] + '/' + result[:name]
  puts result[:full_name]
  # print result[:unknow1]

  word = file.read_word # info
  raise 'not info' if word != 'INFO'

  result[:info] = {
    size: file.read_unsigned_int_big_endians,
    unknow1: file.read_int,
    unknow2: file.read_int,
    unknow3: file.read_int
  }

  word = file.read_word
  raise 'not opts' if word != 'OPTS'

  result[:opts] = {
    size: file.read_unsigned_int_big_endians,
    unknow1: file.read_int,
    id: file.read_name,
    type: object_type = file.read_int,
    story: file.read_int,
    clickable: file.read_negative_bool,
    process_when_visible: file.read_negative_bool,
    process_always: file.read_negative_bool,
    info: parse_item(file, object_type)
  }

  word = file.read_word # COND
  raise 'not COND' if word != 'COND'

  result[:cond] = {
    size: z = file.read_unsigned_int_big_endians,
    data: file.read_hex(z)
  }

  word = file.read_word # TALI
  raise 'not TALI' if word != 'TALI'

  result[:tali] = {
    size: z = file.read_unsigned_int_big_endians,
    data: parse_tali(file, z)
  }

  word = file.read_word # END
  raise 'not END' if word != 'END '

  file.read_word # SKIP
  puts

  # puts "end size: #{file.data.size - file.offset}"

  result
end

# puts res
exit 0

file = File.open 'VaBank_unpack/pack/object_list.bin', 'rb'

data = []
until file.eof?
  file.read(4).to_s
  size = file.read(4).unpack1('N')
  tmp = file.read(size)
  data.push tmp
  # puts tmp.size
end

# int type? = 6
# name
# int parent_folder
# int - size2:
#   name
#   int
#   float
#   float
#   int
#   -100.0
#   bool as 0, -1
#   bool as 0, -1
#   int 0,1,2 - size3:
#     name
#     float
# INFO
#   size (big int)
#   int type? = 3
#   int size? 0-9
#   int
#   OPTS
#     size (big int) ?
#     int type? = 9
#     name
#     int type22 0-9 - 1,4 to COND
#     int story? 0-9 # story
#     bool as 0, -1 Clickable?
#     bool as 0, -1 Process When Visible
#     bool as 0, -1 Process Always
#     see types
#   COND
#     size (big int)
#     int type? = 6
#     TALI || float || int
#   TALI
#     size (big int)
#     0
#     ? DPND TASK

# type = 0 Item
# Weight float always 0

# type = 1 Item - Beute
# Weight float
# Value  float

# type = 2 Item - Tool
# Weight float
# Value  float
# Strength float (0.0 or 1.0)
# PickLocks float
# PickSafes float
# AlarmSystems (0.0 always)
# Volume (0.0 always)
# Damaging negative boolean
# Applicability
#   Glas float
#   Wood  float
#   Steel float
#   HighTech float
# Noise
#   Glas float
#   Wood  float
#   Steel float
#   HighTech float

# type = 3 Immobilie
# WorkingTime float
# Material int (Glass, Wood, Steel, HightTech)
# CrackType int (Undefined, PickLocks, PickSafes, AlarmSystem)

# type = 4 Character A
# Speed float
# Skillfulness (0.0 always)

# type = 5 Character B
# Speed float

# type = 6 Character C
# Speed float

# type = 7 Durchgang - Tuer
# WorkingTime float
# Material int (Glass, Wood, Steel, HightTech)
# CrackType int (Undefined, PickLocks, PickSafes, AlarmSystem)

# type = 8 Durchgang - Fenster
# WorkingTime float
# Material int (Glass, Wood, Steel, HightTech)
# CrackType int (Undefined, PickLocks, PickSafes, AlarmSystem)

# type = 9 Car
# Transp. Space float
# MaxSpeed float
# Acceleration float
# Value float (cost)
# Driving float

data.map do |t|
  of = find_end_of_name(t, 4)
  name = of[:name]
  next unless name == 'DanDumbhole'

  offset = of[:offset]
  size1 = t[offset..offset + 3].unpack1('V')
  offset += 4
  size2 = t[offset..offset + 3].unpack1('V')
  offset += 4
  of = find_end_of_name(t, offset)
  offset = of[:offset]
  size3 = t[offset..offset + 3].unpack('V*')
  offset += 4
  puts t[offset..offset + 3].unpack('e*')
  offset += 4
  puts t[offset..offset + 3].unpack('e*')
  offset += 4
  puts t[offset..offset + 3].unpack('V*')
  offset += 4
  puts t[offset..offset + 3].unpack('e*')
  offset += 4
  puts t[offset..offset + 3].unpack('H*')
  offset += 4
  puts t[offset..offset + 3].unpack('H*')
  offset += 4
  puts t[offset..offset + 3].unpack('V*')
  offset += 4
  puts t[offset..offset + 3].to_s.strip
  puts size1
  puts size2
  puts size3
  # offset += 16 * 2
  # of = find_end_of_name(t, offset)
  # offset = of[:offset]
  # offset += 16 * 2
  # of = find_end_of_name(t, offset)
  # of[:name]
end
# puts "#{aa.uniq}"

# puts v.uniq
data.map do |file|
  file.read_int
  file.read_name
  file.read_int
  size2 = file.read_int
  # sdfsdf
  size2.times.map do
    file.read_name
    file.read_int
    file.read_float
    file.read_float
    file.read_int
    file.read_float # -100.0
    file.read_negative_bool
    file.read_negative_bool
    size5 = file.read_int
    size5.times.map do
      {
        name: file.read_name,
        hex: file.read_float
      }
    end
  end
  file.read_word # info
  file.read_unsigned_int_big_endians
  file.read_int
  file.read_int
  file.read_int
  file.read_word # OPTS
  file.read_unsigned_int_big_endians
  file.read_int
  file.read_name
  object_type = file.read_int # type
  file.read_int # story
  file.read_negative_bool # Clickable?
  file.read_negative_bool # Process When Visible
  file.read_negative_bool # Process Always
  # next if object_type != 9
  # next if name2 != "HeroCar"
  parse_item(file, object_type)

  file.read_word # COND
  z = file.read_unsigned_int_big_endians
  file.read_hex(z)

  file.read_word # TALI
  z = file.read_unsigned_int_big_endians
  cond = file.read_hex(z)

  # puts cond[0..8].
  next if cond[4..7].to_s != 'TASK'

  big_size = cond[8..11].unpack1('N*')
  puts big_size
  # puts cond[12+big_size..12+big_size+3]
  # puts cond[4..7]
  # ww = cond[4..7]
  # next if ww != "TASK"
  # puts cond.size

  file.read_word # END
  file.read_word # SKIP

  # puts file.data.size - file.offset

  # file.read_4hex(1)
  # puts file.read_4hex(1)

  # if a == 'COND'
  #   puts "B: #{b}"
  # else
  #   # puts file.read_int
  # end

  # aa
end

# puts res
exit 0
