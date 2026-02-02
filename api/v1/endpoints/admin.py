import shutil
import logging
import os
import psutil
from datetime import datetime
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Body, File, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from pathlib import Path

from tricys_backend.api.deps import get_session, get_current_active_superuser
from tricys_backend.models.user import User
from tricys_backend.models.project import Project
from tricys_backend.core.config import settings
from tricys_backend.services.file_manager import FileManager

router = APIRouter()
logger = logging.getLogger(__name__)

# --- A. User Management ---

@router.get("/users", response_model=List[User])
def read_users(
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_superuser),
):
    """Retrieve users."""
    users = session.exec(select(User).offset(skip).limit(limit)).all()
    return users

from tricys_backend.core.security import get_password_hash

@router.post("/users", response_model=User)
def create_user(
    username: str = Body(...),
    password: str = Body(...),
    full_name: str = Body(None),
    email: str = Body(None),
    is_superuser: bool = Body(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_superuser),
):
    """Create new user by admin with hashed password."""
    user = User(
        username=username,
        hashed_password=get_password_hash(password),
        full_name=full_name,
        email=email,
        is_superuser=is_superuser
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@router.patch("/users/{user_id}", response_model=User)
def update_user(
    user_id: str,
    user_in: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_superuser),
):
    """Update a user."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if "password" in user_in:
        user.hashed_password = get_password_hash(user_in.pop("password"))

    for field, value in user_in.items():
        if hasattr(user, field):
            setattr(user, field, value)
            
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@router.delete("/users/{user_id}", response_model=Dict[str, str])
def delete_user(
    user_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_superuser),
):
    """Delete a user."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(user)
    session.commit()
    return {"status": "success", "message": "User deleted"}

# --- B. System Monitoring ---

@router.get("/system/stats")
def get_system_stats(
    current_user: User = Depends(get_current_active_superuser),
):
    """Get system stats (CPU, RAM, Disk)."""
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    
    # Disk usage for workspaces
    disk_path = settings.WORKSPACES_DIR
    disk = psutil.disk_usage(str(disk_path))
    
    # Process Count (Tricys related)
    # Simple count for now
    process_count = 0
    for proc in psutil.process_iter(['name']):
        if 'python' in proc.info['name']: # Very rough approximation
             process_count += 1

    return {
        "cpu": cpu_percent,
        "memory": {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent
        },
        "disk": {
            "total": disk.total,
            "free": disk.free,
            "percent": disk.percent
        },
        "processes": process_count
    }

# --- D. Global Project Management ---

@router.get("/projects", response_model=List[Project])
def read_all_projects(
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_superuser),
):
    """Get all projects."""
    projects = session.exec(select(Project).offset(skip).limit(limit)).all()
    return projects

@router.patch("/projects/{project_id}/publish")
def publish_project(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_superuser),
):
    """Make a project public."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.is_public = True
    session.add(project)
    session.commit()
    return {"status": "success", "is_public": True}

@router.patch("/projects/{project_id}/unpublish")
def unpublish_project(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_superuser),
):
    """Make a project private."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.is_public = False
    session.add(project)
    session.commit()
    return {"status": "success", "is_public": False}

@router.delete("/projects/{project_id}")
def delete_project_admin(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_superuser),
):
    """Force delete a project."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Clean up files
    if project.path and os.path.exists(project.path):
        shutil.rmtree(project.path, ignore_errors=True)
        
    session.delete(project)
    session.commit()
    return {"status": "success", "message": "Project deleted"}

# --- E. Asset Management ---

ASSETS_MODELS_DIR = settings.BASE_DIR / "assets" / "models"
DEMO_DIR = settings.BASE_DIR / "assets" / "demo"

@router.get("/assets/models")
def list_asset_models(
    current_user: User = Depends(get_current_active_superuser),
):
    """List global 3D models."""
    models = []
    if ASSETS_MODELS_DIR.exists():
        for f in ASSETS_MODELS_DIR.glob("*.glb"):
            models.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
                "url": f"/static/models/{f.name}" # Helper URL
            })
    return models

@router.delete("/assets/models/{filename}")
def delete_asset_model(
    filename: str,
    current_user: User = Depends(get_current_active_superuser),
):
    """Delete a global 3D model."""
    file_path = ASSETS_MODELS_DIR / filename
    if file_path.exists():
        os.remove(file_path)
        return {"status": "success"}
    raise HTTPException(404, "File not found")

@router.post("/assets/models")
async def upload_asset_model(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_superuser),
):
    """Upload a new global 3D model."""
    if not file.filename.lower().endswith('.glb'):
        raise HTTPException(400, "Only .glb allowed")
    
    ASSETS_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = ASSETS_MODELS_DIR / file.filename
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)
        
    return {"status": "success", "filename": file.filename}

@router.post("/assets/example_model")
async def update_example_model(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_superuser),
):
    """Update the example_model.mo template."""
    if not file.filename.lower().endswith('.mo'):
        raise HTTPException(400, "Only .mo allowed")
        
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    dest = DEMO_DIR / "example_model.mo"
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)
        
    return {"status": "success", "size": len(content)}

@router.get("/logs")
def get_system_logs(
    lines: int = 200,
    current_user: User = Depends(get_current_active_superuser),
):
    """Retrieve the global backend log file."""
    log_file = settings.BASE_DIR / "backend.log"
    if not log_file.exists():
        return {"logs": "Log file not found."}
        
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.readlines()
            return {"logs": "".join(content[-lines:])}
    except Exception as e:
        return {"logs": f"Error reading log file: {str(e)}"}

@router.get("/logs/download")
def download_system_logs(
    current_user: User = Depends(get_current_active_superuser),
):
    """Download the full backend.log file."""
    log_file = settings.BASE_DIR / "backend.log"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found.")
        
    return FileResponse(
        log_file,
        media_type="text/plain",
        filename=f"backend_log_{int(datetime.now().timestamp())}.txt"
    )
