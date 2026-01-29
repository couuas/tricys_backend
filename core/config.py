import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Tricys Backend"
    API_V1_STR: str = "/api/v1"
    
    # Path Configuration
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    WORKSPACES_DIR: Path = BASE_DIR / "workspaces"
    DATABASE_URL: str = "sqlite:///./tricys.db"
    
    TRICYS_CMD: str = "tricys"  # or "python -m tricys"

    class Config:
        case_sensitive = True

settings = Settings()

# Ensure workspaces directory exists
os.makedirs(settings.WORKSPACES_DIR, exist_ok=True)
