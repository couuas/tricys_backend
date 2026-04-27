import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class ProjectPage(SQLModel, table=True):
    __tablename__ = "project_page"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    goview_project_id: str = Field(foreign_key="goview_project.id", index=True)
    page_key: str = Field(default="overview", index=True)
    page_name: str = Field(index=True)
    page_type: str = Field(default="custom", index=True)
    is_default: bool = Field(default=False)
    sort_order: int = Field(default=0)
    visibility: str = Field(default="private")
    remarks: Optional[str] = Field(default="")
    template_key: Optional[str] = Field(default="")
    created_by: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_delete: int = Field(default=0)