#!/bin/bash
# Docker-based database backup script
# Works with Docker Compose setup

set -e

# Configuration
BACKUP_DIR="./backups"
COMPOSE_FILE="docker-compose.yml"
DB_CONTAINER="revofitnesslivecount-db-1"
BACKUP_PREFIX="revo_backup"
MAX_BACKUPS=30

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Function to log messages
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" >&2
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    error "Docker is not running"
    exit 1
fi

# Check if containers are running
if ! docker compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
    error "Docker containers are not running. Start them with: docker compose up -d"
    exit 1
fi

# Generate backup filename
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_PREFIX}_${TIMESTAMP}.sql.gz"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_FILE"

log "Starting database backup..."
log "Backup file: $BACKUP_FILE"

# Create backup using docker exec
if docker exec "$DB_CONTAINER" pg_dump -U postgres -d revo --clean --if-exists --create | gzip > "$BACKUP_PATH"; then
    # Get file size
    SIZE=$(du -h "$BACKUP_PATH" | cut -f1)
    log "Backup completed successfully: $BACKUP_FILE ($SIZE)"
else
    error "Backup failed"
    rm -f "$BACKUP_PATH"  # Clean up partial backup
    exit 1
fi

# Rotate old backups
log "Rotating old backups (keeping last $MAX_BACKUPS)..."
cd "$BACKUP_DIR"
ls -t ${BACKUP_PREFIX}_*.sql.gz 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | while read -r old_backup; do
    if [ -f "$old_backup" ]; then
        log "Removing old backup: $old_backup"
        rm -f "$old_backup"
    fi
done

log "Backup process completed successfully"

# List current backups
BACKUP_COUNT=$(ls -1 ${BACKUP_PREFIX}_*.sql.gz 2>/dev/null | wc -l)
log "Total backups available: $BACKUP_COUNT"