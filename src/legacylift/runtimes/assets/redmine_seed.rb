# Executed only by Rails runner in a disposable, isolated reference container.
require 'json'
require 'securerandom'

Setting.rest_api_enabled = '1'
Setting.default_language = 'en'
Setting.notified_events = []
Setting.mail_from = 'fixture@example.invalid'
Setting.host_name = 'localhost:3000'
Setting.protocol = 'http'

role = Role.create!(:name => 'LegacyLift Operator', :permissions =>
                   [:view_issues, :add_issues, :edit_issues, :add_issue_notes])
project = Project.create!(:name => 'LegacyLift Fixture', :identifier => 'legacylift-fixture',
                          :is_public => false)
project.enabled_module_names = ['issue_tracking']
tracker = Tracker.first!
project.trackers = [tracker]
initial_status = IssueStatus.find_by!(:name => 'New')
progress_status = IssueStatus.find_by!(:name => 'In Progress')
closed_status = IssueStatus.find_by!(:name => 'Closed')
WorkflowTransition.create!(:role => role, :tracker => tracker,
                           :old_status => initial_status, :new_status => progress_status)
WorkflowTransition.create!(:role => role, :tracker => tracker,
                           :old_status => progress_status, :new_status => closed_status)

actors = {}
users = {}
%w(alice outsider).each do |login|
  user = User.new(:login => login, :firstname => login.capitalize, :lastname => 'Fixture',
                 :mail => "#{login}@example.invalid", :language => 'en')
  user.password = SecureRandom.hex(20)
  user.password_confirmation = user.password
  user.must_change_passwd = false
  user.save!
  actors[login] = user.api_key
  users[login] = user
end
Member.create!(:project => project, :user => users.fetch('alice'), :roles => [role])
priority = IssuePriority.default || IssuePriority.first!
issue = Issue.create!(:project => project, :tracker => tracker, :author => users.fetch('alice'),
                      :subject => 'Seeded legacy issue', :description => 'Synthetic fixture.',
                      :priority => priority, :status => initial_status)
File.write('/tmp/legacylift-actors.json', JSON.generate(actors))
File.chmod(0600, '/tmp/legacylift-actors.json')
summary = {'project_id' => project.id, 'tracker_id' => tracker.id, 'issue_id' => issue.id,
           'actor_ids' => users.transform_values(&:id), 'priority_id' => priority.id,
           'status_ids' => {'new' => initial_status.id, 'in_progress' => progress_status.id,
                            'closed' => closed_status.id}}
File.write('/tmp/legacylift-fixture.json', JSON.generate(summary))
puts JSON.generate(summary)
