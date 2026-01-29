import os
import shutil
import time
from pathlib import Path
import logging
import asyncio

logger = logging.getLogger(__name__)

class CleanupService:
    def __init__(self, workspace_path: str, retention_days: int = 7):
        self.workspace_path = Path(workspace_path)
        self.retention_seconds = retention_days * 86400

    def cleanup_old_tasks(self):
        """Scans workspace and deletes directories older than retention period."""
        if not self.workspace_path.exists():
            return

        now = time.time()
        count = 0
        
        logger.info("Starting cleanup of old task workspaces...")
        
        try:
            for item in self.workspace_path.iterdir():
                if item.is_dir():
                    # Check modification time
                    mtime = item.stat().st_mtime
                    if now - mtime > self.retention_seconds:
                        try:
                            # Use shutil.rmtree to remove directory
                            shutil.rmtree(item)
                            logger.info(f"Deleted old task workspace: {item.name}")
                            count += 1
                        except Exception as e:
                            logger.error(f"Failed to delete {item.name}: {e}")
                            
            logger.info(f"Cleanup finished. Removed {count} old workspaces.")
            
        except Exception as e:
            logger.error(f"Error during cleanup scan: {e}")

async def run_cleanup_loop(workspace_path: str, interval_hours: int = 24, retention_days: int = 7):
    """Background task to run cleanup periodically."""
    service = CleanupService(workspace_path, retention_days)
    
    while True:
        try:
            # Run cleanup in a thread to avoid blocking the event loop (file I/O)
            await asyncio.to_thread(service.cleanup_old_tasks)
        except Exception as e:
            logger.error(f"Cleanup loop error: {e}")
            
        # Sleep for the interval
        await asyncio.sleep(interval_hours * 3600)
