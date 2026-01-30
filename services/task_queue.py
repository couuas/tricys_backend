import asyncio
import logging
from sqlmodel import Session, select
from tricys_backend.models.task import Task
from tricys_backend.services.engine import SimulationEngine
from tricys_backend.services.file_manager import FileManager
from tricys_backend.core.config import settings
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine
import psutil

# We need a separate engine for the worker thread/loop
db_engine = create_engine(settings.DATABASE_URL)

logger = logging.getLogger(__name__)

class TaskQueue:
    _queue = asyncio.Queue()
    _engine_service = SimulationEngine()
    
    @classmethod
    async def add_task(cls, task_id: str):
        await cls._queue.put(task_id)
        logger.info(f"Task {task_id} added to queue")

    @classmethod
    async def worker(cls):
        logger.info("TaskQueue worker started")
        while True:
            task_id = await cls._queue.get()
            logger.info(f"Processing task {task_id}")
            
            try:
                await cls._process_task(task_id)
            except Exception as e:
                logger.error(f"Error processing task {task_id}: {e}")
            finally:
                cls._queue.task_done()

    @classmethod
    async def _process_task(cls, task_id: str):
        # Create a new session for this operation
        with Session(db_engine) as session:
            task = session.get(Task, task_id)
            if not task:
                logger.error(f"Task {task_id} not found in DB")
                return

            if task.status == "STOPPED":
                logger.info(f"Task {task_id} was stopped before execution.")
                return

            try:
                # 1. Prepare Workspace
                workspace_path = FileManager.create_workspace(task_id)
                config_path = FileManager.save_config(workspace_path, task.config_json)
                
                # Update Task
                task.status = "RUNNING"
                task.workspace_path = str(workspace_path)
                task.updated_at = datetime.utcnow()
                session.add(task)
                session.commit()
                session.refresh(task)

                # 2. Run Engine (Blocking call for subprocess spawn, but we need to wait for it?)
                # Stage 1: MVP can block the worker (since it's a queue).
                # But wait, os.system blocks? Popen doesn't.
                # Use engine to spawn, then wait.
                
                pid, error = cls._engine_service.run_task(
                    task_id, # Added task_id
                    workspace_path, 
                    config_path, 
                    task.type, 
                    task.enhanced, 
                    task.turbo
                )
                
                if pid < 0:
                    task.status = "FAILED"
                    task.error_msg = error
                    session.add(task)
                    session.commit()
                    return

                task.pid = pid
                session.add(task)
                session.commit()
                
                # 3. Wait for completion (Simple polling for MVP)
                # In Stage 2 we do async stream reading.
                # Here we just wait. SimulationEngine.run_task returns Popen?
                # Ah, I defined run_task to return (pid, error). I lost the Popen object reference.
                # I should modify run_task to wait or return Popen.
                # Or use `os.waitpid(pid, 0)` if os supports it.
                # Better: `SimulationEngine` should probably have a `run_and_wait` or return Popen.
                
                # Let's use psutil or plain os polling.
                # Actually, blocking the async worker loop with `os.waitpid` is bad if we want concurrency > 1.
                # But Stage 1 Requirement says "FIFO Task Queue", so 1 concurrency is fine.
                # We can run `await asyncio.to_thread(wait_for_process, pid)`
                
                try:
                    p = psutil.Process(pid)
                    # Poll in loop to allow cancellation logic later?
                    # For now just wait.
                    exit_code = await asyncio.to_thread(p.wait)
                    
                    if exit_code == 0:
                        task.status = "COMPLETED"
                        # Assume default result path
                        task.result_path = str(workspace_path / "sweep_results.h5") 
                    else:
                        task.status = "FAILED"
                        task.error_msg = f"Process exited with code {exit_code}"
                        
                except psutil.NoSuchProcess:
                    # Already finished?
                    task.status = "FAILED"
                    task.error_msg = "Process disappeared unexpectedly"
                    
            except Exception as e:
                task.status = "FAILED"
                task.error_msg = str(e)
            finally:
                task.updated_at = datetime.utcnow()
                # Clear PID and cleanup process resources
                if task.pid:
                    cls._engine_service.cleanup_process(task.pid)
                task.pid = None
                session.add(task)
                session.commit()

    @classmethod
    def stop_task(cls, pid: int) -> bool:
        """Stops the task with the given PID."""
        return cls._engine_service.stop_task(pid)
