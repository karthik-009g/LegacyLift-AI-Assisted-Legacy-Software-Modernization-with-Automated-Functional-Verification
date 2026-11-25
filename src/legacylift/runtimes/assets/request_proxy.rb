# Trusted local HTTP proxy. No expected results or model credentials live here.
require 'json'
require 'net/http'
require 'uri'

input = JSON.parse(STDIN.read)
if input.key?('fixture_epoch')
  epoch = input.fetch('fixture_epoch')
  unless epoch.is_a?(Integer) && (1768478400..1768564800).include?(epoch)
    abort 'Fixture epoch is outside the allowed synthetic day'
  end
  File.write('/tmp/legacylift-clock', epoch.to_s)
end
path = input.fetch('path')
unless path.is_a?(String) && path.start_with?('/') && !path.start_with?('//') && !path.match?(/[\r\n]/)
  abort 'Invalid local request path'
end
method = input.fetch('method').upcase
methods = {'GET' => Net::HTTP::Get, 'POST' => Net::HTTP::Post, 'PUT' => Net::HTTP::Put,
           'PATCH' => Net::HTTP::Patch, 'DELETE' => Net::HTTP::Delete}
request_class = methods.fetch(method)
uri = URI.parse('http://127.0.0.1:3000' + path)
unless uri.host == '127.0.0.1' && uri.port == 3000
  abort 'Only the local application is accessible'
end
request = request_class.new(uri.request_uri)
request['Accept'] = 'application/json'
request['Content-Type'] = 'application/json'
actor = input.fetch('actor', 'anonymous')
if actor != 'anonymous'
  actors = JSON.parse(File.read('/tmp/legacylift-actors.json'))
  request['X-Redmine-API-Key'] = actors.fetch(actor)
end
request.body = JSON.generate(input['json']) if input.key?('json') && !input['json'].nil?
http = Net::HTTP.new(uri.host, uri.port, nil)
http.open_timeout = 5
http.read_timeout = 20
response = http.request(request)
selected_headers = {}
%w(content-type vary cache-control location).each do |name|
  selected_headers[name] = response[name] if response[name]
end
body = begin
  JSON.parse(response.body.to_s)
rescue JSON::ParserError
  nil
end
puts JSON.generate({'status' => response.code.to_i, 'headers' => selected_headers,
                    'json' => body, 'body_bytes' => response.body.to_s.bytesize})
