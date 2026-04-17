import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Tricys Backend"
    API_V1_STR: str = "/api/v1"
    
    # Path Configuration
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    WORKSPACES_DIR: Path = Path(
        os.getenv("WORKSPACES_DIR", str(BASE_DIR / "workspaces"))
    )
    ASSETS_DIR: Path = Path(os.getenv("ASSETS_DIR", str(BASE_DIR / "assets")))
    
    # Database
    # Supports SQLite by default, but can be overridden by env var for PostgreSQL
    # e.g. postgresql://user:password@localhost/tricys
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR.joinpath('tricys.db')}")
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    HDF5_VISUALIZER_SECRET: str = os.getenv(
        "HDF5_VISUALIZER_SECRET", os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
    )
    HDF5_VISUALIZER_BASE_URL: str = os.getenv("HDF5_VISUALIZER_BASE_URL", "/hdf5/")
    HDF5_VISUALIZER_TOKEN_TTL_SECONDS: int = int(
        os.getenv("HDF5_VISUALIZER_TOKEN_TTL_SECONDS", "900")
    )
    HDF5_CONTEXTS_DIR: Path = Path(
        os.getenv("HDF5_CONTEXTS_DIR", str(BASE_DIR / "hdf5_contexts"))
    )
    HDF5_VISUALIZER_HEALTHCHECK_URL: str = os.getenv(
        "HDF5_VISUALIZER_HEALTHCHECK_URL", ""
    )
    
    TRICYS_CMD: str = "tricys"  # or "python -m tricys"
    
    # CORS Configuration - can be overridden via environment variable
    # Including '*' for development, but note that main.py needs to handle this 
    # carefully with allow_credentials.
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080,http://localhost:5500,http://localhost:5173,null,*")
    
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
os.makedirs(settings.ASSETS_DIR, exist_ok=True)
os.makedirs(settings.HDF5_CONTEXTS_DIR, exist_ok=True)
