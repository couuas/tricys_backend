from sqlmodel import Session, create_engine, SQLModel
from tricys_backend.core.config import settings

# Import models to ensure they are registered with SQLModel metadata
from tricys_backend.models.task import Task
from tricys_backend.models.project import Project
from tricys_backend.models.user import User
from tricys_backend.models.goview_project import GoviewProject

# Shared engine
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
