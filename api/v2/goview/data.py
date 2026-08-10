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
from tricys_backend.api.v2.goview.deps import GoviewTokenContext, require_goview_context
from tricys_backend.api.v2.goview.responses import success, error

from tricys_backend.models.project import Project
from tricys_backend.models.task import Task
from tricys_backend.services.file_browser_service import FileBrowserService
from tricys_backend.services.hdf5_service import HDF5ReaderService
from tricys_backend.services.analysis_service import AnalysisService

router = APIRouter()

file_browser = FileBrowserService()
hdf5_service = HDF5ReaderService()

# Helper to verify Tricys project access (not GoviewProject)
def get_user_project(
    session: Session,
    project_id: str,
    user_id: str,
    scoped_project_id: Optional[str] = None,
) -> Project:
    if scoped_project_id and project_id != scoped_project_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this project")
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this project")
    return project

def get_user_task(
    session: Session,
    task_id: str,
    user_id: str,
    scoped_project_id: Optional[str] = None,
) -> Task:
    # Join with Project to verify ownership
    query = select(Task).join(Project).where(Task.id == task_id, Project.user_id == user_id)
    if scoped_project_id:
        query = query.where(Project.id == scoped_project_id)
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
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        project = get_user_project(session, project_id, current_ctx.user.id, current_ctx.tricys_project_id)
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
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        project = get_user_project(session, project_id, current_ctx.user.id, current_ctx.tricys_project_id)
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


