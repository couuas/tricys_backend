import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import json
from tricys_backend.services.layout_service import LayoutService
from tricys_backend.services.ai_service import AIService

# --- Layout Service Data ---
SAMPLE_MODELICA = """
package Example
  model Cycle
    Plasma plasma annotation(origin={-10, 20});
    Tritium_Storage sds annotation(origin={30, -40});
    
    equation
      connect(plasma.out, sds.in);
      connect(sds.out, plasma.fuel);
  end Cycle;
  
  model Plasma
    parameter Real fb = 0.05;
    parameter Real T = 1000;
  end Plasma;
  
  model Tritium_Storage
    parameter Real capacity = 5000;
  end Tritium_Storage;
end Example;
"""

# --- AI Service Data ---
MOCK_CONFIG = {
    "sensitivity_analysis": {
        "analysis_cases": [
            {
                "independent_variable": "TBR",
                "metrics": ["Doubling_Time"]
            }
        ]
    }
}

# --- Layout Service Tests ---

def test_layout_parse_components():
    data = LayoutService.parse_model_structure(SAMPLE_MODELICA)
    components = data.get("components", [])
    assert len(components) == 2
    plasma = next((c for c in components if c["id"] == "plasma"), None)
    assert plasma["position"] == {"x": -10.0, "y": 20.0}

def test_layout_parse_connections():
    data = LayoutService.parse_model_structure(SAMPLE_MODELICA)
    connections = data.get("connections", [])
    assert len(connections) == 2
    assert connections[0]["from"] == "plasma"
    assert connections[0]["to"] == "sds"

def test_layout_parse_parameters():
    data = LayoutService.parse_model_structure(SAMPLE_MODELICA)
    params = data.get("parameters", {})
    assert params.get("plasma.fb") == 0.05
    assert params.get("sds.capacity") == 5000.0

# --- AI Service Tests ---

@pytest.fixture
def mock_report_file(tmp_path):
    report_path = tmp_path / "standard_report.md"
    report_path.write_text("# Standard Report\n\nMetric: 100", encoding="utf-8")
    return tmp_path, report_path

@patch("tricys_backend.services.ai_service.openai")
def test_ai_report_generation_success(mock_openai, mock_report_file):
    work_dir, report_path = mock_report_file
    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock(message=MagicMock(content="# AI Analysis Result"))]
    mock_client.chat.completions.create.return_value = mock_completion
    mock_openai.OpenAI.return_value = mock_client
    
    result_path = AIService.generate_enhanced_report(work_dir, report_path, MOCK_CONFIG)
    assert result_path is not None
    assert "analysis_report_ai.md" in result_path.name
    assert "# AI Analysis Result" in result_path.read_text(encoding="utf-8")

@patch("tricys_backend.services.ai_service.openai")
def test_ai_report_api_failure(mock_openai, mock_report_file):
    work_dir, report_path = mock_report_file
    mock_openai.OpenAI.side_effect = Exception("API Error")
    result_path = AIService.generate_enhanced_report(work_dir, report_path, MOCK_CONFIG)
    assert result_path is None

# --- API Integration Tests ---
from fastapi.testclient import TestClient
from tricys_backend.main import app

client = TestClient(app)

def test_api_parse_content():
    response = client.post(
        "/api/v1/parse_content",
        content="model Cycle\n ComponentA compA annotation(origin={10, 20});\nend Cycle;",
        headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["components"][0]["id"] == "compA"
    assert data["components"][0]["position"] == {"x": 10.0, "y": 20.0}
