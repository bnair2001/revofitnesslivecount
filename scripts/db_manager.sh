#!/bin/bash
# Database management script
# Provides easy access to backup/restore operations

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"

# Function to print colored output
print_header() {
    echo -e "${BOLD}${BLUE}================================================${NC}"
    echo -e "${BOLD}${BLUE}    Revo Fitness Database Management Tool${NC}"
    echo -e "${BOLD}${BLUE}================================================${NC}\n"
}

print_menu() {
    echo -e "${BOLD}Available operations:${NC}"
    echo -e "  ${GREEN}1.${NC} Create backup"
    echo -e "  ${GREEN}2.${NC} List backups"
    echo -e "  ${GREEN}3.${NC} Restore backup"
    echo -e "  ${GREEN}4.${NC} Setup automated backups (cron)"
    echo -e "  ${GREEN}5.${NC} View backup logs"
    echo -e "  ${GREEN}6.${NC} Clean old backups"
    echo -e "  ${GREEN}7.${NC} Database status"
    echo -e "  ${GREEN}q.${NC} Quit"
    echo
}

# Function to check if Docker is running and containers are up
check_docker_status() {
    if ! docker info >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Docker is not running${NC}"
        return 1
    fi
    
    if ! docker compose -f "$PROJECT_DIR/docker-compose.yml" ps | grep -q "Up"; then
        echo -e "${YELLOW}WARNING: Docker containers are not running${NC}"
        echo -e "Start them with: ${BOLD}docker compose up -d${NC}"
        return 1
    fi
    
    return 0
}

# Function to create backup
create_backup() {
    echo -e "${BLUE}Creating database backup...${NC}"
    if [ -x "$SCRIPT_DIR/backup_docker.sh" ]; then
        cd "$PROJECT_DIR" && "$SCRIPT_DIR/backup_docker.sh"
    else
        echo -e "${RED}ERROR: Backup script not found or not executable${NC}"
        return 1
    fi
}

# Function to list backups
list_backups() {
    echo -e "${BLUE}Available backups:${NC}"
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR"/revo_backup_*.sql.gz 2>/dev/null)" ]; then
        echo -e "${YELLOW}No backup files found${NC}"
        return 0
    fi
    
    local i=1
    for backup in $(ls -t "$BACKUP_DIR"/revo_backup_*.sql.gz 2>/dev/null); do
        local filename=$(basename "$backup")
        local size=$(du -h "$backup" | cut -f1)
        local date=$(stat -c %y "$backup" 2>/dev/null || stat -f %Sm "$backup" 2>/dev/null)
        echo -e "  ${GREEN}$i.${NC} $filename (${BOLD}$size${NC}) - $date"
        ((i++))
    done
}

# Function to restore backup
restore_backup() {
    echo -e "${BLUE}Restore database from backup${NC}"
    if [ -x "$SCRIPT_DIR/restore_docker.sh" ]; then
        cd "$PROJECT_DIR" && "$SCRIPT_DIR/restore_docker.sh"
    else
        echo -e "${RED}ERROR: Restore script not found or not executable${NC}"
        return 1
    fi
}

# Function to setup cron job
setup_cron() {
    echo -e "${BLUE}Setting up automated backups...${NC}"
    
    local cron_script="$SCRIPT_DIR/backup_cron.sh"
    if [ ! -x "$cron_script" ]; then
        echo -e "${RED}ERROR: Cron script not found or not executable${NC}"
        return 1
    fi
    
    echo -e "Choose backup frequency:"
    echo -e "  ${GREEN}1.${NC} Daily at 2 AM"
    echo -e "  ${GREEN}2.${NC} Twice daily (2 AM and 2 PM)"
    echo -e "  ${GREEN}3.${NC} Every 6 hours"
    echo -e "  ${GREEN}4.${NC} Custom schedule"
    echo
    read -p "Select option (1-4): " freq_choice
    
    local cron_schedule=""
    case $freq_choice in
        1) cron_schedule="0 2 * * *" ;;
        2) cron_schedule="0 2,14 * * *" ;;
        3) cron_schedule="0 */6 * * *" ;;
        4) 
            echo "Enter cron schedule (e.g., '0 2 * * *' for daily at 2 AM):"
            read -p "Schedule: " cron_schedule
            ;;
        *) 
            echo -e "${RED}Invalid option${NC}"
            return 1
            ;;
    esac
    
    local cron_line="$cron_schedule $cron_script"
    
    # Add to crontab
    (crontab -l 2>/dev/null | grep -v "$cron_script"; echo "$cron_line") | crontab -
    
    echo -e "${GREEN}Automated backup scheduled: $cron_schedule${NC}"
    echo -e "Logs will be written to: $PROJECT_DIR/logs/backup_cron.log"
}

