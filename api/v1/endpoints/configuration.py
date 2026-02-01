from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from tricys_backend.services.model_service import ModelService

router = APIRouter()

class ParseModelRequest(BaseModel):
    package_path: str
    model_name: str

class ModelParameter(BaseModel):
    name: str
    type: str
    defaultValue: Optional[Any] = None
    description: Optional[str] = None
    # Add other fields as needed based on CLI output

@router.post("/models/parse", response_model=List[Dict[str, Any]])
async def parse_model(request: ParseModelRequest):
    """
    Parses a Modelica model and returns its parameters.
    Invokes 'tricys parse' via subprocess.
    """
    try:
        # Validate file existence is handled by CLI or Service? 
        # Service handles execution, CLI handles file check.
        
        parameters = ModelService.parse_model(request.package_path, request.model_name)
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
