require_relative 'json_file_saver'
require_relative 'binary_file_saver'

class ModelFileSaver
  class << self
    def save(filepath, models_info, with_json_models)
      new(filepath, models_info, with_json_models).save
    end
  end

  def initialize(filepath, models_info, with_json_models)
    @filepath = filepath
    @models_info = models_info
    @with_json_models = with_json_models
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
      if @with_json_models
        JsonFileSaver.save(model[:system_filepath], model[:nmf])
      else
        BinaryFileSaver.save(model[:system_filepath], model[:nmf])
      end
    end
  end
end
