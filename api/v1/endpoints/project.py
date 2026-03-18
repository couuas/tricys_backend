from fastapi import APIRouter, HTTPException, UploadFile, File, Body, Depends, Query
from fastapi.responses import FileResponse
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import os
from sqlmodel import Session, select

from tricys_backend.services.project_service import ProjectService 
from tricys_backend.services.file_manager import FileManager
from tricys_backend.utils.db import get_session
from tricys_backend.models.project import Project
from tricys_backend.models.user import User
from tricys_backend.models.goview_project import GoviewProject
from tricys_backend.api.deps import get_current_user

router = APIRouter()

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
    return project.parameters_json or []

@router.get("/{project_id}/defaults")
def get_defaults(
    project_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = get_user_project(session, project_id, current_user.id, allow_public=True)
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
    
    # Source codes are stored in structure_json["source_codes"]
    struct = project.structure_json or {}
    source_codes = struct.get("source_codes", {})
    
    # Try case-insensitive match
    source = None
    cid_lower = component_id.lower()
    for k, v in source_codes.items():
        if k.lower() == cid_lower:
            source = v
            break
            
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
