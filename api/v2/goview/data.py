from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from tricys_backend.utils.db import get_session
# Use our custom deps for GoView compatibility
# But the plan says "Optional" adapter interfaces.
# If these are consumed by GoView *components*, they likely use the same axios instance as the editor.
# So they will send the `token` header.
# We should probably support `require_token` here too, or standard `get_current_user` if adapters are flexible.
# Let's use `require_token` to be safe and consistent with Goview context.
from tricys_backend.api.v2.goview.deps import require_token
from tricys_backend.api.v2.goview.responses import success, error

from tricys_backend.models.user import User
from tricys_backend.models.project import Project
from tricys_backend.models.task import Task
from tricys_backend.services.file_browser_service import FileBrowserService
from tricys_backend.services.hdf5_service import HDF5ReaderService
from tricys_backend.services.analysis_service import AnalysisService

router = APIRouter()

file_browser = FileBrowserService()
hdf5_service = HDF5ReaderService()

# Helper to verify Tricys project access (not GoviewProject)
def get_user_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this project")
    return project

def get_user_task(session: Session, task_id: str, user_id: str) -> Task:
    # Join with Project to verify ownership
    query = select(Task).join(Project).where(Task.id == task_id, Project.user_id == user_id)
    task = session.exec(query).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

def get_task_workspace(task: Task) -> Path:
    if not task.workspace_path:
        raise HTTPException(status_code=400, detail="Task has no workspace assigned")
    workspace_path = Path(task.workspace_path)
    if not workspace_path.exists():
        raise HTTPException(status_code=404, detail="Workspace directory not found")
    return workspace_path


class TimeSeriesBatchRequest(BaseModel):
    taskId: str
    variables: List[str]
    timeRange: Optional[List[float]] = None
    jobId: Optional[int] = None
    jobIds: Optional[List[int]] = None
    limit: Optional[int] = 2000


@router.get("/summary")
def goview_summary(
    project_id: str = Query(..., alias="projectId"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_token)
):
    try:
        project = get_user_project(session, project_id, current_user.id)
        latest_task = session.exec(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(Task.created_at.desc())
            .limit(1)
        ).first()

        last_updated = project.updated_at or project.created_at
        status = latest_task.status if latest_task else "NO_TASK"

        return success({
            "projectName": project.name,
            "lastUpdated": last_updated,
            "status": status
        })
    except HTTPException as e:
        return error(e.status_code, e.detail)
    except Exception as e:
        return error(500, str(e))


@router.get("/tasks")
def goview_tasks(
    project_id: str = Query(..., alias="projectId"),
    limit: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_token)
):
    try:
        project = get_user_project(session, project_id, current_user.id)
        tasks = session.exec(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(Task.created_at.desc())
            .limit(limit)
        ).all()

        data = [
            {
                "id": task.id,
                "name": task.name,
                "status": task.status,
                "createdAt": task.created_at,
                "updatedAt": task.updated_at,
                "type": task.type
            }
            for task in tasks
        ]
        return success(data)
    except HTTPException as e:
        return error(e.status_code, e.detail)


@router.get("/metrics")
def goview_metrics(
    task_id: str = Query(..., alias="taskId"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_token)
):
    try:
        task = get_user_task(session, task_id, current_user.id)
        workspace_path = get_task_workspace(task)

        metrics = hdf5_service.get_summary_metrics(task_id, workspace_path)
        metrics_sorted = sorted(metrics, key=lambda m: m.get("job_id", 0))

        metrics_map: Dict[str, Any] = {}
        for item in metrics_sorted:
            if not isinstance(item, dict):
                continue
            name = item.get("metric_name") or item.get("name") or item.get("metric")
            if not name:
                continue
            value = item.get("metric_value") if "metric_value" in item else item.get("value")
            metrics_map[name] = value

        return success(metrics_map)
    except HTTPException as e:
        return error(e.status_code, e.detail)


