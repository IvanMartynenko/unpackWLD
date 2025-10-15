MATRIX_SIZE = 16

module Wld
  module Items
    class Nmf
      def unpack(file)
        @file = file
        file.current
        token = file.token # read const char[4] and int = zero
        raise StandardError, "Bad end of ModelList. Expected 'NMF ' but got '#{token}'" unless token == 'NMF '

        model = []
        index = 1
        loop do
          token, _size = @file.token_with_size
          break if token == 'END '

          @file.int # 0 from LOCA, 14 from MESH, other 2. skip
          parent_iid = @file.int # start from 0. 0 for ROOT
          name = @file.name

          data = case token
                 when 'ROOT' then parse_root
                 when 'LOCA' then parse_loca
                 when 'FRAM' then parse_fram
                 when 'JOIN' then parse_join
                 when 'MESH' then parse_mesh
                 else
                   raise StandardError, "Unexpected token in MODEL: #{token}"
                 end

          model << { word: token, name:, parent_iid:, data:, index: }
          index += 1
        end
        model
      end

      def pack(model_file)
        accumulator = BinaryDataBuffer.new
        accumulator.push 'NMF '
        accumulator.push_int 0

        model_file.sort_by { |t| t[:index] }.each do |value|
          item_accumulator = BinaryDataBuffer.new
          # item_accumulator.push_word value[:word]
          case value[:word]
          when 'ROOT'
            item_accumulator.push_int 2
            item_accumulator.push_int value[:parent_iid]
            item_accumulator.push_name value[:name]
            item_accumulator.push_floats value[:data][:matrix].flatten
            keys = %i[translation scaling rotation]
            keys.each { |key| item_accumulator.push_floats value[:data][key] }
            item_accumulator.push_ints value[:data][:unknown]
            item_accumulator.push_int 0

          when 'LOCA'
            item_accumulator.push_int 0
            item_accumulator.push_int value[:parent_iid]
            item_accumulator.push_name value[:name]
          when 'FRAM'
            item_accumulator.push_int 2
            item_accumulator.push_int value[:parent_iid]
            item_accumulator.push_name value[:name]
            item_accumulator.push_floats value[:data][:matrix].flatten
            keys = %i[translation scaling rotation rotate_pivot_translate rotate_pivot scale_pivot_translate
                      scale_pivot shear]
            keys.each { |key| item_accumulator.push_floats value[:data][key] }
            if value[:data][:anim]
              item_accumulator.push pack_anim(value[:data][:anim])
            else
              item_accumulator.push_int 0
            end
          when 'JOIN'
            item_accumulator.push_int 2
            item_accumulator.push_int value[:parent_iid]
            item_accumulator.push_name value[:name]
            item_accumulator.push_floats value[:data][:matrix].flatten
            keys = %i[translation scaling rotation]
            keys.each { |key| item_accumulator.push_floats value[:data][key] }
            item_accumulator.push_floats value[:data][:rotation_matrix].flatten
            item_accumulator.push_floats value[:data][:min_rot_limit]
            item_accumulator.push_floats value[:data][:max_rot_limit]
            if value[:data][:anim]
              item_accumulator.push pack_anim(value[:data][:anim])
            else
              item_accumulator.push_int 0
            end
          when 'MESH'
            item_accumulator.push_int 14
            item_accumulator.push_int value[:parent_iid]
            item_accumulator.push_name value[:name]
            item_accumulator.push_int value[:data][:tnum]
            item_accumulator.push_int value[:data][:vnum]
            item_accumulator.push_floats value[:data][:vbuf].flatten
            item_accumulator.push_floats value[:data][:uvpt].flatten
            item_accumulator.push_int value[:data][:inum]
            item_accumulator.push_ints16 value[:data][:ibuf].flatten
            item_accumulator.push_int16(0) if value[:data][:inum].odd?
            item_accumulator.push_int value[:data][:backface_culling]
            item_accumulator.push_int value[:data][:complex]
            item_accumulator.push_int value[:data][:inside]
            item_accumulator.push_int value[:data][:smooth]
            item_accumulator.push_int value[:data][:light_flare]
            if value[:data][:materials]
              item_accumulator.push_int value[:data][:materials].size
              value[:data][:materials].each do |mt|
                item_accumulator.push_word 'MTRL'
                item_accumulator.push_name mt[:name]
                item_accumulator.push_int mt[:blend_mode]
                item_accumulator.push_ints mt[:unknown_ints]
                item_accumulator.push_int mt[:uv_mapping_flip_horizontal]
                item_accumulator.push_int mt[:uv_mapping_flip_vertical]
                item_accumulator.push_int mt[:rotate]
                item_accumulator.push_float mt[:horizontal_stretch]
                item_accumulator.push_float mt[:vertical_stretch]
                item_accumulator.push_float mt[:red]
                item_accumulator.push_float mt[:green]
                item_accumulator.push_float mt[:blue]
                item_accumulator.push_float mt[:alpha]
                item_accumulator.push_float mt[:red2]
                item_accumulator.push_float mt[:green2]
                item_accumulator.push_float mt[:blue2]
                item_accumulator.push_float mt[:alpha2]
                item_accumulator.push_ints mt[:unknown_zero_ints]

                if mt[:texture]
                  item_accumulator.push_word 'TXPG'
                  item_accumulator.push_name mt[:texture][:name]
                  item_accumulator.push_int mt[:texture][:texture_page]
                  item_accumulator.push_int mt[:texture][:index_texture_on_page]
                  item_accumulator.push_int mt[:texture][:x0]
                  item_accumulator.push_int mt[:texture][:y0]
                  item_accumulator.push_int mt[:texture][:x2]
                  item_accumulator.push_int mt[:texture][:y2]
                elsif mt[:text]
                  item_accumulator.push_word 'TEXT'
                  item_accumulator.push_name mt[:text][:name]
                else
                  item_accumulator.push_int 0
                end
              end
            else
              item_accumulator.push_int 0
            end

            if value[:data][:mesh_anim]
              value[:data][:mesh_anim].each do |anim|
                item_accumulator.push_word 'ANIM'
                item_accumulator.push_int anim[:unknown_bool]
                item_accumulator.push_int anim[:unknown_ints].size
                item_accumulator.push_ints anim[:unknown_ints]
                item_accumulator.push_floats anim[:unknown_floats]
                item_accumulator.push_int anim[:unknown_size1]
                item_accumulator.push_int anim[:unknown_size2]
                item_accumulator.push_int anim[:unknown_size3]
                item_accumulator.push_floats anim[:unknown_floats1]
                item_accumulator.push_floats anim[:unknown_floats2]
                item_accumulator.push_floats anim[:unknown_floats3]
              end
            end
            item_accumulator.push_int 0

            if value[:data][:unknown_floats]
              # item_accumulator.push_int value[:data][:unknown_count_of_floats]
              item_accumulator.push_int value[:data][:unknown_floats].size / 3
              item_accumulator.push_floats value[:data][:unknown_floats]
            else
              item_accumulator.push_int 0
            end
            if value[:data][:unknown_ints]
              item_accumulator.push_int value[:data][:unknown_ints].size
              item_accumulator.push_ints value[:data][:unknown_ints]
            else
              item_accumulator.push_int 0
            end
          end

          data = item_accumulator.data
          accumulator.push value[:word]
          accumulator.push_size data.size
          accumulator.push data
        end
        accumulator.push 'END '
        accumulator.push_int 0

        accumulator.data
      end

      protected

      def parse_root
        return parse_fram
        # res = {}
        # keys = %i[translation scaling rotation]
        # res[:matrix] = @file.floats(MATRIX_SIZE).each_slice(4).to_a
        # keys.each { |key| res[key] = @file.floats(3) }
        # @file.word == 'ANIM' ? parse_anim : nil
        # res[:unknown] = @file.ints(15)
        # # res[:anim] = a if a
        # res
      end

      def parse_loca
        {}
      end

      def parse_fram
        res = {}
        keys = %i[translation scaling rotation rotate_pivot_translate rotate_pivot scale_pivot_translate
                  scale_pivot shear]
        res[:matrix] = @file.floats(MATRIX_SIZE).each_slice(4).to_a
        keys.each { |key| res[key] = @file.floats(3) }
        a = @file.word == 'ANIM' ? parse_anim : nil
        res[:anim] = a if a
        res
      end

      def parse_join
        res = {}
        keys = %i[translation scaling rotation]
        res[:matrix] = @file.floats(MATRIX_SIZE).each_slice(4).to_a
        keys.each { |key| res[key] = @file.floats(3) }
        res[:rotation_matrix] = @file.floats(MATRIX_SIZE).each_slice(4).to_a
        res[:min_rot_limit] = @file.floats(3)
        res[:max_rot_limit] = @file.floats(3)
        a = @file.word == 'ANIM' ? parse_anim : nil
        res[:anim] = a if a
        res
      end

      def parse_anim
        res = {}
        sizes = {}
        res[:unknown] = @file.int
        keys = %i[translation rotation scaling]
        keys.each { |key| res[key] = {} }
        keys.each { |key| sizes[key] = {} }
        keys.each { |key| sizes[key][:sizes] = @file.ints(3) }
        keys.each { |key| res[key].merge!(parse_curve(sizes[key][:sizes], key)) }
        res
      end

      def parse_curve(sizes, key)
        res = { values: {}, keys: {} }
        coordinates = %i[x y z]

        coordinates.each_with_index do |coord, idx|
          n = sizes[idx]
          next if n <= 0
          res[:keys][coord]   = @file.floats(n)  # сначала ключи этой оси
          res[:values][coord] = @file.floats(n)  # сразу следом значения этой оси
        end

        res
      end

      def parse_mesh
        res = {}
        res[:tnum] = @file.int
        res[:vnum] = @file.int

        vbuf_count = 10
        uvbuf_count = 2
        vbuf_count_float = res[:vnum] * vbuf_count
        uvbuf_count_float = res[:vnum] * uvbuf_count

        res[:vbuf] = @file.floats(vbuf_count_float).each_slice(vbuf_count).to_a
        res[:uvpt] = @file.floats(uvbuf_count_float).each_slice(uvbuf_count).to_a

        res[:inum] = @file.int
        ibuf = @file.ints16(res[:inum])
        res[:ibuf] = ibuf.each_slice(3).to_a
        @file.int16 if res[:inum].odd?
        res[:backface_culling] = @file.int
        res[:complex] = @file.int
        res[:inside] = @file.int
        res[:smooth] = @file.int
        res[:light_flare] = @file.int
        material_count = @file.int

        if material_count > 0
          res[:materials] = []
          material_count.times { res[:materials] << parse_mtrl }
        end

        a = @file.word == 'ANIM' ? parse_anim_mesh : nil
        res[:mesh_anim] = a if a

        # anti-ground
        unknown_count_of_floats = @file.int
        res[:unknown_floats] = @file.floats(unknown_count_of_floats * 3) if unknown_count_of_floats > 0

        # Если кратко, наиболее вероятно, что это либо:
        # Индексы вершин для треугольных стрипов (Triangle Strips) или фанов (Triangle Fans), которые описывают поверхность модели.
        # Группы (Submesh), идущие одна за другой, где каждая группа представляет свой набор индексов.
        unknown_count_of_ints = @file.int
        res[:unknown_ints] = @file.ints(unknown_count_of_ints) if unknown_count_of_ints > 0

        res
      end

      def parse_mtrl
        res = {}
        token = @file.word
        raise StandardError, "Expected 'MTRL' but got '#{token}'" unless token == 'MTRL'

        res[:name] = @file.name
        res[:blend_mode] = @file.int
        res[:unknown_ints] = @file.ints(4)
        res[:uv_mapping_flip_horizontal] = @file.int
        res[:uv_mapping_flip_vertical] = @file.int
        res[:rotate] = @file.int
        res[:horizontal_stretch] = @file.float
        res[:vertical_stretch] = @file.float
        res[:red] = @file.float
        res[:green] = @file.float
        res[:blue] = @file.float
        res[:alpha] = @file.float
        res[:red2] = @file.float
        res[:green2] = @file.float
        res[:blue2] = @file.float
        res[:alpha2] = @file.float
        res[:unknown_zero_ints] = @file.ints(9)

        token = @file.word
        if token.to_s == 'TXPG'
          res[:texture] = {
            name: @file.filename,
            texture_page: @file.int,
            index_texture_on_page: @file.int,
            x0: @file.int,
            y0: @file.int,
            x2: @file.int,
            y2: @file.int
          }
        elsif token.to_s == 'TEXT'
          res[:text] = { name: @file.filename }
        end

        res
      end

      def pack_anim(item)
        accumulator = BinaryDataBuffer.new
        accumulator.push_word 'ANIM'
        accumulator.push_int item[:unknown]

        keys = %i[translation scaling rotation]
        keys.each do |key|
          %i[x y z].each do |coord|
            accumulator.push_int item[key][:values][coord] ? item[key][:values][coord].size : 0
          end
        end

        keys.each do |key|
          %i[x y z].each do |coord|
            accumulator.push_floats item[key][:values][coord] if item[key][:values][coord]
          end
          %i[x y z].each do |coord|
            accumulator.push_floats item[key][:keys][coord] if item[key][:keys][coord]
          end
        end

        accumulator.data
      end

      def parse_anim_mesh
        anim_meshes = []
        anim_meshes << parse_single_anim_mesh
        anim_meshes << parse_single_anim_mesh while @file.word == 'ANIM'
        anim_meshes.flatten
      end

      def parse_single_anim_mesh
        {
          unknown_bool: @file.int,
          unknown_size_of_ints: size = @file.int,
          unknown_ints: @file.ints(size),
          unknown_floats: @file.floats(3),
          unknown_size1: s1 = @file.int,
          unknown_size2: s2 = @file.int,
          unknown_size3: s3 = @file.int,
          unknown_floats1: @file.floats(s1 * 2),
          unknown_floats2: @file.floats(s2 * 2),
          unknown_floats3: @file.floats(s3 * 2)
        }
      end
    end
  end
end
