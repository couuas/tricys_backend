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
from tricys_backend.api.v2.goview.deps import (
    GoviewTokenContext,
    optional_goview_context,
    require_goview_context,
)
from tricys_backend.models.project import Project
from tricys_backend.models.goview_project import GoviewProject
from tricys_backend.models.project_page import ProjectPage
from tricys_backend.models.project_page_release import ProjectPageRelease
from tricys_backend.core.config import settings
from tricys_backend.services.project_service import ProjectService

router = APIRouter()


def resolve_index_image(value: str, request: Optional[Request]) -> str:
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


def get_scoped_project_page(
    session: Session,
    goview_project_id: str,
    context: Optional[GoviewTokenContext],
) -> Optional[ProjectPage]:
    query = select(ProjectPage).where(
        ProjectPage.goview_project_id == goview_project_id,
        ProjectPage.is_delete == 0,
    )
    if context and context.tricys_project_id:
        query = query.where(ProjectPage.project_id == context.tricys_project_id)
    return session.exec(query).first()


def can_manage_project(
    goview_project: GoviewProject,
    context: Optional[GoviewTokenContext],
    scoped_page: Optional[ProjectPage] = None,
) -> bool:
    if not context or not context.user:
        return False
    if context.tricys_project_id:
        return bool(scoped_page and scoped_page.project_id == context.tricys_project_id)
    return goview_project.create_user_id == context.user.id


