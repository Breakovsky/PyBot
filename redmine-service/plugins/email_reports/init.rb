require 'redmine'

Redmine::Plugin.register :email_reports do
  name 'Email Reports'
  author 'RodionovSA'
  description 'Generate and send automated email reports'
  version '1.4.0'
  
  permission :manage_email_reports, {
    email_reports: [:index, :show, :new, :create, :edit, :update, :destroy, :test, :toggle_active, :available_principals]
  }, require: :member
  
  menu :admin_menu, :email_reports,
       { controller: 'email_reports', action: 'index' },
       caption: :label_email_reports,
       html: { class: 'icon' }
end
