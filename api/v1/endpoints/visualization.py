from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import FileResponse
from sqlmodel import Session
from typing import Dict, Any, List
from pathlib import Path

from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task
from tricys_backend.models.data_query import DataQueryRequest
from tricys_backend.services.file_browser_service import FileBrowserService
from tricys_backend.services.hdf5_service import HDF5ReaderService
from tricys_backend.services.archive_service import ArchiveService

router = APIRouter()

file_browser = FileBrowserService()
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

# --- File Management ---

@router.get("/tasks/{task_id}/files", response_model=List[Dict[str, Any]])
def list_task_files(
    task_id: str,
    session: Session = Depends(get_session)
):
    """List all files in the task workspace."""
    workspace_path = get_task_workspace(task_id, session)
    try:
        return file_browser.list_files(workspace_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")

@router.get("/tasks/{task_id}/files/download")
def download_task_file(
    task_id: str,
    path: str,
    session: Session = Depends(get_session)
):
    """Download or stream a specific file from the workspace."""
    workspace_path = get_task_workspace(task_id, session)
    try:
        full_path = file_browser.get_file_path(workspace_path, path)
        filename = full_path.name
        return FileResponse(full_path, filename=filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve file: {str(e)}")

@router.get("/tasks/{task_id}/archive", response_class=FileResponse)
def download_task_archive(
    task_id: str,
    session: Session = Depends(get_session)
):
    """Download a zip archive of the task workspace."""
    workspace_path = get_task_workspace(task_id, session)
    try:
        zip_path = archive_service.create_task_archive(task_id, workspace_path)
        return FileResponse(
            path=zip_path, 
            filename=zip_path.name, 
            media_type="application/zip"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating archive: {str(e)}")

# --- Results & Visualization ---

@router.get("/tasks/{task_id}/result_summary")
def get_result_summary(
    task_id: str,
    session: Session = Depends(get_session)
):
    """Get summary scalar metrics for the simulation task."""
    workspace_path = get_task_workspace(task_id, session)
    try:
        metrics = hdf5_service.get_summary_metrics(task_id, workspace_path)
        return {"metrics": metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get summary: {str(e)}")

@router.post("/tasks/{task_id}/results/query", response_model=Dict[str, Any])
def query_results(
    task_id: str,
    query: DataQueryRequest,
    session: Session = Depends(get_session)
):
    """Raw HDF5 query for internal frontend usage."""
    workspace_path = get_task_workspace(task_id, session)
    try:
        return hdf5_service.query_results(
            task_id=task_id,
            workspace_path=workspace_path,
            variables=query.variables,
            time_range=query.time_range,
            job_id=query.job_id,
            job_ids=query.job_ids,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying data: {str(e)}")

@router.post("/tasks/{task_id}/results/query_bi")
def query_results_bi(
    task_id: str,
    request_data: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session)
):
    """
    Grafana SimpleJSON compatible query endpoint.
    Body: {"targets": [{"target": "sds.I"}], "range": {"from": "...", "to": "..."}}
    """
    workspace_path = get_task_workspace(task_id, session)
    try:
        return hdf5_service.query_results_bi(task_id, workspace_path, request_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying BI data: {str(e)}")
