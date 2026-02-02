from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import FileResponse
from sqlmodel import Session
from typing import Dict, Any, List, Optional
from pathlib import Path
import json

from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task
from tricys_backend.models.project import Project
from tricys_backend.models.user import User
from tricys_backend.api.deps import get_current_user
from tricys_backend.models.data_query import DataQueryRequest
from tricys_backend.services.file_browser_service import FileBrowserService
from tricys_backend.services.hdf5_service import HDF5ReaderService
from tricys_backend.services.archive_service import ArchiveService
from tricys_backend.services.ai_service import AIService

router = APIRouter()

file_browser = FileBrowserService()
hdf5_service = HDF5ReaderService()
archive_service = ArchiveService()

def get_task_workspace(task_id: str, session: Session, current_user: User) -> Path:    
    """Helper to get and validate task workspace path with ownership check."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify ownership via Project
    project = session.get(Project, task.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this task")

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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """List all files in the task workspace."""
    workspace_path = get_task_workspace(task_id, session, current_user)
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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Download or stream a specific file from the workspace."""   
    workspace_path = get_task_workspace(task_id, session, current_user)
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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Download a zip archive of the task workspace."""
    workspace_path = get_task_workspace(task_id, session, current_user)
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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get summary scalar metrics for the simulation task."""      
    workspace_path = get_task_workspace(task_id, session, current_user)
    try:
        metrics = hdf5_service.get_summary_metrics(task_id, workspace_path)
        return {"metrics": metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get summary: {str(e)}")

@router.post("/tasks/{task_id}/results/query", response_model=Dict[str, Any])
def query_results(
    task_id: str,
    query: DataQueryRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Raw HDF5 query for internal frontend usage."""
    workspace_path = get_task_workspace(task_id, session, current_user)
    try:
        return hdf5_service.query_results(
            task_id=task_id,
            workspace_path=workspace_path,
            variables=query.variables,
            time_range=query.time_range,
            job_id=query.job_id,
            job_ids=query.job_ids,
            limit=query.limit
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying data: {str(e)}")

@router.post("/tasks/{task_id}/results/query_bi")
def query_results_bi(
    task_id: str,
    request_data: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Grafana SimpleJSON compatible query endpoint.
    Body: {"targets": [{"target": "sds.I"}], "range": {"from": "...", "to": "..."}}
    """
    workspace_path = get_task_workspace(task_id, session, current_user)
    try:
        return hdf5_service.query_results_bi(task_id, workspace_path, request_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying BI data: {str(e)}")

# --- AI Analysis (New) ---

@router.post("/tasks/{task_id}/analyze")
def trigger_ai_analysis(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Triggers AI-enhanced analysis for a completed task.
    Requires a standard analysis report (markdown) to exist in the workspace.
    """
    workspace_path = get_task_workspace(task_id, session, current_user)
    
    # 1. Load Config
    analysis_config = {}
    # Try different config names
    for cfg_name in ["analysis_config.json", "config.json"]:
        cfg_path = workspace_path / cfg_name
        if cfg_path.exists():
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    analysis_config = json.load(f)
                break
            except Exception:
                continue
    
    # 2. Find Report
    report_path = None
    # Search recursively for "analysis_report_*.md"
    try:
        found_reports = list(workspace_path.rglob("analysis_report_*.md"))
        # Exclude previously generated AI reports to avoid loops if naming conflicts
        found_reports = [p for p in found_reports if "_ai.md" not in p.name]
        
        if found_reports:
            # Pick the latest modified
            found_reports.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            report_path = found_reports[0]
        else:
            # Fallback check
            fallback = workspace_path / "standard_report.md"
            if fallback.exists():
                report_path = fallback
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching for reports: {str(e)}")
            
    if not report_path:
        raise HTTPException(status_code=404, detail="Standard analysis report not found in workspace.")
        
    # 3. Generate
    result_path = AIService.generate_enhanced_report(workspace_path, report_path, analysis_config)
    
    if not result_path:
        raise HTTPException(status_code=500, detail="AI analysis failed (check logs/dependencies).")
        
    return {
        "status": "success", 
        "report_path": str(result_path.relative_to(workspace_path)),
        "full_path": str(result_path)
    }