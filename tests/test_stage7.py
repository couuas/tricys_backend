from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from tricys_backend.main import app
import json
from pathlib import Path

client = TestClient(app)

def test_model_parse_api_mock():
    """Test the model parsing API with mocked service."""
    mock_params = [
        {"name": "test.param", "type": "Real", "default": 1.0, "description": "Test param"}
    ]
    
    with patch("tricys_backend.services.model_service.ModelService.parse_model") as mock_service:
        mock_service.return_value = mock_params
        
        payload = {
            "package_path": "/tmp/test.mo",
            "model_name": "Test.Model"
        }
        response = client.post("/api/v1/models/parse", json=payload)
        
        assert response.status_code == 200
        assert response.json() == mock_params
        mock_service.assert_called_once_with("/tmp/test.mo", "Test.Model")

def test_bi_query_api_mock():
    """Test the Grafana BI query API with mocked service and workspace helper."""
    
    mock_bi_result = [
        {"target": "sds.inventory", "datapoints": [[10.5, 1000], [11.0, 2000]]}
    ]
    
    # We must patch 1) get_task_workspace to bypass DB/Disk check, 2) query_results_bi
    with patch("tricys_backend.api.v1.endpoints.visualization.get_task_workspace") as mock_get_ws, \
         patch("tricys_backend.services.hdf5_service.HDF5ReaderService.query_results_bi") as mock_query:
        
        mock_get_ws.return_value = Path("/tmp/mock_workspace")
        mock_query.return_value = mock_bi_result
        
        payload = {
            "targets": [{"target": "sds.inventory"}],
            "range": {"from": "2023-01-01T00:00:00Z", "to": "2023-01-01T01:00:00Z"}
        }
        
        response = client.post("/api/v1/tasks/dummy-id/results/query_bi", json=payload)
        
        assert response.status_code == 200
        assert response.json() == mock_bi_result
        mock_get_ws.assert_called()
        mock_query.assert_called_once()
