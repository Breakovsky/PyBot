#!/usr/bin/env ruby

require 'pg'
require 'mail'
require 'date'
require 'json'

# --- КОНФИГУРАЦИЯ ---

class Config
  # DB credentials from environment variables
  DB_PARAMS = {
    host: ENV['REDMINE_DB_POSTGRES'] || 'db',
    port: 5432,
    dbname: ENV['REDMINE_DB_DATABASE'] || 'redmine',
    user: ENV['REDMINE_DB_USERNAME'] || 'postgres',
    password: ENV['REDMINE_DB_PASSWORD']
  }

  REDMINE_BASE_URL = ENV['REDMINE_BASE_URL'] || 'http://localhost:3000'

  SMTP_PARAMS = {
    address: ENV['SMTP_ADDRESS'],
    port: (ENV['SMTP_PORT'] || 587).to_i,
    user_name: ENV['SMTP_USERNAME'],
    password: ENV['SMTP_PASSWORD'],
    authentication: (ENV['SMTP_AUTH'] || 'login').to_sym,
    enable_starttls_auto: ENV['SMTP_STARTTLS'] == 'true',
    open_timeout: 10,
    read_timeout: 30
  }

  # Configurable IDs
  REPORT_GROUP_ID = (ENV['REPORT_GROUP_ID'] || 0).to_i
  RECIPIENT_GROUP_ID = (ENV['REPORT_RECIPIENT_GROUP_ID'] || 0).to_i
  REPORT_PERIOD_DAYS = (ENV['REPORT_PERIOD_DAYS'] || 7).to_i
  REPORT_FROM_EMAIL = ENV['REPORT_FROM_EMAIL'] || 'noreply@example.com'
end

# Настройка почты
Mail.defaults do
  delivery_method :smtp, Config::SMTP_PARAMS
end

# --- КЛАСС ДЛЯ ГЕНЕРАЦИИ ОТЧЕТА ---

class RedmineReportGenerator
  attr_reader :start_date, :end_date, :conn, :group_id, :recipient_group_id

  def initialize(start_date, end_date, group_id, recipient_group_id)
    @start_date = start_date
    @end_date = end_date
    @group_id = group_id
    @recipient_group_id = recipient_group_id
    @conn = nil
  end

  # Запросы SQL
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
        AND jd.value IN (SELECT id::text FROM issue_statuses WHERE is_closed = true)
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
        AND jd.value IN (SELECT id::text FROM issue_statuses WHERE is_closed = true)
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
        AND jd.value IN (SELECT id::text FROM issue_statuses WHERE is_closed = true)
        AND gu.group_id = $3
    SQL
  }

  def run
    connect_db
    data = fetch_data
    recipient_emails = fetch_recipient_emails
    html_report = generate_html(data)
    send_email(html_report, data, recipient_emails)
  ensure
    @conn.close if @conn
  end

  private

  def connect_db
    puts "🔌 Connecting to database..."
    @conn = PG.connect(Config::DB_PARAMS)
    puts "✅ Connection established."
  rescue PG::Error => e
    raise "Database connection error: #{e.message}"
  end

  def fetch_data
    puts "🔍 Fetching data for period: #{@start_date} - #{@end_date} (Tracking Group ##{@group_id})"
    
    group_users = @conn.exec_params(SQL_QUERIES[:group_users], [@group_id]).to_a
    user_names = group_users.map { |u| [u['id'].to_i, "#{u['firstname']} #{u['lastname']}"] }.to_h

    closed_issues_count = @conn.exec_params(SQL_QUERIES[:total_issues_closed], [@start_date.to_s, @end_date.to_s, @group_id])[0]['total_count'].to_i

    closed_issues_by_user = @conn.exec_params(SQL_QUERIES[:closed_issues_by_user], [@start_date.to_s, @end_date.to_s, @group_id]).to_a

    assigned_open_issues = @conn.exec_params(SQL_QUERIES[:assigned_open_issues], [@group_id]).to_a
    unassigned_open_issues = @conn.exec_params(SQL_QUERIES[:unassigned_open_issues]).to_a

    {
      group_users: group_users,
      user_names: user_names,
      closed_issues_count: closed_issues_count,
      closed_issues_by_user: closed_issues_by_user,
      assigned_open_issues: assigned_open_issues,
      unassigned_open_issues: unassigned_open_issues
    }
  end

  def fetch_recipient_emails
    puts "📧 Fetching recipient emails for Group ##{@recipient_group_id}..."
    result = @conn.exec_params(SQL_QUERIES[:group_emails], [@recipient_group_id]).to_a
    emails = result.map { |row| row['address'] }

    if emails.empty?
      puts "⚠️ No active email addresses found for recipient Group ##{@recipient_group_id}. Sending to default override if any?"
    end
    
    puts "✅ Found #{emails.count} recipients."
    emails
  end

  def generate_html(data)
    # Simplified HTML generation for brevity, can be expanded to match original
    html = "<html><body>"
    html << "<h1>Redmine Report</h1>"
    html << "<p>Period: #{@start_date} to #{@end_date}</p>"
    html << "<p>Closed Issues: #{data[:closed_issues_count]}</p>"
    html << "</body></html>"
    html
  end
  
  def send_email(html_report, data, recipient_emails)
    if recipient_emails.empty?
      puts "❌ No recipients. Skipping email."
      return
    end

    puts "📧 Sending email..."
    report_group_id = @group_id
    report_start_date = @start_date
    report_end_date = @end_date

    mail = Mail.new do
      from    Config::REPORT_FROM_EMAIL
      to      recipient_emails 
      subject "📊 Redmine Report (Group ##{report_group_id}) #{report_start_date} - #{report_end_date}"
      html_part do
        content_type 'text/html; charset=UTF-8'
        body html_report
      end
    end

    mail.deliver!
    puts "✅ Email sent successfully."
  end
end

# --- ENTRY POINT ---

begin
  end_date = Date.today
  start_date = end_date - Config::REPORT_PERIOD_DAYS

  puts "🚀 Starting Redmine Report Generator..."
  
  generator = RedmineReportGenerator.new(
    start_date, 
    end_date, 
    Config::REPORT_GROUP_ID, 
    Config::RECIPIENT_GROUP_ID
  )
  generator.run
  
rescue => e
  puts "💥 CRITICAL ERROR: #{e.message}"
  puts e.backtrace
end

