require_relative '../base'
require_relative 'nmf'

MODEL_FIELDS = {
  base: [
    { key: :name, type: :name },
    { key: :influences_camera, type: :bool },
    { key: :no_camera_check, type: :bool },
    { key: :anti_ground, type: :bool },
    { key: :default_skeleton, type: :int },
    { key: :use_skeleton, type: :int }
  ],
  camera_values: [
    { key: :x, type: :float },
    { key: :y, type: :float },
    { key: :z, type: :float },
    { key: :pitch, type: :float },
    { key: :yaw, type: :float }
  ],
  attack_points: [
    { key: :x, type: :float },
    { key: :y, type: :float },
    { key: :z, type: :float },
    { key: :radius, type: :float }
  ]
}.freeze

module Wld
  module Items
    class Models < Base
      def initialize(file_or_hash, marker = 'LIST')
        @separator = 'MODL'
        super(file_or_hash, marker)
      end

      protected

      def unpack_node(file, index)
        file.skip # always 9, skip
        file.skip # always 1, skip
        model_info = file.read MODEL_FIELDS[:base]

        camera = unpack_camera(file)
        parent_folder_iid = file.int
        attack_points = unpack_attack_points(file)

        model_info[:camera] = camera if camera
        model_info[:parent_folder_iid] = parent_folder_iid
        model_info[:attack_points] = attack_points unless attack_points.empty?
        model_info[:nmf] = Nmf.new.unpack(file)
        model_info[:index] = index + 2

        model_info
      end

      def pack_node(node)
        accumulator = BinaryDataBuffer.new

        accumulator.push_int 9
        accumulator.push_int 1
        accumulator.add MODEL_FIELDS[:base], node
        accumulator.concat pack_camera(node)
        accumulator.push_int node[:parent_folder_iid]
        accumulator.concat pack_attack_points(node)
        accumulator.concat Nmf.new.pack(node[:nmf])

        accumulator.data
      end

      def unpack_camera(file)
        camera_token = file.word
        return nil unless camera_token == 'RMAC'

        {
          camera: file.read(MODEL_FIELDS[:camera_values]),
          item: file.read(MODEL_FIELDS[:camera_values])
        }
      end

      def pack_camera(node)
        accumulator = BinaryDataBuffer.new
        if node[:camera]
          accumulator.push_word 'RMAC'
          accumulator.add MODEL_FIELDS[:camera_values], node[:camera][:camera]
          accumulator.add MODEL_FIELDS[:camera_values], node[:camera][:item]
        else
          accumulator.push_zero
        end

        accumulator.data
      end

      def unpack_attack_points(file)
        count_of_attack_points = file.int
        count_of_attack_points.times.map do
          file.read MODEL_FIELDS[:attack_points]
        end
      end

      def pack_attack_points(node)
        accumulator = BinaryDataBuffer.new
        if node[:attack_points]
          accumulator.push_int node[:attack_points].size
          node[:attack_points].each do |attack_point|
            accumulator.add MODEL_FIELDS[:attack_points], attack_point
          end
        else
          accumulator.push_zero
        end

        accumulator.data
      end
    end
  end
end
