require 'redmine'

Redmine::Plugin.register :redmine_force_time2 do
  name 'Force Time BLOCKER'
  author 'RodionovSA'
  version '2.1'
  description 'Blocks closing issues without spent time (with project filtering)'
  
  settings default: {
    'statuses' => '5',
    'projects' => '',
    'message_time' => '🚫 Cannot close without spent time!',
    'message_category' => '🚫 Cannot close with category "<<Unspecified>>". Change category!'
  }, partial: 'force_time_settings'
end

class Issue
  alias_method :original_save, :save unless method_defined?(:original_save)
  
  def save(*args)
    settings = Setting.plugin_redmine_force_time2 || {}
    
    # 1. Project Filter
    project_ids = (settings['projects'] || '').split(',').map(&:strip).reject(&:empty?)
    
    if project_ids.any? && !project_ids.include?(project_id.to_s)
      return original_save(*args)
    end

    # 2. Status Check
    required_statuses = (settings['statuses'] || '5').split(',').map(&:strip)
    
    if status_id && required_statuses.include?(status_id.to_s)
      
      # 3. Time Check
      if time_entries.sum(:hours).to_f <= 0.0
        errors.add(:base, settings['message_time'])
      end

      # 4. Category Check (ID=1 example)
      # category_val = custom_field_values.detect { |v| v.custom_field_id == 1 }&.value.to_s
      # if category_val == '<<Неопределенно>>'
      #   errors.add(:base, settings['message_category'])
      # end

      if errors[:base].any?
        Rails.logger.error "FORCE_TIME2: BLOCKED ##{id} (Project: #{project_id})"
        return false
      end
    end

    original_save(*args)
  end
end

