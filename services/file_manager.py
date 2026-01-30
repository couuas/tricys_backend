import os
import shutil
import json
import re
from datetime import datetime
from pathlib import Path
from tricys_backend.core.config import settings

class FileManager:
    @staticmethod
    def create_workspace(task_id: str) -> Path:
        """Creates a unique workspace directory for a task."""
        # Security: Validate task_id is a clean UUID format to prevent path traversal
        # Accept both uppercase and lowercase hex digits
        if not re.match(r'^[a-fA-F0-9\-]{36}$', task_id):
            raise ValueError(f"Invalid task_id format: {task_id}")
        
        # Structure: workspaces/YYYY-MM-DD/task_id
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        workspace_path = (settings.WORKSPACES_DIR / date_str / task_id).resolve()
        
        # Security: Verify path is within allowed directory to prevent path traversal
        # Use is_relative_to for proper validation across platforms
        workspaces_base = settings.WORKSPACES_DIR.resolve()
        try:
            # Python 3.9+ method
            if not workspace_path.is_relative_to(workspaces_base):
                raise ValueError(f"Path traversal detected: {workspace_path}")
        except AttributeError:
            # Fallback for Python < 3.9
            if not str(workspace_path).startswith(str(workspaces_base) + os.sep):
                raise ValueError(f"Path traversal detected: {workspace_path}")
        
        os.makedirs(workspace_path, exist_ok=True)
        return workspace_path

    @staticmethod
    def save_config(workspace_path: Path, config: dict) -> Path:
        """Saves the configuration JSON to the workspace."""
        config_path = workspace_path / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return config_path
    
    @staticmethod
    def get_log_path(workspace_path: Path) -> Path:
        return workspace_path / "simulation.log"

    @staticmethod
    def cleanup_workspace(task_id: str, date_str: str):
        """Removes the workspace directory."""
        # Security: Validate task_id format (accept uppercase and lowercase)
        if not re.match(r'^[a-fA-F0-9\-]{36}$', task_id):
            raise ValueError(f"Invalid task_id format: {task_id}")
        
        path = (settings.WORKSPACES_DIR / date_str / task_id).resolve()
        
        # Security: Verify path is within allowed directory
        workspaces_base = settings.WORKSPACES_DIR.resolve()
        try:
            # Python 3.9+ method
            if not path.is_relative_to(workspaces_base):
                raise ValueError(f"Path traversal detected: {path}")
        except AttributeError:
            # Fallback for Python < 3.9
            if not str(path).startswith(str(workspaces_base) + os.sep):
                raise ValueError(f"Path traversal detected: {path}")
        
        if path.exists():
            shutil.rmtree(path)
