#!/usr/bin/env python3
"""
Database backup script for Revo Fitness Live Count
Creates timestamped backups with compression and rotation
"""

import os
import sys
import subprocess
import datetime as dt
import logging
import argparse
from pathlib import Path

# Add parent directory to path to import db config
sys.path.append(str(Path(__file__).parent.parent / "app"))
from db import DB_URL

# Configuration
BACKUP_DIR = Path(__file__).parent.parent / "backups"
MAX_BACKUPS = 30  # Keep last 30 backups
BACKUP_PREFIX = "revo_backup"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def ensure_backup_dir():
    """Create backup directory if it doesn't exist"""
    BACKUP_DIR.mkdir(exist_ok=True)
    logger.info(f"Backup directory: {BACKUP_DIR}")


def parse_db_url(db_url):
    """Parse database URL for pg_dump parameters"""
    # Extract components from postgresql://user:pass@host:port/dbname
    if not db_url.startswith("postgresql://"):
        raise ValueError("Invalid PostgreSQL URL")
    
    # Remove protocol
    url_parts = db_url.replace("postgresql://", "")
    
    # Split user:pass@host:port/dbname
    auth_part, rest = url_parts.split("@")
    user, password = auth_part.split(":")
    
    host_port, dbname = rest.split("/")
    if ":" in host_port:
        host, port = host_port.split(":")
    else:
        host, port = host_port, "5432"
    
    return {
        "user": user,
        "password": password,
        "host": host,
        "port": port,
        "dbname": dbname
    }


def create_backup(compress=True, verbose=False):
    """Create database backup"""
    try:
        # Parse database connection
        db_config = parse_db_url(DB_URL)
        
        # Generate backup filename
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        if compress:
            backup_file = BACKUP_DIR / f"{BACKUP_PREFIX}_{timestamp}.sql.gz"
        else:
            backup_file = BACKUP_DIR / f"{BACKUP_PREFIX}_{timestamp}.sql"
        
        logger.info(f"Creating backup: {backup_file.name}")
        
        # Build pg_dump command
        pg_dump_cmd = [
            "pg_dump",
            f"--host={db_config['host']}",
            f"--port={db_config['port']}",
            f"--username={db_config['user']}",
            "--no-password",  # Use PGPASSWORD env var
            "--verbose" if verbose else "--quiet",
            "--clean",  # Include DROP commands
            "--if-exists",  # Use IF EXISTS for DROP commands
            "--create",  # Include CREATE DATABASE command
            db_config['dbname']
        ]
        
        # Set password environment variable
        env = os.environ.copy()
        env["PGPASSWORD"] = db_config['password']
        
        # Execute backup
        if compress:
            # Pipe to gzip
            with open(backup_file, 'wb') as f:
                pg_dump = subprocess.Popen(
                    pg_dump_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )
                gzip_cmd = subprocess.Popen(
                    ["gzip", "-c"],
                    stdin=pg_dump.stdout,
                    stdout=f,
                    stderr=subprocess.PIPE
                )
                pg_dump.stdout.close()
                
                # Wait for both processes
                pg_dump_stderr = pg_dump.communicate()[1]
                gzip_stderr = gzip_cmd.communicate()[1]
                
                if pg_dump.returncode != 0:
                    raise subprocess.CalledProcessError(
                        pg_dump.returncode, 
                        pg_dump_cmd, 
                        pg_dump_stderr
                    )
                if gzip_cmd.returncode != 0:
                    raise subprocess.CalledProcessError(
                        gzip_cmd.returncode, 
                        ["gzip"], 
                        gzip_stderr
                    )
        else:
            # Direct output to file
            with open(backup_file, 'w') as f:
                result = subprocess.run(
                    pg_dump_cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True
                )
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode, 
                        pg_dump_cmd, 
                        result.stderr
                    )
        
        # Get file size
        size_mb = backup_file.stat().st_size / (1024 * 1024)
        logger.info(f"Backup completed successfully: {backup_file.name} ({size_mb:.2f} MB)")
        
        return backup_file
        
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        # Clean up partial backup file
        if 'backup_file' in locals() and backup_file.exists():
            backup_file.unlink()
        raise


def rotate_backups():
    """Remove old backup files, keeping only the most recent ones"""
    try:
        # Get all backup files sorted by modification time
        backup_files = sorted(
            BACKUP_DIR.glob(f"{BACKUP_PREFIX}_*.sql*"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        if len(backup_files) <= MAX_BACKUPS:
            logger.info(f"Backup rotation: {len(backup_files)} files, no cleanup needed")
            return
        
        # Remove old backups
        files_to_remove = backup_files[MAX_BACKUPS:]
        logger.info(f"Backup rotation: removing {len(files_to_remove)} old files")
        
        for backup_file in files_to_remove:
            logger.info(f"Removing old backup: {backup_file.name}")
            backup_file.unlink()
            
    except Exception as e:
        logger.error(f"Backup rotation failed: {e}")


def list_backups():
    """List available backup files"""
    backup_files = sorted(
        BACKUP_DIR.glob(f"{BACKUP_PREFIX}_*.sql*"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    
    if not backup_files:
        logger.info("No backup files found")
        return []
    
    logger.info("Available backups:")
    for backup_file in backup_files:
        size_mb = backup_file.stat().st_size / (1024 * 1024)
        mtime = dt.datetime.fromtimestamp(backup_file.stat().st_mtime)
        logger.info(f"  {backup_file.name} ({size_mb:.2f} MB) - {mtime}")
    
    return backup_files


def main():
    parser = argparse.ArgumentParser(description="Backup Revo Fitness database")
    parser.add_argument(
        "--no-compress", 
        action="store_true", 
        help="Don't compress backup (default: compress with gzip)"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true", 
        help="Verbose output"
    )
    parser.add_argument(
        "--list", 
        action="store_true", 
        help="List available backups"
    )
    parser.add_argument(
        "--no-rotate", 
        action="store_true", 
        help="Skip backup rotation"
    )
    
    args = parser.parse_args()
    
    ensure_backup_dir()
    
    if args.list:
        list_backups()
        return
    
    try:
        # Create backup
        backup_file = create_backup(
            compress=not args.no_compress, 
            verbose=args.verbose
        )
        
        # Rotate old backups
        if not args.no_rotate:
            rotate_backups()
        
        logger.info("Backup process completed successfully")
        
    except Exception as e:
        logger.error(f"Backup process failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()