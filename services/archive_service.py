import shutil
import zipfile
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class ArchiveService:
    def __init__(self, root_dir: str = None):
         self.root_dir = root_dir

    def create_task_archive(self, task_id: str, workspace_path: Path) -> Path:
        """
        Creates a zip archive of the task workspace.
        Returns the path to the zip file.
        """
        task_dir = workspace_path
        if not task_dir.exists():
            raise FileNotFoundError(f"Task directory {task_dir} not found")
        
        # Define zip path inside the task directory to avoid permission issues or polluting root
        # But wait, if we zip the task dir inside itself, the zip grows infinitely if we do it recursively?
        # Better to put the zip somewhere else or carefully exclude it.
        # Let's put it in the task dir but name it specially.
        zip_filename = f"{task_id}_archive.zip"
        zip_path = task_dir / zip_filename
        
        # If it already exists, return it (cache)
        if zip_path.exists():
            return zip_path
            
        logger.info(f"Archiving task {task_id} to {zip_path}")
        
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(task_dir):
                    # Exclude the zip file itself if we are writing it there
                    if zip_filename in files:
                        files.remove(zip_filename)
                        
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(task_dir)
                        zipf.write(file_path, arcname)
                        
            return zip_path
        except Exception as e:
            # Cleanup partial zip
            if zip_path.exists():
                os.remove(zip_path)
            logger.error(f"Failed to archive task {task_id}: {str(e)}")
            raise
