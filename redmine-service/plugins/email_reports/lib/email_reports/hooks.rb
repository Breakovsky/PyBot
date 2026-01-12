# plugins/email_reports/lib/email_reports/hooks.rb
module EmailReports
  class Hooks < Redmine::Hook::ViewListener
    # Добавляет ссылку в меню проекта
    render_on :view_projects_show_sidebar,
              partial: 'hooks/email_reports/project_link'
  end
end
