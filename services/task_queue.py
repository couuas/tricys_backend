import asyncio
import logging
from sqlmodel import Session, select
from tricys_backend.models.project import Project
from tricys_backend.models.task import Task
from tricys_backend.services.engine import SimulationEngine
from tricys_backend.services.file_manager import FileManager
from tricys_backend.services.connection_manager import manager # Import ConnectionManager
from tricys_backend.core.config import settings
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine
import psutil
import shutil
import os

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
        # Notify clients
        await manager.broadcast_to_task(task_id, {"type": "status", "status": "PENDING"})

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
                await manager.broadcast_to_task(task_id, {"type": "status", "status": "STOPPED"})
                return

            logger.info(f"TaskQueue processing: {task_id}. Enhanced={task.enhanced}, Turbo={task.turbo}")
            await manager.broadcast_to_task(task_id, {"type": "status", "status": "RUNNING"})
            
            # Fetch Project (required for workspace and model path)
            project = session.get(Project, task.project_id)
            if not project:
                logger.error(f"Project {task.project_id} not found for task {task_id}")
                task.status = "FAILED"
                task.error_msg = "Associated project not found"
                session.add(task)
                session.commit()
                await manager.broadcast_to_task(task_id, {"type": "status", "status": "FAILED", "error": "Project not found"})
                return

            try:
                # 1. Prepare Workspace
                is_analysis = (task.type == "analysis")
                workspace_path = FileManager.create_workspace(task_id, task.project_id, is_analysis=is_analysis)
                
                # Determine Config Content
                if is_analysis and "analysis_spec" in task.config_json:
                     # Unwrap analysis spec to be the root config
                     config = task.config_json["analysis_spec"]
                else:
                     config = task.config_json
                
                # 2. Setup Model File
                if project.model_file_path:
                    source_path = Path(project.model_file_path)
                    
                    if source_path.exists():
                        # Copy to task workspace
                        dest_path = workspace_path / source_path.name
                        try:
                            shutil.copy2(source_path, dest_path)
                            
                            # Update config to use local file name
                            if "paths" not in config: config["paths"] = {}
                            
                            # For Analysis, the engine might expect package_path to run the model
                            # The model file is now in the current working directory (workspace_path)
                            # So just filename is enough
                            config["paths"]["package_path"] = source_path.name
                            
                            # Also ensure 'simulation' block has model_name if missing?
                            # Usually supplied by template/form.
                            
                            logger.info(f"Copied model from {source_path} to {dest_path}")
                        except Exception as exc:
                             logger.error(f"Failed to copy model file: {exc}")
                             raise exc
                    else:
                        logger.error(f"Source model file missing: {source_path}")
                        raise FileNotFoundError(f"Source model file not found at {source_path}")

                config_path = FileManager.save_config(workspace_path, config)
                
                # Update Task
                task.status = "RUNNING"
                task.workspace_path = str(workspace_path)
                task.updated_at = datetime.now(timezone.utc)
                session.add(task)
                session.commit()
                session.refresh(task)

                # 3. Run Engine
                pid, error = cls._engine_service.run_task(
                    task_id, 
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
                    await manager.broadcast_to_task(task_id, {"type": "status", "status": "FAILED", "error": error})
                    return

                task.pid = pid
                session.add(task)
                session.commit()
                
                # 4. Wait for completion
                try:
                    p = psutil.Process(pid)
                    # Poll while process is running to stream logs?
                    # For MVP, we wait.
                    exit_code = await asyncio.to_thread(p.wait)
                    
                    if exit_code == 0:
                        task.status = "COMPLETED"
                        # Standard sweep results name
                        task.result_path = str(workspace_path / "sweep_results.h5") 
                        await manager.broadcast_to_task(task_id, {"type": "status", "status": "COMPLETED"})
                    else:
                        task.status = "FAILED"
                        task.error_msg = f"Process exited with code {exit_code}"
                        await manager.broadcast_to_task(task_id, {"type": "status", "status": "FAILED", "error": f"Exit code {exit_code}"})
                        
                except psutil.NoSuchProcess:
                    task.status = "FAILED"
                    task.error_msg = "Process disappeared unexpectedly"
                    await manager.broadcast_to_task(task_id, {"type": "status", "status": "FAILED", "error": "Process disappeared"})
                    
            except Exception as e:
                task.status = "FAILED"
                task.error_msg = str(e)
                await manager.broadcast_to_task(task_id, {"type": "status", "status": "FAILED", "error": str(e)})
            finally:
                task.updated_at = datetime.now(timezone.utc)
                if task.pid:
                    cls._engine_service.cleanup_process(task.pid)
                task.pid = None
                session.add(task)
                session.commit()