@router.get("/parameters")
def goview_parameters(
    project_id: str = Query(..., alias="projectId"),
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        project = get_user_project(session, project_id, current_ctx.user.id, current_ctx.tricys_project_id)
        parameters = project.parameters_json or project.defaults_json or []
        if isinstance(parameters, dict):
            parameters = [
                {"name": key, "value": value}
                for key, value in parameters.items()
            ]
        return success(parameters)
    except HTTPException as e:
        return error(e.status_code, e.detail)


@router.get("/latest-task")
def goview_latest_task(
    project_id: str = Query(..., alias="projectId"),
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        project = get_user_project(session, project_id, current_ctx.user.id, current_ctx.tricys_project_id)
        latest_task = session.exec(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(Task.created_at.desc())
            .limit(1)
        ).first()
        if not latest_task:
            return success(None)
        return success({
            "id": latest_task.id,
            "name": latest_task.name,
            "status": latest_task.status,
            "createdAt": latest_task.created_at,
            "updatedAt": latest_task.updated_at,
            "type": latest_task.type,
        })
    except HTTPException as e:
        return error(e.status_code, e.detail)


@router.get("/metrics")
def goview_metrics(
    task_id: str = Query(..., alias="taskId"),
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
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
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
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
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, payload.taskId, current_ctx.user.id, current_ctx.tricys_project_id)
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
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
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
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    # This returns a FileResponse directly, not JSON.
    # Front-end should handle binary download.
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
        workspace_path = get_task_workspace(task)
        full_path = file_browser.get_file_path(workspace_path, path)
        return FileResponse(full_path, filename=full_path.name)
    except HTTPException as e:
        # If we return JSON here, it might break download expectation, but better than crashing.
        return error(e.status_code, e.detail)


@router.get("/analysis/tasks")
def goview_analysis_tasks(
    project_id: Optional[str] = Query(None, alias="projectId"),
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    get_user_project(session, project_id, current_ctx.user.id, current_ctx.tricys_project_id)
    tasks = AnalysisService.get_tasks(current_ctx.user.id, project_id)
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
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
    task = AnalysisService.get_task(task_id, current_ctx.user.id)
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


# --- New Planned Endpoints for GoView HDF5 Integration ---

class GoviewTimeseriesRequest(BaseModel):
    variables: List[str]
    job_ids: Optional[List[int]] = None
    limit: Optional[int] = 500
    time_range: Optional[List[float]] = None

class GoviewMetricsRequest(BaseModel):
    metrics: List[str]
    job_id: int

@router.get("/{task_id}/metadata")
def get_goview_metadata(
    task_id: str,
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
        workspace_path = get_task_workspace(task)
        meta = hdf5_service.get_visualizer_metadata(task_id, workspace_path)
        
        variables = meta.get("variable_options", [])
        metrics_list = meta.get("parameter_options", [])
        
        # Format jobs
        jobs_raw = meta.get("jobs_data", [])
        jobs = []
        for j in jobs_raw:
            job_dict = {"job_id": j.get("job_id", 0), "status": "COMPLETED"}
            for k, v in j.items():
                if k != "job_id":
                    job_dict[k] = v
            jobs.append(job_dict)

        return success({
            "variables": variables,
            "jobs": jobs,
            "metrics": metrics_list
        })
    except HTTPException as e:
        return error(e.status_code, e.detail)
    except Exception as e:
        return error(500, str(e))


@router.post("/{task_id}/timeseries")
def query_goview_timeseries(
    task_id: str,
    payload: GoviewTimeseriesRequest,
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
        workspace_path = get_task_workspace(task)

        time_range: Optional[Tuple[float, float]] = None
        if payload.time_range and len(payload.time_range) == 2:
            time_range = (payload.time_range[0], payload.time_range[1])

        data = hdf5_service.query_results(
            task_id=task_id,
            workspace_path=workspace_path,
            variables=payload.variables,
            time_range=time_range,
            job_ids=payload.job_ids,
            limit=payload.limit
        )

        # Format to ECharts Dataset format
        # data = {"time": [...], "temperature": [...]}
        times = data.get("time", [])
        dimensions = ["time"] + payload.variables
        source = []
        
        if times:
            for i in range(len(times)):
                row = [times[i]]
                for var in payload.variables:
                    var_arr = data.get(var, [])
                    row.append(var_arr[i] if i < len(var_arr) else None)
                source.append(row)

        return success({
            "dimensions": dimensions,
            "source": source
        })
    except HTTPException as e:
        return error(e.status_code, e.detail)
    except Exception as e:
        return error(500, str(e))


@router.post("/{task_id}/metrics")
def query_goview_metrics(
    task_id: str,
    payload: GoviewMetricsRequest,
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
        workspace_path = get_task_workspace(task)

        metrics = hdf5_service.get_summary_metrics(task_id, workspace_path)
        
        # Filter for the requested job_id
        filtered_metrics = [m for m in metrics if m.get("job_id") == payload.job_id]
        
        result = []
        for m_name in payload.metrics:
            # Find the metric
            found = False
            for m in filtered_metrics:
                name = m.get("metric_name") or m.get("name") or m.get("metric")
                if name == m_name:
                    val = m.get("metric_value") if "metric_value" in m else m.get("value")
                    result.append({"name": m_name, "value": val})
                    found = True
                    break
            if not found:
                result.append({"name": m_name, "value": None})

        return success(result)
    except HTTPException as e:
        return error(e.status_code, e.detail)
    except Exception as e:
        return error(500, str(e))


@router.post("/{task_id}/table")
def query_goview_table(
    task_id: str,
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
        workspace_path = get_task_workspace(task)

        meta = hdf5_service.get_visualizer_metadata(task_id, workspace_path)
        jobs_data = meta.get("jobs_data", [])
        
        metrics = hdf5_service.get_summary_metrics(task_id, workspace_path)
        
        # Join jobs_data with metrics
        # jobs_data: [{"job_id": 1, "param_a": 10}, ...]
        # metrics: [{"job_id": 1, "metric_name": "max_temp", "metric_value": 315.2}, ...]
        
        job_metrics_map = {}
        for m in metrics:
            jid = m.get("job_id")
            name = m.get("metric_name") or m.get("name") or m.get("metric")
            val = m.get("metric_value") if "metric_value" in m else m.get("value")
            if jid is not None and name:
                if jid not in job_metrics_map:
                    job_metrics_map[jid] = {}
                job_metrics_map[jid][name] = val
                
        result_table = []
        for job in jobs_data:
            jid = job.get("job_id")
            row = dict(job)
            if jid in job_metrics_map:
                row.update(job_metrics_map[jid])
            result_table.append(row)

        return success(result_table)
    except HTTPException as e:
        return error(e.status_code, e.detail)
    except Exception as e:
        return error(500, str(e))

class GoviewLatestValuesRequest(BaseModel):
    variables: List[str]
    job_id: Optional[int] = None

@router.post("/{task_id}/latest_values")
def query_goview_latest_values(
    task_id: str,
    payload: GoviewLatestValuesRequest,
    session: Session = Depends(get_session),
    current_ctx: GoviewTokenContext = Depends(require_goview_context)
):
    try:
        task = get_user_task(session, task_id, current_ctx.user.id, current_ctx.tricys_project_id)
        workspace_path = get_task_workspace(task)

        hdf5_file = hdf5_service.resolve_hdf5_file(task_id, workspace_path)
        if not hdf5_file or not hdf5_file.exists():
            return success({"dimensions": ["variable", "value"], "source": []})

        import pandas as pd
        import numpy as np
        where_str = None
        if payload.job_id is not None:
             where_str = f"job_id == {payload.job_id}"
             
        cols = list(set(payload.variables + ["time"])) if payload.variables else None

        with pd.HDFStore(hdf5_file, mode='r') as store:
            if '/results' not in store:
                return success({"dimensions": ["variable", "value"], "source": []})
            
            df = store.select('results', where=where_str, columns=cols)
            
        if df.empty:
            return success({"dimensions": ["variable", "value"], "source": []})
            
        last_row = df.iloc[-1]
        
        dimensions = ["variable", "value"]
        source = []
        for var in payload.variables:
            val = last_row.get(var)
            if pd.isna(val):
                val = None
            elif isinstance(val, (np.integer, np.floating)):
                val = val.item()
            source.append([var, val])

        return success({
            "dimensions": dimensions,
            "source": source
        })
    except HTTPException as e:
        return error(e.status_code, e.detail)
    except Exception as e:
        return error(500, str(e))
