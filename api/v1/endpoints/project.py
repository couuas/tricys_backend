from fastapi import APIRouter, HTTPException, UploadFile, File, Body, Depends, Query
from fastapi.responses import FileResponse
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import os
import re
from sqlmodel import Session, select

from tricys_backend.services.project_service import ProjectService 
from tricys_backend.services.file_manager import FileManager
from tricys_backend.services.layout_service import LayoutService
from tricys_backend.core.security import create_access_token
from tricys_backend.utils.db import get_session
from tricys_backend.models.project import Project
from tricys_backend.models.user import User
from tricys_backend.models.goview_project import GoviewProject
from tricys_backend.models.project_page import ProjectPage
from tricys_backend.models.task import Task
from tricys_backend.api.deps import get_current_user
from tricys_backend.services.project_page_templates import (
    build_project_page_template,
    list_project_page_data_sources,
    list_project_page_templates,
)

router = APIRouter()


def refresh_project_structure_if_needed(project: Project, session: Session) -> Project:
    if not project.model_file_path or not os.path.exists(project.model_file_path):
        return project

    structure = project.structure_json or {}
    source_codes = structure.get("source_codes", {}) or {}
    components = structure.get("components", []) or []
    parameters = project.parameters_json or []
    parameter_names = {
        item.get("name")
        for item in parameters
        if isinstance(item, dict) and item.get("name")
    }

    needs_refresh = not project.defaults_json or not parameters or not source_codes

    main_model_name = structure.get("model_name", "").split(".")[-1]
    if not main_model_name:
        main_model_name = "Cycle"

    if not needs_refresh and components:
        component_ids = {component.get("id") for component in components if component.get("id")}
        if main_model_name not in source_codes or not component_ids.issubset(set(source_codes.keys())):
            needs_refresh = True

    if not needs_refresh:
        for component_id, source_code in source_codes.items():
            if component_id == main_model_name or not isinstance(source_code, str):
                continue
            stripped_source = source_code.strip()
            if stripped_source.startswith(("model ", "block ")):
                continue
            constructor_match = re.search(rf"\b{re.escape(component_id)}(?:\[[^\]]+\])?\s*\((.*)\)", stripped_source, re.DOTALL)
            if not constructor_match:
                continue
            if '=' not in constructor_match.group(1):
                continue
            prefix = f"{component_id}."
            if not any(name.startswith(prefix) for name in parameter_names):
                needs_refresh = True
                break

    if not needs_refresh:
        return project

    with open(project.model_file_path, "r", encoding="utf-8") as model_file:
        refreshed_struct = LayoutService.parse_model_structure(model_file.read())

    extracted_params = refreshed_struct.get("parameters", [])
    project.structure_json = refreshed_struct
    project.defaults_json = extracted_params
    project.parameters_json = [dict(item) for item in extracted_params]
    project.updated_at = datetime.now(timezone.utc)
    flag_modified(project, "structure_json")
    flag_modified(project, "defaults_json")
    flag_modified(project, "parameters_json")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

