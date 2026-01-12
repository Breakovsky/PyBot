namespace :email_reports do
  desc "Send pending email reports"
  task send_pending: :environment do
    # Simply call the job for active reports
    EmailReport.active.each do |report|
        puts "Processing report #{report.name}"
        # Logic to check time would go here
    end
  end
end

