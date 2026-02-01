from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from typing import List, Dict
import logging
from datetime import datetime, timezone
from pathlib import Path

from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task, TaskCreate, TaskRead
from tricys_backend.services.task_queue import TaskQueue

router = APIRouter()
logger = logging.getLogger(__name__)

# --- In-simulation Monitoring & Lifecycle Management ---

@router.post("/tasks", response_model=TaskRead)
async def create_task(task_in: TaskCreate, session: Session = Depends(get_session)):
    """Create a new simulation task"""
    try:
        # Pre-simulation hook: The config is already validated by Pydantic model in theory,
        # but logically this is the transition from "Config" to "Monitoring/Running".
        
        # 1. Save to DB
        task = Task.from_orm(task_in)
        session.add(task)
        session.commit()
        session.refresh(task)
        
        # 2. Enqueue
        await TaskQueue.add_task(task.id)
        
        logger.info(f"Created task {task.id} with type {task.type}")
        return task
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")

@router.get("/tasks", response_model=List[TaskRead])
def read_tasks(
    offset: int = 0,
    limit: int = Query(default=20, lte=100),
    status: str = None,
    session: Session = Depends(get_session)
):
    """Retrieve tasks with optional filtering and pagination"""
    query = select(Task).offset(offset).limit(limit).order_by(Task.created_at.desc())
    if status:
        query = query.where(Task.status == status)
        
    tasks = session.exec(query).all()
    return tasks

@router.get("/tasks/stats/summary")
def get_tasks_summary(session: Session = Depends(get_session)) -> Dict:
    """Get summary statistics of all tasks"""
    try:
        total_tasks = session.exec(select(func.count(Task.id))).one()
        
        status_counts = {}
        for status in ["PENDING", "RUNNING", "COMPLETED", "FAILED", "STOPPED"]:
            count = session.exec(
                select(func.count(Task.id)).where(Task.status == status)
            ).one()
            status_counts[status.lower()] = count
        
        # Get recent tasks (completed today)
        recent_completed = session.exec(
            select(func.count(Task.id))
            .where(Task.status == "COMPLETED")
            .where(Task.updated_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0))
        ).one()
        
        return {
            "total_tasks": total_tasks,
            "status_counts": status_counts,
            "completed_today": recent_completed,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting task summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve task summary")

@router.get("/tasks/{task_id}", response_model=TaskRead)
def read_task(task_id: str, session: Session = Depends(get_session)):
    """Retrieve a specific task"""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: str, session: Session = Depends(get_session)):
    """Stop a running or pending task"""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task.status not in ["RUNNING", "PENDING"]:
        raise HTTPException(status_code=400, detail=f"Task is in {task.status} state, cannot stop")
    
    try:
        if task.status == "RUNNING" and task.pid:
            success = TaskQueue.stop_task(task.pid)
            if success:
                task.status = "STOPPED"
                task.updated_at = datetime.now(timezone.utc)
                session.add(task)
                session.commit()
                logger.info(f"Successfully stopped running task {task_id}")
                return {"message": "Task stopped successfully", "task_id": task_id}
            else:
                logger.error(f"Failed to stop process for task {task_id}")
                raise HTTPException(status_code=500, detail="Failed to stop process")
                
        elif task.status == "PENDING":
            task.status = "STOPPED"
            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()
            logger.info(f"Marked pending task {task_id} as stopped")
            return {"message": "Task marked as stopped (was pending)", "task_id": task_id}
        
        return {"message": "Task not running", "task_id": task_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error stopping task: {str(e)}")

@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: str, 
    cleanup_files: bool = Query(default=False), 
    session: Session = Depends(get_session)
):
    """Delete a task from database. Optionally cleanup workspace files."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task.status == "RUNNING":
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete a running task. Stop it first."
        )

    files_deleted = False
    if cleanup_files and task.workspace_path:
        import shutil
        path = Path(task.workspace_path)
        if path.exists():
            try:
                shutil.rmtree(path)
                files_deleted = True
                logger.info(f"Deleted workspace files for task {task_id}")
            except Exception as e:
                logger.warning(f"Failed to delete workspace {path}: {e}")
                
    try:
        session.delete(task)
        session.commit()
        logger.info(f"Deleted task {task_id} from database")
        
        return {
            "message": "Task deleted successfully",
            "task_id": task_id,
            "files_deleted": files_deleted
        }
    except Exception as e:
        logger.error(f"Error deleting task {task_id}: {e}")
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete task: {str(e)}")
