import os
import shutil
import json
import re
from datetime import datetime
from pathlib import Path
from tricys_backend.core.config import settings

class FileManager:
    
    @staticmethod
    def _validate_id(resource_id: str, id_type: str = "id"):
        """Validates that an ID is a safe UUID-like string."""
        if not re.match(r'^[a-fA-F0-9\-]{36}$', resource_id):
             raise ValueError(f"Invalid {id_type} format: {resource_id}")

    @staticmethod
    def _validate_path(path: Path):
        """Ensures path is within the workspaces directory."""
        workspaces_base = settings.WORKSPACES_DIR.resolve()
        if not path.is_relative_to(workspaces_base):
             raise ValueError(f"Path traversal detected: {path}")

    # --- Path Generators ---

    @classmethod
    def get_project_dir(cls, project_id: str) -> Path:
        cls._validate_id(project_id, "project_id")
        path = (settings.WORKSPACES_DIR / project_id).resolve()
        cls._validate_path(path)
        return path

    @classmethod
    def get_task_dir(cls, project_id: str, task_id: str) -> Path:
        cls._validate_id(project_id, "project_id")
        cls._validate_id(task_id, "task_id")
        path = (settings.WORKSPACES_DIR / project_id / "tasks" / task_id).resolve()
        cls._validate_path(path)
        return path

    @classmethod
    def get_analysis_dir(cls, project_id: str, task_id: str) -> Path:
        cls._validate_id(project_id, "project_id")
        cls._validate_id(task_id, "task_id")
        # User requested: project_id/analysis/task_id
        path = (settings.WORKSPACES_DIR / project_id / "analysis" / task_id).resolve()
        cls._validate_path(path)
        return path
    
    @classmethod
    def get_source_file_path(cls, project_id: str, filename: str) -> Path:
        """Returns the path to a source file within a project."""
        p_dir = cls.get_project_dir(project_id)
        # We assume the filename itself is safe (cleaned before calling)
        # But we check traversal just in case
        clean_name = os.path.basename(filename) 
        path = (p_dir / "source" / clean_name).resolve()
        if not path.is_relative_to(p_dir): # Ensure it's inside project dir
             raise ValueError(f"Path traversal in filename: {filename}")
        return path

    @classmethod
    def get_result_file_path(cls, project_id: str, task_id: str, filename: str, is_analysis: bool = False) -> Path:
        if is_analysis:
            t_dir = cls.get_analysis_dir(project_id, task_id)
        else:
            t_dir = cls.get_task_dir(project_id, task_id)
            
        clean_name = os.path.basename(filename)
        path = (t_dir / clean_name).resolve()
        if not path.is_relative_to(t_dir):
            raise ValueError(f"Path traversal in filename: {filename}")
        return path
        
    @classmethod
    def get_log_path(cls, project_id: str, task_id: str, is_analysis: bool = False) -> Path:
        if is_analysis:
            return cls.get_analysis_dir(project_id, task_id) / "simulation.log"
        return cls.get_task_dir(project_id, task_id) / "simulation.log"

    # --- Directory Management ---

    @classmethod
    def create_project_directory(cls, project_id: str) -> Path:
        """Creates the base project directory structure."""
        project_path = cls.get_project_dir(project_id)
        
        (project_path / "source").mkdir(parents=True, exist_ok=True)
        (project_path / "tasks").mkdir(parents=True, exist_ok=True)
        (project_path / "analysis").mkdir(parents=True, exist_ok=True)
        return project_path

    @classmethod
    def create_workspace(cls, task_id: str, project_id: str, is_analysis: bool = False) -> Path:
        """Creates a unique workspace directory for a task within a project."""
        if is_analysis:
            workspace_path = cls.get_analysis_dir(project_id, task_id)
        else:
            workspace_path = cls.get_task_dir(project_id, task_id)
            
        os.makedirs(workspace_path, exist_ok=True)
        return workspace_path

    @staticmethod
    def save_config(workspace_path: Path, config: dict) -> Path:
        """Saves the configuration JSON to the workspace."""
        config_path = workspace_path / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return config_path
    
    @classmethod
    def cleanup_workspace(cls, task_id: str, project_id: str):
        """Removes the task workspace directory."""
        path = cls.get_task_dir(project_id, task_id)
        if path.exists():
            shutil.rmtree(path)
