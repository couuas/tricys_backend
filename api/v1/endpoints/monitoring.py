from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from typing import List, Dict
import logging
from datetime import datetime, timezone
from pathlib import Path

from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task, TaskCreate, TaskRead
from tricys_backend.models.project import Project
from tricys_backend.models.user import User
from tricys_backend.api.deps import get_current_user
from tricys_backend.services.task_queue import TaskQueue
from tricys_backend.services.connection_manager import manager
from tricys_backend.services.file_manager import FileManager

router = APIRouter()
logger = logging.getLogger(__name__)

# --- In-simulation Monitoring & Lifecycle Management ---

@router.post("/tasks", response_model=TaskRead)
async def create_task(
    task_in: TaskCreate, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new simulation task"""
    # Verify project ownership
    project = session.get(Project, task_in.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to create tasks for this project")
        
    try:
        task = Task.from_orm(task_in)
        task.enhanced = task_in.enhanced
        task.turbo = task_in.turbo
        
        session.add(task)
        session.commit()
        session.refresh(task)
        
        # 2. Enqueue
        await TaskQueue.add_task(task.id)
        
        logger.info(f"Created task {task.id} for user {current_user.id}")
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
    project_id: str = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Retrieve tasks for the current user or a specific public project"""
    if project_id:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.user_id != current_user.id and not project.is_public:
            raise HTTPException(status_code=403, detail="Not authorized to access this project")
        query = select(Task).where(Task.project_id == project_id)
    else:
        # Join with Project to filter by user_id
        query = select(Task).join(Project).where(Project.user_id == current_user.id)

    query = query.offset(offset).limit(limit).order_by(Task.created_at.desc())
    if status:
        query = query.where(Task.status == status)

    tasks = session.exec(query).all()
    return tasks

@router.get("/tasks/stats/summary")
def get_tasks_summary(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Dict:
    """Get summary statistics of tasks belonging to the current user"""
    try:
        # Filter by user_id
        user_tasks_subquery = select(Task.id).join(Project).where(Project.user_id == current_user.id)
        
        total_tasks = session.exec(
            select(func.count(Task.id)).join(Project).where(Project.user_id == current_user.id)
        ).one()
        
        status_counts = {}
        for s in ["PENDING", "RUNNING", "COMPLETED", "FAILED", "STOPPED"]:
            count = session.exec(
                select(func.count(Task.id))
                .join(Project)
                .where(Project.user_id == current_user.id)
                .where(Task.status == s)
            ).one()
            status_counts[s.lower()] = count
        
        recent_completed = session.exec(
            select(func.count(Task.id))
            .join(Project)
            .where(Project.user_id == current_user.id)
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

def get_user_task(session: Session, task_id: str, user_id: str, allow_public: bool = False) -> Task:
    """Helper to get task and verify ownership"""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    project = session.get(Project, task.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user_id and not (allow_public and project.is_public):
        raise HTTPException(status_code=403, detail="Not authorized to access this task")
    return task

@router.get("/tasks/{task_id}", response_model=TaskRead)
def read_task(
    task_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Retrieve a specific task"""
    return get_user_task(session, task_id, current_user.id, allow_public=True)

@router.post("/tasks/{task_id}/stop")
async def stop_task(
    task_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Stop a running or pending task"""
    task = get_user_task(session, task_id, current_user.id)
        
    if task.status not in ["RUNNING", "PENDING"]:
        raise HTTPException(status_code=400, detail=f"Task is in {task.status} state, cannot stop")
    
    try:
        if task.status == "RUNNING" and task.pid:
            success = TaskQueue.stop_task(task.pid)
            task.status = "STOPPED"
            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()
            
            try:
                await manager.broadcast_to_task(task_id, {"type": "status", "status": "STOPPED"})
            except Exception as b_err:
                logger.warning(f"Broadcast stop status failed: {b_err}")
            
            if not success:
                logger.warning(f"Process for task {task_id} could not be stopped cleanly or already terminated")
            return {"message": "Task stopped successfully", "task_id": task_id}
                
        elif task.status in ["PENDING", "RUNNING"]:
            task.status = "STOPPED"
            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()
            
            try:
                await manager.broadcast_to_task(task_id, {"type": "status", "status": "STOPPED"})
            except Exception as b_err:
                logger.warning(f"Broadcast stop status failed: {b_err}")
            return {"message": "Task marked as stopped", "task_id": task_id}
        
        return {"message": "Task not running", "task_id": task_id}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        logger.error(f"Error stopping task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error stopping task: {str(e)}")

@router.get("/tasks/{task_id}/logs")
def get_task_logs(
    task_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Retrieve the simulation logs for a task."""
    task = get_user_task(session, task_id, current_user.id, allow_public=True)
        
    if not task.workspace_path:
        return {"logs": []}
        
    log_path = Path(task.workspace_path) / "simulation.log"
    if not log_path.exists():
        return {"logs": []}
        
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        lines = content.splitlines()
        structured_logs = [{"timestamp": "", "content": line, "level": "INFO"} for line in lines]
        return {"logs": structured_logs}
    except Exception as e:
         logger.error(f"Error reading logs: {e}")
         return {"logs": []}

@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: str, 
    cleanup_files: bool = Query(default=False), 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a task from database. Optionally cleanup workspace files."""
    task = get_user_task(session, task_id, current_user.id)
        
    if task.status == "RUNNING":
        raise HTTPException(status_code=400, detail="Cannot delete a running task. Stop it first.")

    files_deleted = False
    if cleanup_files:
        try:
            FileManager.cleanup_workspace(task_id, task.project_id)
            files_deleted = True
        except Exception as e:
            logger.warning(f"Failed to delete workspace files: {e}")
                
    try:
        session.delete(task)
        session.commit()
        return {
            "message": "Task deleted successfully",
            "task_id": task_id,
            "files_deleted": files_deleted
        }
    except Exception as e:
        logger.error(f"Error deleting task {task_id}: {e}")
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete task: {str(e)}")
