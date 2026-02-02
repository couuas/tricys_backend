from fastapi import APIRouter, HTTPException, Body, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from sqlmodel import Session

from tricys_backend.services.model_service import ModelService
from tricys_backend.services.project_service import ProjectService
from tricys_backend.utils.db import get_session
from tricys_backend.models.user import User
from tricys_backend.models.project import Project
from tricys_backend.api.deps import get_current_user

router = APIRouter()

class ParseModelRequest(BaseModel):
    project_id: str
    model_name: str

@router.post("/models/parse", response_model=List[Dict[str, Any]])
async def parse_model(
    request: ParseModelRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Parses a Modelica model from a project and returns its parameters.
    """
    project = session.get(Project, request.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this project")
    
    if not project.model_file_path:
        raise HTTPException(status_code=400, detail="Project has no model file")
        
    try:
        parameters = ModelService.parse_model(project.model_file_path, request.model_name)
        return parameters
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config/template")
async def get_config_template():
    """
    Returns a default configuration template.
    In a real scenario, this might read from a file or use a Pydantic model's schema.
    For now, we return a structural placeholder matching Tricys requirements.
    """
    return {
        "simulation": {
            "start_time": 0,
            "stop_time": 100,
            "tolerance": 1e-6,
            "solver": "dassl",
            "execute_mode": "basic", # or enhanced
            "maximize_workers": False,
            "concurrent": False
        },
        "paths": {
            "model_path": "/path/to/package.mo",
            "model_name": "ModelName",
            "output_dir": "output"
        },
        "parameters": {
            # "ParamName": 123.45
        }
    }
