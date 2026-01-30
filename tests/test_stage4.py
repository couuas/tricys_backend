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
from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task

# Use a separate test workspace directory
TEST_WORKSPACES_DIR = Path(settings.BASE_DIR) / "test_other_workspaces"
TEST_DB_URL = "sqlite:///./test_other.db"

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})

@pytest.fixture(scope="module", autouse=True)
def setup_test_env():
    # 0. Cleanup Stale DB
    db_path = "./test_other.db"
    if os.path.exists(db_path):
        os.remove(db_path)

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

def test_delete_task(api_client):
    task_id = "test_task_delete"
    task_dir = create_task_record(task_id)
    (task_dir / "data.txt").write_text("content")
    
    # Delete without cleanup
    response = api_client.delete(f"/api/v1/tasks/{task_id}?cleanup_files=false")
    assert response.status_code == 200
    assert task_dir.exists()
    
    # Re-create for cleanup test
    create_task_record(task_id)
    response = api_client.delete(f"/api/v1/tasks/{task_id}?cleanup_files=true")
    assert response.status_code == 200
    assert not task_dir.exists()

def test_health_and_template(api_client):
    # Health
    response = api_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    
    # Template
    response = api_client.get("/api/v1/config/template")
    assert response.status_code == 200
    assert "simulation" in response.json()

def test_query_multijob_hdf5(api_client):
    try:
        import tables
    except ImportError:
        pytest.skip("PyTables not installed")

    task_id = "test_task_multijob"
    task_dir = create_task_record(task_id)
    results_dir = task_dir / "results"
    os.makedirs(results_dir, exist_ok=True)
    
    # Create HDF5 with multiple jobs
    df = pd.DataFrame({
        "time": [1.0, 1.0, 1.0],
        "val": [10, 20, 30],
        "job_id": [1, 2, 3]
    })
    store_path = results_dir / "sweep_results.h5"
    with pd.HDFStore(str(store_path), mode='w') as store:
        store.put('results', df, format='table', data_columns=True)
        
    # Query job 1 and 3
    response = api_client.post(
        f"/api/v1/results/{task_id}/query", 
        json={"variables": ["val"], "job_ids": [1, 3]}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "val" in data
    # Should get 10 and 30
    assert set(data["val"]) == {10, 30}
    assert 20 not in data["val"]

def test_task_list_filtering(api_client):
    """Test standard history query (US-05) with filtering."""
    # Create COMPLETED task
    t1 = create_task_record("task_completed_1")
    
    # Create PENDING task manually
    with Session(engine) as session:
        t2 = Task(id="task_pending_1", status="PENDING", config_json={})
        session.add(t2)
        session.commit()

    # Test get all
    resp = api_client.get("/api/v1/tasks?limit=100")
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert "task_completed_1" in ids
    assert "task_pending_1" in ids
    
    # Test filter COMPLETED
    resp = api_client.get("/api/v1/tasks?status=COMPLETED&limit=100")
    assert resp.status_code == 200
    completed_ids = [t["id"] for t in resp.json()]
    assert "task_completed_1" in completed_ids
    assert "task_pending_1" not in completed_ids

    # Test filter PENDING
    resp = api_client.get("/api/v1/tasks?status=PENDING&limit=100")
    assert resp.status_code == 200
    pending_ids = [t["id"] for t in resp.json()]
    assert "task_pending_1" in pending_ids
    assert "task_completed_1" not in pending_ids

def test_task_list_pagination(api_client):
    """Test limit and offset for GET /tasks."""
    # Create multiple tasks
    for i in range(5):
        create_task_record(f"pagination_task_{i}")
    
    # Test limit=2
    resp = api_client.get("/api/v1/tasks?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    
    # Test offset=1
    resp = api_client.get("/api/v1/tasks?limit=10&offset=1")
    assert resp.status_code == 200
    all_tasks = api_client.get("/api/v1/tasks?limit=100").json()
    offset_tasks = resp.json()
    assert offset_tasks[0]["id"] == all_tasks[1]["id"]
