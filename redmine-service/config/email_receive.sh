#!/bin/bash

# Load environment variables if they are not set (though Docker passes them)
export RAILS_ENV=production
export LANG=C.UTF-8

cd /usr/src/redmine

# Execute the Rake task using credentials from environment variables
# This makes it more flexible than hardcoding credentials in the script
bundle exec rake redmine:email:receive_imap \
    host=${IMAP_HOST:-email.example.com} \
    port=${IMAP_PORT:-993} \
    ssl=${IMAP_SSL:-true} \
    username=${IMAP_USERNAME:-user@example.com} \
    password=${IMAP_PASSWORD:-secret} \
    project=${IMAP_PROJECT:-helpdesk} \
    tracker=${IMAP_TRACKER:-support} \
    unknown_user=${IMAP_UNKNOWN_USER:-accept} \
    no_permission_check=1

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "Email receive failed with code $EXIT_CODE"
fi

exit $EXIT_CODE

