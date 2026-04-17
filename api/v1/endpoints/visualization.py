from fastapi import APIRouter, HTTPException, Depends, Body, Query
from fastapi.responses import FileResponse
from sqlmodel import Session
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import date, datetime
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import quote
import json
import math
import pandas as pd
import numpy as np

from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task
from tricys_backend.models.project import Project
from tricys_backend.models.user import User
from tricys_backend.api.deps import get_current_user
from tricys_backend.core.config import settings
from tricys_backend.models.data_query import DataQueryRequest
from tricys_backend.services.file_browser_service import FileBrowserService
from tricys_backend.services.hdf5_service import HDF5ReaderService
from tricys_backend.services.archive_service import ArchiveService
from tricys_backend.services.ai_service import AIService
from tricys.visualizer.filtering import filter_dataframe
from tricys.visualizer.context import (
    build_viewer_context,
    create_context_reference,
    issue_context_token,
)

router = APIRouter()

file_browser = FileBrowserService()
hdf5_service = HDF5ReaderService()
archive_service = ArchiveService()


def sanitize_json_payload(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, dict):
        return {key: sanitize_json_payload(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [sanitize_json_payload(item) for item in value]

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.bool_):
        return bool(value)

    if isinstance(value, np.floating):
        value = float(value)

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    return value


def resolve_requested_hdf5_file(
    workspace_path: Path,
    requested_path: Optional[str],
) -> Optional[Path]:
    if not requested_path:
        return None

    full_path = file_browser.get_file_path(workspace_path, requested_path)
    if full_path.suffix.lower() != ".h5":
        raise HTTPException(status_code=400, detail="Only .h5 files are supported")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="HDF5 file not found")

    return full_path


def build_hdf5_service_url(token: str) -> str:
    base_url = settings.HDF5_VISUALIZER_BASE_URL or "/hdf5/"
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}token={quote(token)}"


def probe_hdf5_service() -> Dict[str, Any]:
    healthcheck_url = settings.HDF5_VISUALIZER_HEALTHCHECK_URL
    if not healthcheck_url:
        return {"running": False, "detail": "HDF5 healthcheck URL not configured"}

    try:
        with urlopen(healthcheck_url, timeout=3) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "running": 200 <= response.status < 300,
                "status_code": response.status,
                "detail": body[:200],
            }
    except URLError as exc:
        return {"running": False, "detail": str(exc)}

