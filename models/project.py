import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from sqlmodel import SQLModel, Field, JSON, Column, Relationship

if False: # TYPE_CHECKING
    from tricys_backend.models.task import Task
    from tricys_backend.models.user import User

class Project(SQLModel, table=True):
    """
    Represents a specific Project/Model environment.
    One project corresponds to one uploaded Model (.mo) and contains multiple simulation tasks.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    
    # --- Ownership ---
    user_id: Optional[str] = Field(default=None, foreign_key="user.id", nullable=True) # Optional for now to support legacy/default
    
    name: str = "New Project"
    description: Optional[str] = None
    
    # --- Visibility ---
    is_public: bool = Field(default=False)
    archived_owner_id: Optional[str] = Field(default=None)
    
    # --- Paths ---
    # Absolute path to the project directory: workspaces/{project_id}
    path: str 
    # Absolute path to the source model file: workspaces/{project_id}/source/model.mo
    model_file_path: str
    
    # --- Model Structure State ---
    # Stores the parsed structure (components, connections) from the .mo file
    structure_json: Dict = Field(default={}, sa_column=Column(JSON))
    
    # Stores the flattened parameters map (defaults from file)
    defaults_json: Dict = Field(default={}, sa_column=Column(JSON))
    
    # Stores User's current parameter overrides
    parameters_json: Dict = Field(default={}, sa_column=Column(JSON))
    
    # --- UI/Editor State ---
    # Stores alert configuration
    alert_rules: Dict = Field(default={}, sa_column=Column(JSON))
    
    # Stores component grouping
    component_groups: Dict = Field(default={}, sa_column=Column(JSON))
    
    # Stores sidebar visibility (hidden components list)
    sidebar_config: List[str] = Field(default=[], sa_column=Column(JSON))
    
    # Stores graphical annotations/notes
    annotations: Dict = Field(default={}, sa_column=Column(JSON))  

    # Stores custom layouts for component detail dashboards
    # Format: { "componentId": [ { "i": "...", "x": 0, ... }, ... ] }
    component_layouts: Dict = Field(default={}, sa_column=Column(JSON))

    # --- Simulation Config State ---
    # Stores last used simulation configuration (stop_time, step_size, etc.)
    simulation_config: Dict = Field(default={}, sa_column=Column(JSON))    
    # Stores temporary simulation data cache (could be moved to Task later)
    simulation_data: Dict = Field(default={"time": [], "components": {}}, sa_column=Column(JSON))
    
    # Stores 3D visualization configuration (custom models, scales)
    # Format: { "componentId": { "type": "custom", "url": "...", "scale": 1.0 } }
    visual_config: Dict = Field(default={}, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # --- Relationships ---
    tasks: List["Task"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    user: Optional["User"] = Relationship(back_populates="projects")
