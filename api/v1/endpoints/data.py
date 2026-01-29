from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List
from sqlmodel import Session
from fastapi.responses import FileResponse
from pathlib import Path

from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task
from tricys_backend.services.hdf5_service import HDF5ReaderService
from tricys_backend.services.archive_service import ArchiveService
from tricys_backend.models.data_query import DataQueryRequest

router = APIRouter()

# Services are now stateless helpers
hdf5_service = HDF5ReaderService()
archive_service = ArchiveService()

def get_task_workspace(task_id: str, session: Session) -> Path:
    """Helper to get and validate task workspace path."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if not task.workspace_path:
        raise HTTPException(status_code=400, detail="Task has no workspace assigned (failed or pending)")
        
    path = Path(task.workspace_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Workspace directory not found on disk: {path}")
        
    return path

@router.post("/{task_id}/query", response_model=Dict[str, Any])
async def query_task_results(
    task_id: str,
    query: DataQueryRequest,
    session: Session = Depends(get_session)
):
    """
    Query simulation results. Supports HDF5 (Optimized) and CSV (Fallback).
    Auto-discovers results in nested timestamp directories if needed.
    """
    workspace_path = get_task_workspace(task_id, session)
    
    try:
        results = hdf5_service.query_results(
            task_id=task_id,
            workspace_path=workspace_path,
            variables=query.variables,
            time_range=query.time_range,
            job_id=query.job_id,
            job_ids=query.job_ids,
        )
        return results
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying data: {str(e)}")

@router.get("/{task_id}/download", response_class=FileResponse)
async def download_task_archive(
    task_id: str,
    session: Session = Depends(get_session)
):
    """
    Download a zip archive of the task workspace.
    """
    workspace_path = get_task_workspace(task_id, session)
    
    try:
        zip_path = archive_service.create_task_archive(task_id, workspace_path)
        return FileResponse(
            path=zip_path, 
            filename=zip_path.name, 
            media_type="application/zip"
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating archive: {str(e)}")
