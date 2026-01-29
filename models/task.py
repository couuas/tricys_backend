import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, JSON

class TaskBase(SQLModel):
    name: Optional[str] = Field(default=None)
    type: str = Field(default="BASIC") # BASIC or ANALYSIS
    enhanced: bool = Field(default=False)
    turbo: bool = Field(default=False)
    config_json: dict = Field(default={}, sa_column=Column(JSON))

class Task(TaskBase, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    status: str = Field(default="PENDING")
    workspace_path: Optional[str] = None
    result_path: Optional[str] = None
    pid: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    error_msg: Optional[str] = None

class TaskCreate(TaskBase):
    @classmethod
    def validate_config(cls, v):
        if not v or not isinstance(v, dict):
             raise ValueError("config_json must be a non-empty dictionary")
        return v
        
    # Pydantic v2 style
    from pydantic import field_validator
    @field_validator("config_json")
    @classmethod
    def check_config_not_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("config_json cannot be empty")
        return v

class TaskRead(TaskBase):
    id: str
    status: str
    created_at: datetime
    updated_at: datetime
    workspace_path: Optional[str] = None
    result_path: Optional[str] = None
    error_msg: Optional[str] = None
