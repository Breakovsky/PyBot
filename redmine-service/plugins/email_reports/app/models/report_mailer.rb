# plugins/email_reports/app/models/report_mailer.rb
class ReportMailer < Mailer  # Было: ApplicationMailer
  def report_email(email_report, user, data)
    @email_report = email_report
    @user = user
    @data = data

    mail(to: user.mail,
         from: Setting.mail_from,
         subject: "#{email_report.name} - #{format_date(Time.current)}") do |format|
      format.html { render layout: 'mailer' }
      format.text
    end
  end

  private

  def format_date(date)
    I18n.l(date, format: :long)
  end
end
