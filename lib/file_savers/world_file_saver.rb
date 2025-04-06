require_relative 'json_file_saver'

class WorldFileSaver
  class << self
    def save(filepath, world, objects, models, with_shadows: false)
      new(filepath).save(world, objects, models, with_shadows:)
    end
  end

  def initialize(filepath)
    @filepath = filepath
  end

  def save(old_world, objects, models, with_shadows: false)
    world = old_world.dup
    world.each do |new_hash|
      new_hash.delete(:shad) unless with_shadows
      new_hash[:object_name] = objects[new_hash[:object_id] - 1][:name] if new_hash[:object_id]
      new_hash[:model_name] = models[new_hash[:model_id] - 2][:name] if new_hash[:model_id]
    end

    JsonFileSaver.save(@filepath, world)
  end
end
