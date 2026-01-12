#!/bin/bash
set -e

# Run standard entrypoint logic check (db setup)
# But simply: wait for DB and migrate
echo "Waiting for DB..."
sleep 10

echo "Running migrations..."
bundle exec rake db:migrate RAILS_ENV=production
bundle exec rake redmine:plugins:migrate RAILS_ENV=production

echo "Starting Supervisor..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf

