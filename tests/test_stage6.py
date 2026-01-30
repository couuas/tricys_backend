
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import pandas as pd
import json
import os
from pathlib import Path

# Adjust import path to include backend root
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from services.hdf5_service import HDF5ReaderService

client = TestClient(app)

@pytest.fixture
def mock_hdf5_data():
    """Mock HDF5 summary data"""
    return {
        "job_id": [1, 2],
        "metric_name": ["Startup_Inventory", "Startup_Inventory"],
        "metric_value": [100.0, 200.0]
    }

@pytest.fixture
def mock_file_structure():
    """Mock file structure for file browser"""
    return [
        {"name": "job_1", "type": "directory", "path": "job_1", "children": []},
        {"name": "sweep_results.csv", "type": "file", "path": "sweep_results.csv", "size": 1024}
    ]

class TestStage6ResultManagement:
    
    @patch("services.hdf5_service.HDF5ReaderService.get_summary_metrics")
    def test_get_result_summary_success(self, mock_get_summary, mock_hdf5_data):
        """Test successful retrieval of summary metrics"""
        mock_get_summary.return_value = mock_hdf5_data
        
        # Test with task_id "123"
        response = client.get("/api/v1/results/tasks/123/result_summary")
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert "metric_name" in data
        assert data["job_id"] == [1, 2]
        assert data["metric_name"] == ["Startup_Inventory", "Startup_Inventory"]

    @patch("services.hdf5_service.HDF5ReaderService.get_summary_metrics")
    def test_get_result_summary_empty(self, mock_get_summary):
        """Test retrieval when no summary metrics exist"""
        mock_get_summary.return_value = {}
        
        response = client.get("/api/v1/results/tasks/123/result_summary")
        
        assert response.status_code == 200
        assert response.json() == {}

    @patch("services.file_browser_service.FileBrowserService.list_files")
    def test_list_files_success(self, mock_list_files, mock_file_structure):
        """Test successful listing of task workspace files"""
        mock_list_files.return_value = mock_file_structure
        
        response = client.get("/api/v1/results/tasks/123/files")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "job_1"
        assert data[1]["name"] == "sweep_results.csv"

    @patch("services.file_browser_service.FileBrowserService.list_files")
    def test_list_files_not_found(self, mock_list_files):
        """Test listing files for a non-existent task/workspace"""
        mock_list_files.side_effect = FileNotFoundError("Workspace not found")
        
        response = client.get("/api/v1/results/tasks/999/files")
        
        assert response.status_code == 404
        assert response.json()["detail"] == "Workspace not found"

    @patch("services.file_browser_service.FileBrowserService.get_file_path")
    def test_stream_file_success(self, mock_get_file_path):
        """Test successful file streaming"""
        # Create a dummy file for testing
        dummy_content = b"test content"
        dummy_file = Path("test_file.txt")
        with open(dummy_file, "wb") as f:
            f.write(dummy_content)
            
        try:
            mock_get_file_path.return_value = dummy_file.resolve()
            
            response = client.get("/api/v1/results/tasks/123/files/test_file.txt")
            
            assert response.status_code == 200
            assert response.content == dummy_content
            # Check content-disposition
            assert "attachment; filename=test_file.txt" in response.headers["content-disposition"]
        finally:
            if dummy_file.exists():
                os.remove(dummy_file)

    @patch("services.file_browser_service.FileBrowserService.get_file_path")
    def test_stream_file_not_found(self, mock_get_file_path):
        """Test streaming a non-existent file"""
        mock_get_file_path.side_effect = FileNotFoundError("File not found")
        
        response = client.get("/api/v1/results/tasks/123/files/nonexistent.txt")
        
        assert response.status_code == 404
        assert response.json()["detail"] == "File not found"

    @patch("services.file_browser_service.FileBrowserService.get_file_path")
    def test_stream_file_security_error(self, mock_get_file_path):
        """Test streaming with security violation (path traversal)"""
        mock_get_file_path.side_effect = ValueError("Access denied")
        
        response = client.get("/api/v1/results/tasks/123/files/../../secret.txt")
        
        assert response.status_code == 403
        assert response.json()["detail"] == "Access denied"

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
