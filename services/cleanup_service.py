import os
import shutil
import time
from pathlib import Path
import logging
import asyncio
from sqlmodel import Session, select
from tricys_backend.models.task import Task
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class CleanupService:
    def __init__(self, workspace_path: str, retention_days: int = 7):
        self.workspace_path = Path(workspace_path)
        self.retention_seconds = retention_days * 86400
        self.retention_days = retention_days

    def cleanup_old_tasks(self, db_engine):
        """
        Scans workspace and deletes directories older than retention period.
        Now checks database to ensure only completed/failed/stopped tasks are cleaned up.
        """
        if not self.workspace_path.exists():
            return

        now = time.time()
        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
        count = 0
        
        logger.info(f"Starting cleanup of task workspaces older than {self.retention_days} days...")
        
        try:
            # Get tasks from database that are candidates for cleanup
            with Session(db_engine) as session:
                # Only cleanup tasks that are in terminal states and old enough
                eligible_tasks = session.exec(
                    select(Task).where(
                        Task.status.in_(["COMPLETED", "FAILED", "STOPPED"]),
                        Task.updated_at < cutoff_date
                    )
                ).all()
                
                eligible_task_ids = {task.id for task in eligible_tasks}
                logger.info(f"Found {len(eligible_task_ids)} eligible tasks for cleanup in database")
            
            # Scan workspace directories
            for date_dir in self.workspace_path.iterdir():
                if not date_dir.is_dir():
                    continue
                    
                # Iterate through task directories within each date directory
                for task_dir in date_dir.iterdir():
                    if not task_dir.is_dir():
                        continue
                    
                    task_id = task_dir.name
                    
                    # Check modification time
                    mtime = task_dir.stat().st_mtime
                    is_old_enough = (now - mtime) > self.retention_seconds
                    
                    if is_old_enough and task_id in eligible_task_ids:
                        try:
                            # Safe to delete - task is in terminal state and old
                            shutil.rmtree(task_dir)
                            logger.info(f"Deleted old task workspace: {task_id}")
                            count += 1
                        except Exception as e:
                            logger.error(f"Failed to delete {task_id}: {e}")
                    elif is_old_enough and task_id not in eligible_task_ids:
                        # Old but not in database or not in terminal state - skip with warning
                        logger.warning(f"Skipping cleanup of {task_id}: not in eligible state or not in database")
                
                # Clean up empty date directories
                try:
                    if date_dir.is_dir() and not any(date_dir.iterdir()):
                        date_dir.rmdir()
                        logger.info(f"Removed empty date directory: {date_dir.name}")
                except Exception as e:
                    logger.debug(f"Could not remove date directory {date_dir.name}: {e}")
                            
            logger.info(f"Cleanup finished. Removed {count} old workspaces.")
            
        except Exception as e:
            logger.error(f"Error during cleanup scan: {e}")

async def run_cleanup_loop(workspace_path: str, interval_hours: int = 24, retention_days: int = 7):
    """Background task to run cleanup periodically."""
    from tricys_backend.services.task_queue import db_engine
    
    service = CleanupService(workspace_path, retention_days)
    
    while True:
        try:
            # Run cleanup in a thread to avoid blocking the event loop (file I/O)
            await asyncio.to_thread(service.cleanup_old_tasks, db_engine)
        except Exception as e:
            logger.error(f"Cleanup loop error: {e}")
            
        # Sleep for the interval
        await asyncio.sleep(interval_hours * 3600)
