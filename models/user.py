import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship

if False:
    from tricys_backend.models.project import Project

class User(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    username: str = Field(index=True, unique=True)
    email: Optional[str] = None
    hashed_password: str
    full_name: Optional[str] = None
    
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    projects: List["Project"] = Relationship(back_populates="user")
