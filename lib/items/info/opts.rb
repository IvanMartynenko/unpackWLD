require_relative '../base'

OPTS_FIELDS = {
  base: [
    { key: :unknown1, type: :int },
    { key: :id, type: :name },
    { key: :type, type: :int },
    { key: :story, type: :int },
    { key: :clickable, type: :bool },
    { key: :process_when_visible, type: :bool },
    { key: :process_always, type: :bool }
  ]
}

ITEM_FIELDS = {
  # type = 0 Item
  # Weight float always 0
  item: [
    { key: :weight, type: :float }
  ],
  # type = 1 Item - Loot
  # Weight float, Value float
  item_loot: [
    { key: :weight, type: :float },
    { key: :value, type: :float }
  ],
  # type = 2 Item - Tool
  # Weight float, Value float,
  # Strength float (0.0 or 1.0), PickLocks float, PickSafes float,
  # AlarmSystems float (0.0 always), Volume float (0.0 always),
  # Damaging negative boolean,
  # Applicability: { Glass, Wood, Steel, HighTech } all floats,
  # Noise: { Glass, Wood, Steel, HighTech } all floats.
  item_tool: {
    base: [
      { key: :weight, type: :float },
      { key: :value, type: :float },
      { key: :strength, type: :float },
      { key: :pick_locks, type: :float },
      { key: :pick_safes, type: :float },
      { key: :alarm_systems, type: :float },
      { key: :volume, type: :float },
      { key: :damaging, type: :float }
    ],
    attr: [
      { key: :glass, type: :float },
      { key: :wood, type: :float },
      { key: :steel, type: :float },
      { key: :high_tech, type: :float }
    ]
  },
  # type = 3 Real estate
  # type = 7 Passage - Door
  # type = 8 Passage - Window
  # WorkingTime float, Material int, CrackType int
  passage: [
    { key: :working_time, type: :float },
    { key: :material, type: :int },
    { key: :crack_type, type: :int }
  ],
  # type = 4 Character A
  # Speed float, Skillfulness (0.0 always)
  character_a: [
    { key: :speed, type: :float },
    { key: :occupation, type: :name }
  ],
  # type = 5 Character B
  # type = 6 Character C
  # Speed float
  character_b: [
    { key: :speed, type: :float }
  ],
  # type = 9 Car
  # Transp. Space float, MaxSpeed float, Acceleration float,
  # Value float (cost), Driving float
  car: [
    { key: :transp_space, type: :float },
    { key: :max_speed, type: :float },
    { key: :acceleration, type: :float },
    { key: :value, type: :float },
    { key: :driving, type: :float }
  ]
}.freeze

module Wld
  module Items
    module Info
      class Opts < Base
        def initialize(file_or_hash, marker = 'OPTS')
          super
        end

        def unpack(file)
          token, _size = file.token_with_size
          raise_token(token, @marker) if token != @marker

          @nodes = {}
          @nodes = file.read OPTS_FIELDS[:base]
          @nodes[:info] = unpack_item(file, @nodes[:type])
        end

        def pack
          bindata = BinaryDataBuffer.new
          tmp_bindata = BinaryDataBuffer.new

          tmp_bindata.add OPTS_FIELDS[:base], @nodes
          tmp_bindata.concat pack_item(@nodes[:info], @nodes[:type])

          data = tmp_bindata.data
          bindata.push_word @marker
          bindata.push_size data.size
          bindata.concat data
          @binary = bindata.data
        end

        def unpack_item(file, type)
          case type
          when 0
            file.read ITEM_FIELDS[:item]
          when 1
            file.read ITEM_FIELDS[:item_loot]
          when 2
            item = file.read ITEM_FIELDS[:item_tool][:base]
            item[:applicability] = file.read ITEM_FIELDS[:item_tool][:attr]
            item[:noise] = file.read ITEM_FIELDS[:item_tool][:attr]
            item
          when 3, 7, 8
            file.read ITEM_FIELDS[:passage]
          when 4
            file.read ITEM_FIELDS[:character_a]
          when 5, 6
            file.read ITEM_FIELDS[:character_b]
          when 9
            file.read ITEM_FIELDS[:car]
          else
            raise "Unknown type: #{type}"
          end
        end

        def pack_item(node, type)
          bindata = BinaryDataBuffer.new
          case type
          when 0
            bindata.add ITEM_FIELDS[:item], node
          when 1
            bindata.add ITEM_FIELDS[:item_loot], node
          when 2
            bindata.add ITEM_FIELDS[:item_tool][:base], node
            bindata.add ITEM_FIELDS[:item_tool][:attr], node[:applicability]
            bindata.add ITEM_FIELDS[:item_tool][:attr], node[:noise]
          when 3, 7, 8
            bindata.add ITEM_FIELDS[:passage], node
          when 4
            bindata.add ITEM_FIELDS[:character_a], node
          when 5, 6
            bindata.add ITEM_FIELDS[:character_b], node
          when 9
            bindata.add ITEM_FIELDS[:car], node
          else
            raise "Unknown type: #{type}"
          end

          bindata.data
        end
      end
    end
  end
end
