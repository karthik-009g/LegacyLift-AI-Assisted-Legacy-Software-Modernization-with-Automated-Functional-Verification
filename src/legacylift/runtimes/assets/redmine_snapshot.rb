# Read selected state; never include user passwords, API tokens or session secrets.
require 'json'
require 'sqlite3'
db = SQLite3::Database.new('file:/usr/src/redmine/sqlite/reference.sqlite3?mode=ro', :uri => true)
db.results_as_hash = true
snapshot = {}
%w(issues journals journal_details).each do |table|
  snapshot[table] = db.execute("SELECT * FROM #{table} ORDER BY id").map do |row|
    row.select {|key, _| key.is_a?(String)}
  end
end
db.close
puts JSON.generate(snapshot)
