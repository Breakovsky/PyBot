class EmailReportRecipient < ActiveRecord::Base
  belongs_to :email_report

  validates :recipient_type, inclusion: { in: %w[user group role email] }
  validates :recipient_id, presence: true, if: -> { !email? }
  validates :email, presence: true, if: -> { email? }

  def email?
    recipient_type == 'email'
  end
end
