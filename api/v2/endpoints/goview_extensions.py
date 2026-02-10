from typing import Any, Dict, List, Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session

from tricys_backend.utils.db import get_session
from tricys_backend.api.deps import get_current_user
from tricys_backend.models.user import User
from tricys_backend.services.file_browser_service import FileBrowserService
from tricys_backend.api.v2.goview.data import get_user_task, get_task_workspace

router = APIRouter()
file_browser = FileBrowserService()

@router.get("/files/model")
def goview_files_model(
    task_id: str = Query(..., alias="taskId"),
    path: str = Query(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Optimized endpoint for serving 3D model files (GLTF/STL/OBJ).
    """
    task = get_user_task(session, task_id, current_user.id)
    workspace_path = get_task_workspace(task)
    
    try:
        full_path = file_browser.get_file_path(workspace_path, path)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Determine media type for common 3D formats
    media_type = "application/octet-stream"
    if full_path.suffix.lower() == ".gltf":
        media_type = "model/gltf+json"
    elif full_path.suffix.lower() == ".glb":
        media_type = "model/gltf-binary"
    elif full_path.suffix.lower() == ".stl":
        media_type = "model/stl"
    elif full_path.suffix.lower() == ".obj":
        media_type = "model/obj"

    return FileResponse(full_path, media_type=media_type, filename=full_path.name)
