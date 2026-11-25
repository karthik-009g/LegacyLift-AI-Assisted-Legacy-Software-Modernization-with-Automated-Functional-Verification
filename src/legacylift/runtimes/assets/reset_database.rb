require 'sqlite3'
destination = SQLite3::Database.new('/usr/src/redmine/sqlite/reference.sqlite3')
source = SQLite3::Database.new('/tmp/legacylift-baseline.sqlite3')
backup = SQLite3::Backup.new(destination, 'main', source, 'main')
backup.step(-1)
backup.finish
source.close
destination.close
File.write('/tmp/legacylift-clock', '1768478400')
