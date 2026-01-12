namespace :email_reports do
  desc "Send pending email reports"
  task send_pending: :environment do
    EmailReport.active.ready_to_send.find_each do |report|
      EmailReportJob.perform_later(report.id)
    end
  end

  desc "Initialize demo email reports"
  task init_demo: :environment do
    group = Group.find_or_create_by!(lastname: 'Test Email Reports') do |g|
      g.users = User.where(admin: true).limit(3)
    end
    
    project = Project.active.first
    
    report = EmailReport.create!(
      name: "Demo Weekly Report",
      description: "Автоматически сгенерированный демонстрационный отчёт",
      schedule_type: "weekly",
      send_time: Time.parse("09:00"),
      author: User.active.admin.first,
      project: project,
      report_type: "issues",
      query_filters: {
        "status_id" => { "operator" => "o", "values" => [""] },
        "assigned_to_id" => { "operator" => "=", "values" => ["me"] }
      },
      columns: ["id", "subject", "status", "assigned_to", "updated_on"],
      group_by: "status",
      is_active: true
    )

    report.recipients.create!(recipient_type: "group", recipient_id: group.id)
    
    puts "✅ Demo отчёт создан: ID=#{report.id}"
    puts "👥 Группа получателей: #{group.lastname} (#{group.users.count} пользователей)"
    puts "📊 Тип отчёта: #{report.report_type}"
    puts "⏰ Расписание: #{report.schedule_type} в #{report.send_time.strftime('%H:%M')}"
  end
end
