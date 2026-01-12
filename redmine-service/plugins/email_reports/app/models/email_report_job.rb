# app/jobs/email_report_job.rb
class EmailReportJob < ActiveJob::Base
  queue_as :default

  def perform(email_report_id)
    email_report = EmailReport.find(email_report_id)
    return unless email_report.ready_to_send?

    begin
      data = email_report.generate_report_data
      recipients = email_report.recipient_users

      recipients.each do |user|
        ReportMailer.report_email(email_report, user, data).deliver_later
      end

      email_report.update(last_sent_at: Time.current)
    rescue => e
      Rails.logger.error "Failed to send EmailReport##{email_report_id}: #{e.message}"
      Rails.logger.error e.backtrace.join("\n")
      raise # Перезапускаем job при ошибке
    end
  end
end
