import os
import shutil
import time
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from typing import Generator

from tricys_backend.main import app
from tricys_backend.core.config import settings
from tricys_backend.services.cleanup_service import CleanupService
from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task

# Use a separate test workspace directory
TEST_WORKSPACES_DIR = Path(settings.BASE_DIR) / "test_stage3_workspaces"
TEST_DB_NAME = "test_stage3.db"
TEST_DB_PATH = settings.BASE_DIR / TEST_DB_NAME
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})

@pytest.fixture(scope="module", autouse=True)
def setup_test_env():
    # 0. Cleanup Stale DB
    if TEST_DB_PATH.exists():
        os.remove(TEST_DB_PATH)

    # 1. Setup Workspaces
    if TEST_WORKSPACES_DIR.exists():
        shutil.rmtree(TEST_WORKSPACES_DIR)
    os.makedirs(TEST_WORKSPACES_DIR, exist_ok=True)
    
    # 2. Setup DB
    SQLModel.metadata.create_all(engine)
    
    # Override Dependency
    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session
            
    app.dependency_overrides[get_session] = override_get_session
    
    # Monkey patch settings.WORKSPACES_DIR (globally for this process)
    original_workspaces_dir = settings.WORKSPACES_DIR
    settings.WORKSPACES_DIR = TEST_WORKSPACES_DIR
    
    yield
    
    # Cleanup
    app.dependency_overrides.clear()
    settings.WORKSPACES_DIR = original_workspaces_dir
    if TEST_WORKSPACES_DIR.exists():
        shutil.rmtree(TEST_WORKSPACES_DIR)
    # Don't delete DB here to allow inspection if failed, or delete it.
    # We delete at start anyway.

@pytest.fixture
def api_client():
    return TestClient(app)

def create_task_record(task_id: str):
    """Helper to inject task into Test DB"""
    with Session(engine) as session:
        # Check if exists first to avoid integrity error on re-runs in interactive modes
        existing = session.get(Task, task_id)
        if existing:
            return Path(existing.workspace_path)

        # Create directory
        task_dir = TEST_WORKSPACES_DIR / task_id
        os.makedirs(task_dir, exist_ok=True)
        
        task = Task(
            id=task_id,
            status="COMPLETED",
            workspace_path=str(task_dir),
            config_json={"test": True}
        )
        session.add(task)
        session.commit()
    return task_dir

def test_query_results_csv(api_client):
    task_id = "test_task_csv"
    task_dir = create_task_record(task_id)
    
    # Structure: task_id / {timestamp} / results / sweep_results.csv
    timestamp_dir = task_dir / "20231027_120000"
    results_dir = timestamp_dir / "results"
    os.makedirs(results_dir, exist_ok=True)
    
    # Create dummy CSV
    df = pd.DataFrame({
        "time": [0.0, 1.0, 2.0],
        "speed": [10, 20, 30],
        "job_id": [1, 1, 1]
    })
    df.to_csv(results_dir / "sweep_results.csv", index=False)
    
    response = api_client.post(
        f"/api/v1/results/{task_id}/query", 
        json={"variables": ["speed"], "time_range": [0.0, 1.0]}
    )
    
    assert response.status_code == 200, response.text
    data = response.json()
    assert "speed" in data
    assert data["speed"] == [10, 20]
    assert len(data["time"]) == 2

def test_query_results_csv_wide_format(api_client):
    """Test support for 'variable&param=val' column headers."""
    task_id = "test_task_csv_wide"
    task_dir = create_task_record(task_id)
    
    results_dir = task_dir / "results"
    os.makedirs(results_dir, exist_ok=True)
    
    # Create CSV with wide format
    df = pd.DataFrame({
        "time": [0.0, 1.0],
        "speed&p=1": [10, 20],
        "speed&p=2": [15, 25],
        "other": [9, 9]
    })
    df.to_csv(results_dir / "sweep_results.csv", index=False)
    
    # Query for "speed"
    response = api_client.post(
        f"/api/v1/results/{task_id}/query", 
        json={"variables": ["speed"], "time_range": [0.0, 1.0]}
    )
    
    assert response.status_code == 200, response.text
    data = response.json()
    
    # Should contain time, speed&p=1, speed&p=2
    assert "time" in data
    assert "speed&p=1" in data
    assert "speed&p=2" in data
    assert data["speed&p=1"] == [10, 20]
    # Should NOT contain "other"
    assert "other" not in data

def test_query_results_hdf5(api_client):
    try:
        import tables
    except ImportError:
        pytest.skip("PyTables not installed, skipping HDF5 test")

    task_id = "test_task_hdf5"
    task_dir = create_task_record(task_id)
    
    # Nested structure
    timestamp_dir = task_dir / "20231027_130000"
    results_dir = timestamp_dir / "results"
    os.makedirs(results_dir, exist_ok=True)
    
    # Create dummy HDF5
    df = pd.DataFrame({
        "time": [0.0, 1.0, 2.0],
        "power": [100, 200, 300],
        "job_id": [1, 1, 1]
    })
    store_path = results_dir / "sweep_results.h5"
    with pd.HDFStore(str(store_path), mode='w') as store:
        store.put('results', df, format='table', data_columns=True)
        
    response = api_client.post(
        f"/api/v1/results/{task_id}/query", 
        json={"variables": ["power"], "time_range": [1.0, 2.0]}
    )
    
    assert response.status_code == 200, response.text
    data = response.json()
    assert "power" in data
    assert data["power"] == [200, 300]

def test_download_archive(api_client):
    task_id = "test_task_archive"
    task_dir = create_task_record(task_id)
    (task_dir / "data.txt").write_text("hello content")
    
    response = api_client.get(f"/api/v1/results/{task_id}/download")
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

def test_config_validation(api_client):
    # Invalid empty config
    response = api_client.post("/api/v1/tasks", json={"type": "BASIC", "config_json": {}})
    assert response.status_code == 422



