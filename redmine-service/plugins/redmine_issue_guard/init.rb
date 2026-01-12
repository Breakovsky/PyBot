require 'redmine'

Redmine::Plugin.register :redmine_issue_guard do
  name 'Issue Guard'
  author 'RodionovSA'
  version '2.1'
  description 'Валидация задач: блокирует закрытие без трудозатрат и с некорректной категорией (с фильтрацией по проектам)'
  
  settings default: {
    'statuses' => '5',
    'projects' => '',
    'message_time' => '🚫 Нельзя закрыть без трудозатрат!',
    'message_category' => '🚫 Нельзя закрыть с категорией "<<Неопределенно>>". Измените категорию!'
  }, partial: 'force_time_settings'
end

class Issue
  alias_method :original_save, :save unless method_defined?(:original_save)
  
  def save(*args)
    settings = Setting.plugin_redmine_issue_guard || {}
    
    # 1. Фильтр по проектам
    project_ids = (settings['projects'] || '').split(',').map(&:strip).reject(&:empty?)
    
    # Если проекты заданы и текущий НЕ в списке -> пропускаем проверки
    if project_ids.any? && !project_ids.include?(project_id.to_s)
      return original_save(*args)
    end

    # 2. Проверка статуса
    required_statuses = (settings['statuses'] || '5').split(',').map(&:strip)
    
    if status_id && required_statuses.include?(status_id.to_s)
      
      # 3. Проверка ВРЕМЕНИ
      if time_entries.sum(:hours).to_f <= 0.0
        errors.add(:base, settings['message_time'])
      end

      # 4. Проверка КАТЕГОРИИ (ID=1)
      category_val = custom_field_values.detect { |v| v.custom_field_id == 1 }&.value.to_s
      if category_val == '<<Неопределенно>>'
        errors.add(:base, settings['message_category'])
      end

      if errors[:base].any?
        Rails.logger.error "ISSUE_GUARD: BLOCKED ##{id} (Project: #{project_id})"
        return false
      end
    end

    original_save(*args)
  end
end

Rails.logger.info 'ISSUE_GUARD v2.1: ACTIVE!'
