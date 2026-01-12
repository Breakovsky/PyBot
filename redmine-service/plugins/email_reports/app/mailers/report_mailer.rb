class ReportMailer < ActionMailer::Base
  helper :application
  default from: Setting.mail_from
  
  def report_email(report, user, data)
    @report = report
    @user = user
    @data = data
    
    # Установка host для генерации ссылок
    host = Setting.host_name
    protocol = Setting.protocol
    default_url_options[:host] = host
    default_url_options[:protocol] = protocol
    
    # ОТЛАДКА: Логирование попытки отправки
    Rails.logger.info "📧 Отправка отчёта #{report.name} пользователю #{user.mail}"
    
    subject = "[#{Setting.app_title}] #{report.name}"
    
    mail(to: user.mail, subject: subject) do |format|
      format.html { render layout: 'mailer' }
    end
    
    # ОТЛАДКА: Логирование успешной отправки
    Rails.logger.info "✅ Отчёт #{report.name} успешно поставлен в очередь для #{user.mail}"
  rescue => e
    Rails.logger.error "❌ Ошибка при отправке отчёта #{report.name} для #{user.mail}: #{e.message}"
    raise e
  end
end
