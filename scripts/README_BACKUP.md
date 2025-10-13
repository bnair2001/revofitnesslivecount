# Database Backup and Restore System

A comprehensive backup and restore system for the Revo Fitness Live Count PostgreSQL database.

## 📁 Files Overview

```
scripts/
├── backup_db.py          # Python-based backup script
├── restore_db.py         # Python-based restore script  
├── backup_docker.sh      # Docker-based backup script
├── restore_docker.sh     # Docker-based restore script
├── backup_cron.sh        # Automated backup cron job
├── db_manager.sh         # Interactive management tool
└── README_BACKUP.md      # This documentation

backups/                  # Backup files storage
logs/                    # Backup operation logs
```

## 🚀 Quick Start

### Using the Management Tool (Recommended)

The easiest way to manage backups:

```bash
# Make executable and run
chmod +x scripts/db_manager.sh
./scripts/db_manager.sh
```

This provides an interactive menu with all backup/restore operations.

### Manual Operations

#### Create Backup
```bash
# Docker-based (recommended for Docker setup)
chmod +x scripts/backup_docker.sh
./scripts/backup_docker.sh

# Python-based (more features)
python3 scripts/backup_db.py
```

#### Restore Backup
```bash
# Docker-based (recommended)
chmod +x scripts/restore_docker.sh
./scripts/restore_docker.sh

# Python-based
python3 scripts/restore_db.py
```

## 📊 Features

### Backup Features
- ✅ **Compressed backups** (gzip) to save space
- ✅ **Automatic rotation** (keeps last 30 backups by default)
- ✅ **Timestamped filenames** for easy identification
- ✅ **Size reporting** for backup files
- ✅ **Error handling** with cleanup on failure
- ✅ **Docker integration** for containerized environments

### Restore Features
- ✅ **Interactive backup selection** 
- ✅ **Safety confirmations** to prevent accidental overwrites
- ✅ **Database connection testing**
- ✅ **Transaction safety** (single-transaction restores)
- ✅ **Automatic service management** (stops/starts app during restore)

### Automation Features
- ✅ **Cron job support** for scheduled backups
- ✅ **Log rotation** to manage log file sizes
- ✅ **Multiple backup frequencies** (daily, twice daily, every 6 hours)
- ✅ **Email notifications** (when configured with system mail)

## 📋 Detailed Usage

### 1. Docker-based Scripts (Recommended)

These scripts work directly with your Docker Compose setup:

#### Backup
```bash
./scripts/backup_docker.sh
```

**What it does:**
- Connects to the PostgreSQL container
- Creates compressed SQL dump
- Saves to `./backups/` directory
- Rotates old backups automatically
- Reports backup size and status

#### Restore
```bash
# Interactive selection
./scripts/restore_docker.sh

# Restore specific file
./scripts/restore_docker.sh --file backups/revo_backup_20241013_143022.sql.gz

# List available backups
./scripts/restore_docker.sh --list
```

**What it does:**
- Shows available backups
- Asks for confirmation (safety check)
- Stops application container during restore
- Restores database with transaction safety
- Restarts application container

### 2. Python Scripts

More advanced scripts with additional features:

#### Backup
```bash
# Basic backup
python3 scripts/backup_db.py

# Uncompressed backup
python3 scripts/backup_db.py --no-compress

# Verbose output
python3 scripts/backup_db.py --verbose

# Skip rotation
python3 scripts/backup_db.py --no-rotate

# List existing backups
python3 scripts/backup_db.py --list
```

#### Restore
```bash
# Interactive restore
python3 scripts/restore_db.py

# Restore specific file
python3 scripts/restore_db.py --file backups/revo_backup_20241013_143022.sql.gz

# Verbose output
python3 scripts/restore_db.py --verbose

# Custom database URL
python3 scripts/restore_db.py --db-url "postgresql://user:pass@host:5432/dbname"
```

### 3. Automated Backups

#### Setup Cron Job
```bash
# Using management tool (recommended)
./scripts/db_manager.sh
# Then select option 4

# Manual setup - daily at 2 AM
echo "0 2 * * * $(pwd)/scripts/backup_cron.sh" | crontab -

# Manual setup - twice daily (2 AM and 2 PM)
echo "0 2,14 * * * $(pwd)/scripts/backup_cron.sh" | crontab -
```

#### View Backup Logs
```bash
# Recent log entries
tail -f logs/backup_cron.log

# Or use management tool
./scripts/db_manager.sh
# Then select option 5
```

## 🔧 Configuration

### Environment Variables

The scripts use these environment variables:

```bash
# Database connection (from docker-compose.yml)
DATABASE_URL=postgresql://postgres:postgres@db:5432/revo
```

### Customizable Settings

Edit the scripts to change:

