import os
from pathlib import Path
from typing import List, Dict, Any, Union
import logging

logger = logging.getLogger(__name__)

class FileBrowserService:
    def list_files(self, root_path: Path) -> List[Dict[str, Any]]:
        """
        Recursively lists files and directories in the given root path.
        Returns a tree structure.
        """
        if not root_path.exists():
            raise FileNotFoundError(f"Root path {root_path} does not exist")

        def _scan(path: Path) -> List[Dict[str, Any]]:
            items = []
            try:
                # specific sort: folders first, then files
                entries = sorted(list(path.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
                
                for entry in entries:
                    item = {
                        "name": entry.name,
                        "path": entry.relative_to(root_path).as_posix(),
                        "type": "directory" if entry.is_dir() else "file",
                    }
                    
                    if entry.is_dir():
                        item["children"] = _scan(entry)
                    else:
                        item["size"] = entry.stat().st_size
                        
                    items.append(item)
            except PermissionError:
                pass # Skip folders we can't read
            return items

        return _scan(root_path)

    def get_file_path(self, root_path: Path, relative_path: str) -> Path:
        """
        Resolves a relative path within the root_path and checks for traversal.
        """
        # Security check
        if ".." in relative_path or relative_path.startswith("/"):
             raise ValueError(f"Invalid path: {relative_path}")
             
        full_path = (root_path / relative_path).resolve()
        
        # Ensure it's still inside root_path (prevent symlink attacks or traversal)
        if not str(full_path).startswith(str(root_path.resolve())):
             raise ValueError("Access denied: Path is outside workspace")
             
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
            
        return full_path