def get_task_workspace(task_id: str, session: Session, current_user: User, allow_public: bool = False) -> Path:    
    """Helper to get and validate task workspace path with ownership check."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify ownership via Project
    project = session.get(Project, task.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id and not (allow_public and project.is_public):
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
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
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
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
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

@router.get("/tasks/{task_id}/files/content")
def get_task_file_content(
    task_id: str,
    path: str,
    max_bytes: int = Query(200000, ge=1000, le=2000000),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Return text content for preview with size limit."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
    try:
        full_path = file_browser.get_file_path(workspace_path, path)
        with open(full_path, "rb") as f:
            data = f.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        content = data.decode("utf-8", errors="replace")
        return {
            "path": path,
            "size": full_path.stat().st_size,
            "truncated": truncated,
            "content": content
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")

@router.get("/tasks/{task_id}/archive", response_class=FileResponse)
def download_task_archive(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Download a zip archive of the task workspace."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
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

@router.get("/tasks/{task_id}/visualizer/metadata")
def get_visualizer_metadata(
    task_id: str,
    path: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get HDF5 visualizer metadata (variables, parameters, jobs table, config, logs)."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
    try:
        selected_path = resolve_requested_hdf5_file(workspace_path, path)
        payload = hdf5_service.get_visualizer_metadata(task_id, workspace_path, selected_path)
        return sanitize_json_payload(payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load visualizer metadata: {str(e)}")

@router.get("/tasks/{task_id}/visualizer/jobs")
def get_visualizer_jobs(
    task_id: str,
    path: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = Query("asc"),
    filter: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get paginated jobs table for visualizer with optional filter/sort."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
    try:
        selected_path = resolve_requested_hdf5_file(workspace_path, path)
        jobs_df = hdf5_service.get_jobs_df(task_id, workspace_path, selected_path)
        if jobs_df.empty:
            return {"items": [], "page": page, "page_size": page_size, "total": 0}

        # Normalize id field for frontend
        if "job_id" in jobs_df.columns:
            jobs_df = jobs_df.rename(columns={"job_id": "id"})

        # Filter
        if filter:
            try:
                jobs_df = filter_dataframe(jobs_df, filter)
            except Exception:
                pass

        # Sort
        if sort_by and sort_by in jobs_df.columns:
            ascending = str(sort_dir).lower() != "desc"
            jobs_df = jobs_df.sort_values(by=sort_by, ascending=ascending)

        total = len(jobs_df)
        start = (page - 1) * page_size
        end = start + page_size
        items = jobs_df.iloc[start:end].to_dict("records")

        return sanitize_json_payload({"items": items, "page": page, "page_size": page_size, "total": total})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load jobs: {str(e)}")


@router.get("/tasks/{task_id}/visualizer/series")
def get_visualizer_series(
    task_id: str,
    path: Optional[str] = None,
    job_ids: Optional[str] = None,
    vars: Optional[str] = None,
    limit: int = Query(2000, ge=1, le=200000),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get time series data for selected job_ids and variables."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
    try:
        selected_path = resolve_requested_hdf5_file(workspace_path, path)
        parsed_job_ids = [int(j) for j in job_ids.split(",") if j.strip()] if job_ids else []
        parsed_vars = [v for v in vars.split(",") if v.strip()] if vars else []

        data_dict = hdf5_service.query_results(
            task_id=task_id,
            workspace_path=workspace_path,
            variables=parsed_vars,
            job_ids=parsed_job_ids,
            limit=limit,
            selected_path=selected_path,
        )

        if "time" not in data_dict:
            return {"records": []}

        df = pd.DataFrame(data_dict)
        return sanitize_json_payload({"records": df.to_dict("records")})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load series: {str(e)}")


@router.get("/tasks/{task_id}/visualizer/metrics")
def get_visualizer_metrics(
    task_id: str,
    path: Optional[str] = None,
    job_ids: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get summary metrics for selected job_ids from /summary."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
    try:
        selected_path = resolve_requested_hdf5_file(workspace_path, path)
        metrics = hdf5_service.get_summary_metrics(task_id, workspace_path, selected_path)
        if not metrics:
            return {"records": []}

        if job_ids:
            target_ids = {int(j) for j in job_ids.split(",") if j.strip()}
            metrics = [m for m in metrics if int(m.get("job_id", -1)) in target_ids]

        return sanitize_json_payload({"records": metrics})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load metrics: {str(e)}")


@router.get("/tasks/{task_id}/visualizer/config")
def get_visualizer_config(
    task_id: str,
    path: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get config data from HDF5."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
    try:
        selected_path = resolve_requested_hdf5_file(workspace_path, path)
        data = hdf5_service.get_config_log(task_id, workspace_path, selected_path)
        return sanitize_json_payload({"config": data.get("config_data")})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {str(e)}")


@router.get("/tasks/{task_id}/visualizer/log")
def get_visualizer_log(
    task_id: str,
    path: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get log data from HDF5."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
    try:
        selected_path = resolve_requested_hdf5_file(workspace_path, path)
        data = hdf5_service.get_config_log(task_id, workspace_path, selected_path)
        return sanitize_json_payload({"log": data.get("log_data")})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load log: {str(e)}")


@router.post("/tasks/{task_id}/visualizer/hdf5/open")
def open_hdf5_visualizer(
    task_id: str,
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Validate the selected HDF5 file and return a signed shared-viewer URL."""
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
    file_path = payload.get("path")
    if not file_path:
        raise HTTPException(status_code=400, detail="Missing file path")

    full_path = resolve_requested_hdf5_file(workspace_path, file_path)
    task = session.get(Task, task_id)
    project_id = str(task.project_id) if task else None
    viewer_context = build_viewer_context(
        str(full_path),
        display_path=file_path,
        task_id=task_id,
        project_id=project_id,
        mode="server",
    )
    context_reference = create_context_reference(
        viewer_context,
        str(settings.HDF5_CONTEXTS_DIR),
        settings.HDF5_VISUALIZER_TOKEN_TTL_SECONDS,
    )
    token = issue_context_token(
        {"context_id": context_reference["context_id"]},
        settings.HDF5_VISUALIZER_SECRET,
        settings.HDF5_VISUALIZER_TOKEN_TTL_SECONDS,
    )
    service_url = build_hdf5_service_url(token)
    return {
        "status": "ready",
        "path": file_path,
        "file": file_path,
        "project_id": project_id,
        "context_id": context_reference["context_id"],
        "token": token,
        "service_url": service_url,
        "viewer_path": (
            f"/visualizer?taskId={task_id}"
            f"&projectId={project_id or ''}"
            f"&path={quote(file_path)}"
            f"&token={quote(token)}"
        ),
    }


