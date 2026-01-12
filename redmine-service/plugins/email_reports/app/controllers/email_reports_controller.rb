class EmailReportsController < ApplicationController
  layout 'admin'
  before_action :require_admin
  before_action :find_email_report, only: [:show, :edit, :update, :destroy, :test, :toggle_active]

  def index
    @email_reports = EmailReport.includes(:author, :recipients).order(:name)
  end

  def show
    @data = @email_report.generate_report_data
  end

  def new
    @email_report = EmailReport.new(
      author: User.current,
      send_time: Time.parse('08:00'),
      schedule_type: 'weekly',
      report_type: 'issues',
      query_filters: { "status_id" => { "operator" => "o", "values" => [""] } },
      columns: %w[id subject status assigned_to updated_on],
      report_period_days: 7
    )
  end

  def create
    @email_report = EmailReport.new(email_report_params)
    @email_report.author = User.current

    if @email_report.save
      update_recipients
      flash[:notice] = l(:notice_successful_create)
      redirect_to email_reports_path
    else
      render :new
    end
  end

  def edit
  end

  def update
    if @email_report.update(email_report_params)
      update_recipients
      flash[:notice] = l(:notice_successful_update)
      redirect_to email_reports_path
    else
      render :edit
    end
  end

  def destroy
    @email_report.destroy
    flash[:notice] = l(:notice_successful_delete)
    redirect_to email_reports_path
  end

  def test
    EmailReportJob.perform_now(@email_report.id)
    flash[:notice] = l(:notice_email_report_test_sent)
  rescue => e
    flash[:error] = "#{l(:notice_email_report_test_failed)}: #{e.message}"
  ensure
    redirect_to email_reports_path
  end

  def toggle_active
    @email_report.update(is_active: !@email_report.is_active)
    flash[:notice] = @email_report.is_active ? l(:notice_email_report_activated) : l(:notice_email_report_deactivated)
    redirect_to email_reports_path
  end

  def available_principals
    scope = Principal.active.like(params[:q]).limit(20)
    scope = scope.where(type: params[:type]) if params[:type].present?
    
    principals = scope.map do |p|
      extra_info = ""
      if p.is_a?(User)
        groups = p.groups.map(&:lastname).join(', ')
        extra_info = groups.present? ? "(#{groups})" : ""
      end

      {
        id: p.id,
        name: p.name,
        type: p.type,
        extra: extra_info,
        icon: p.is_a?(User) ? 'icon-user' : 'icon-group'
      }
    end
    
    render json: principals
  rescue => e
    render json: { error: e.message }, status: 500
  end

  private

  def find_email_report
    @email_report = EmailReport.find(params[:id])
  rescue ActiveRecord::RecordNotFound
    render_404
  end

  def email_report_params
    # 1. Разрешаем стандартные параметры + week_days массив + time_hour + time_min
    p = params.require(:email_report).permit(
      :name, :description, :schedule_type, :schedule_cron, 
      :project_id, :report_type, :group_by, :is_active, 
      :source_group_id, :report_period_days, 
      { query_filters: {} }, { columns: [] }, { week_days: [] },
      :time_hour, :time_min
    )

    # 2. СБОРКА ВРЕМЕНИ ИЗ СЕЛЕКТОВ
    if params[:email_report][:time_hour].present? && params[:email_report][:time_min].present?
      # Склеиваем "08" и "30" в "08:30"
      p[:send_time] = "#{params[:email_report][:time_hour]}:#{params[:email_report][:time_min]}"
    end

    # 3. ЛОГИКА ДНЕЙ НЕДЕЛИ (Weekly)
    if p[:schedule_type] == 'weekly'
      if params[:email_report][:week_days].present?
        # Склеиваем массив ["1", "5"] в строку "1,5"
        p[:schedule_cron] = params[:email_report][:week_days].join(',')
      else
        # Дефолт, если не выбрано
        p[:schedule_cron] = '1' 
      end
    end

    # 4. Очистка параметров перед передачей в модель
    # Удаляем week_days, time_hour, time_min - они не нужны в update(attributes)
    p.except(:week_days, :time_hour, :time_min)
  end

  def update_recipients
    incoming_recipients = []
    
    # UI (User/Group)
    if params[:recipients_data].present?
      params[:recipients_data].each do |_, data|
        next if data[:id].blank? || data[:type].blank?
        
        type = data[:type] == 'User' ? 'user' : 'group'
        incoming_recipients << { type: type, id: data[:id].to_i, email: nil }
      end
    end
    
    # Textarea Emails
    if params[:recipient_emails].present?
      params[:recipient_emails].split("\n").map(&:strip).reject(&:blank?).each do |email|
        incoming_recipients << { type: 'email', id: nil, email: email }
      end
    end

    # Удаление отсутствующих
    @email_report.recipients.each do |existing|
      found = incoming_recipients.find do |inc|
        if existing.recipient_type == 'email'
          inc[:type] == 'email' && inc[:email] == existing.email
        else
          inc[:type] == existing.recipient_type && inc[:id] == existing.recipient_id
        end
      end
      
      existing.destroy unless found
    end

    # Создание новых
    incoming_recipients.each do |inc|
      exists = @email_report.recipients.exists?(
        recipient_type: inc[:type],
        recipient_id: inc[:id],
        email: inc[:email]
      )
      
      unless exists
        @email_report.recipients.create!(
          recipient_type: inc[:type],
          recipient_id: inc[:id],
          email: inc[:email]
        )
      end
    end
  end
end
