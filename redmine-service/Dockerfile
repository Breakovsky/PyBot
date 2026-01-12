FROM redmine:6.0-alpine

# Install system dependencies
RUN apk add --no-cache \
    supervisor \
    curl \
    bash \
    build-base \
    ruby-dev \
    libxml2-dev \
    libxslt-dev \
    postgresql-dev \
    tzdata \
    git \
    imagemagick

# Install additional gems
RUN gem install whenever -v '1.0.0' && \
    gem install chronic -v '0.10.2' && \
    gem install mail && \
    gem install pg

# --- PLUGINS INSTALLATION ---

# 1. Recurring Tasks (Standard)
RUN git clone https://github.com/southbridgeio/redmine_recurring_tasks.git plugins/redmine_recurring_tasks && \
    cd plugins/redmine_recurring_tasks && \
    git checkout master 

# 2. Spent Time Required (Skipped due to git auth issues, using custom redmine_issue_guard instead)
# RUN git clone https://github.com/juggler/redmine_spent_time_required.git plugins/redmine_spent_time_required

# Copy Custom Plugins (Using root context paths)
COPY redmine-service/plugins/email_reports /usr/src/redmine/plugins/email_reports
COPY redmine-service/plugins/redmine_issue_guard /usr/src/redmine/plugins/redmine_issue_guard

# Install plugin dependencies
RUN bundle config set --local without 'development test' && \
    bundle install

# Copy Supervisor config
COPY redmine-service/config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy Init script
COPY redmine-service/init.sh /docker-entrypoint-custom.sh
RUN chmod +x /docker-entrypoint-custom.sh

# Create log directories
RUN mkdir -p /var/log/supervisor /var/log/redmine && \
    chmod -R 777 /var/log && \
    chown -R redmine:redmine /usr/src/redmine

ENTRYPOINT ["/docker-entrypoint-custom.sh"]
