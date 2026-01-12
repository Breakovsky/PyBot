class AddLastSentAtToEmailReports < ActiveRecord::Migration[7.0]
  def change
    add_column :email_reports, :last_sent_at, :datetime
  end
end
