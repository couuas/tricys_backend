import os
import shutil
import json
from datetime import datetime
from pathlib import Path
from tricys_backend.core.config import settings

class FileManager:
    @staticmethod
    def create_workspace(task_id: str) -> Path:
        """Creates a unique workspace directory for a task."""
        # Structure: workspaces/YYYY-MM-DD/task_id
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        workspace_path = settings.WORKSPACES_DIR / date_str / task_id
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
        path = settings.WORKSPACES_DIR / date_str / task_id
        if path.exists():
            shutil.rmtree(path)
