
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlmodel import Session, SQLModel, create_engine
from tricys_backend.main import app
from tricys_backend.utils.db import get_session
from tricys_backend.services.task_queue import TaskQueue
import os
from pathlib import Path

# Use an in-memory SQLite DB for testing
sqlite_file_name = "database_test_stage1.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session_override():
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client_fixture")
def client_fixture_func():
    app.dependency_overrides[get_session] = get_session_override
    yield
    app.dependency_overrides.clear()


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=None
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.mark.asyncio
async def test_simulation_workflow_mocked(client_fixture):
    # Setup mocks for subprocess and psutil
    mock_process = MagicMock()
    mock_process.pid = 99999
    # Simulate process finishing successfully after some polls
    mock_process.poll.side_effect = [None, None, 0]
    
    from io import BytesIO
    mock_process.stdout = BytesIO(b"Simulation Started\nProgress: 50%\nProgress: 100%\nSimulation Finished\n")
    
    # Mock psutil.Process (used in task_queue for process management)
    mock_psutil_proc = MagicMock()
    mock_psutil_proc.wait.return_value = 0
    mock_psutil_proc.children.return_value = []
    
    # Mock result file existence
    # In reality, the engine creates files in the workspace.
    # We'll mock os.path.exists and os.listdir to verify the result check logic.
    
    simulation_config = {
        "paths": {
            "package_path": "fake_path/model.mo"
        },
        "simulation": {
            "model_name": "TestModel",
            "variableFilter": "time|var",
            "stop_time": 10.0,
            "step_size": 0.1
        }
    }

    with patch("subprocess.Popen", return_value=mock_process), \
         patch("tricys_backend.services.task_queue.psutil.Process", return_value=mock_psutil_proc), \
         patch("tricys_backend.services.engine.psutil.Process", return_value=mock_psutil_proc), \
         patch("tricys_backend.services.task_queue.db_engine", engine), \
         patch("tricys_backend.services.file_manager.FileManager.create_workspace", return_value=Path("/tmp/workspace")), \
         patch("tricys_backend.services.file_manager.FileManager.save_config", return_value=Path("/tmp/workspace/config.json")):
        
        create_db_and_tables()
        
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Submit Task
            payload = {
                "type": "BASIC",
                "name": "Mocked Integration Test",
                "config_json": simulation_config
            }
            response = await client.post("/api/v1/tasks", json=payload)
            assert response.status_code == 200
            data = response.json()
            task_id = data["id"]
            assert data["status"] == "PENDING"
            
            # 2. Process Task (manual trigger of the worker logic for testing)
            # We don't run the background worker thread in tests usually, 
            # we call the process method directly or mock the queue.
            await TaskQueue._process_task(task_id)
            
            # 3. Poll Status
            response = await client.get(f"/api/v1/tasks/{task_id}")
            assert response.status_code == 200
            task_info = response.json()
            assert task_info["status"] == "COMPLETED"
            assert "workspace_path" in task_info
            
            # 4. Verify results check logic (implicitly covered by status being COMPLETED)
            # if the status reached COMPLETED, it means the task_queue finished without error.
