from pathlib import Path

from tricys_backend.models.task import ConfigJsonSchema
from tricys_backend.services.task_queue import _prepare_foc_config_for_workspace


def test_prepare_foc_config_writes_inline_content(tmp_path):
    workspace_path = tmp_path / "task-workspace"
    workspace_path.mkdir()
    foc_content = "POWER 1000\nBURN 10\nDWELL 5\n"

    normalized = _prepare_foc_config_for_workspace(
        {
            "simulation": {"model_name": "example_model.Cycle"},
            "foc": {
                "foc_component": "pulseSource",
                "foc_name": "task_input.foc",
                "foc_content": foc_content,
            },
        },
        workspace_path,
    )

    written_path = workspace_path / "foc" / "task_input.foc"
    assert written_path.exists()
    assert written_path.read_text(encoding="utf-8") == foc_content
    assert normalized["foc"]["foc_component"] == "pulseSource"
    assert normalized["foc"]["foc_path"] == "foc/task_input.foc"
    assert normalized["foc"]["foc_name"] == "task_input.foc"
    assert "foc_content" not in normalized["foc"]


def test_prepare_foc_config_copies_relative_foc_path(tmp_path):
    project_root = tmp_path / "project-root"
    source_dir = project_root / "example" / "basic"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "schedule.foc"
    source_content = "PULSE 1500 1 1 2\n"
    source_path.write_text(source_content, encoding="utf-8")

    workspace_path = tmp_path / "task-workspace"
    workspace_path.mkdir()

    normalized = _prepare_foc_config_for_workspace(
        {
            "simulation": {"model_name": "example_model.Cycle"},
            "foc": {
                "foc_component": "pulseSource",
                "foc_path": "example/basic/schedule.foc",
            },
        },
        workspace_path,
        source_roots=[project_root],
    )

    copied_path = workspace_path / "foc" / "schedule.foc"
    assert copied_path.exists()
    assert copied_path.read_text(encoding="utf-8") == source_content
    assert normalized["foc"]["foc_path"] == "foc/schedule.foc"
    assert normalized["foc"]["foc_name"] == "schedule.foc"


def test_config_json_schema_accepts_top_level_foc_content():
    config = ConfigJsonSchema(
        paths={"package_path": "model.mo"},
        simulation={
            "model_name": "example_model.Cycle",
            "stop_time": 10.0,
            "step_size": 0.1,
        },
        foc={
            "foc_component": "pulseSource",
            "foc_name": "task_input.foc",
            "foc_content": "POWER 1000\nBURN 10\nDWELL 5\n",
        },
    )

    assert config.foc is not None
    assert config.foc.foc_component == "pulseSource"
    assert config.foc.foc_name == "task_input.foc"