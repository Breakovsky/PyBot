class EmailReport < ActiveRecord::Base
  belongs_to :author, class_name: 'User'
  belongs_to :project
  belongs_to :source_group, class_name: 'Group', foreign_key: 'source_group_id', optional: true
  belongs_to :recipient_group, class_name: 'Group', foreign_key: 'recipient_group_id', optional: true
  has_many :recipients, class_name: 'EmailReportRecipient', dependent: :destroy

  validates :name, presence: true, length: { maximum: 255 }
  validates :schedule_type, inclusion: { in: %w[daily weekly monthly custom] }
  validates :report_type, inclusion: { in: %w[issues time_entries] }
  validates :send_time, presence: true

  scope :active, -> { where(is_active: true) }
  scope :ready_to_send, -> { where("last_sent_at IS NULL OR (CASE schedule_type 
                 WHEN 'daily'    THEN last_sent_at < ?
                 WHEN 'weekly'   THEN last_sent_at < ? 
                 WHEN 'monthly'  THEN last_sent_at < ?
               END)", 1.day.ago, 1.week.ago, 1.month.ago) }

  def ready_to_send?
    return false unless is_active
    return true if last_sent_at.nil?

    case schedule_type
    when 'daily'   then last_sent_at < 1.day.ago
    when 'weekly'  then last_sent_at < 1.week.ago
    when 'monthly' then last_sent_at < 1.month.ago
    else false
    end
  end

  def recipient_users
    users = Set.new

    recipients.each do |recipient|
      case recipient.recipient_type
      when 'user'
        user = User.find_by(id: recipient.recipient_id)
        users << user if user && user.active?
      when 'group'
        group = Group.find_by(id: recipient.recipient_id)
        users.merge(group.users.active) if group
      when 'role'
        role = Role.find_by(id: recipient.recipient_id)
        if role && project
          users.merge(project.principals_by_role[role]&.select(&:active?) || [])
        end
      when 'email'
        user = User.new(mail: recipient.email, firstname: 'External', lastname: 'User')
        users << user
      end
    end

    users.compact
  end

  # SQL Queries
  SQL_QUERIES = {
    group_users: <<-SQL,
      SELECT u.id, u.firstname, u.lastname
      FROM users u
      JOIN groups_users gu ON gu.user_id = u.id
      WHERE gu.group_id = $1
      ORDER BY u.lastname, u.firstname
    SQL
    
    group_emails: <<-SQL,
      SELECT DISTINCT ea.address
      FROM users u
      JOIN groups_users gu ON gu.user_id = u.id
      JOIN email_addresses ea ON ea.user_id = u.id
      WHERE gu.group_id = $1
        AND u.status = 1
        AND ea.is_default = true
    SQL
    
    closed_issues_by_user: <<-SQL,
      SELECT 
        closer.id as user_id,
        closer.firstname,
        closer.lastname,
        COUNT(DISTINCT i.id) as closed_count
      FROM issues i
      JOIN journals j ON j.journalized_id = i.id AND j.journalized_type = 'Issue'
      JOIN journal_details jd ON jd.journal_id = j.id
      JOIN users closer ON closer.id = j.user_id
      JOIN groups_users gu ON gu.user_id = closer.id
      WHERE j.created_on BETWEEN $1 AND $2
        AND jd.prop_key = 'status_id'
        AND jd.value IN (SELECT CAST(id AS text) FROM issue_statuses WHERE is_closed = true)
        AND gu.group_id = $3
      GROUP BY closer.id, closer.firstname, closer.lastname
      ORDER BY closed_count DESC, closer.lastname, closer.firstname
    SQL
    
    user_closed_issues_detail: <<-SQL,
      SELECT DISTINCT
        i.id as issue_id,
        i.subject,
        i.created_on,
        i.closed_on,
        s.name as status_name,
        j.created_on as closed_date
      FROM issues i
      JOIN issue_statuses s ON s.id = i.status_id
      JOIN journals j ON j.journalized_id = i.id AND j.journalized_type = 'Issue'
      JOIN journal_details jd ON jd.journal_id = j.id
      JOIN users closer ON closer.id = j.user_id
      JOIN groups_users gu ON gu.user_id = closer.id
      WHERE j.created_on BETWEEN $1 AND $2
        AND jd.prop_key = 'status_id'
        AND jd.value IN (SELECT CAST(id AS text) FROM issue_statuses WHERE is_closed = true)
        AND gu.group_id = $3
        AND closer.id = $4
      ORDER BY j.created_on DESC
    SQL
    
    assigned_open_issues: <<-SQL,
      SELECT 
        i.id,
        i.subject,
        i.created_on,
        s.name as status_name,
        i.assigned_to_id,
        assignee.firstname as assignee_firstname,
        assignee.lastname as assignee_lastname,
        u.firstname as author_firstname,
        u.lastname as author_lastname
      FROM issues i
      JOIN issue_statuses s ON s.id = i.status_id
      JOIN users u ON u.id = i.author_id
      JOIN users assignee ON assignee.id = i.assigned_to_id
      JOIN groups_users gu ON gu.user_id = assignee.id
      WHERE s.is_closed = false
        AND i.assigned_to_id IS NOT NULL
        AND gu.group_id = $1
      ORDER BY assignee.lastname, assignee.firstname, i.updated_on DESC
    SQL
    
    unassigned_open_issues: <<-SQL,
      SELECT 
        i.id,
        i.subject,
        i.created_on,
        s.name as status_name,
        u.firstname as author_firstname,
        u.lastname as author_lastname
      FROM issues i
      JOIN issue_statuses s ON s.id = i.status_id
      JOIN users u ON u.id = i.author_id
      WHERE s.is_closed = false
        AND i.assigned_to_id IS NULL
      ORDER BY i.updated_on DESC
    SQL
    
    total_issues_closed: <<-SQL
      SELECT COUNT(DISTINCT i.id) as total_count
      FROM issues i
      JOIN journals j ON j.journalized_id = i.id AND j.journalized_type = 'Issue'
      JOIN journal_details jd ON jd.journal_id = j.id
      JOIN users closer ON closer.id = j.user_id
      JOIN groups_users gu ON gu.user_id = closer.id
      WHERE j.created_on BETWEEN $1 AND $2
        AND jd.prop_key = 'status_id'
        AND jd.value IN (SELECT CAST(id AS text) FROM issue_statuses WHERE is_closed = true)
        AND gu.group_id = $3
    SQL
  }

  def generate_report_data
    case report_type
    when 'issues'        then generate_issues_report_with_group_logic
    when 'time_entries'  then generate_time_entries_report
    else raise "Unknown report type: #{report_type}"
    end
  end

  private

  def generate_issues_report_with_group_logic
    source_group_id = source_group_id_for_query
    
    unless source_group_id
      Rails.logger.warn "EmailReport ##{id}: No source_group_id found. Falling back to standard report."
      return generate_issues_report 
    end
    
    conn = PG.connect(db_config)
    
    end_date = Date.today
    period = report_period_days || 7
    start_date = end_date - period
    
    # Преобразование параметров в строки/числа для PG exec_params
    start_date_s = start_date.to_s
    end_date_s = end_date.to_s
    group_id_i = source_group_id.to_i
    
    group_users = conn.exec_params(SQL_QUERIES[:group_users], [group_id_i]).to_a
    user_names = group_users.map { |u| [u['id'].to_i, "#{u['firstname']} #{u['lastname']}"] }.to_h
    
    closed_issues_count = conn.exec_params(
      SQL_QUERIES[:total_issues_closed], 
      [start_date_s, end_date_s, group_id_i]
    )[0]['total_count'].to_i
    
    closed_issues_by_user = conn.exec_params(
      SQL_QUERIES[:closed_issues_by_user], 
      [start_date_s, end_date_s, group_id_i]
    ).to_a
    
    assigned_open_issues = conn.exec_params(
      SQL_QUERIES[:assigned_open_issues], 
      [group_id_i]
    ).to_a
    
    unassigned_open_issues = conn.exec_params(SQL_QUERIES[:unassigned_open_issues]).to_a
    
    # Добавляем детали
    closed_issues_by_user.each do |user|
      user_id = user['user_id'].to_i
      user_closed_issues = conn.exec_params(
        SQL_QUERIES[:user_closed_issues_detail],
        [start_date_s, end_date_s, group_id_i, user_id]
      ).to_a
      user['_closed_issues_details'] = user_closed_issues
    end
    
    conn.close
    
    {
      start_date: start_date,
      end_date: end_date,
      source_group: Group.find_by(id: group_id_i),
      group_users: group_users,
      user_names: user_names,
      closed_issues_count: closed_issues_count,
      closed_issues_by_user: closed_issues_by_user,
      assigned_open_issues: assigned_open_issues,
      unassigned_open_issues: unassigned_open_issues,
      issues: generate_issues_from_data(assigned_open_issues + unassigned_open_issues),
      query: nil,
      total_count: closed_issues_count + assigned_open_issues.count + unassigned_open_issues.count
    }
  rescue => e
    Rails.logger.error "Ошибка в generate_issues_report_with_group_logic: #{e.message}"
    Rails.logger.error e.backtrace.join("\n")
    raise e
  end

  def generate_issues_from_data(issues_data)
    return [] unless issues_data.is_a?(Array)
    issue_ids = issues_data.map { |i| i['id'] }.compact
    Issue.where(id: issue_ids).limit(1000)
  end

  def source_group_id_for_query
    return source_group.id if source_group
    return self[:source_group_id] if self[:source_group_id].present?
    nil
  end

  def db_config
    {
      host: ENV['DATABASE_HOST'] || 'postgres',
      port: 5432,
      dbname: ENV['DATABASE_NAME'] || 'redmine',
      user: ENV['DATABASE_USER'] || 'postgres',
      password: ENV['DATABASE_PASSWORD'] || 'PASSWORD'
    }
  end

  def generate_issues_report
    query = IssueQuery.new(name: name, project: project, user: author)
    query.filters = query_filters.deep_stringify_keys
    query.column_names = columns if columns.any?
    query.group_by = group_by if group_by.present?

    issues = query.issues(limit: 1000)
    {
      issues:      issues,
      query:       query,
      total_count: query.issue_count
    }
  end

  def generate_time_entries_report
    scope = TimeEntry.where(project: project).includes(:issue, :user, :activity)
    # ... standard filters ...
    {
      time_entries: scope.limit(1000),
      total_hours:  scope.sum(:hours)
    }
  end
end