@router.get("/tasks/{task_id}/visualizer/hdf5/status")
def get_hdf5_status(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return shared HDF5 service mode status."""
    _ = get_task_workspace(task_id, session, current_user, allow_public=True)
    probe = probe_hdf5_service()
    return {
        "running": probe.get("running", False),
        "mode": "shared-service",
        "service_url": settings.HDF5_VISUALIZER_BASE_URL,
        "detail": probe.get("detail"),
        "status_code": probe.get("status_code"),
    }


@router.get("/tasks/visualizer/stats")
def get_visualizer_stats(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Get aggregate statistics of result files across all completed tasks.
    Counts .h5, .svg, and .md files in task workspaces.
    """
    statement = (
        session.query(Task)
        .join(Project)
        .filter(Project.user_id == current_user.id)
        .filter(Task.status == "COMPLETED")
    )
    tasks = statement.all()
    
    stats = {
        "total_tasks": len(tasks),
        "h5": 0,
        "svg": 0,
        "md": 0
    }
    
    for task in tasks:
        if not task.workspace_path:
            continue
        ws = Path(task.workspace_path)
        if not ws.exists():
            continue
            
        try:
            # Recursively count files
            # rglob iterates recursively
            # converting to list to get length
            stats["h5"] += sum(1 for _ in ws.rglob("*.h5"))
            stats["svg"] += sum(1 for _ in ws.rglob("*.svg"))
            stats["md"] += sum(1 for _ in ws.rglob("*.md"))
        except Exception:
            pass
            
    return stats


@router.get("/tasks/visualizer/hdf5/processes")
def get_active_hdf5_processes(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Legacy endpoint kept for compatibility.
    Per-task subprocesses are no longer used after switching to a shared viewer service.
    """
    return []


@router.post("/tasks/{task_id}/visualizer/hdf5/stop")
def stop_hdf5_visualizer(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Legacy no-op endpoint for the shared HDF5 viewer service."""
    _ = get_task_workspace(task_id, session, current_user, allow_public=True)
    return {
        "status": "noop",
        "detail": "Per-task HDF5 processes are no longer used; the shared service stays running.",
    }


@router.post("/tasks/{task_id}/visualizer/export")
def export_visualizer_data(
    task_id: str,
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Export results data in wide or long CSV format."""
    workspace_path = get_task_workspace(task_id, session, current_user)
    try:
        fmt = str(payload.get("format", "wide")).lower()
        job_ids = payload.get("job_ids") or []

        hdf5_file = hdf5_service.resolve_hdf5_file(task_id, workspace_path)
        if not hdf5_file:
            raise HTTPException(status_code=404, detail="HDF5 results file not found")

        # Load results
        where_clause = None
        if job_ids:
            jids = [int(j) for j in job_ids]
            where_clause = f"job_id in {jids}"

        df = pd.read_hdf(hdf5_file, "results", where=where_clause)
        if df.empty:
            raise HTTPException(status_code=400, detail="No results data to export")

        # Load jobs params
        jobs_df = hdf5_service.get_jobs_df(task_id, workspace_path)
        if "job_id" in jobs_df.columns:
            jobs_df = jobs_df.rename(columns={"job_id": "job_id"})

        if fmt == "long":
            params = jobs_df.rename(columns={"job_id": "job_id"}) if not jobs_df.empty else None
            if params is not None and not params.empty:
                df = pd.merge(df, params, on="job_id", how="left")

            suffix = "long"
            export_df = df
        else:
            # Wide format: time as index, columns per job + variable
            export_df = pd.DataFrame({"time": df["time"].unique()}).sort_values("time")
            for job_id in df["job_id"].unique():
                params = None
                if not jobs_df.empty:
                    row = jobs_df[jobs_df["job_id"] == job_id]
                    if not row.empty:
                        params = row.iloc[0].to_dict()
                params_str = ""
                if params:
                    params_str = "(" + ", ".join([f"{k}={v}" for k, v in params.items()]) + ")"
                job_df = df[df["job_id"] == job_id].drop(columns="job_id")
                job_df = job_df.rename(
                    columns={
                        col: f"{col} {params_str}" for col in job_df.columns if col != "time"
                    }
                )
                export_df = pd.merge(export_df, job_df, on="time", how="outer")
            suffix = "wide"

        export_dir = workspace_path / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"visualizer_export_{suffix}.csv"
        export_df.to_csv(export_path, index=False)
        rel_path = export_path.relative_to(workspace_path)
        return {"download_url": f"/api/v1/tasks/{task_id}/files/download?path={rel_path.as_posix()}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export data: {str(e)}")

@router.get("/tasks/{task_id}/result_summary")
def get_result_summary(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get summary scalar metrics for the simulation task."""      
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
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
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
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
    workspace_path = get_task_workspace(task_id, session, current_user, allow_public=True)
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