#!/bin/bash
set -e

# Fix permissions for mounted volumes
# This is crucial because volumes are mounted at runtime, overriding Dockerfile permissions
echo "Fixing permissions..."
chown -R redmine:redmine /usr/src/redmine/files
chown -R redmine:redmine /usr/src/redmine/log
chown -R redmine:redmine /usr/src/redmine/public/plugin_assets
chown -R redmine:redmine /usr/src/redmine/tmp
chown -R redmine:redmine /usr/src/redmine/db
chown -R redmine:redmine /var/log/redmine
chown -R redmine:redmine /var/log/supervisor

# Wait for DB
echo "Waiting for DB..."
sleep 10

# Run migrations as redmine user to avoid permission issues later
echo "Running migrations..."
su -s /bin/bash redmine -c "bundle exec rake db:migrate RAILS_ENV=production"
su -s /bin/bash redmine -c "bundle exec rake redmine:plugins:migrate RAILS_ENV=production"

echo "Starting Supervisor..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