def get_scoped_tricys_project(session: Session, context: GoviewTokenContext) -> Optional[Project]:
    if not context.tricys_project_id:
        return None
    project = session.get(Project, context.tricys_project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Tricys project not found")
    if context.user and project.user_id != context.user.id and not project.is_public:
        raise HTTPException(status_code=403, detail="permission denied")
    return project

@router.get("/list")
def list_projects(
    page: int = Query(1, ge=1),
    pageSize: Optional[int] = Query(None, ge=1, le=200),
    keyword: Optional[str] = None,
    request: Request = None,
    session: Session = Depends(get_session),
    context: GoviewTokenContext = Depends(require_goview_context)
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
    if context.tricys_project_id:
        query = (
            select(GoviewProject)
            .join(ProjectPage, ProjectPage.goview_project_id == GoviewProject.id)
            .where(
                ProjectPage.project_id == context.tricys_project_id,
                ProjectPage.is_delete == 0,
                GoviewProject.is_delete == 0,
            )
        )
    else:
        query = select(GoviewProject).where(
            GoviewProject.create_user_id == context.user.id,
            GoviewProject.is_delete == 0
        )
    if keyword:
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
        "indexImage": resolve_index_image(p.index_image, request),
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
    context: GoviewTokenContext = Depends(require_goview_context)
):
    name = (payload.get("projectName") or "New Project").strip()
    if len(name) > 200:
        return error(400, "projectName too long")

    requested_id = payload.get("id")
    if requested_id:
        existing = session.get(GoviewProject, requested_id)
        if existing:
            existing_page = get_scoped_project_page(session, existing.id, context)
            if not can_manage_project(existing, context, existing_page):
                return error(403, "permission denied")
            return success({"id": existing.id})

    scoped_project = get_scoped_tricys_project(session, context)
    if scoped_project is not None:
        created_page = ProjectService.create_project_page(
            session=session,
            project=scoped_project,
            user_id=context.user.id,
            page_name=name,
            page_type=(payload.get("pageType") or payload.get("page_type") or "custom"),
            remarks=payload.get("remarks") or "",
            template_key=payload.get("templateKey") or payload.get("template_key") or "",
            is_default=bool(payload.get("isDefault") or payload.get("is_default") or False),
            content=payload.get("content") or "{}",
            state=int(payload.get("state", -1)),
            index_image=payload.get("indexImage") or "",
            page_key=payload.get("pageKey") or payload.get("page_key"),
        )
        return success({
            "id": created_page.goview_project_id,
            "pageId": created_page.id,
            "tricysProjectId": created_page.project_id,
        })

    project = GoviewProject(
        id=requested_id or str(uuid.uuid4()),
        project_name=name,
        content=payload.get("content") or "{}",
        state=int(payload.get("state", -1)),
        index_image=payload.get("indexImage") or "",
        remarks=payload.get("remarks") or "",
        create_user_id=context.user.id,
    )
    session.add(project)
    session.commit()
    return success({"id": project.id})

@router.get("/getData")
def get_data(
    id: Optional[str] = Query(None),
    projectId: Optional[str] = Query(None),
    releaseMode: Optional[str] = Query(None),
    releaseId: Optional[str] = Query(None),
    request: Request = None,
    session: Session = Depends(get_session),
    context: Optional[GoviewTokenContext] = Depends(optional_goview_context)
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
    
    scoped_page = get_scoped_project_page(session, project.id, context)
    is_author = can_manage_project(project, context, scoped_page)
    if not is_author and project.state != 1:
        return error(403, "not published or no permission")

    page = scoped_page or session.exec(
        select(ProjectPage).where(
            ProjectPage.goview_project_id == project.id,
            ProjectPage.is_delete == 0,
        )
    ).first()
    active_release = None
    if page:
        active_release = session.exec(
            select(ProjectPageRelease)
            .where(
                ProjectPageRelease.page_id == page.id,
                ProjectPageRelease.is_active == 1,
                ProjectPageRelease.is_delete == 0,
            )
            .order_by(ProjectPageRelease.version.desc(), ProjectPageRelease.published_at.desc())
        ).first()
        if releaseId and is_author:
            selected_release = session.exec(
                select(ProjectPageRelease).where(
                    ProjectPageRelease.id == releaseId,
                    ProjectPageRelease.page_id == page.id,
                    ProjectPageRelease.is_delete == 0,
                )
            ).first()
            if selected_release:
                active_release = selected_release

    use_release_snapshot = False
    if active_release and project.state == 1:
        if not is_author:
            use_release_snapshot = True
        elif str(releaseMode or "").lower() in {"published", "release", "snapshot"}:
            use_release_snapshot = True

    return success({
        "id": project.id,
        "projectName": project.project_name,
        "state": project.state,
        "indexImage": resolve_index_image(project.index_image, request),
        "createUserId": project.create_user_id,
        "createTime": project.create_time.isoformat(),
        "remarks": project.remarks,
        "content": active_release.content if use_release_snapshot else project.content,
        "isDelete": project.is_delete,
        "releaseVersion": active_release.version if active_release else None,
        "releaseMode": "snapshot" if use_release_snapshot else "live",
    })

@router.post("/save/data")
def save_data(
    id: Optional[str] = Form(None),
    projectId: Optional[str] = Form(None),
    content: str = Form(...),
    session: Session = Depends(get_session),
    context: GoviewTokenContext = Depends(require_goview_context)
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

    scoped_page = get_scoped_project_page(session, project.id, context)
    if not can_manage_project(project, context, scoped_page):
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
    context: GoviewTokenContext = Depends(require_goview_context)
):
    project = session.get(GoviewProject, payload.get("id"))
    if not project:
        return error(404, "project not found")

    scoped_page = get_scoped_project_page(session, project.id, context)
    if not can_manage_project(project, context, scoped_page):
        return error(403, "permission denied")
        
    if "projectName" in payload:
        name = payload.get("projectName") or ""
        if len(name) > 200:
            return error(400, "projectName too long")
        project.project_name = name
        if scoped_page:
            scoped_page.page_name = name
            scoped_page.updated_at = datetime.now(timezone.utc)
            session.add(scoped_page)
        
    if "remarks" in payload:
        project.remarks = payload.get("remarks") or ""
        if scoped_page:
            scoped_page.remarks = payload.get("remarks") or ""
            scoped_page.updated_at = datetime.now(timezone.utc)
            session.add(scoped_page)
        
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
    context: GoviewTokenContext = Depends(require_goview_context)
):
    project = session.get(GoviewProject, payload.get("id"))
    if not project:
        return error(404, "project not found")

    scoped_page = get_scoped_project_page(session, project.id, context)
    if not can_manage_project(project, context, scoped_page):
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
    context: GoviewTokenContext = Depends(require_goview_context)
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
        if not project:
            continue
        scoped_page = get_scoped_project_page(session, project.id, context)
        if can_manage_project(project, context, scoped_page):
            project.is_delete = 1
            project.update_time = datetime.now(timezone.utc)
            session.add(project)
            if scoped_page:
                scoped_page.is_delete = 1
                scoped_page.updated_at = datetime.now(timezone.utc)
                session.add(scoped_page)
    
    session.commit()
    return success(None)

@router.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    context: GoviewTokenContext = Depends(require_goview_context)
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
