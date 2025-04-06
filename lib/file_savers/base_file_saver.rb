require 'json'

class BaseFileSaver
  class << self
    def save(filepath, data)
      saver = new(filepath)
      saver.save(data)
      saver.close
    end
  end

  def initialize(filepath)
    @file = File.open(filepath, 'w')
    raise StandardError, "Can not open file for writing #{filepath}" unless @file
  end

  def save(data)
    raise NotImplementedError, 'This method must be implemented in a subclass'
  end

  def close
    @file.close
  end
end
