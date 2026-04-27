import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class ProjectPageRelease(SQLModel, table=True):
    __tablename__ = "project_page_release"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    page_id: str = Field(foreign_key="project_page.id", index=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    goview_project_id: str = Field(foreign_key="goview_project.id", index=True)
    version: int = Field(default=1, index=True)
    content: str = Field(default="{}")
    index_image: Optional[str] = Field(default="")
    remarks: Optional[str] = Field(default="")
    created_by: Optional[str] = Field(default=None, index=True)
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    is_active: int = Field(default=1, index=True)
    is_delete: int = Field(default=0, index=True)