@router.get("/export", response_class=FileResponse)
def export_current_project(
    project_id: str = Query(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Exports a project as a ZIP archive."""
    # Verify ownership
    get_user_project(session, project_id, current_user.id, allow_public=True)
    
    zip_path = ProjectService.export_project(session, project_id)
    return FileResponse(
        zip_path, 
        media_type='application/zip', 
        filename=f"project_{project_id}.zip"
    )

@router.post("/import", response_model=Dict[str, Any])
async def import_project_archive(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Imports a project from a ZIP archive."""
    try:
        content = await file.read()
        project = ProjectService.import_project(session, content, current_user.id)
        return {
            "project_id": project.id,
            "name": project.name,
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import project: {str(e)}")
@router.get("/", response_model=List[Dict[str, Any]])
def list_projects(
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """List projects, automatically filtered by the current authenticated user."""
    projects = ProjectService.list_projects(session, current_user.id, skip, limit)
    return [
        {
            "id": p.id,
            "name": p.name,
            "user_id": p.user_id,
            "created_at": p.created_at,
            "updated_at": p.updated_at
        }
        for p in projects
    ]

@router.get("/public", response_model=List[Dict[str, Any]])
def list_public_projects(
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """List all projects marked as public."""
    projects = ProjectService.list_public_projects(session, skip, limit)
    return [
        {
            "id": p.id,
            "name": p.name,
            "user_id": p.user_id,
            "created_at": p.created_at,
            "updated_at": p.updated_at
        }
        for p in projects
    ]

@router.post("/upload", response_model=Dict[str, Any])
async def upload_model(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Uploads a .mo file and creates a new Project environment for the current user.
    """
    try:
        content = (await file.read()).decode('utf-8')
        filename = file.filename or "model.mo"
        
        project = ProjectService.create_project(session, content, filename, current_user.id)
        
        return {
            "project_id": project.id,
            "name": project.name,
            "user_id": project.user_id,
            "components": project.structure_json.get("components", []),
            "connections": project.structure_json.get("connections", []),
            "parameters": project.defaults_json,
            "file_path": project.model_file_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)}")

@router.post("/demo", response_model=Dict[str, Any])
def create_demo_project(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Creates a demo project using the server-side example model.
    """
    # Try to locate the demo file relative to this file or cwd
    # Assuming cwd is the root of the repo (where tricys_backend is located)
    possible_paths = [
        os.path.join("tricys_backend", "assets", "demo", "example_model.mo"),
        os.path.join("assets", "demo", "example_model.mo"), # If cwd is inside tricys_backend
        # Fallback relative to this file: .../api/v1/endpoints/project.py -> .../assets/demo/example_model.mo
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "demo", "example_model.mo"))
    ]
    
    demo_file_path = None
    for p in possible_paths:
        if os.path.exists(p):
            demo_file_path = p
            break
            
    if not demo_file_path:
        raise HTTPException(status_code=404, detail="Demo asset 'example_model.mo' not found on server.")

    try:
        with open(demo_file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        filename = "example_model.mo"
        
        # Create project using service
        project = ProjectService.create_project(session, content, filename, current_user.id)
        
        # Customize name
        project.name = f"Demo Project {datetime.now().strftime('%H%M%S')}"
        session.add(project)
        session.commit()
        session.refresh(project)
        ProjectService.sync_goview_name(session, project.id, project.name, current_user.id)

        return {
            "project_id": project.id,
            "name": project.name,
            "user_id": project.user_id,
            "components": project.structure_json.get("components", []),
            "connections": project.structure_json.get("connections", []),
            "parameters": project.defaults_json,
            "file_path": project.model_file_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create demo project: {str(e)}")

def get_user_project(session: Session, project_id: str, user_id: str, allow_public: bool = False) -> Project:
    project = ProjectService.get_project(session, project_id)
    if project.user_id == user_id:
        return project
    if allow_public and project.is_public:
        return project
    raise HTTPException(status_code=403, detail="Not authorized to access this project")


@router.post("/{project_id}/goview/session", response_model=Dict[str, Any])
def create_goview_project_session(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    token = create_access_token(
        current_user.id,
        extra_claims={
            "operator_user_id": current_user.id,
            "tricys_project_id": project.id,
            "scope": "goview:project",
        },
    )
    return {
        "token": token,
        "project_id": project.id,
        "scope": "goview:project",
    }


def serialize_project_page(project: Project, page: ProjectPage, goview_project: GoviewProject) -> Dict[str, Any]:
    return {
        "id": page.id,
        "project_id": project.id,
        "goview_project_id": goview_project.id,
        "page_key": page.page_key,
        "page_name": page.page_name,
        "page_type": page.page_type,
        "is_default": page.is_default,
        "visibility": page.visibility,
        "published": goview_project.state == 1,
        "state": goview_project.state,
        "index_image": goview_project.index_image,
        "remarks": page.remarks or goview_project.remarks,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
        "schema_version": 2,
        "editor": "goview"
    }


def serialize_project_page_with_release(
    session: Session,
    project: Project,
    page: ProjectPage,
    goview_project: GoviewProject,
) -> Dict[str, Any]:
    payload = serialize_project_page(project, page, goview_project)
    active_release = ProjectService.get_active_project_page_release(session, page.id)
    releases = ProjectService.list_project_page_releases(session, page.id, include_inactive=True)
    payload["active_release"] = (
        {
            "id": active_release.id,
            "version": active_release.version,
            "published_at": active_release.published_at,
        }
        if active_release
        else None
    )
    payload["active_release_version"] = active_release.version if active_release else None
    payload["release_count"] = len(releases)
    return payload


def serialize_project_page_release(release) -> Dict[str, Any]:
    content_summary = {"component_count": 0, "data_pond_count": 0, "background": None, "theme": None}
    try:
        content = json.loads(release.content or "{}")
        component_list = content.get("componentList") or []
        request_global_config = content.get("requestGlobalConfig") or {}
        canvas_config = content.get("editCanvasConfig") or {}
        content_summary = {
            "component_count": len(component_list),
            "data_pond_count": len(request_global_config.get("requestDataPond") or []),
            "background": canvas_config.get("background"),
            "theme": canvas_config.get("chartThemeColor"),
        }
    except Exception:
        pass
    return {
        "id": release.id,
        "page_id": release.page_id,
        "project_id": release.project_id,
        "goview_project_id": release.goview_project_id,
        "version": release.version,
        "remarks": release.remarks,
        "index_image": release.index_image,
        "published_at": release.published_at,
        "is_active": bool(release.is_active),
        "content_summary": content_summary,
    }

@router.post("/{project_id}/fork", response_model=Project)
def fork_project(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Clone a public project or own project."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if project.user_id != current_user.id and not project.is_public:
        raise HTTPException(status_code=403, detail="Not authorized to fork this project")
        
    return ProjectService.fork_project(session, project_id, current_user.id)



@router.get("/consistency")
def check_project_consistency(
    fix: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    projects = ProjectService.list_projects(session, current_user.id, 0, 100000)
    project_ids = {p.id for p in projects}

    goview_projects = session.exec(
        select(GoviewProject).where(GoviewProject.create_user_id == current_user.id)
    ).all()
    goview_ids = {p.id for p in goview_projects}

    missing_goview = sorted(list(project_ids - goview_ids))
    orphan_goview = sorted(list(goview_ids - project_ids))

    fixed = []
    if fix and missing_goview:
        id_to_project = {p.id: p for p in projects}
        for pid in missing_goview:
            project = id_to_project.get(pid)
            if not project:
                continue
            ProjectService.ensure_goview_project(
                session,
                project_id=pid,
                project_name=project.name,
                user_id=current_user.id,
                commit=True
            )
            fixed.append(pid)

    return {
        "status": "success",
        "missing_goview": missing_goview,
        "orphan_goview": orphan_goview,
        "fixed": fixed
    }

@router.post("/{project_id}/fork", response_model=Project)
def fork_project(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Clone a public project or own project."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if project.user_id != current_user.id and not project.is_public:
        raise HTTPException(status_code=403, detail="Not authorized to fork this project")
        
    return ProjectService.fork_project(session, project_id, current_user.id)

@router.get("/{project_id}", response_model=Dict[str, Any])
def get_project_details(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    project = refresh_project_structure_if_needed(project, session)
    return {
        "id": project.id,
        "name": project.name,
        "user_id": project.user_id,
        "created_at": project.created_at,
        "file_path": project.model_file_path,
        "structure": project.structure_json,
        "current_parameters": project.parameters_json,
        "visual_config": project.visual_config or {},
        "simulation_config": project.simulation_config or {}
    }


@router.get("/page-templates", response_model=List[Dict[str, Any]])
def get_project_page_templates(
    current_user: User = Depends(get_current_user)
):
    return list_project_page_templates()


@router.get("/{project_id}/page-data-sources", response_model=List[Dict[str, Any]])
def get_project_page_data_sources(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    return list_project_page_data_sources(project)


@router.get("/{project_id}/pages", response_model=Dict[str, Any])
def list_project_pages(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    items: List[Dict[str, Any]] = []

    owned_by_user = project.user_id == current_user.id
    if owned_by_user:
        ProjectService.ensure_default_project_page(
            session,
            project=project,
            user_id=current_user.id,
            commit=True,
        )

    pages = ProjectService.list_project_pages(session, project.id)
    for page in pages:
        goview_project = session.get(GoviewProject, page.goview_project_id)
        if not goview_project or goview_project.is_delete == 1:
            continue
        if not owned_by_user and goview_project.state != 1:
            continue
        items.append(serialize_project_page_with_release(session, project, page, goview_project))

    return {
        "project_id": project.id,
        "items": items,
        "total": len(items),
        "phase": "phase-2-multi-page"
    }


@router.post("/{project_id}/pages/ensure", response_model=Dict[str, Any])
def ensure_project_page(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id)
    created = ProjectService.ensure_default_project_page(
        session,
        project=project,
        user_id=current_user.id,
        commit=True,
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to initialize default page")
    goview_project = session.get(GoviewProject, created.goview_project_id)
    if not goview_project:
        raise HTTPException(status_code=500, detail="Linked GoView editor project not found")
    return serialize_project_page_with_release(session, project, created, goview_project)


@router.post("/{project_id}/pages", response_model=Dict[str, Any])
def create_project_page(
    project_id: str,
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id)
    template_key = str(payload.get("template_key") or payload.get("templateKey") or "").strip()
    page_name = str(payload.get("page_name") or payload.get("pageName") or "New Page").strip()
    if not page_name:
        raise HTTPException(status_code=400, detail="page_name is required")
    if len(page_name) > 200:
        raise HTTPException(status_code=400, detail="page_name too long")

    template_payload = None
    if template_key:
        latest_task = session.exec(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(Task.created_at.desc())
            .limit(1)
        ).first()
        template_payload = build_project_page_template(project, template_key, page_name, latest_task=latest_task)

    created = ProjectService.create_project_page(
        session,
        project=project,
        user_id=current_user.id,
        page_name=page_name,
        page_type=str((template_payload or {}).get("page_type") or payload.get("page_type") or payload.get("pageType") or "custom"),
        remarks=str((template_payload or {}).get("remarks") or payload.get("remarks") or ""),
        template_key=str((template_payload or {}).get("template_key") or template_key or ""),
        is_default=bool(payload.get("is_default") or payload.get("isDefault") or False),
        content=str((template_payload or {}).get("content") or payload.get("content") or "{}"),
        state=int(payload.get("state", -1)),
        index_image=str(payload.get("index_image") or payload.get("indexImage") or ""),
    )
    goview_project = session.get(GoviewProject, created.goview_project_id)
    if not goview_project:
        raise HTTPException(status_code=500, detail="Linked GoView editor project not found")
    return serialize_project_page_with_release(session, project, created, goview_project)


@router.patch("/{project_id}/pages/{page_id}/publish", response_model=Dict[str, Any])
def publish_project_page(
    project_id: str,
    page_id: str,
    payload: Dict[str, Any] = Body(default={}),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id)
    page = ProjectService.get_project_page(session, page_id)
    if not page or page.project_id != project.id:
        raise HTTPException(status_code=404, detail="Page not found")
    goview_project = session.get(GoviewProject, page.goview_project_id)
    if not goview_project or goview_project.is_delete == 1:
        raise HTTPException(status_code=404, detail="Linked GoView editor project not found")
    if goview_project.create_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to manage this page")

    published = payload.get("published")
    state = payload.get("state")
    if state is None:
        state = 1 if published is not False else -1

    updated = ProjectService.update_project_page_publish_state(
        session,
        page=page,
        published=int(state) == 1,
        created_by=current_user.id,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update page state")
    refreshed_goview = session.get(GoviewProject, updated.goview_project_id)
    if not refreshed_goview:
        raise HTTPException(status_code=500, detail="Linked GoView editor project not found")
    return serialize_project_page_with_release(session, project, updated, refreshed_goview)


@router.get("/{project_id}/pages/{page_id}/releases", response_model=List[Dict[str, Any]])
def list_project_page_releases(
    project_id: str,
    page_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    page = ProjectService.get_project_page(session, page_id)
    if not page or page.project_id != project.id:
        raise HTTPException(status_code=404, detail="Page not found")
    goview_project = session.get(GoviewProject, page.goview_project_id)
    if not goview_project or goview_project.is_delete == 1:
        raise HTTPException(status_code=404, detail="Linked GoView editor project not found")
    if project.user_id != current_user.id and goview_project.state != 1:
        raise HTTPException(status_code=403, detail="Not authorized to access release history")

    releases = ProjectService.list_project_page_releases(
        session,
        page.id,
        include_inactive=project.user_id == current_user.id,
    )
    return [serialize_project_page_release(release) for release in releases]


@router.post("/{project_id}/pages/{page_id}/releases/{release_id}/restore", response_model=Dict[str, Any])
def restore_project_page_release(
    project_id: str,
    page_id: str,
    release_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id)
    page = ProjectService.get_project_page(session, page_id)
    if not page or page.project_id != project.id:
        raise HTTPException(status_code=404, detail="Page not found")

    goview_project = session.get(GoviewProject, page.goview_project_id)
    if not goview_project or goview_project.is_delete == 1:
        raise HTTPException(status_code=404, detail="Linked GoView editor project not found")
    if goview_project.create_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to manage this page")

    release = ProjectService.get_project_page_release(session, release_id)
    if not release or release.page_id != page.id:
        raise HTTPException(status_code=404, detail="Release not found")

    restored = ProjectService.restore_project_page_release(session, page, release)
    if not restored:
        raise HTTPException(status_code=500, detail="Failed to restore release")
    refreshed_goview = session.get(GoviewProject, restored.goview_project_id)
    if not refreshed_goview:
        raise HTTPException(status_code=500, detail="Linked GoView editor project not found")
    return serialize_project_page_with_release(session, project, restored, refreshed_goview)


@router.delete("/{project_id}/pages/{page_id}", response_model=Dict[str, Any])
def delete_project_page(
    project_id: str,
    page_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id)
    page = ProjectService.get_project_page(session, page_id)
    if not page or page.project_id != project.id:
        raise HTTPException(status_code=404, detail="Page not found")
    goview_project = session.get(GoviewProject, page.goview_project_id)
    if not goview_project or goview_project.is_delete == 1:
        raise HTTPException(status_code=404, detail="Linked GoView editor project not found")
    if goview_project.create_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to manage this page")

    ProjectService.delete_project_page(session, page)

    return {"status": "success", "project_id": project.id, "page_id": page_id}

@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    # Verify ownership
    get_user_project(session, project_id, current_user.id)
    ProjectService.delete_project(session, project_id)
    return {"status": "success", "message": "Project deleted"}

@router.patch("/{project_id}")
def update_project(
    project_id: str,
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id)
    name = payload.get("name")
    if name is None:
        raise HTTPException(status_code=400, detail="name is required")
    name = str(name).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name cannot be empty")
    if len(name) > 200:
        raise HTTPException(status_code=400, detail="name too long")

    project.name = name
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    session.refresh(project)
    ProjectService.sync_goview_name(session, project.id, project.name, current_user.id)
    return {
        "id": project.id,
        "name": project.name,
        "updated_at": project.updated_at
    }

@router.get("/{project_id}/structure")
def get_structure(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    return project.structure_json or {"components": [], "connections": []}

@router.get("/{project_id}/parameters")
def get_parameters(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    project = refresh_project_structure_if_needed(project, session)
    return project.parameters_json or []

@router.get("/{project_id}/defaults")
def get_defaults(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    project = refresh_project_structure_if_needed(project, session)
    return project.defaults_json or []

@router.post("/{project_id}/parameters")
def save_parameters(
    project_id: str,
    params: List[Dict[str, Any]] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    # Authorization check inside get_user_project call equivalent logic
    project = get_user_project(session, project_id, current_user.id)
    ProjectService.update_parameters(session, project_id, params)
    return {"status": "success"}

@router.get("/{project_id}/run_config")
def get_run_config(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    return project.simulation_config or {}

@router.post("/{project_id}/run_config")
def save_run_config(
    project_id: str,
    config: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id)
    project.simulation_config = config
    session.add(project)
    session.commit()
    return {"status": "success"}

# --- UI State ---

@router.get("/{project_id}/groups")
def get_groups(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    return project.component_groups or {}

@router.post("/{project_id}/groups")
def save_groups(
    project_id: str,
    groups: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    # Ensure ownership
    get_user_project(session, project_id, current_user.id)
    ProjectService.update_ui_state(session, project_id, "component_groups", groups)
    return {"status": "success"}

@router.get("/{project_id}/sidebar_config")
def get_sidebar_config(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    return project.sidebar_config or []

@router.post("/{project_id}/sidebar_config")
def save_sidebar_config(
    project_id: str,
    config: List[str] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    get_user_project(session, project_id, current_user.id)
    ProjectService.update_ui_state(session, project_id, "sidebar_config", config)
    return {"status": "success"}

@router.get("/{project_id}/annotations")
def get_annotations(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    return project.annotations or {}

@router.post("/{project_id}/annotations")
def save_annotations(
    project_id: str,
    notes: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    get_user_project(session, project_id, current_user.id)
    ProjectService.update_ui_state(session, project_id, "annotations", notes)
    return {"status": "success"}

@router.get("/{project_id}/alerts")
def get_alerts(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    return project.alert_rules or {}

@router.post("/{project_id}/alerts")
def save_alerts(
    project_id: str,
    alerts: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    get_user_project(session, project_id, current_user.id)
    ProjectService.update_ui_state(session, project_id, "alert_rules", alerts)
    return {"status": "success"}

from sqlalchemy.orm.attributes import flag_modified
import logging

# Get logger (assuming defined at top or getting here)
logger = logging.getLogger(__name__)

@router.post("/{project_id}/update_position")
def update_position(
    project_id: str,
    update: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id)
    # Use deepcopy or ensure we modify the dict in a way that marks dirty
    # But flag_modified is best
    struct = project.structure_json
    
    if not struct: raise HTTPException(404, "No structure found")
    
    components = struct.get("components", [])
    found = False
    tid = update.get("id", "").lower()
    
    for c in components:
        if c.get("id", "").lower() == tid:
            if "position" not in c or not isinstance(c["position"], dict):
                c["position"] = {}
            c["position"]["x"] = update["x"]
            c["position"]["y"] = update["y"]
            found = True
            break
            
    if found:
        # Check if we need to update timestamp
        project.updated_at = datetime.now(timezone.utc)
        
        # Explicitly mark structure_json as modified
        project.structure_json = struct # Reassign helpful?
        flag_modified(project, "structure_json")
        
        session.add(project)
        session.commit()
        return {"status": "success"}
        
    raise HTTPException(404, "Component not found")

@router.post("/{project_id}/component_visuals")
def update_component_visuals(
    project_id: str,
    update: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Updates visual configuration (scale, type, url) for a component.
    Payload: { "id": "component_id", "visual": { ... } }
    """
    get_user_project(session, project_id, current_user.id)
    cid = update.get("id")
    visual = update.get("visual")
    if not cid or not visual: raise HTTPException(400, "Invalid payload")
    
    ProjectService.set_component_visual(session, project_id, cid, visual)
    return {"status": "success"}

@router.get("/{project_id}/visual_config")
def get_visual_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    get_user_project(session, project_id, current_user.id, allow_public=True)
    return ProjectService.get_visual_config(session, project_id)

@router.post("/{project_id}/visual_config")
def save_visual_config(
    project_id: str,
    config: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    get_user_project(session, project_id, current_user.id)
    ProjectService.update_visual_config(session, project_id, config)
    return {"status": "success"}

# --- Component Source & Layouts ---

@router.get("/{project_id}/components/{component_id}/source")
def get_component_source(
    project_id: str,
    component_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Retrieves source code for a specific component from model structure."""
    project = get_user_project(session, project_id, current_user.id, allow_public=True)

    def lookup_source(structure: Dict[str, Any]) -> Optional[str]:
        source_codes = structure.get("source_codes", {})
        cid_lower = component_id.lower()
        for key, value in source_codes.items():
            if key.lower() == cid_lower:
                return value
        return None

    project = refresh_project_structure_if_needed(project, session)
    struct = project.structure_json or {}
    source = lookup_source(struct)

    if source is None and project.model_file_path and os.path.exists(project.model_file_path):
        try:
            project = refresh_project_structure_if_needed(project, session)
            struct = project.structure_json or {}
            source = lookup_source(struct)
        except Exception as exc:
            logger.warning(
                "Failed to refresh project structure for component source lookup",
                extra={"project_id": project_id, "component_id": component_id, "error": str(exc)}
            )
            
    if source is None:
        raise HTTPException(status_code=404, detail=f"Source for component {component_id} not found")
        
    return {"id": component_id, "code": source}

@router.get("/{project_id}/components/{component_id}/layout")
def get_component_layout(
    project_id: str,
    component_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Retrieves custom dashboard layout for a component."""
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
    layouts = project.component_layouts or {}
    return layouts.get(component_id.lower(), [])

@router.post("/{project_id}/components/{component_id}/layout")
def save_component_layout(
    project_id: str,
    component_id: str,
    layout: List[Dict[str, Any]] = Body(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Saves custom dashboard layout for a component."""
    project = get_user_project(session, project_id, current_user.id)
    
    layouts = dict(project.component_layouts or {})
    layouts[component_id.lower()] = layout
    project.component_layouts = layouts
    
    flag_modified(project, "component_layouts")
    session.add(project)
    session.commit()
    return {"status": "success"}

@router.post("/{project_id}/media")
async def upload_project_media(
    project_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Uploads a media file (image, video, md) to the project's media folder."""
    get_user_project(session, project_id, current_user.id)
    
    try:
        content = await file.read()
        filename = file.filename or "unnamed_media"
        
        # Use FileManager to get project directory
        project_dir = FileManager.get_project_dir(project_id)
        media_dir = project_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        
        # Add timestamp to prevent name collisions
        timestamp = int(datetime.now().timestamp())
        safe_name = f"{timestamp}_{filename}"
        file_path = media_dir / safe_name
        
        with open(file_path, "wb") as f:
            f.write(content)
            
        # Return URL relative to static mount /assets -> workspaces/
        return {"status": "success", "url": f"/assets/{project_id}/media/{safe_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Media upload failed: {str(e)}")

@router.post("/{project_id}/components/{component_id}/model")      
async def upload_component_model(
    project_id: str,
    component_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Uploads a GLB/GLTF file for a specific component.
    """
    get_user_project(session, project_id, current_user.id)
    
    try:
        content = await file.read()
        filename = file.filename or f"{component_id}.glb"
        
        # Save file
        asset_url = ProjectService.save_model_file(project_id, component_id, content, filename)
        
        # Update config automatically
        # Preserving existing scale if any, defaulting to 1.0
        current_config = ProjectService.get_visual_config(session, project_id)
        cid = component_id.lower()
        existing = current_config.get(cid, {})
        
        new_visual = {
           "type": "custom",
           "url": asset_url,
           "scale": existing.get("scale", 1.0)
        }
        
        ProjectService.set_component_visual(session, project_id, cid, new_visual)
        
        return {"status": "success", "visual": new_visual}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload model: {str(e)}")