# Function to view logs
view_logs() {
    local log_file="$PROJECT_DIR/logs/backup_cron.log"
    
    if [ ! -f "$log_file" ]; then
        echo -e "${YELLOW}No backup logs found${NC}"
        return 0
    fi
    
    echo -e "${BLUE}Recent backup log entries (last 50 lines):${NC}"
    tail -n 50 "$log_file"
}

# Function to clean old backups
clean_backups() {
    echo -e "${BLUE}Cleaning old backups...${NC}"
    
    if [ ! -d "$BACKUP_DIR" ]; then
        echo -e "${YELLOW}No backup directory found${NC}"
        return 0
    fi
    
    local backup_count=$(ls -1 "$BACKUP_DIR"/revo_backup_*.sql.gz 2>/dev/null | wc -l)
    echo -e "Current backups: $backup_count"
    
    if [ "$backup_count" -eq 0 ]; then
        echo -e "${YELLOW}No backups to clean${NC}"
        return 0
    fi
    
    read -p "Keep how many recent backups? (default: 30): " keep_count
    keep_count=${keep_count:-30}
    
    if ! [[ "$keep_count" =~ ^[0-9]+$ ]]; then
        echo -e "${RED}Invalid number${NC}"
        return 1
    fi
    
    cd "$BACKUP_DIR"
    local removed=0
    for old_backup in $(ls -t revo_backup_*.sql.gz 2>/dev/null | tail -n +$((keep_count + 1))); do
        echo -e "Removing: $old_backup"
        rm -f "$old_backup"
        ((removed++))
    done
    
    echo -e "${GREEN}Removed $removed old backups${NC}"
}

# Function to show database status
show_status() {
    echo -e "${BLUE}Database Status:${NC}"
    
    if ! check_docker_status; then
        return 1
    fi
    
    # Container status
    echo -e "\n${BOLD}Container Status:${NC}"
    docker compose -f "$PROJECT_DIR/docker-compose.yml" ps
    
    # Database connection test
    echo -e "\n${BOLD}Database Connection:${NC}"
    if docker exec revofitnesslivecount-db-1 pg_isready -U postgres >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Database is ready${NC}"
        
        # Database size
        local db_size=$(docker exec revofitnesslivecount-db-1 psql -U postgres -d revo -t -c "SELECT pg_size_pretty(pg_database_size('revo'));" 2>/dev/null | xargs)
        echo -e "Database size: ${BOLD}$db_size${NC}"
        
        # Record counts
        local gym_count=$(docker exec revofitnesslivecount-db-1 psql -U postgres -d revo -t -c "SELECT COUNT(*) FROM gym;" 2>/dev/null | xargs)
        local count_records=$(docker exec revofitnesslivecount-db-1 psql -U postgres -d revo -t -c "SELECT COUNT(*) FROM live_count;" 2>/dev/null | xargs)
        
        echo -e "Gyms: ${BOLD}$gym_count${NC}"
        echo -e "Live count records: ${BOLD}$count_records${NC}"
    else
        echo -e "${RED}✗ Database connection failed${NC}"
    fi
    
    # Backup status
    echo -e "\n${BOLD}Backup Status:${NC}"
    if [ -d "$BACKUP_DIR" ]; then
        local backup_count=$(ls -1 "$BACKUP_DIR"/revo_backup_*.sql.gz 2>/dev/null | wc -l)
        echo -e "Available backups: ${BOLD}$backup_count${NC}"
        
        if [ "$backup_count" -gt 0 ]; then
            local latest_backup=$(ls -t "$BACKUP_DIR"/revo_backup_*.sql.gz 2>/dev/null | head -1)
            local backup_age=$(stat -c %y "$latest_backup" 2>/dev/null || stat -f %Sm "$latest_backup" 2>/dev/null)
            echo -e "Latest backup: ${BOLD}$(basename "$latest_backup")${NC} ($backup_age)"
        fi
    else
        echo -e "${YELLOW}No backup directory found${NC}"
    fi
}

# Make scripts executable
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

# Main menu loop
main() {
    cd "$PROJECT_DIR"
    
    while true; do
        clear
        print_header
        
        # Quick status check
        if check_docker_status >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Docker containers are running${NC}\n"
        else
            echo -e "${YELLOW}⚠ Docker containers need to be started${NC}\n"
        fi
        
        print_menu
        read -p "Select operation: " choice
        
        echo
        case $choice in
            1)
                if check_docker_status; then
                    create_backup
                fi
                ;;
            2)
                list_backups
                ;;
            3)
                if check_docker_status; then
                    restore_backup
                fi
                ;;
            4)
                setup_cron
                ;;
            5)
                view_logs
                ;;
            6)
                clean_backups
                ;;
            7)
                show_status
                ;;
            q|Q|quit|exit)
                echo -e "${GREEN}Goodbye!${NC}"
                exit 0
                ;;
            *)
                echo -e "${RED}Invalid option${NC}"
                ;;
        esac
        
        echo
        read -p "Press Enter to continue..."
    done
}

# Run main function
main "$@"