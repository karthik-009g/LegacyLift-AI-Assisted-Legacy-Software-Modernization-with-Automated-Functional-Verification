# Test-only wall clock. Monotonic clocks and timeout measurement remain real.
require 'date'

module LegacyLiftFixtureClock
  BASE_EPOCH = 1768478400 # 2026-01-15T12:00:00Z
  def self.epoch
    path = '/tmp/legacylift-clock'
    File.exist?(path) ? Integer(File.read(path)) : BASE_EPOCH
  end
end

class << Time
  def now
    Time.at(LegacyLiftFixtureClock.epoch).utc
  end
end

class << Date
  def today(*args)
    Time.now.to_date
  end
end

class << DateTime
  def now(*args)
    Time.now.to_datetime
  end
end
