import uuid
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, JSON
from pydantic import BaseModel, field_validator, model_validator

if False: # TYPE_CHECKING
    from tricys_backend.models.project import Project

# Config validation models
class PathsConfig(BaseModel):
    """Configuration for model paths."""
    mo_file: Optional[str] = None
    fmu_file: Optional[str] = None
    package_path: Optional[str] = None # Support legacy/CLI naming
    
    class Config:
        extra = 'allow'

    @field_validator('mo_file', 'fmu_file', 'package_path')
    @classmethod
    def validate_path_safety(cls, v: Optional[str]) -> Optional[str]:
        """Ensure paths don't contain traversal sequences."""
        if v and ('..' in v or v.startswith('/')):
            raise ValueError(f"Unsafe path detected: {v}")
        return v

class SimulationConfig(BaseModel):
    """Configuration for simulation parameters."""
    model_name: Optional[str] = None
    stop_time: Optional[float] = Field(default=None, gt=0, le=1e7)
    step_size: Optional[float] = Field(default=None, gt=0, le=1e6)
    solver: Optional[str] = None
    tolerance: Optional[float] = Field(default=None, gt=0, le=1.0)
    variableFilter: Optional[str] = None
    
    class Config:
        extra = 'allow'
    
    @field_validator('model_name')
    @classmethod
    def validate_model_name_inner(cls, v: Optional[str]) -> Optional[str]:
        """Ensure model_name contains only safe characters."""
        if v and not re.match(r'^[a-zA-Z0-9_.\-]+$', v):
            raise ValueError(f"model_name contains invalid characters: {v}")
        return v
    
class ConfigJsonSchema(BaseModel):
    """Schema for validating config_json structure."""
    paths: Optional[PathsConfig] = None
    simulation: Optional[SimulationConfig] = None
    # Support direct dictionary for parameters as per user standard
    simulation_parameters: Optional[Dict[str, Union[List[Any], Any]]] = None
    model_name: Optional[str] = None
    
    # [NEW] Enhanced validation fields
    active_alerts: Optional[List[Dict[str, Any]]] = None
    metrics_definition: Optional[Dict[str, Any]] = None
    sensitivity_analysis: Optional[Dict[str, Any]] = None
    analysis: Optional[Dict[str, Any]] = None  # For generic analysis specs
    optimization: Optional[Dict[str, Any]] = None # For optimization specs
    
    @field_validator('model_name')
    @classmethod
    def validate_model_name(cls, v: Optional[str]) -> Optional[str]:
        """Ensure model_name contains only safe characters."""
        if v and not re.match(r'^[a-zA-Z0-9_.\-]+$', v):
            raise ValueError(f"model_name contains invalid characters: {v}")
        return v

    @field_validator('simulation_parameters')
    @classmethod
    def validate_sweep(cls, v: Optional[Dict[str, Union[List[Any], Any]]]) -> Optional[Dict[str, Union[List[Any], Any]]]:
        """Validate parameter sweep combinations."""
        if v:
            total_combinations = 1
            for param_name, values in v.items():
                if not isinstance(values, list):
                    # Scalar value = 1 combination
                    continue
                
                if len(values) > 1000:
                    raise ValueError(f"Parameter {param_name} values must be a list")
                total_combinations *= len(values)
            
            if total_combinations > 10000:
                raise ValueError(f"Total parameter combinations ({total_combinations}) exceeds limit (10000)")
        return v

    @model_validator(mode='after')
    def validate_has_required_fields(self):
        """Ensure at least basic configuration is provided."""
        has_model_name = self.model_name or (self.simulation and self.simulation.model_name)
        if not self.paths and not has_model_name:
            raise ValueError("config_json must contain either 'paths' or 'model_name'")
        return self

class TaskBase(SQLModel):
    name: Optional[str] = Field(default=None)
    type: str = Field(default="BASIC") # BASIC or ANALYSIS
    enhanced: bool = Field(default=False)
    turbo: bool = Field(default=False)
    config_json: dict = Field(default={}, sa_column=Column(JSON))

class Task(TaskBase, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    status: str = Field(default="PENDING")
    workspace_path: Optional[str] = None
    result_path: Optional[str] = None
    pid: Optional[int] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_msg: Optional[str] = None
    
    project: Optional["Project"] = Relationship(back_populates="tasks")

class TaskCreate(TaskBase):
    project_id: str

    @field_validator("config_json")
    @classmethod
    def validate_config_schema(cls, v: dict) -> dict:
        """Validate config_json against schema to prevent malformed configs."""
        if not v:
            raise ValueError("config_json cannot be empty")
        
        # Validate against schema
        try:
            ConfigJsonSchema(**v)
        except Exception as e:
            raise ValueError(f"Invalid config_json structure: {str(e)}")
        
        return v
    
    @model_validator(mode='after')
    def validate_task_create(self) -> 'TaskCreate':
        """Ensure config_json is not empty after all other validations."""
        if not self.config_json:
            raise ValueError("config_json cannot be empty")
        return self
    
    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate task type is one of allowed values."""
        v_upper = v.upper()
        allowed_types = ["BASIC", "ANALYSIS"]
        if v_upper not in allowed_types:
            raise ValueError(f"type must be one of {allowed_types}")
        return v_upper

class TaskRead(TaskBase):
    id: str
    project_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    workspace_path: Optional[str] = None
    result_path: Optional[str] = None
    error_msg: Optional[str] = None
