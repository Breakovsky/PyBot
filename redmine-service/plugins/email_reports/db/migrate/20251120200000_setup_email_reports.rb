class SetupEmailReports < ActiveRecord::Migration[7.0]
  def change
    # 1. Создаем таблицу отчетов (email_reports)
    create_table :email_reports do |t|
      t.string :name                        # Название отчета
      t.text :description                   # Описание
      t.string :schedule_type, default: 'weekly'  # Тип расписания (daily, weekly)
      t.string :schedule_cron               # Cron-выражение (если нужно)
      t.time :send_time                     # Время отправки
      t.integer :report_period_days, default: 7   # Период отчета в днях
      
      t.string :report_type, default: 'issues'    # Тип отчета (issues, time_entries)
      t.string :group_by                    # Группировка
      t.integer :project_id                 # ID проекта (если отчет по проекту)
      t.integer :author_id                  # Автор отчета
      t.integer :source_group_id            # Группа-источник (если нужно)
      
      t.boolean :is_active, default: true   # Активен ли отчет
      
      # Хранение сложных структур (массивы, хеши)
      t.text :query_filters                 # Фильтры запроса (JSON/YAML)
      t.text :columns                       # Список колонок (JSON/YAML)
      
      t.timestamps
    end

    # Индексы для email_reports
    add_index :email_reports, :author_id
    add_index :email_reports, :project_id
    add_index :email_reports, :is_active

    # 2. Создаем таблицу получателей (email_report_recipients)
    create_table :email_report_recipients do |t|
      t.references :email_report, foreign_key: true
      
      t.string :recipient_type   # 'user', 'group', 'email'
      t.integer :recipient_id    # ID пользователя или группы
      t.string :email            # Email (если внешний получатель)
      
      t.timestamps
    end

    # Индекс с коротким именем для получателей
    add_index :email_report_recipients, [:recipient_type, :recipient_id], name: 'idx_email_rep_recip_on_type_id'
  end
end
