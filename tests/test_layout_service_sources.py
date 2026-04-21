from tricys_backend.services.layout_service import LayoutService


SAMPLE_MODELICA = """
within example_model;
model Cycle
  Modelica.Blocks.Sources.Pulse pulseSource(amplitude = 9.60984, period = 500, width = 100) annotation(
    Placement(transformation(origin = {-120, -20}, extent = {{-60, 20}, {-40, 40}})));
  Plasma plasma annotation(
    Placement(transformation(origin = {-140, 10}, extent = {{0, -10}, {20, 10}})));
equation
  connect(pulseSource.y, plasma.pulseInput);
end Cycle;

model Plasma
  parameter Real fb = 0.05;
end Plasma;
"""


def test_parse_model_structure_captures_builtin_component_declaration_sources():
    data = LayoutService.parse_model_structure(SAMPLE_MODELICA)

    components = {component["id"]: component for component in data["components"]}
    assert "pulseSource" in components
    assert components["pulseSource"]["type"] == "Modelica.Blocks.Sources.Pulse"
    assert components["pulseSource"]["position"] == {"x": -120.0, "y": -20.0}

    pulse_source_code = data["source_codes"]["pulseSource"]
    assert "Modelica.Blocks.Sources.Pulse pulseSource" in pulse_source_code
    assert "amplitude = 9.60984" in pulse_source_code


def test_parse_model_structure_preserves_cycle_and_custom_model_sources():
    data = LayoutService.parse_model_structure(SAMPLE_MODELICA)

    cycle_source_code = data["source_codes"]["Cycle"]
    assert cycle_source_code.startswith("within example_model;")
    assert "model Cycle" in cycle_source_code
    assert "connect(pulseSource.y, plasma.pulseInput);" in cycle_source_code

    plasma_source_code = data["source_codes"]["plasma"]
    assert plasma_source_code.startswith("model Plasma")
    assert "parameter Real fb = 0.05;" in plasma_source_code


def test_parse_model_structure_extracts_builtin_constructor_parameters():
    data = LayoutService.parse_model_structure(SAMPLE_MODELICA)

    parameter_map = {item["name"]: item for item in data["parameters"]}
    assert parameter_map["pulseSource.amplitude"]["value"] == 9.60984
    assert parameter_map["pulseSource.period"]["value"] == 500
    assert parameter_map["pulseSource.width"]["value"] == 100


def test_parse_model_structure_applies_instance_override_over_model_defaults():
    content = """
model Cycle
  Plasma plasma(fb = 0.1) annotation(origin={0, 0});
equation
end Cycle;

model Plasma
  parameter Real fb = 0.05;
  parameter Real T = 1000;
end Plasma;
"""

    data = LayoutService.parse_model_structure(content)
    parameter_map = {item["name"]: item for item in data["parameters"]}

    assert parameter_map["plasma.fb"]["value"] == 0.1
    assert parameter_map["plasma.fb"]["defaultValue"] == 0.1
    assert parameter_map["plasma.T"]["value"] == 1000