#!/usr/bin/env python3
"""
Database restore script for Revo Fitness Live Count
Restores database from backup files with safety checks
"""

import os
import sys
import subprocess
import logging
import argparse
from pathlib import Path

# Add parent directory to path to import db config
sys.path.append(str(Path(__file__).parent.parent / "app"))

# Configuration
BACKUP_DIR = Path(__file__).parent.parent / "backups"
BACKUP_PREFIX = "revo_backup"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_db_url(db_url):
    """Parse database URL for psql parameters"""
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
    for i, backup_file in enumerate(backup_files, 1):
        size_mb = backup_file.stat().st_size / (1024 * 1024)
        import datetime as dt
        mtime = dt.datetime.fromtimestamp(backup_file.stat().st_mtime)
        logger.info(f"  {i}. {backup_file.name} ({size_mb:.2f} MB) - {mtime}")
    
    return backup_files


def confirm_restore(backup_file, db_config):
    """Ask for user confirmation before restore"""
    logger.warning("⚠️  DATABASE RESTORE WARNING ⚠️")
    logger.warning(f"This will COMPLETELY REPLACE the database '{db_config['dbname']}'")
    logger.warning(f"Host: {db_config['host']}:{db_config['port']}")
    logger.warning(f"Backup file: {backup_file.name}")
    logger.warning("ALL CURRENT DATA WILL BE LOST!")
    
    response = input("\nType 'yes' to continue with restore: ")
    return response.lower() == 'yes'


def test_database_connection(db_config):
    """Test if we can connect to the database"""
    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = db_config['password']
        
        result = subprocess.run([
            "psql",
            f"--host={db_config['host']}",
            f"--port={db_config['port']}",
            f"--username={db_config['user']}",
            "--dbname=postgres",  # Connect to default db first
            "--command=SELECT 1;"
        ], 
        env=env, 
        capture_output=True, 
        text=True
        )
        
        if result.returncode == 0:
            logger.info("Database connection successful")
            return True
        else:
            logger.error(f"Database connection failed: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False


def restore_backup(backup_file, db_url, verbose=False):
    """Restore database from backup file"""
    try:
        # Parse database connection
        db_config = parse_db_url(db_url)
        
        # Test connection first
        if not test_database_connection(db_config):
            raise Exception("Cannot connect to database server")
        
        # Confirm restore
        if not confirm_restore(backup_file, db_config):
            logger.info("Restore cancelled by user")
            return False
        
        logger.info(f"Starting restore from: {backup_file.name}")
        
        # Set password environment variable
        env = os.environ.copy()
        env["PGPASSWORD"] = db_config['password']
        
        # Build restore command
        if backup_file.name.endswith('.gz'):
            # Decompress and pipe to psql
            logger.info("Decompressing backup file...")
            
            gunzip_cmd = subprocess.Popen(
                ["gunzip", "-c", str(backup_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            psql_cmd = [
                "psql",
                f"--host={db_config['host']}",
                f"--port={db_config['port']}",
                f"--username={db_config['user']}",
                "--dbname=postgres",  # Connect to default db for restore
                "--quiet" if not verbose else "--echo-all",
                "--single-transaction"  # Wrap in transaction
            ]
            
            psql_proc = subprocess.Popen(
                psql_cmd,
                stdin=gunzip_cmd.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )
            
            gunzip_cmd.stdout.close()
            
            # Wait for both processes
            gunzip_stderr = gunzip_cmd.communicate()[1]
            psql_stdout, psql_stderr = psql_proc.communicate()
            
            if gunzip_cmd.returncode != 0:
                raise subprocess.CalledProcessError(
                    gunzip_cmd.returncode, 
                    ["gunzip"], 
                    gunzip_stderr
                )
            
            if psql_proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    psql_proc.returncode, 
                    psql_cmd, 
                    psql_stderr
                )
                
        else:
            # Direct restore from SQL file
            psql_cmd = [
                "psql",
                f"--host={db_config['host']}",
                f"--port={db_config['port']}",
                f"--username={db_config['user']}",
                "--dbname=postgres",  # Connect to default db for restore
                "--quiet" if not verbose else "--echo-all",
                "--single-transaction",  # Wrap in transaction
                f"--file={backup_file}"
            ]
            
            result = subprocess.run(
                psql_cmd,
                env=env,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode, 
                    psql_cmd, 
                    result.stderr
                )
        
        logger.info("Database restore completed successfully")
        
        # Fix collation version mismatch after restore
        logger.info("Refreshing collation versions...")
        try:
            # Refresh collation for postgres database
            refresh_cmd = [
                "psql",
                f"--host={db_config['host']}",
                f"--port={db_config['port']}",
                f"--username={db_config['user']}",
                "--dbname=postgres",
                "--quiet",
                "--command=ALTER DATABASE postgres REFRESH COLLATION VERSION;"
            ]
            
            result = subprocess.run(refresh_cmd, env=env, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Postgres database collation version refreshed")
            
            # Refresh collation for revo database
            refresh_cmd[5] = "--dbname=revo"
            refresh_cmd[7] = "ALTER DATABASE revo REFRESH COLLATION VERSION;"
            
            result = subprocess.run(refresh_cmd, env=env, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Revo database collation version refreshed")
                
        except Exception as e:
            logger.warning(f"Could not refresh collation versions: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Restore Revo Fitness database")
    parser.add_argument(
        "--file", 
        type=str, 
        help="Specific backup file to restore"
    )
    parser.add_argument(
        "--list", 
        action="store_true", 
        help="List available backups"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true", 
        help="Verbose output"
    )
    parser.add_argument(
        "--db-url", 
        type=str, 
        help="Database URL (default: from environment)"
    )
    
    args = parser.parse_args()
    
    # Get database URL
    if args.db_url:
        db_url = args.db_url
    else:
        from db import DB_URL
        db_url = DB_URL
    
    # List backups if requested
    if args.list:
        list_backups()
        return
    
    # Get backup file
    if args.file:
        backup_file = Path(args.file)
        if not backup_file.exists():
            # Try in backup directory
            backup_file = BACKUP_DIR / args.file
            if not backup_file.exists():
                logger.error(f"Backup file not found: {args.file}")
                sys.exit(1)
    else:
        # Interactive selection
        backups = list_backups()
        if not backups:
            logger.error("No backup files available")
            sys.exit(1)
        
        try:
            choice = int(input(f"\nSelect backup (1-{len(backups)}): "))
            if 1 <= choice <= len(backups):
                backup_file = backups[choice - 1]
            else:
                logger.error("Invalid selection")
                sys.exit(1)
        except (ValueError, KeyboardInterrupt):
            logger.info("Restore cancelled")
            sys.exit(0)
    
    # Perform restore
    try:
        success = restore_backup(backup_file, db_url, verbose=args.verbose)
        if success:
            logger.info("Restore process completed successfully")
        else:
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Restore cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Restore process failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()