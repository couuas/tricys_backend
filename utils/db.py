from sqlmodel import Session, create_engine, SQLModel
from tricys_backend.core.config import settings

# Shared engine
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
