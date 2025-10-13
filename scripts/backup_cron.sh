#!/bin/bash
# Automated backup cron script
# Run daily backups with logging

# Change to the project directory
cd "$(dirname "$0")/.."

# Configuration
BACKUP_SCRIPT="./scripts/backup_docker.sh"
LOG_DIR="./logs"
LOG_FILE="$LOG_DIR/backup_cron.log"

# Create log directory
mkdir -p "$LOG_DIR"

# Function to log with timestamp
log_with_timestamp() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Redirect all output to log file
{
    log_with_timestamp "Starting automated backup..."
    
    if [ -x "$BACKUP_SCRIPT" ]; then
        $BACKUP_SCRIPT
        if [ $? -eq 0 ]; then
            log_with_timestamp "Automated backup completed successfully"
        else
            log_with_timestamp "Automated backup failed with exit code $?"
        fi
    else
        log_with_timestamp "ERROR: Backup script not found or not executable: $BACKUP_SCRIPT"
        exit 1
    fi
    
    log_with_timestamp "Automated backup process finished"
    
} >> "$LOG_FILE" 2>&1

# Keep only last 30 days of logs
find "$LOG_DIR" -name "backup_cron.log.*" -mtime +30 -delete 2>/dev/null || true

# Rotate log if it gets too big (>10MB)
if [ -f "$LOG_FILE" ] && [ $(stat -c%s "$LOG_FILE" 2>/dev/null || stat -f%z "$LOG_FILE" 2>/dev/null || echo 0) -gt 10485760 ]; then
    mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d_%H%M%S)"
    touch "$LOG_FILE"
fi