@router.get("/timeseries")
def goview_timeseries(
    task_id: str = Query(..., alias="taskId"),
    var: str = Query(...),
    job_id: Optional[int] = Query(None, alias="jobId"),
    limit: int = Query(2000, ge=1, le=200000),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_token)
):
    try:
        task = get_user_task(session, task_id, current_user.id)
        workspace_path = get_task_workspace(task)

        data = hdf5_service.query_results(
            task_id=task_id,
            workspace_path=workspace_path,
            variables=[var],
            job_id=job_id,
            limit=limit
        )

        return success({
            "time": data.get("time", []),
            "value": data.get(var, [])
        })
    except HTTPException as e:
        return error(e.status_code, e.detail)


@router.post("/timeseries/batch")
def goview_timeseries_batch(
    payload: TimeSeriesBatchRequest = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_token)
):
    try:
        task = get_user_task(session, payload.taskId, current_user.id)
        workspace_path = get_task_workspace(task)

        time_range: Optional[Tuple[float, float]] = None
        if payload.timeRange and len(payload.timeRange) == 2:
            time_range = (payload.timeRange[0], payload.timeRange[1])

        data = hdf5_service.query_results(
            task_id=payload.taskId,
            workspace_path=workspace_path,
            variables=payload.variables,
            time_range=time_range,
            job_id=payload.jobId,
            job_ids=payload.jobIds,
            limit=payload.limit
        )

        series = {var: data.get(var, []) for var in payload.variables}

        return success({
            "time": data.get("time", []),
            "series": series
        })
    except HTTPException as e:
        return error(e.status_code, e.detail)


@router.get("/files")
def goview_files(
    task_id: str = Query(..., alias="taskId"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_token)
):
    try:
        task = get_user_task(session, task_id, current_user.id)
        workspace_path = get_task_workspace(task)
        files = file_browser.list_files(workspace_path)
        return success(files)
    except HTTPException as e:
        return error(e.status_code, e.detail)


@router.get("/files/download")
def goview_files_download(
    task_id: str = Query(..., alias="taskId"),
    path: str = Query(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_token)
):
    # This returns a FileResponse directly, not JSON.
    # Front-end should handle binary download.
    try:
        task = get_user_task(session, task_id, current_user.id)
        workspace_path = get_task_workspace(task)
        full_path = file_browser.get_file_path(workspace_path, path)
        return FileResponse(full_path, filename=full_path.name)
    except HTTPException as e:
        # If we return JSON here, it might break download expectation, but better than crashing.
        return error(e.status_code, e.detail)


@router.get("/analysis/tasks")
def goview_analysis_tasks(
    project_id: Optional[str] = Query(None, alias="projectId"),
    current_user: User = Depends(require_token)
):
    tasks = AnalysisService.get_tasks(current_user.id, project_id)
    data = [
        {
            "id": task.id,
            "name": task.name,
            "status": task.status,
            "createdAt": task.created_at,
            "updatedAt": task.updated_at,
            "config": task.config_json
        }
        for task in tasks
    ]
    return success(data)


@router.get("/analysis/report")
def goview_analysis_report(
    task_id: str = Query(..., alias="taskId"),
    current_user: User = Depends(require_token)
):
    task = AnalysisService.get_task(task_id, current_user.id)
    if not task:
        return error(404, "Task not found")

    if task.status != "COMPLETED":
         return error(400, "Task not completed yet")

    if not task.result_path:
        return success({"content": "# Report not found\nResult path does not exist."})

    try:
        result_dir = Path(task.result_path)
        if not result_dir.exists():
            return success({"content": "# Report not found\nResult path does not exist."})

        report_files = list(result_dir.glob("*report*.md"))
        if not report_files:
            report_files = list(result_dir.glob("*.md"))

        if report_files:
            target = report_files[0]
            for report in report_files:
                if "analysis_report" in report.name:
                    target = report
                    break
            return success({"content": target.read_text(encoding="utf-8")})
    except Exception as exc:
        return success({"content": f"# Error reading report\n{str(exc)}"})

    return success({"content": "# Report not generated yet."})
