require_relative '../base'

module Wld
  module Items
    module Info
      class Dialog
        def unpack(file, _item)
          marker = 'COND'
          token, size = file.token_with_size
          raise_token(token, marker) if token != marker

          file.skip # skip 6
          return { dialogs: [] } if size == 4

          if size == 8
            nodes = { bad_size: true, unknown_value: file.int, dialogs: [] }
            return nodes
          end

          count = file.int
          nodes = { good_nodes: true, dialogs: [], count: }
          count.times.each do |_|
            new_item = {}
            new_item[:active] = file.int    # 0,1 Active
            new_item[:Q] = file.name        # Q
            new_item[:A] = file.name        # A
            new_item[:'Dlg-'] = file.name    # Dlg-
            new_item[:'Dlg+'] = file.name    # Dlg+
            new_item[:'Always-'] = file.name # Always-
            new_item[:'Always+'] = file.name # Always+
            new_item[:Always] = file.int     # Always
            new_item[:Story] = file.int      # Story
            new_item[:Coohess] = file.int    # Coohess
            new_item[:DialogEvent] = file.int # DialogEvent
            nodes[:dialogs].push new_item
          end

          nodes
        end

        def pack(node, opts)
          bindata = BinaryDataBuffer.new
          tmp_bindata = BinaryDataBuffer.new

          tmp_bindata.push_int 6
          if node[:bad_size]
            tmp_bindata.push_int node[:unknown_value]
          elsif node[:good_nodes]
            tmp_bindata.push_int node[:count]
            node[:dialogs].each do |new_item|
              tmp_bindata.push_int new_item[:active]
              tmp_bindata.push_name new_item[:Q]
              tmp_bindata.push_name new_item[:A]
              tmp_bindata.push_name new_item[:'Dlg-']
              tmp_bindata.push_name new_item[:'Dlg+']
              tmp_bindata.push_name new_item[:'Always-']
              tmp_bindata.push_name new_item[:'Always+']
              tmp_bindata.push_int new_item[:Always]
              tmp_bindata.push_int new_item[:Story]
              tmp_bindata.push_int new_item[:Coohess]
              tmp_bindata.push_int new_item[:DialogEvent]
            end
          end
          case opts[:type]
          when 7, 8
            tmp_bindata.push_int opts[:custom][:open]
            tmp_bindata.push_int opts[:custom][:locked]
          when 3
            tmp_bindata.push_int opts[:custom][:open]
            tmp_bindata.push_int opts[:custom][:locked]
            tmp_bindata.push_int opts[:custom][:active]
          when 4
            tmp_bindata.push_int opts[:custom][:open]
            tmp_bindata.push_int opts[:custom][:locked]
            tmp_bindata.push_floats opts[:custom][:values]
          end

          data = tmp_bindata.data
          bindata.push_word 'COND'
          bindata.push_size data.size
          bindata.concat data
          bindata.data
        end
      end
    end
  end
end
