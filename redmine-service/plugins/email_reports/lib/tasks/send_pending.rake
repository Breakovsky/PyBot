namespace :email_reports do
  desc "Send pending email reports based on schedule"
  task send_pending: :environment do
    # 1. Текущее время в Москве
    msk_zone = ActiveSupport::TimeZone.new('Europe/Moscow')
    now_msk = Time.now.in_time_zone(msk_zone)
    
    Rails.logger.info "---------------------------------------------------"
    Rails.logger.info "EmailReports: Checking schedule at #{now_msk}"

    EmailReport.active.find_each do |report|
      unless report.send_time
        Rails.logger.info "Report ##{report.id}: No send_time set."
        next
      end

      # 2. Получаем "целевое" время из БД
      target_hour = report.send_time.strftime('%H').to_i
      target_min = report.send_time.strftime('%M').to_i

      Rails.logger.info "Report ##{report.id} ('#{report.name}'):"
      Rails.logger.info "  - Target Time (DB): #{target_hour.to_s.rjust(2, '0')}:#{target_min.to_s.rjust(2, '0')}"
      Rails.logger.info "  - Current Time (MSK): #{now_msk.hour.to_s.rjust(2, '0')}:#{now_msk.min.to_s.rjust(2, '0')}"

      # 3. Сравнение времени с окном в 5 минут
      # Это решает проблему, если крон запустился в 12:00:05 или 12:02:00
      is_time_match = now_msk.hour == target_hour && 
                      now_msk.min >= target_min && 
                      now_msk.min < (target_min + 5)

      Rails.logger.info "  - Time window match? #{is_time_match ? 'YES' : 'NO'}"

      if is_time_match
        # === ЛОГИКА ПРОВЕРКИ ДНЯ ===
        should_run_today = false
        
        case report.schedule_type
        when 'daily'
          should_run_today = true
        when 'weekly'
          # Если в schedule_cron сохранены дни (например "1,3,5"), используем их
          # Если пусто, по умолчанию понедельник (1)
          # 0=Вс, 1=Пн, ... 6=Сб
          target_days = report.schedule_cron.present? ? report.schedule_cron.split(',').map(&:to_i) : [1]
          should_run_today = target_days.include?(now_msk.wday)
          Rails.logger.info "  - Weekly check: Today is #{now_msk.wday}. Targets: #{target_days}. Match? #{should_run_today}"
        when 'monthly'
          # Отправляем 1-го числа месяца
          should_run_today = (now_msk.day == 1)
        else
          # Custom cron или иное - пока разрешаем, если время совпало
          should_run_today = true
        end

        Rails.logger.info "  - Schedule (Day) match? #{should_run_today}"

        # === ПРОВЕРКА ПОВТОРНОЙ ОТПРАВКИ ===
        # Если сегодня уже отправляли - пропускаем
        already_sent_today = false
        
        if report.last_sent_at
          last_sent_msk = report.last_sent_at.in_time_zone(msk_zone)
          
          # Создаем точку отсчета: сегодня в целевое время запуска
          today_window_start = now_msk.change(hour: target_hour, min: target_min, sec: 0)
          
          # Если последняя отправка была позже начала сегодняшнего окна - значит уже отправлено
          if last_sent_msk >= today_window_start
            already_sent_today = true
          end
        end

        if already_sent_today
          Rails.logger.info "  - Already sent today? YES (Last sent: #{report.last_sent_at})"
          next 
        else
          Rails.logger.info "  - Already sent today? NO"
        end

        # === ФИНАЛЬНЫЙ ЗАПУСК ===
        if should_run_today
          begin
            Rails.logger.info "  => SENDING NOW..."
            EmailReportJob.perform_now(report.id)
            
            # Обновляем время отправки
            report.update_column(:last_sent_at, Time.now.utc)
            Rails.logger.info "  => SENT SUCCESS."
          rescue => e
            Rails.logger.error "  => ERROR: #{e.message}"
            Rails.logger.error e.backtrace.join("\n")
          end
        else
          Rails.logger.info "  => Skipping (Not the right day)."
        end
      end
    end
    Rails.logger.info "---------------------------------------------------"
  end
end
