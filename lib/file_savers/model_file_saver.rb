require_relative 'json_file_saver'
require_relative 'binary_file_saver'

class ModelFileSaver
  class << self
    def save(filepath, models_info)
      new(filepath, models_info).save
    end
  end

  def initialize(filepath, models_info)
    @filepath = filepath
    @models_info = models_info
  end

  def save
    save_model_info
    save_nmf_models
  end

  def save_model_info
    info = @models_info.map { |p| p.except(:nmf) }
    JsonFileSaver.save(@filepath, info)
  end

  def save_nmf_models
    @models_info.each do |model|
      JsonFileSaver.save(model[:system_filepath], model[:nmf])
      # BinaryFileSaver.save(model[:system_filepath], model[:nmf])
    end
  end
end
