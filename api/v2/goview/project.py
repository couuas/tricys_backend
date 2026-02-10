from fastapi import APIRouter, Depends, Query, Form, UploadFile, File, HTTPException, Request
from sqlmodel import Session, select
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime, timezone
import uuid
from pathlib import Path
import shutil

from tricys_backend.utils.db import get_session
from tricys_backend.api.v2.goview.responses import success, error
from tricys_backend.api.v2.goview.deps import require_token, optional_token
from tricys_backend.models.goview_project import GoviewProject
from tricys_backend.core.config import settings

router = APIRouter()

@router.get("/list")
def list_projects(
    page: int = Query(1, ge=1),
    pageSize: Optional[int] = Query(None, ge=1, le=200),
    keyword: Optional[str] = None,
    request: Request = None,
    session: Session = Depends(get_session),
    user = Depends(require_token)
):
    if pageSize is None:
        limit = None
        if request is not None:
            limit = request.query_params.get("limit")
        if limit and limit.isdigit():
            pageSize = int(limit)
        else:
            pageSize = 20
    offset = (page - 1) * pageSize
    def resolve_index_image(value: str) -> str:
        if not value:
            return value
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if request is None:
            return value
        base = str(request.base_url).rstrip("/")
        if value.startswith("/"):
            return f"{base}{value}"
        return f"{base}/{value}"

    query = select(GoviewProject).where(
        GoviewProject.create_user_id == user.id,
        GoviewProject.is_delete == 0
    )
    if keyword:
        # Standard SQLModel/SQLAlchemy contains
        query = query.where(GoviewProject.project_name.contains(keyword))
    
    # Count total
    # Use explicit subquery for counting to avoid issues with some db backends
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    
    # Get items
    query = query.order_by(GoviewProject.create_time.desc())
    items = session.exec(query.offset(offset).limit(pageSize)).all()
    
    data = [{
        "id": p.id,
        "projectName": p.project_name,
        "state": p.state,
        "createTime": p.create_time.isoformat(),
        "indexImage": resolve_index_image(p.index_image),
        "createUserId": p.create_user_id,
        "remarks": p.remarks,
    } for p in items]

    return {
        "code": 200,
        "msg": "success",
        "data": data,
        "meta": {
            "page": page,
            "pageSize": pageSize,
            "total": total
        }
    }

@router.post("/create")
def create_project(
    payload: dict,
    session: Session = Depends(get_session),
    user = Depends(require_token)
):
    name = (payload.get("projectName") or "New Project").strip()
    if len(name) > 200:
        return error(400, "projectName too long")

    requested_id = payload.get("id")
    if requested_id:
        existing = session.get(GoviewProject, requested_id)
        if existing:
            if existing.create_user_id != user.id:
                return error(403, "permission denied")
            return success({"id": existing.id})

    project = GoviewProject(
        id=requested_id or str(uuid.uuid4()),
        project_name=name,
        content=payload.get("content") or "{}",
        state=int(payload.get("state", -1)),
        index_image=payload.get("indexImage") or "",
        remarks=payload.get("remarks") or "",
        create_user_id=user.id,
    )
    session.add(project)
    session.commit()
    return success({"id": project.id})

@router.get("/getData")
def get_data(
    id: Optional[str] = Query(None),
    projectId: Optional[str] = Query(None),
    request: Request = None,
    session: Session = Depends(get_session),
    user = Depends(optional_token)
):
    target_id = id or projectId
    if not target_id:
        return error(400, "id is required")
    project = session.get(GoviewProject, target_id)
    if not project:
        return error(404, "project not found")
    
    if project.is_delete == 1:
        return error(404, "project deleted")

    # Access control:
    # 1. Author can access
    # 2. If published (state=1), anyone can access (even without token)
    
    is_author = user and project.create_user_id == user.id
    if not is_author and project.state != 1:
        return error(403, "not published or no permission")
        
    def resolve_index_image(value: str) -> str:
        if not value:
            return value
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if request is None:
            return value
        base = str(request.base_url).rstrip("/")
        if value.startswith("/"):
            return f"{base}{value}"
        return f"{base}/{value}"

    return success({
        "id": project.id,
        "projectName": project.project_name,
        "state": project.state,
        "indexImage": resolve_index_image(project.index_image),
        "createUserId": project.create_user_id,
        "createTime": project.create_time.isoformat(),
        "remarks": project.remarks,
        "content": project.content,
        "isDelete": project.is_delete
    })

@router.post("/save/data")
def save_data(
    id: Optional[str] = Form(None),
    projectId: Optional[str] = Form(None),
    content: str = Form(...),
    session: Session = Depends(get_session),
    user = Depends(require_token)
):
    target_id = id or projectId
    if not target_id:
        return error(400, "id is required")
    # Depending on axios setting, it might be JSON too.
    # But usually save/data is large JSON string.
    # Let's support Form first as per plan.
    project = session.get(GoviewProject, target_id)
    if not project:
        return error(404, "project not found")
        
    if project.create_user_id != user.id:
        return error(403, "permission denied")
        
    project.content = content
    project.update_time = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    return success(None)

@router.post("/edit")
def edit_project(
    payload: dict,
    session: Session = Depends(get_session),
    user = Depends(require_token)
):
    project = session.get(GoviewProject, payload.get("id"))
    if not project:
        return error(404, "project not found")
        
    if project.create_user_id != user.id:
        return error(403, "permission denied")
        
    if "projectName" in payload:
        name = payload.get("projectName") or ""
        if len(name) > 200:
            return error(400, "projectName too long")
        project.project_name = name
        
    if "remarks" in payload:
        project.remarks = payload.get("remarks") or ""
        
    if "indexImage" in payload:
        project.index_image = payload.get("indexImage") or ""
        
    project.update_time = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    return success(None)

@router.put("/publish")
def publish_project(
    payload: dict,
    session: Session = Depends(get_session),
    user = Depends(require_token)
):
    project = session.get(GoviewProject, payload.get("id"))
    if not project:
        return error(404, "project not found")

    if project.create_user_id != user.id:
        return error(403, "permission denied")
        
    state = payload.get("state")
    if state is not None:
        project.state = int(state)
        
    project.update_time = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    return success(None)

@router.delete("/delete")
def delete_project(
    id: Optional[str] = Query(None),
    ids: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    user = Depends(require_token)
):
    # Support comma separated if needed, but plan says single id for now
    # Check if id allows multiple
    target = id or ids
    if not target:
        return error(400, "id is required")
    id_list = target.split(",")
    for pid in id_list:
        if not pid: continue
        project = session.get(GoviewProject, pid)
        if project and project.create_user_id == user.id:
            project.is_delete = 1
            project.update_time = datetime.now(timezone.utc)
            session.add(project)
    
    session.commit()
    return success(None)

@router.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    user = Depends(require_token)
):
    # 1. Validate info
    ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
    MAX_SIZE_MB = 10
    
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()
    
    if suffix not in ALLOWED_EXT:
        return error(400, "file type not allowed")
        
    # Check size if possible, or during read
    
    # 2. Save
    ASSETS_DIR = settings.BASE_DIR / "assets" / "goview"
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    target_path = ASSETS_DIR / safe_name
    
    try:
        with target_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        return error(500, "upload failed")
        
    # 3. Return URL
    # Assuming standard static mount at /static or /assets?
    # backend/main.py mounts:
    # app.mount("/static", StaticFiles(directory=assets_dir), name="static")
    # So URL is /static/goview/xxx
    
    return success({
        "fileName": filename,
        "fileurl": f"/assets/goview/{safe_name}"
    })
