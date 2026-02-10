from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field
import uuid

class GoviewProject(SQLModel, table=True):
    __tablename__ = "goview_project"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_name: str = Field(index=True)
    content: Optional[str] = Field(default="{}")
    state: int = Field(default=-1)  # -1: draft, 1: published
    index_image: Optional[str] = Field(default="")
    remarks: Optional[str] = Field(default="")
    create_user_id: str = Field(index=True)
    create_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    update_time: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_delete: int = Field(default=0) # 0: normal, 1: deleted
