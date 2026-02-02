import json
import logging
import asyncio
from typing import List, Optional, Dict, Any
from sqlmodel import Session, select
from datetime import datetime

from tricys_backend.models.task import Task
from tricys_backend.services.task_queue import TaskQueue, db_engine
from tricys_backend.core.config import settings

logger = logging.getLogger(__name__)

class AnalysisService:
    @staticmethod
    def create_analysis_task(
        user_id: int, 
        project_id: str,
        name: str, 
        analysis_config: Dict[str, Any],
        template_id: str = None
    ) -> Task:
        """
        Create a new analysis task record and queue it.
        """
        
        # If template_id is provided, build the complex config from the form data
        if template_id:
             from tricys_backend.services.analysis_templates import AnalysisTemplates
             # here analysis_config is the simple form data
             full_config = AnalysisTemplates.build_config(template_id, analysis_config)
             # Check if project info needed to merge? (Skipped for now)
             task_config = {
                "project_id": project_id,
                "type": "analysis",
                "analysis_spec": full_config
             }
        else:
            # Raw config mode
            task_config = {
                "project_id": project_id,
                "type": "analysis",
                "analysis_spec": analysis_config,
            }

        with Session(db_engine) as session:
            new_task = Task(
                name=name,
                type="analysis",
                status="PENDING",
                # user_id=user_id, # Removed as field doesn't exist
                project_id=project_id,
                config_json=task_config,
                created_at=datetime.utcnow()
            )
            session.add(new_task)
            session.commit()
            session.refresh(new_task)
            
            # Add to Queue
            # We need to run this in the event loop since TaskQueue.add_task is async
            # But we are in a sync wrapper or need to await it if this is called from async endpoint
            return new_task

    @staticmethod
    async def submit_task(task_id: int):
        await TaskQueue.add_task(task_id)

    @staticmethod
    def get_tasks(user_id: int, project_id: Optional[str] = None) -> List[Task]:
        from tricys_backend.models.project import Project
        with Session(db_engine) as session:
            # Filter by Project Owner = user_id
            # This ensures users only see tasks for their own projects
            query = select(Task).join(Project).where(Project.user_id == user_id, Task.type == "analysis")
            
            if project_id:
                query = query.where(Task.project_id == project_id)
            query = query.order_by(Task.created_at.desc())
            return session.exec(query).all()

    @staticmethod
    def get_task(task_id: int, user_id: int) -> Optional[Task]:
        from tricys_backend.models.project import Project
        with Session(db_engine) as session:
            # Verify ownership via Join
            query = select(Task).join(Project).where(Task.id == task_id, Project.user_id == user_id)
            return session.exec(query).first()

    @staticmethod
    def delete_task(task_id: int, user_id: int) -> bool:
        from tricys_backend.models.project import Project
        with Session(db_engine) as session:
            # Verify ownership via Join
            query = select(Task).join(Project).where(Task.id == task_id, Project.user_id == user_id)
            task = session.exec(query).first()
            if task:
                session.delete(task)
                session.commit()
                return True
            return False