```bash
# In backup scripts
MAX_BACKUPS=30        # Number of backups to keep
BACKUP_PREFIX="revo_backup"  # Backup filename prefix

# In cron script  
LOG_RETENTION_DAYS=30 # Days to keep logs
MAX_LOG_SIZE=10485760 # 10MB log rotation size
```

## 📁 Backup File Format

Backup files follow this naming convention:
```
revo_backup_YYYYMMDD_HHMMSS.sql.gz
```

Examples:
- `revo_backup_20241013_143022.sql.gz` - Oct 13, 2024 at 14:30:22
- `revo_backup_20241013_020001.sql.gz` - Oct 13, 2024 at 02:00:01

## 🛡️ Safety Features

### Backup Safety
- **Atomic operations**: Backup files are written completely or not at all
- **Cleanup on failure**: Partial backups are automatically removed
- **Size verification**: Reports backup file sizes for validation
- **Connection testing**: Verifies database connectivity before backup

### Restore Safety
- **Multiple confirmations**: Requires explicit "yes" to proceed
- **Service management**: Stops application to prevent data corruption
- **Transaction safety**: Uses single-transaction mode for consistency
- **Rollback capable**: Failed restores don't leave partial data

## 📊 Monitoring and Maintenance

### Check Backup Status
```bash
# Using management tool
./scripts/db_manager.sh
# Select option 7 for database status

# Manual check
ls -la backups/
du -sh backups/
```

### Clean Old Backups
```bash
# Using management tool (recommended)
./scripts/db_manager.sh
# Select option 6

# Manual cleanup (keep last 10)
cd backups
ls -t revo_backup_*.sql.gz | tail -n +11 | xargs rm -f
```

### Log Management
```bash
# View recent backup activity
tail -n 50 logs/backup_cron.log

# Check log file size
du -h logs/backup_cron.log

# Archive old logs
mv logs/backup_cron.log logs/backup_cron.log.$(date +%Y%m%d)
```

## 🚨 Troubleshooting

### Common Issues

#### Docker Container Not Running
```bash
# Check container status
docker-compose ps

# Start containers
docker-compose up -d

# Check logs
docker-compose logs db
```

#### Permission Issues
```bash
# Make scripts executable
chmod +x scripts/*.sh

# Fix backup directory permissions
mkdir -p backups
chmod 755 backups
```

#### Database Connection Issues
```bash
# Test database connection
docker exec revofitnesslivecount-db-1 pg_isready -U postgres

# Check environment variables
docker-compose config
```

#### Backup File Corruption
```bash
# Test compressed backup
gunzip -t backups/revo_backup_20241013_143022.sql.gz

# Test SQL syntax (first few lines)
gunzip -c backups/revo_backup_20241013_143022.sql.gz | head -20
```

### Recovery Scenarios

#### Full Database Loss
1. Ensure containers are running: `docker-compose up -d`
2. Use restore script: `./scripts/restore_docker.sh`
3. Select most recent backup
4. Verify data after restore

#### Partial Data Corruption
1. Create current backup first: `./scripts/backup_docker.sh`
2. Restore from known good backup
3. Compare data between backups if needed

#### Backup Directory Loss
1. Check if backups exist in other locations
2. Create new backup immediately: `./scripts/backup_docker.sh`
3. Set up automated backups: `./scripts/db_manager.sh`

## 📈 Best Practices

### Backup Strategy
- **Daily automated backups** for production
- **Pre-deployment backups** before updates
- **Multiple retention periods** (daily, weekly, monthly)
- **Off-site backup storage** for disaster recovery

### Testing
- **Test restores regularly** to verify backup integrity
- **Document recovery procedures** for your team
- **Monitor backup sizes** for unusual changes
- **Validate backup compression** doesn't corrupt data

### Security
- **Restrict backup file permissions**: `chmod 600 backups/*.gz`
- **Secure backup storage location**
- **Use encrypted storage** for sensitive data
- **Regular security audits** of backup processes

## 🔗 Integration

### CI/CD Pipeline
```bash
# Pre-deployment backup
- name: Create backup before deployment
  run: ./scripts/backup_docker.sh

# Post-deployment verification  
- name: Verify deployment
  run: ./scripts/db_manager.sh --status
```

### Monitoring Systems
```bash
# Check backup age (alert if > 25 hours)
find backups -name "revo_backup_*.sql.gz" -mtime -1 | wc -l

# Check backup size (alert on significant changes)
ls -la backups/revo_backup_*.sql.gz | tail -5
```

---

## 📞 Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Docker and PostgreSQL logs
3. Test database connectivity manually
4. Verify file permissions and disk space

## 🔄 Updates

To update the backup system:
1. Backup current configuration
2. Replace script files
3. Test with a manual backup/restore
4. Update cron jobs if needed