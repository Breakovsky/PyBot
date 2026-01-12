FROM redmine:6.0-alpine

# Install system dependencies
# We need build-base and ruby-dev for installing gems with native extensions if needed
# Supervisor is needed for process management
# Curl for healthchecks
RUN apk add --no-cache \
    supervisor \
    curl \
    bash \
    build-base \
    ruby-dev \
    libxml2-dev \
    libxslt-dev \
    postgresql-dev \
    tzdata

# Install additional gems used in the old project
RUN gem install whenever -v '1.0.0' && \
    gem install chronic -v '0.10.2' && \
    gem install mail && \
    gem install pg

# Copy configuration files
COPY config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY config/email_receive.sh /usr/local/bin/email_receive
COPY config/send_report.rb /usr/local/bin/send_report.rb

# Make scripts executable
RUN chmod +x /usr/local/bin/email_receive /usr/local/bin/send_report.rb

# Create log directories
RUN mkdir -p /var/log/supervisor /var/log/redmine

# Start via Supervisor
ENTRYPOINT ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

