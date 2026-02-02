from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from typing import List, Dict, Any
import os
import shutil
from pathlib import Path
from tricys_backend.core.config import settings
from tricys_backend.models.user import User
from tricys_backend.api.deps import get_current_user, get_current_active_superuser

import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Define Library Directory
LIBRARY_DIR = settings.BASE_DIR / "assets" / "models"
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

@router.get("/models", response_model=List[Dict[str, str]])
def get_library_models():
    """List available 3D models in the library."""
    models = []
    if LIBRARY_DIR.exists():
        for f in LIBRARY_DIR.glob("*.glb"):
            models.append({
                "name": f.stem,
                "filename": f.name,
                "url": f"/static/models/{f.name}"
            })
    return models

@router.post("/upload")
async def upload_model(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_superuser)
):
    """Upload a new 3D model (.glb) to the library."""
    if not file.filename.lower().endswith('.glb'):
        raise HTTPException(status_code=400, detail="Only .glb files are supported")
    
    try:
        # Sanitize filename
        filename = os.path.basename(file.filename)
        destination = LIBRARY_DIR / filename
        
        # Async read and write
        content = await file.read()
        with open(destination, "wb") as f:
            f.write(content)
            
        logger.info(f"User {current_user.username} uploaded library model {filename}")
        
        return {
            "name": destination.stem,
            "filename": filename,
            "url": f"/static/models/{filename}",
            "status": "success",
            "uploaded_by": current_user.username
        }
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
