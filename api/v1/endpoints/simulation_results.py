from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from typing import Dict, Any, List
from sqlmodel import Session
from pathlib import Path

from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task
from tricys_backend.services.file_browser_service import FileBrowserService
from tricys_backend.services.hdf5_service import HDF5ReaderService
from tricys_backend.api.v1.endpoints.data import get_task_workspace

router = APIRouter()
file_browser = FileBrowserService()
hdf5_service = HDF5ReaderService()

@router.get("/tasks/{task_id}/files", response_model=List[Dict[str, Any]])
def list_task_files(
    task_id: str,
    session: Session = Depends(get_session)
):
    """
    List all files in the task workspace as a tree structure.
    """
    workspace_path = get_task_workspace(task_id, session)
    try:
        return file_browser.list_files(workspace_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")

@router.get("/tasks/{task_id}/files/{file_path:path}")
def get_task_file(
    task_id: str,
    file_path: str,
    session: Session = Depends(get_session)
):
    """
    Download or stream a specific file from the workspace.
    """
    workspace_path = get_task_workspace(task_id, session)
    try:
        full_path = file_browser.get_file_path(workspace_path, file_path)
        return FileResponse(full_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve file: {str(e)}")

@router.get("/tasks/{task_id}/result_summary")
def get_result_summary(
    task_id: str,
    session: Session = Depends(get_session)
):
    """
    Get summary scalar metrics for the simulation task.
    Reads from HDF5 '/summary' table if available.
    """
    workspace_path = get_task_workspace(task_id, session)
    try:
        metrics = hdf5_service.get_summary_metrics(task_id, workspace_path)
        return {"metrics": metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get summary: {str(e)}")
