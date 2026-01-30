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
    
    # CORS Configuration - can be overridden via environment variable
    # Including '*' for development, but note that main.py needs to handle this 
    # carefully with allow_credentials.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8080,http://localhost:5500,http://localhost:5173,null,*"
    
    @property
    def cors_origins_list(self) -> list:
        """Parse CORS_ORIGINS string into list."""
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
        return origins

    class Config:
        case_sensitive = True

settings = Settings()

# Ensure workspaces directory exists
os.makedirs(settings.WORKSPACES_DIR, exist_ok=True)
