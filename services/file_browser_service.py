import os
import platform
from pathlib import Path
from typing import List, Dict, Any, Union
import logging

logger = logging.getLogger(__name__)

def _to_extended_path(p: Path) -> Path:
    """Converts a Path to a Windows extended path to bypass the MAX_PATH limit."""
    if platform.system() == 'Windows':
        s = str(p.resolve())
        if not s.startswith('\\\\?\\'):
            return Path('\\\\?\\' + s)
    return p.resolve()

class FileBrowserService:
    def list_files(self, root_path: Path) -> List[Dict[str, Any]]:
        """
        Recursively lists files and directories in the given root path.
        Returns a tree structure.
        """
        extended_root = _to_extended_path(root_path)
        if not extended_root.exists():
            raise FileNotFoundError(f"Root path {root_path} does not exist")

        def _scan(path: Path) -> List[Dict[str, Any]]:
            items = []
            try:
                # specific sort: folders first, then files
                entries = sorted(list(path.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
                
                for entry in entries:
                    item = {
                        "name": entry.name,
                        "path": entry.relative_to(extended_root).as_posix(),
                        "type": "directory" if entry.is_dir() else "file",
                    }
                    
                    if entry.is_dir():
                        item["children"] = _scan(entry)
                    else:
                        item["size"] = entry.stat().st_size
                        
                    items.append(item)
            except (PermissionError, FileNotFoundError, OSError) as e:
                logger.warning(f"Skipped reading path due to error: {e}")
            return items

        return _scan(extended_root)

    def get_file_path(self, root_path: Path, relative_path: str) -> Path:
        """
        Resolves a relative path within the root_path and checks for traversal.
        """
        # Security check
        if ".." in relative_path or relative_path.startswith("/"):
             raise ValueError(f"Invalid path: {relative_path}")
             
        full_path = _to_extended_path(root_path / relative_path)
        extended_root = _to_extended_path(root_path)
        
        # Ensure it's still inside root_path (prevent symlink attacks or traversal)
        if not str(full_path).startswith(str(extended_root)):
             raise ValueError("Access denied: Path is outside workspace")
             
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
            
        return full_path
