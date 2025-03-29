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
  # puts result[:full_name]
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
    data: file.read_hex(z)
    # data: parse_tali(file, z)
  }

  word = file.read_word # END
  raise 'not END' if word != 'END '

  file.read_word # SKIP
  # puts

  puts "end size: #{file.data.size - file.offset}"

  result
end
