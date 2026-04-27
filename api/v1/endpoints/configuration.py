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
from tricys.core.foc import FOCParseError, build_foc_preview

router = APIRouter()

class ParseModelRequest(BaseModel):
    project_id: str
    model_name: str


class FocPreviewRequest(BaseModel):
    content: str
    strategy: str = "table"
    stop_time: Optional[float] = None


class FocPreviewResponse(BaseModel):
    valid: bool
    strategy: str
    amplitudes: List[float]
    durations: List[float]
    rows: List[List[float]]
    schedule_duration: float
    step_count: int
    warnings: List[str]
    error: Optional[str] = None

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


@router.post("/foc/preview", response_model=FocPreviewResponse)
async def preview_foc(
    request: FocPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    del current_user

    strategy = (request.strategy or "table").strip().lower()
    if strategy not in {"table", "array"}:
        raise HTTPException(status_code=400, detail="FOC strategy must be 'table' or 'array'.")

    try:
        preview = build_foc_preview(request.content)
    except (FOCParseError, ValueError) as exc:
        return FocPreviewResponse(
            valid=False,
            strategy=strategy,
            amplitudes=[],
            durations=[],
            rows=[],
            schedule_duration=0.0,
            step_count=0,
            warnings=[],
            error=str(exc),
        )

    warnings = []
    if request.stop_time is not None and request.stop_time < preview["schedule_duration"]:
        warnings.append(
            "Configured stop_time is shorter than the FOC schedule duration."
        )

    return FocPreviewResponse(
        valid=True,
        strategy=strategy,
        amplitudes=[float(value) for value in preview["amplitudes"]],
        durations=[float(value) for value in preview["durations"]],
        rows=[[float(time_value), float(power_value)] for time_value, power_value in preview["rows"]],
        schedule_duration=float(preview["schedule_duration"]),
        step_count=int(preview["step_count"]),
        warnings=warnings,
        error=None,
    )
