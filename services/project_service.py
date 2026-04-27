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
from tricys_backend.models.project_page import ProjectPage
from tricys_backend.models.project_page_release import ProjectPageRelease
from tricys_backend.services.layout_service import LayoutService   
from tricys_backend.services.file_manager import FileManager       

logger = logging.getLogger(__name__)

class ProjectService:

    @staticmethod
    def _slugify_page_key(value: str) -> str:
        raw = (value or "page").strip().lower()
        cleaned = []
        previous_dash = False
        for char in raw:
            if char.isalnum():
                cleaned.append(char)
                previous_dash = False
            elif not previous_dash:
                cleaned.append("-")
                previous_dash = True
        page_key = "".join(cleaned).strip("-")
        return page_key or "page"

    @staticmethod
    def list_project_pages(session: Session, project_id: str) -> List[ProjectPage]:
        return session.exec(
            select(ProjectPage)
            .where(ProjectPage.project_id == project_id, ProjectPage.is_delete == 0)
            .order_by(ProjectPage.is_default.desc(), ProjectPage.sort_order.asc(), ProjectPage.created_at.asc())
        ).all()

    @staticmethod
    def get_project_page(session: Session, page_id: str) -> Optional[ProjectPage]:
        page = session.get(ProjectPage, page_id)
        if not page or page.is_delete == 1:
            return None
        return page

    @staticmethod
    def ensure_default_project_page(
        session: Session,
        project: Project,
        user_id: Optional[str],
        commit: bool = True
    ) -> Optional[ProjectPage]:
        if not user_id:
            return None

        existing = session.exec(
            select(ProjectPage)
            .where(
                ProjectPage.project_id == project.id,
                ProjectPage.is_default == True,
                ProjectPage.is_delete == 0,
            )
            .order_by(ProjectPage.created_at.asc())
        ).first()
        if existing:
            return existing

        legacy_goview = session.get(GoviewProject, project.id)
        if not legacy_goview:
            ProjectService.ensure_goview_project(
                session,
                project_id=project.id,
                project_name=project.name,
                user_id=user_id,
                commit=False,
            )
            legacy_goview = session.get(GoviewProject, project.id)

        if not legacy_goview:
            return None

        legacy_goview.is_delete = 0
        legacy_goview.update_time = datetime.now(timezone.utc)
        session.add(legacy_goview)

        page = ProjectPage(
            project_id=project.id,
            goview_project_id=legacy_goview.id,
            page_key="overview",
            page_name=legacy_goview.project_name or f"{project.name} Overview",
            page_type="overview",
            is_default=True,
            sort_order=0,
            visibility="public" if legacy_goview.state == 1 else "private",
            remarks=legacy_goview.remarks or f"Default project overview page for {project.id}",
            template_key="project-overview",
            created_by=user_id,
        )
        session.add(page)
        if commit:
            session.commit()
            session.refresh(page)
        return page

    @staticmethod
    def create_project_page(
        session: Session,
        project: Project,
        user_id: str,
        page_name: str,
        page_type: str = "custom",
        remarks: str = "",
        template_key: str = "",
        is_default: bool = False,
        content: str = "{}",
        state: int = -1,
        index_image: str = "",
        page_key: Optional[str] = None,
    ) -> ProjectPage:
        safe_name = (page_name or "New Page").strip() or "New Page"
        key_base = page_key or ProjectService._slugify_page_key(safe_name)

        existing_keys = {
            page.page_key
            for page in ProjectService.list_project_pages(session, project.id)
        }
        resolved_key = key_base
        suffix = 2
        while resolved_key in existing_keys:
            resolved_key = f"{key_base}-{suffix}"
            suffix += 1

        current_pages = ProjectService.list_project_pages(session, project.id)
        sort_order = len(current_pages)

        if is_default:
            for existing in current_pages:
                if existing.is_default:
                    existing.is_default = False
                    existing.updated_at = datetime.now(timezone.utc)
                    session.add(existing)

        goview_project = GoviewProject(
            id=str(uuid.uuid4()),
            project_name=safe_name,
            content=content or "{}",
            state=int(state),
            index_image=index_image or "",
            remarks=remarks or f"Tricys project page: {project.id}",
            create_user_id=user_id,
        )
        session.add(goview_project)

        page = ProjectPage(
            project_id=project.id,
            goview_project_id=goview_project.id,
            page_key=resolved_key,
            page_name=safe_name,
            page_type=(page_type or "custom").strip() or "custom",
            is_default=is_default,
            sort_order=sort_order,
            visibility="public" if int(state) == 1 else "private",
            remarks=remarks or "",
            template_key=template_key or "",
            created_by=user_id,
        )
        session.add(page)
        session.commit()
        session.refresh(page)
        return page

    @staticmethod
    def list_project_page_releases(
        session: Session,
        page_id: str,
        include_inactive: bool = False,
    ) -> List[ProjectPageRelease]:
        query = select(ProjectPageRelease).where(
            ProjectPageRelease.page_id == page_id,
            ProjectPageRelease.is_delete == 0,
        )
        if not include_inactive:
            query = query.where(ProjectPageRelease.is_active == 1)
        query = query.order_by(ProjectPageRelease.version.desc(), ProjectPageRelease.published_at.desc())
        return list(session.exec(query).all())

    @staticmethod
    def get_project_page_release(session: Session, release_id: str) -> Optional[ProjectPageRelease]:
        release = session.get(ProjectPageRelease, release_id)
        if not release or release.is_delete == 1:
            return None
        return release

    @staticmethod
    def get_active_project_page_release(session: Session, page_id: str) -> Optional[ProjectPageRelease]:
        return session.exec(
            select(ProjectPageRelease)
            .where(
                ProjectPageRelease.page_id == page_id,
                ProjectPageRelease.is_active == 1,
                ProjectPageRelease.is_delete == 0,
            )
            .order_by(ProjectPageRelease.version.desc(), ProjectPageRelease.published_at.desc())
        ).first()

    @staticmethod
    def _deactivate_project_page_releases(session: Session, page_id: str) -> None:
        releases = session.exec(
            select(ProjectPageRelease).where(
                ProjectPageRelease.page_id == page_id,
                ProjectPageRelease.is_delete == 0,
                ProjectPageRelease.is_active == 1,
            )
        ).all()
        for release in releases:
            release.is_active = 0
            session.add(release)

    @staticmethod
    def create_project_page_release(
        session: Session,
        page: ProjectPage,
        goview_project: GoviewProject,
        created_by: Optional[str],
    ) -> ProjectPageRelease:
        current_max = session.exec(
            select(ProjectPageRelease)
            .where(
                ProjectPageRelease.page_id == page.id,
                ProjectPageRelease.is_delete == 0,
            )
            .order_by(ProjectPageRelease.version.desc())
        ).first()
        next_version = (current_max.version if current_max else 0) + 1

        ProjectService._deactivate_project_page_releases(session, page.id)
        release = ProjectPageRelease(
            page_id=page.id,
            project_id=page.project_id,
            goview_project_id=page.goview_project_id,
            version=next_version,
            content=goview_project.content or "{}",
            index_image=goview_project.index_image or "",
            remarks=page.remarks or goview_project.remarks or "",
            created_by=created_by,
            is_active=1,
        )
        session.add(release)
        return release

    @staticmethod
    def restore_project_page_release(
        session: Session,
        page: ProjectPage,
        release: ProjectPageRelease,
    ) -> Optional[ProjectPage]:
        goview_project = session.get(GoviewProject, page.goview_project_id)
        if not goview_project:
            return None

        ProjectService._deactivate_project_page_releases(session, page.id)
        release.is_active = 1
        goview_project.content = release.content or "{}"
        goview_project.index_image = release.index_image or goview_project.index_image or ""
        goview_project.state = 1
        goview_project.update_time = datetime.now(timezone.utc)
        page.visibility = "public"
        page.updated_at = datetime.now(timezone.utc)

        session.add(release)
        session.add(goview_project)
        session.add(page)
        session.commit()
        session.refresh(page)
        return page

    @staticmethod
    def update_project_page_publish_state(
        session: Session,
        page: ProjectPage,
        published: bool,
        created_by: Optional[str] = None,
    ) -> Optional[ProjectPage]:
        goview_project = session.get(GoviewProject, page.goview_project_id)
        if not goview_project:
            return None

        if published:
            ProjectService.create_project_page_release(
                session,
                page=page,
                goview_project=goview_project,
                created_by=created_by,
            )
        else:
            ProjectService._deactivate_project_page_releases(session, page.id)

        goview_project.state = 1 if published else -1
        goview_project.update_time = datetime.now(timezone.utc)
        page.visibility = "public" if published else "private"
        page.updated_at = datetime.now(timezone.utc)
        session.add(goview_project)
        session.add(page)
        session.commit()
        session.refresh(page)
        return page

    @staticmethod
    def delete_project_page(session: Session, page: ProjectPage) -> None:
        goview_project = session.get(GoviewProject, page.goview_project_id)
        if goview_project:
            goview_project.is_delete = 1
            goview_project.update_time = datetime.now(timezone.utc)
            session.add(goview_project)

        releases = session.exec(
            select(ProjectPageRelease).where(
                ProjectPageRelease.page_id == page.id,
                ProjectPageRelease.is_delete == 0,
            )
        ).all()
        for release in releases:
            release.is_delete = 1
            release.is_active = 0
            session.add(release)

        page.is_delete = 1
        page.updated_at = datetime.now(timezone.utc)
        session.add(page)
        session.commit()

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

        page_links = session.exec(
            select(ProjectPage).where(ProjectPage.project_id == project_id, ProjectPage.is_delete == 0)
        ).all()
        for page in page_links:
            page.is_delete = 1
            page.updated_at = datetime.now(timezone.utc)
            session.add(page)
            releases = session.exec(
                select(ProjectPageRelease).where(
                    ProjectPageRelease.page_id == page.id,
                    ProjectPageRelease.is_delete == 0,
                )
            ).all()
            for release in releases:
                release.is_delete = 1
                release.is_active = 0
                session.add(release)
            linked_goview = session.get(GoviewProject, page.goview_project_id)
            if linked_goview:
                linked_goview.is_delete = 1
                linked_goview.update_time = datetime.now(timezone.utc)
                session.add(linked_goview)

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

            pages_payload = []
            for page in ProjectService.list_project_pages(session, project.id):
                goview_page = session.get(GoviewProject, page.goview_project_id)
                if not goview_page or goview_page.is_delete == 1:
                    continue
                pages_payload.append({
                    "id": page.id,
                    "goview_project_id": page.goview_project_id,
                    "page_key": page.page_key,
                    "page_name": page.page_name,
                    "page_type": page.page_type,
                    "is_default": page.is_default,
                    "sort_order": page.sort_order,
                    "visibility": page.visibility,
                    "remarks": page.remarks,
                    "template_key": page.template_key,
                    "content": goview_page.content,
                    "state": goview_page.state,
                    "index_image": goview_page.index_image,
                    "releases": [
                        {
                            "version": release.version,
                            "content": release.content,
                            "index_image": release.index_image,
                            "remarks": release.remarks,
                            "published_at": release.published_at.isoformat() if release.published_at else None,
                            "is_active": release.is_active,
                        }
                        for release in ProjectService.list_project_page_releases(session, page.id, include_inactive=True)
                    ],
                })
            if pages_payload:
                metadata["pages"] = pages_payload
            
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

            imported_pages = metadata.get("pages") if isinstance(metadata.get("pages"), list) else []
            if imported_pages:
                for index, page_payload in enumerate(imported_pages):
                    is_default = bool(page_payload.get("is_default"))
                    page_name = page_payload.get("page_name") or page_payload.get("project_name") or f"Page {index + 1}"
                    if is_default:
                        goview_id = new_project_id
                    else:
                        goview_id = str(uuid.uuid4())

                    goview_project = GoviewProject(
                        id=goview_id,
                        project_name=page_name,
                        content=page_payload.get("content") or "{}",
                        state=int(page_payload.get("state", -1)),
                        index_image=page_payload.get("index_image") or "",
                        remarks=page_payload.get("remarks") or "",
                        create_user_id=user_id,
                    )
                    session.add(goview_project)

                    project_page = ProjectPage(
                        project_id=new_project_id,
                        goview_project_id=goview_id,
                        page_key=page_payload.get("page_key") or ("overview" if is_default else ProjectService._slugify_page_key(page_name)),
                        page_name=page_name,
                        page_type=page_payload.get("page_type") or ("overview" if is_default else "custom"),
                        is_default=is_default,
                        sort_order=int(page_payload.get("sort_order", index)),
                        visibility=page_payload.get("visibility") or ("public" if int(page_payload.get("state", -1)) == 1 else "private"),
                        remarks=page_payload.get("remarks") or "",
                        template_key=page_payload.get("template_key") or "",
                        created_by=user_id,
                    )
                    session.add(project_page)
                    for release_payload in page_payload.get("releases") or []:
                        release = ProjectPageRelease(
                            page_id=project_page.id,
                            project_id=new_project_id,
                            goview_project_id=goview_id,
                            version=int(release_payload.get("version") or 1),
                            content=release_payload.get("content") or page_payload.get("content") or "{}",
                            index_image=release_payload.get("index_image") or page_payload.get("index_image") or "",
                            remarks=release_payload.get("remarks") or page_payload.get("remarks") or "",
                            created_by=user_id,
                            published_at=datetime.fromisoformat(release_payload.get("published_at")) if release_payload.get("published_at") else datetime.now(timezone.utc),
                            is_active=int(release_payload.get("is_active", 0)),
                        )
                        session.add(release)
                session.commit()
            else:
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
                ProjectService.ensure_default_project_page(
                    session,
                    project=project,
                    user_id=user_id,
                    commit=True,
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
        ProjectService.ensure_default_project_page(
            session,
            project=forked,
            user_id=user_id,
            commit=True,
        )

        source_pages = ProjectService.list_project_pages(session, project_id)
        if source_pages:
            default_source_ids = {page.goview_project_id for page in source_pages if page.is_default}
            for source_page in source_pages:
                source_goview = session.get(GoviewProject, source_page.goview_project_id)
                if not source_goview or source_goview.is_delete == 1:
                    continue
                if source_page.goview_project_id in default_source_ids:
                    target_default = session.exec(
                        select(ProjectPage)
                        .where(ProjectPage.project_id == new_project_id, ProjectPage.is_default == True, ProjectPage.is_delete == 0)
                    ).first()
                    if target_default:
                        target_default.page_name = source_page.page_name
                        target_default.page_type = source_page.page_type
                        target_default.visibility = source_page.visibility
                        target_default.remarks = source_page.remarks
                        target_default.template_key = source_page.template_key
                        target_default.updated_at = datetime.now(timezone.utc)
                        session.add(target_default)

                        target_goview = session.get(GoviewProject, target_default.goview_project_id)
                        if target_goview:
                            target_goview.project_name = source_goview.project_name
                            target_goview.content = source_goview.content
                            target_goview.state = source_goview.state
                            target_goview.index_image = source_goview.index_image
                            target_goview.remarks = source_goview.remarks
                            target_goview.update_time = datetime.now(timezone.utc)
                            session.add(target_goview)
                    continue

                ProjectService.create_project_page(
                    session,
                    project=forked,
                    user_id=user_id,
                    page_name=source_page.page_name,
                    page_type=source_page.page_type,
                    remarks=source_page.remarks or "",
                    template_key=source_page.template_key or "",
                    is_default=False,
                    content=source_goview.content or "{}",
                    state=source_goview.state,
                    index_image=source_goview.index_image or "",
                    page_key=source_page.page_key,
                )

            session.commit()
        return forked