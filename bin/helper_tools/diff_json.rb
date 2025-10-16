#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
require 'optparse'

# ---- CLI ----
opts = {
  epsilon: 0.001,
  format: :text
}

parser = OptionParser.new do |o|
  o.banner = 'Usage: json_diff.rb [options] file_a.json file_b.json'
  o.on('-e', '--epsilon N', Float, 'Числовой допуск для сравнения (по умолчанию 0.0)') { |v| opts[:epsilon] = v }
  o.on('--json', 'Вывести результат в формате JSON') { opts[:format] = :json }
  o.on('-h', '--help', 'Показать помощь') do
    puts o
    exit
  end
end
begin
  parser.parse!
  abort(parser.to_s) unless ARGV.size == 2
rescue OptionParser::ParseError => e
  abort("#{e.message}\n\n#{parser}")
end

file_a, file_b = ARGV

def read_json!(path)
  JSON.parse(File.read(path))
rescue Errno::ENOENT
  abort("Файл не найден: #{path}")
rescue JSON::ParserError => e
  abort("Некорректный JSON в #{path}: #{e.message}")
end

a = read_json!(file_a)
b = read_json!(file_b)

# ---- Дифф ----

DiffItem = Struct.new(:type, :path, :left, :right) # :added, :removed, :changed, :type_mismatch

def json_pointer(parts)
  # puts "part #{parts}"
  # RFC 6901: escape ~ -> ~0, / -> ~1
  '/' + parts.map { |p| p.to_s.gsub('~', '~0').gsub('/', '~1') }.join('/')
end

def numeric?(x) = x.is_a?(Numeric)

def equal_numbers?(x, y, eps)
  return false unless numeric?(x) && numeric?(y)

  (x - y).abs <= eps
end

def skip(path_parts)
  # path_parts.any? { |v| %w[anim materials vbuf uvpt].include?(v) }
  # 
  path_parts.any? { |v| %w[rotation ].include?(v) }
  # false
end

def diff_values(left, right, path_parts, epsilon, out)
  # Типы
  if left.is_a?(Hash) && right.is_a?(Hash)
    keys = (left.keys + right.keys).uniq
    keys.each do |k|
      if !left.key?(k)
        out << DiffItem.new(:added, json_pointer(path_parts + [k]), nil, right[k]) unless skip(path_parts)
      elsif !right.key?(k)
        out << DiffItem.new(:removed, json_pointer(path_parts + [k]), left[k], nil) unless skip(path_parts)
      else
        diff_values(left[k], right[k], path_parts + [k], epsilon, out)
      end
    end
  elsif left.is_a?(Array) && right.is_a?(Array)
    min = [left.length, right.length].min
    (0...min).each { |i| diff_values(left[i], right[i], path_parts + [i], epsilon, out) }
    if left.length > right.length
      (min...left.length).each do |i|
        out << DiffItem.new(:removed, json_pointer(path_parts + [i]), left[i], nil) unless skip(path_parts)
      end
    elsif right.length > left.length
      (min...right.length).each do |i|
        out << DiffItem.new(:added, json_pointer(path_parts + [i]), nil, right[i]) unless skip(path_parts)
      end
    end
  elsif numeric?(left) && numeric?(right)
    # Скалярные значения или несовпадение типов
    return if equal_numbers?(left, right, epsilon)

    out << DiffItem.new(:changed, json_pointer(path_parts), left, right) unless skip(path_parts)
  elsif left.class != right.class
    out << DiffItem.new(:type_mismatch, json_pointer(path_parts), left, right)
  elsif !skip(path_parts) && !(left == right)
    out << DiffItem.new(:changed, json_pointer(path_parts), left, right)
  end
end

diffs = []
diff_values(a, b, [], opts[:epsilon], diffs)

# ---- Вывод ----

if opts[:format] == :json
  payload = diffs.map do |d|
    { type: d.type, path: d.path, left: d.left, right: d.right }
  end
  puts JSON.pretty_generate({
                              summary: {
                                added: diffs.count { |d| d.type == :added },
                                removed: diffs.count { |d| d.type == :removed },
                                changed: diffs.count { |d| d.type == :changed },
                                type_mismatch: diffs.count { |d| d.type == :type_mismatch }
                              },
                              epsilon: opts[:epsilon],
                              diffs: payload
                            })
else
  if diffs.empty?
    puts "Файлы идентичны (epsilon=#{opts[:epsilon]})."
    exit 0
  end

  puts "Найдены различия (epsilon=#{opts[:epsilon]}):"
  diffs.each do |d|
    case d.type
    when :added
      puts "[ADDED]   #{d.path}\n          -> #{d.right.inspect}"
    when :removed
      puts "[REMOVED] #{d.path}\n          <- #{d.left.inspect}"
    when :changed
      puts "[CHANGED] #{d.path}\n          #{d.left.inspect} -> #{d.right.inspect}"
    when :type_mismatch
      puts "[TYPE]    #{d.path}\n          #{d.left.class} #{d.left.inspect}  vs  #{d.right.class} #{d.right.inspect}"
    end
  end

  puts "\nИтого: added=#{diffs.count { |d| d.type == :added }}, " \
       "removed=#{diffs.count { |d| d.type == :removed }}, " \
       "changed=#{diffs.count { |d| d.type == :changed }}, " \
       "type_mismatch=#{diffs.count { |d| d.type == :type_mismatch }}"
end
