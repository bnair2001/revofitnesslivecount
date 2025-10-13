#!/bin/bash
# Docker-based database restore script
# Works with Docker Compose setup

set -e

# Configuration
BACKUP_DIR="./backups"
COMPOSE_FILE="docker-compose.yml"
DB_CONTAINER="revofitnesslivecount-db-1"
BACKUP_PREFIX="revo_backup"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] INFO:${NC} $1"
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

# Function to list available backups
list_backups() {
    echo -e "\n${BLUE}Available backups:${NC}"
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR"/${BACKUP_PREFIX}_*.sql.gz 2>/dev/null)" ]; then
        echo "No backup files found in $BACKUP_DIR"
        return 1
    fi
    
    local i=1
    for backup in $(ls -t "$BACKUP_DIR"/${BACKUP_PREFIX}_*.sql.gz); do
        local filename=$(basename "$backup")
        local size=$(du -h "$backup" | cut -f1)
        local date=$(stat -c %y "$backup" 2>/dev/null || stat -f %Sm "$backup" 2>/dev/null)
        echo "  $i. $filename ($size) - $date"
        ((i++))
    done
    return 0
}

# Function to get user confirmation
confirm_restore() {
    local backup_file="$1"
    
    warn "⚠️  DATABASE RESTORE WARNING ⚠️"
    warn "This will COMPLETELY REPLACE the current database!"
    warn "Backup file: $(basename "$backup_file")"
    warn "ALL CURRENT DATA WILL BE LOST!"
    
    echo
    read -p "Type 'yes' to continue with restore: " response
    if [ "$response" != "yes" ]; then
        log "Restore cancelled by user"
        exit 0
    fi
}

# Function to restore from backup
restore_backup() {
    local backup_file="$1"
    
    if [ ! -f "$backup_file" ]; then
        error "Backup file not found: $backup_file"
        exit 1
    fi
    
    confirm_restore "$backup_file"
    
    log "Starting database restore from: $(basename "$backup_file")"
    
    # Stop the application container to prevent connections
    log "Stopping application container..."
    docker compose -f "$COMPOSE_FILE" stop dash
    
    # Wait a moment for connections to close
    sleep 2
    
    # Restore the database
    if gunzip -c "$backup_file" | docker exec -i "$DB_CONTAINER" psql -U postgres -d postgres; then
        log "Database restore completed successfully"
        
        # Fix collation version mismatch after restore
        log "Refreshing collation versions..."
        if docker exec "$DB_CONTAINER" psql -U postgres -d postgres -c "ALTER DATABASE postgres REFRESH COLLATION VERSION;" >/dev/null 2>&1; then
            log "Postgres database collation version refreshed"
        fi
        
        if docker exec "$DB_CONTAINER" psql -U postgres -d revo -c "ALTER DATABASE revo REFRESH COLLATION VERSION;" >/dev/null 2>&1; then
            log "Revo database collation version refreshed"
        fi
    else
        error "Database restore failed"
        # Restart application container even if restore failed
        log "Restarting application container..."
        docker compose -f "$COMPOSE_FILE" start dash
        exit 1
    fi
    
    # Restart application container
    log "Restarting application container..."
    docker compose -f "$COMPOSE_FILE" start dash
    
    log "Restore process completed successfully"
}

# Parse command line arguments
BACKUP_FILE=""
LIST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --file|-f)
            BACKUP_FILE="$2"
            shift 2
            ;;
        --list|-l)
            LIST_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  -f, --file FILENAME   Restore from specific backup file"
            echo "  -l, --list           List available backups"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# List backups if requested
if [ "$LIST_ONLY" = true ]; then
    list_backups
    exit 0
fi

# If no specific file provided, show interactive selection
if [ -z "$BACKUP_FILE" ]; then
    if ! list_backups; then
        exit 1
    fi
    
    echo
    read -p "Select backup number (or 'q' to quit): " selection
    
    if [ "$selection" = "q" ] || [ "$selection" = "quit" ]; then
        log "Restore cancelled by user"
        exit 0
    fi
    
    # Validate selection
    if ! [[ "$selection" =~ ^[0-9]+$ ]]; then
        error "Invalid selection: $selection"
        exit 1
    fi
    
    # Get the selected backup file
    BACKUP_FILE=$(ls -t "$BACKUP_DIR"/${BACKUP_PREFIX}_*.sql.gz | sed -n "${selection}p")
    
    if [ -z "$BACKUP_FILE" ]; then
        error "Invalid selection: $selection"
        exit 1
    fi
else
    # Handle relative path
    if [[ "$BACKUP_FILE" != /* ]]; then
        # Try in backup directory first
        if [ -f "$BACKUP_DIR/$BACKUP_FILE" ]; then
            BACKUP_FILE="$BACKUP_DIR/$BACKUP_FILE"
        elif [ ! -f "$BACKUP_FILE" ]; then
            error "Backup file not found: $BACKUP_FILE"
            exit 1
        fi
    fi
fi

# Perform the restore
restore_backup "$BACKUP_FILE"