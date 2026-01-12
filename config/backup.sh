#!/bin/bash

echo "Starting backup service..."
echo "Backup dir: /backups"

while true; do
    DATE=$(date +%Y%m%d_%H%M%S)
    BACKUP_PATH="/backups/redmine_backup_$DATE"
    mkdir -p $BACKUP_PATH
    
    echo "--- Starting backup cycle at $(date) ---"
    
    # 1. DB Backup
    # Uses PGPASSWORD/PGUSER/PGHOST from env
    pg_dump -h db -U $POSTGRES_USER -d $POSTGRES_DB > $BACKUP_PATH/db_dump.sql
    
    if [ $? -ne 0 ]; then
        echo "ERROR: Database backup FAILED."
        rm -rf $BACKUP_PATH
    else
        echo "Database dumped."
    fi
    
    # 2. Files Backup
    if [ -d "/usr/src/redmine/files" ]; then
        cp -r /usr/src/redmine/files $BACKUP_PATH/files
        echo "Files copied."
    fi

    # 3. Archive
    tar -czf /backups/backup_$DATE.tar.gz -C /backups redmine_backup_$DATE
    rm -rf $BACKUP_PATH
    
    echo "SUCCESS: Backup created at /backups/backup_$DATE.tar.gz"
    
    # Cleanup old backups (keep last 7 days)
    find /backups -name "backup_*.tar.gz" -mtime +7 -delete
    
    echo "Cycle finished. Sleeping for 24 hours..."
    sleep 86400
done

