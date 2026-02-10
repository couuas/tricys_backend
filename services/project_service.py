import shutil
import logging
import uuid
import os
import json
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select
from fastapi import HTTPException

from tricys_backend.models.project import Project
from tricys_backend.models.task import Task
from tricys_backend.models.goview_project import GoviewProject
from tricys_backend.services.layout_service import LayoutService   
from tricys_backend.services.file_manager import FileManager       

logger = logging.getLogger(__name__)

class ProjectService:

    @staticmethod
    def ensure_goview_project(
        session: Session,
        project_id: str,
        project_name: str,
        user_id: Optional[str],
        commit: bool = True
    ) -> None:
        if not user_id:
            return
        try:
            existing = session.get(GoviewProject, project_id)
            if existing:
                return

            safe_name = project_name or f"Tricys-{str(project_id)[:8]}"
            goview_project = GoviewProject(
                id=project_id,
                project_name=safe_name,
                content="{}",
                state=-1,
                index_image="",
                remarks=f"Tricys project: {project_id}",
                create_user_id=user_id,
            )
            session.add(goview_project)
            if commit:
                session.commit()
        except Exception as e:
            logger.warning(f"Goview sync failed for project {project_id}: {e}")

    @staticmethod
    def sync_goview_name(
        session: Session,
        project_id: str,
        project_name: str,
        user_id: Optional[str]
    ) -> None:
        if not user_id:
            return
        try:
            goview_project = session.get(GoviewProject, project_id)
            if not goview_project:
                ProjectService.ensure_goview_project(
                    session,
                    project_id=project_id,
                    project_name=project_name,
                    user_id=user_id,
                    commit=True
                )
                return

            if goview_project.create_user_id != user_id:
                return

            goview_project.project_name = project_name
            goview_project.update_time = datetime.now(timezone.utc)
            session.add(goview_project)
            session.commit()
        except Exception as e:
            logger.warning(f"Goview rename sync failed for project {project_id}: {e}")

    @staticmethod
    def sync_goview_payload(
        session: Session,
        project_id: str,
        user_id: Optional[str],
        payload: Optional[Dict[str, Any]]
    ) -> None:
        if not user_id or not payload:
            return
        try:
            ProjectService.ensure_goview_project(
                session,
                project_id=project_id,
                project_name=payload.get("project_name") or payload.get("projectName") or "",
                user_id=user_id,
                commit=False
            )
            goview_project = session.get(GoviewProject, project_id)
            if not goview_project:
                return

            if goview_project.create_user_id != user_id:
                return

            if payload.get("project_name") or payload.get("projectName"):
                goview_project.project_name = payload.get("project_name") or payload.get("projectName")
            if "content" in payload:
                goview_project.content = payload.get("content") or "{}"
            if "state" in payload and payload.get("state") is not None:
                goview_project.state = int(payload.get("state"))
            if "index_image" in payload or "indexImage" in payload:
                goview_project.index_image = payload.get("index_image") or payload.get("indexImage") or ""
            if "remarks" in payload:
                goview_project.remarks = payload.get("remarks") or ""

            goview_project.update_time = datetime.now(timezone.utc)
            session.add(goview_project)
            session.commit()
        except Exception as e:
            logger.warning(f"Goview payload sync failed for project {project_id}: {e}")

    @staticmethod
    def create_project(
        session: Session,
        file_content: str,
        filename: str,
        user_id: Optional[str] = None
    ) -> Project:
        """
        Creates a new project from an uploaded .mo file.
        """
        project_id = str(uuid.uuid4())

        try:
            # 2. File System
            project_dir = FileManager.create_project_directory(project_id)

            # Save file
            model_path = FileManager.get_source_file_path(project_id, filename)

            with open(model_path, 'w', encoding='utf-8') as f:     
                f.write(file_content)

            # 3. Parse Structure
            structure_data = LayoutService.parse_model_structure(file_content)
            extracted_params = structure_data.get("parameters", {})

            # 4. Create DB Entry
            project = Project(
                id=project_id,
                user_id=user_id,
                name=os.path.basename(filename),
                path=str(project_dir),
                model_file_path=str(model_path),
                structure_json=structure_data,
                defaults_json=extracted_params,
                parameters_json=extracted_params.copy(), 
                simulation_config={"model_name": structure_data.get("model_name", "Model")}
            )

            session.add(project)
            ProjectService.ensure_goview_project(
                session,
                project_id=project_id,
                project_name=project.name,
                user_id=user_id,
                commit=False
            )
            session.commit()
            session.refresh(project)

            logger.info(f"Created project {project_id} from {filename} for user {user_id}")
            return project

        except Exception as e:
            logger.error(f"Failed to create project: {e}")
            raise e

    @staticmethod
    def list_projects(
        session: Session,
        user_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Project]:
        query = select(Project).offset(skip).limit(limit).order_by(Project.updated_at.desc())
        if user_id:
            query = query.where(Project.user_id == user_id)        
        return session.exec(query).all()

    @staticmethod
    def list_public_projects(
        session: Session,
        skip: int = 0,
        limit: int = 100
    ) -> List[Project]:
        query = select(Project).where(Project.is_public == True).offset(skip).limit(limit).order_by(Project.updated_at.desc())
        return session.exec(query).all()

    @staticmethod
    def get_project(session: Session, project_id: str) -> Project: 
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @staticmethod
    def update_parameters(session: Session, project_id: str, new_params: List[Dict]) -> Project:
        project = ProjectService.get_project(session, project_id)  
        current = project.parameters_json or []

        if isinstance(current, dict):
            current_list = [{"name": k, "value": v} for k, v in current.items()]
        else:
            current_list = current

        current_map = {p['name']: p for p in current_list}

        for p in new_params:
            name = p.get('name')
            if name:
                current_map[name] = p

        updated_list = list(current_map.values())
        project.parameters_json = updated_list
        project.updated_at = datetime.now(timezone.utc)

        session.add(project)
        session.commit()
        session.refresh(project)
        return project

    @staticmethod
    def update_ui_state(
        session: Session,
        project_id: str,
        field: str,
        data: Any
    ) -> Project:
        project = ProjectService.get_project(session, project_id)  
        
        if hasattr(project, field):
            setattr(project, field, data)
            project.updated_at = datetime.now(timezone.utc)        
            session.add(project)
            session.commit()
            session.refresh(project)
        else:
            raise ValueError(f"Invalid field {field} on Project")  

        return project

    @staticmethod
    def delete_project(session: Session, project_id: str) -> None: 
        project = ProjectService.get_project(session, project_id)  

        try:
            if project.path and os.path.exists(project.path):      
                shutil.rmtree(project.path)
        except Exception as e:
            logger.error(f"Failed to delete project files for {project_id}: {e}")

        goview_project = session.get(GoviewProject, project_id)
        if goview_project:
            goview_project.is_delete = 1
            goview_project.update_time = datetime.now(timezone.utc)
            session.add(goview_project)

        session.delete(project)
        session.commit()

    @staticmethod
    def get_visual_config(session: Session, project_id: str) -> Dict:
        project = ProjectService.get_project(session, project_id)  
        return project.visual_config or {}

    @staticmethod
    def update_visual_config(session: Session, project_id: str, config: Dict) -> Project:
        project = ProjectService.get_project(session, project_id)  
        project.visual_config = config
        project.updated_at = datetime.now(timezone.utc)
        session.add(project)
        session.commit()
        session.refresh(project)
        return project

    @staticmethod
    def set_component_visual(session: Session, project_id: str, component_id: str, visual_data: Dict) -> Project:
        project = ProjectService.get_project(session, project_id)  
        current_config = dict(project.visual_config or {})
        cid = component_id.lower()
        current_config[cid] = visual_data
        project.visual_config = current_config
        project.updated_at = datetime.now(timezone.utc)
        session.add(project)
        session.commit()
        session.refresh(project)
        return project

    @staticmethod
    def save_model_file(project_id: str, component_id: str, file_content: bytes, filename: str) -> str:
        project_dir = FileManager.get_project_dir(project_id)
        visuals_dir = project_dir / "visuals"
        visuals_dir.mkdir(parents=True, exist_ok=True)

        safe_name = f"{component_id}_{filename}"
        file_path = visuals_dir / safe_name

        with open(file_path, "wb") as f:
            f.write(file_content)

        return f"/assets/{project_id}/visuals/{safe_name}"

    @staticmethod
    def export_project(session: Session, project_id: str) -> str:
        """
        Creates a ZIP archive containing the ENTIRE project workspace and metadata.
        """
        project = ProjectService.get_project(session, project_id)
        project_dir = FileManager.get_project_dir(project_id)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            gather_path = Path(temp_dir)
            
            # 1. Generate Metadata
            
            # Serialize Tasks
            tasks_data = []
            for task in project.tasks:
                tasks_data.append({
                    "id": task.id,
                    "name": task.name,
                    "type": task.type,
                    "status": task.status,
                    "config_json": task.config_json,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                    "error_msg": task.error_msg
                    # Note: pid, is not relevant for restored tasks (they are not running)
                    # Workspace/Result paths will be reconstructed
                })

            metadata = {
                "id": project.id,
                "name": project.name,
                "structure_json": project.structure_json,
                "defaults_json": project.defaults_json,
                "parameters_json": project.parameters_json,
                "visual_config": project.visual_config,
                "simulation_config": project.simulation_config,
                "component_groups": project.component_groups,
                "annotations": project.annotations,
                "alert_rules": project.alert_rules,
                "sidebar_config": project.sidebar_config,
                "model_file_path_rel": os.path.relpath(project.model_file_path, project_dir) if project.model_file_path else None,
                "tasks": tasks_data,
                "component_layouts": project.component_layouts # [NEW] Persist component dashboards
            }

            goview_project = session.get(GoviewProject, project.id)
            if goview_project:
                metadata["goview"] = {
                    "project_name": goview_project.project_name,
                    "content": goview_project.content,
                    "state": goview_project.state,
                    "index_image": goview_project.index_image,
                    "remarks": goview_project.remarks,
                    "is_delete": goview_project.is_delete
                }
            
            with open(gather_path / "project_metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4)
            
            # 2. Copy ENTIRE workspace content
            # ignore_func = shutil.ignore_patterns('__pycache__', '*.pyc', '*.tmp')
            # shutil.copytree(project_dir, gather_path, dirs_exist_ok=True, ignore=ignore_func)
            
            # Simple copy of everything in project_dir to gather_path
            # We use dirs_exist_ok=True to merge with the existing directory (which contains metadata)
            if project_dir.exists():
                shutil.copytree(
                    project_dir, 
                    gather_path, 
                    dirs_exist_ok=True, 
                    ignore=shutil.ignore_patterns('__pycache__')
                )
                
            # 3. Create Zip
            zip_fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix=f"project_{project_id}_")
            os.close(zip_fd) 
            
            base_zip_path = zip_path.replace(".zip", "")
            shutil.make_archive(base_zip_path, 'zip', gather_path)
            
            return zip_path

    @staticmethod
    def import_project(session: Session, zip_content: bytes, user_id: Optional[str] = None) -> Project:
        """
        Restores a project from a ZIP archive (Full Workspace).
        """
        new_project_id = str(uuid.uuid4())
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_zip = Path(temp_dir) / "import.zip"
            with open(temp_zip, "wb") as f:
                f.write(zip_content)
                
            extract_path = Path(temp_dir) / "extracted"
            extract_path.mkdir()
            
            try:
                with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail="Invalid ZIP archive")
                
            metadata_path = extract_path / "project_metadata.json"
            if not metadata_path.exists():
                raise HTTPException(status_code=400, detail="Invalid project archive: missing metadata.")
                
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
                
            old_project_id = metadata.get("id")
            project_dir = FileManager.create_project_directory(new_project_id)
            
            # --- FULL RESTORE ---
            # Copy EVERYTHING from extracted path to new project dir
            # This includes source, visuals, media, tasks, etc.
            # We exclude project_metadata.json from the final workspace if desired, 
            # but getting rid of it is not strictly necessary. Let's exclude it to keep it clean.
            
            if metadata_path.exists():
                os.remove(metadata_path) # Remove metadata file before copying
            
            shutil.copytree(extract_path, project_dir, dirs_exist_ok=True)
                
            # --- PATH & ID REWRITES ---
            
            model_file_path = None
            if metadata.get("model_file_path_rel"):
                # If path was relative, it should be valid in new dir
                model_file_path = str((project_dir / metadata["model_file_path_rel"]).resolve())
            
            visual_config = metadata.get("visual_config")
            if visual_config and old_project_id:
                vc_str = json.dumps(visual_config)
                # Replace old project ID in URLs with new project ID
                vc_str = vc_str.replace(f"/assets/{old_project_id}/", f"/assets/{new_project_id}/")
                visual_config = json.loads(vc_str)
                
                
            project = Project(
                id=new_project_id,
                user_id=user_id,
                name=metadata.get("name", "Imported Project"),
                path=str(project_dir),
                model_file_path=model_file_path,
                structure_json=metadata.get("structure_json"),
                defaults_json=metadata.get("defaults_json"),
                parameters_json=metadata.get("parameters_json"),
                visual_config=visual_config,
                simulation_config=metadata.get("simulation_config"),
                component_groups=metadata.get("component_groups"),
                annotations=metadata.get("annotations"),
                alert_rules=metadata.get("alert_rules"),
                sidebar_config=metadata.get("sidebar_config"),
                component_layouts=metadata.get("component_layouts")
            )
            
            session.add(project)
            session.commit() # Commit project first to ensure foreign key validity
            session.refresh(project)

            ProjectService.ensure_goview_project(
                session,
                project_id=new_project_id,
                project_name=project.name,
                user_id=user_id,
                commit=True
            )

            goview_payload = metadata.get("goview") if isinstance(metadata.get("goview"), dict) else None
            if goview_payload:
                ProjectService.sync_goview_payload(
                    session,
                    project_id=new_project_id,
                    user_id=user_id,
                    payload=goview_payload
                )
            
            # --- RESTORE TASKS ---
            restored_tasks_data = metadata.get("tasks", [])
            tasks_dir = project_dir / "tasks"
            
            for task_data in restored_tasks_data:
                old_task_id = task_data.get("id")
                new_task_id = str(uuid.uuid4())
                
                # Check for existing folder (renaming old ID to new ID)
                old_task_path = tasks_dir / old_task_id
                new_task_path = tasks_dir / new_task_id
                
                final_workspace_path = None
                
                if old_task_path.exists():
                     try:
                         # Rename directory to match new ID
                         old_task_path.rename(new_task_path)
                         final_workspace_path = str(new_task_path)
                     except Exception as e:
                         logger.warning(f"Failed to rename task dir {old_task_id} to {new_task_id}: {e}")
                
                # Create Task Record
                # Parse timestamps safely
                created_at = datetime.now(timezone.utc)
                if task_data.get("created_at"):
                    try:
                        created_at = datetime.fromisoformat(task_data["created_at"])
                    except: pass
                    
                new_task = Task(
                    id=new_task_id,
                    project_id=new_project_id,
                    name=task_data.get("name"),
                    type=task_data.get("type", "BASIC"),
                    status=task_data.get("status", "COMPLETED"), # Assume completed/stored status
                    config_json=task_data.get("config_json", {}),
                    created_at=created_at,
                    updated_at=datetime.now(timezone.utc),
                    workspace_path=final_workspace_path,
                    result_path=final_workspace_path if final_workspace_path else None, 
                    error_msg=task_data.get("error_msg")
                )
                session.add(new_task)
            
            session.commit()
            
            return project

    @staticmethod
    def fork_project(session: Session, project_id: str, user_id: str) -> Project:
        """
        Creates a copy of an existing project for a different user.
        """
        original = ProjectService.get_project(session, project_id)
        new_project_id = str(uuid.uuid4())
        
        # 1. Copy Files
        original_dir = FileManager.get_project_dir(project_id)
        new_dir = FileManager.create_project_directory(new_project_id)
        
        if original_dir.exists():
            # Copy source and visuals
            if (original_dir / "source").exists():
                shutil.copytree(original_dir / "source", new_dir / "source", dirs_exist_ok=True)
            if (original_dir / "visuals").exists():
                shutil.copytree(original_dir / "visuals", new_dir / "visuals", dirs_exist_ok=True)
        
        # 2. Prepare new DB record
        model_file_path = None
        if original.model_file_path:
            # Re-calculate absolute path for new dir
            rel = os.path.relpath(original.model_file_path, original_dir)
            model_file_path = str((new_dir / rel).resolve())

        # Update URLs in visual_config if they contain the old ID
        visual_config = original.visual_config
        if visual_config:
             vc_str = json.dumps(visual_config)
             vc_str = vc_str.replace(f"/assets/{project_id}/", f"/assets/{new_project_id}/")
             visual_config = json.loads(vc_str)

        forked = Project(
            id=new_project_id,
            user_id=user_id,
            name=f"{original.name} (Copy)",
            path=str(new_dir),
            model_file_path=model_file_path,
            structure_json=original.structure_json,
            defaults_json=original.defaults_json,
            parameters_json=original.parameters_json,
            visual_config=visual_config,
            simulation_config=original.simulation_config,
            component_groups=original.component_groups,
            annotations=original.annotations,
            alert_rules=original.alert_rules,
            sidebar_config=original.sidebar_config,
            is_public=False # Forked project is private by default
        )
        
        session.add(forked)
        session.commit()
        session.refresh(forked)

        ProjectService.ensure_goview_project(
            session,
            project_id=new_project_id,
            project_name=forked.name,
            user_id=user_id,
            commit=True
        )
        return forked