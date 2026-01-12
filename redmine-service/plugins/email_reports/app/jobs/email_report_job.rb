class EmailReportJob < ApplicationJob
  queue_as :default

  def perform(report_id)
    report = EmailReport.find_by(id: report_id)
    return unless report
    
    data = report.generate_report_data
    
    report.recipient_users.each do |user|
      begin
        ReportMailer.report_email(report, user, data).deliver_now
      rescue => e
        Rails.logger.error "Failed to send report #{report.id} to #{user.mail}: #{e.message}"
      end
    end
    
    report.update_column(:last_sent_at, Time.current)
  rescue => e
    Rails.logger.error "Failed to process email report #{report_id}: #{e.message}"
    raise e
  end
end
