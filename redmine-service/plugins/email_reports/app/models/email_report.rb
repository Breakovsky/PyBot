class EmailReport < ActiveRecord::Base
  belongs_to :author, class_name: 'User'
  belongs_to :project
  belongs_to :source_group, class_name: 'Group', foreign_key: 'source_group_id', optional: true
  has_many :recipients, class_name: 'EmailReportRecipient', dependent: :destroy

  scope :active, -> { where(is_active: true) }

  # Simplified logic for example
  def ready_to_send?
    return false unless is_active
    return true if last_sent_at.nil?
    # Basic check, real logic is in rake task
    true 
  end

  def recipient_users
    # Simplified: return admin for safety if logic complex
    User.where(admin: true)
  end

  def generate_report_data
    # Placeholder for the complex SQL logic from prod_project.txt
    {
        start_date: Date.today - 7,
        end_date: Date.today,
        closed_issues_count: 0,
        group_users: [],
        issues: []
    }
  end
end

class EmailReportRecipient < ActiveRecord::Base
  belongs_to :email_report
end

