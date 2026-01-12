class SetupEmailReports < ActiveRecord::Migration[7.0]
  def change
    create_table :email_reports do |t|
      t.string :name
      t.text :description
      t.string :schedule_type, default: 'weekly'
      t.string :schedule_cron
      t.time :send_time
      t.integer :report_period_days, default: 7
      t.string :report_type, default: 'issues'
      t.string :group_by
      t.integer :project_id
      t.integer :author_id
      t.integer :source_group_id
      t.boolean :is_active, default: true
      t.text :query_filters
      t.text :columns
      t.datetime :last_sent_at
      t.timestamps
    end

    create_table :email_report_recipients do |t|
      t.references :email_report, foreign_key: true
      t.string :recipient_type
      t.integer :recipient_id
      t.string :email
      t.timestamps
    end
  end
end

