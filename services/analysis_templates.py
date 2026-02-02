from typing import List, Dict, Any

class AnalysisTemplates:
    @staticmethod
    def get_templates() -> List[Dict[str, Any]]:
        return [
            {
                "id": "single_param_sensitivity",
                "name": "Single Parameter Sensitivity",
                "description": "Sweep a single variable across a defined range.",
                "icon": "📈",
                "schema": {
                    "independent_variable": {"type": "string", "label": "Parameter to Sweep", "placeholder": "e.g. plasma.nf"},
                    "sampling_method": {"type": "csv", "label": "Values (comma separated)", "placeholder": "0.1, 0.2, 0.3"},
                    "target_kpis": {"type": "csv", "label": "Target KPIs", "default": "Startup_Inventory, Doubling_Time"}
                }
            },
            {
                "id": "multi_param_sensitivity",
                "name": "Multi-Parameter Sensitivity",
                "description": "Combine a primary sweep with discrete variations of other parameters.",
                "icon": "📉",
                "schema": {
                    "independent_variable": {"type": "string", "label": "Primary Parameter (X-Axis)", "placeholder": "e.g. plasma.nf"},
                    "sampling_method": {"type": "csv", "label": "Primary Values", "placeholder": "0.1, 0.2, 0.3"},
                    "secondary_params": {
                        "type": "key_value_lists", 
                        "label": "Secondary Parameters (Combinatorial)", 
                        "placeholder_key": "Parameter (e.g. plasma.fb)",
                        "placeholder_val": "Values (e.g. 0.05, 0.1)"
                    },
                    "target_kpis": {"type": "csv", "label": "Target KPIs", "default": "Startup_Inventory, Required_TBR"}
                }
            },
            {
                "id": "sobol_sensitivity",
                "name": "Global Sensitivity (Sobol)",
                "description": "Analyze global sensitivity using Sobol sequence sampling.",
                "icon": "🕸️",
                "schema": {
                     "params": {
                        "type": "param_bounds",
                        "label": "Parameters & Bounds",
                        "columns": ["Parameter", "Min", "Max", "Distribution"]
                     },
                     "sample_n": {"type": "number", "label": "Sample N (Power of 2)", "default": 256},
                     "target_kpis": {"type": "csv", "label": "Target KPIs", "default": "Startup_Inventory"}
                }
            },
             {
                "id": "latin_uncertainty",
                "name": "Uncertainty Analysis (Latin Hypercube)",
                "description": "Quantify uncertainty using Latin Hypercube Sampling.",
                "icon": "🎲",
                "schema": {
                     "params": {
                        "type": "param_bounds",
                        "label": "Parameters & Bounds",
                        "columns": ["Parameter", "Min", "Max", "Distribution"]
                     },
                     "sample_n": {"type": "number", "label": "Sample Size", "default": 100},
                     "target_kpis": {"type": "csv", "label": "Target KPIs", "default": "Startup_Inventory"}
                }
            },
            {
                "id": "bisection_optimization",
                "name": "Target Optimization (Bisection)",
                "description": "Find parameter value to achieve specific target (e.g., TBR > 1.05).",
                "icon": "🎯",
                "schema": {
                    "target_param": {"type": "string", "label": "Parameter to Adjust", "placeholder": "e.g. blanket.TBR"},
                    "target_metric": {"type": "string", "label": "Target Metric", "default": "Required_TBR"},
                    "search_range": {"type": "range", "label": "Search Range [Min, Max]", "default": [1.0, 1.5]},
                    "tolerance": {"type": "number", "label": "Tolerance", "default": 0.005},
                    "max_iterations": {"type": "number", "label": "Max Iterations", "default": 10}
                }
            }
        ]

    @staticmethod
    def build_config(template_id: str, form_data: Dict[str, Any], project_default_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Converts the simplified form_data from UI into the complex logic-ready config.json structure.
        """
        # Base Analysis Structure
        base_config = {
            "sensitivity_analysis": {
                "enabled": True,
                "analysis_cases": [],
                "metrics_definition": AnalysisTemplates._get_default_metrics(), 
                 # In real app, metrics_definition should merge with project defaults or user provided
                "unit_map": AnalysisTemplates._get_default_units()
            }
        }
        
        case_config = {}
        
        if template_id == "single_param_sensitivity":
            case_config = {
                "name": form_data.get("name", "SingleParamAnalysis"),
                "independent_variable": form_data["independent_variable"],
                "independent_variable_sampling": [float(x.strip()) for x in form_data["sampling_method"].split(',')],
                "dependent_variables": [x.strip() for x in form_data.get("target_kpis", "").split(',')],
                "plot_type": "line",
                "combine_plots": True
            }
            base_config["sensitivity_analysis"]["analysis_cases"].append(case_config)

        elif template_id == "multi_param_sensitivity":
            # Process secondary params
            sim_params = {}
            for item in form_data.get("secondary_params", []):
                if item["key"] and item["val"]:
                    sim_params[item["key"]] = [float(x.strip()) for x in item["val"].split(',')]

            case_config = {
                "name": form_data.get("name", "MultiParamAnalysis"),
                "independent_variable": form_data["independent_variable"],
                "independent_variable_sampling": [float(x.strip()) for x in form_data["sampling_method"].split(',')],
                "dependent_variables": [x.strip() for x in form_data.get("target_kpis", "").split(',')],
                "simulation_parameters": sim_params,
                "plot_type": "line",
                "combine_plots": True
            }
            base_config["sensitivity_analysis"]["analysis_cases"].append(case_config)

        elif template_id in ["sobol_sensitivity", "latin_uncertainty"]:
            method = "sobol" if template_id == "sobol_sensitivity" else "latin"
            
            # Param Bounds Construction
            sampling = {}
            indep_vars = []
            for p in form_data.get("params", []):
                name = p["param"]
                indep_vars.append(name)
                sampling[name] = {
                    "bounds": [float(p["min"]), float(p["max"])],
                    "distribution": p.get("dist", "unif")
                }

            case_config = {
                "name": form_data.get("name", "GlobalAnalysis"),
                "independent_variable": indep_vars,
                "independent_variable_sampling": sampling,
                "dependent_variables": [x.strip() for x in form_data.get("target_kpis", "").split(',')],
                "analyzer": {
                    "method": method,
                    "sample_N": int(form_data.get("sample_n", 100))
                }
            }
            base_config["sensitivity_analysis"]["analysis_cases"].append(case_config)
            
        elif template_id == "bisection_optimization":
             # Optimization is unique: it puts config in metrics_definition
             target_metric = form_data.get("target_metric", "Required_TBR")
             
             # Optimization often needs a base sweep (e.g. sds.I[1] vs time? No, it runs iteratively)
             # Actually, in the example, it is usually embedded in a sensitivity analysis or runs standalone?
             # Tricys logic: _run_bisection_search_fast checks for "Required_" vars.
             # So we need a dummy analysis case that lists this variable?
             # Or just a basic simulation with this metric requested.
             
             # Let's create a "dummy" case to trigger the flow if needed, 
             # or simply rely on the fact that if "Required_" is in dependent_vars, it triggers.
             
             case_config = {
                 "name": form_data.get("name", "Optimization"),
                 "independent_variable": "dummy", # Might need valid var
                 "independent_variable_sampling": [1], # Dummy run
                 "dependent_variables": [target_metric],
             }
             
             base_config["sensitivity_analysis"]["analysis_cases"].append(case_config)
             
             # Inject the optimization definition into metrics_definition
             base_config["sensitivity_analysis"]["metrics_definition"][target_metric] = {
                 "source_column": "sds.I[1]", # simplified assumption or user input?
                 "method": "bisection_search",
                 "parameter_to_optimize": form_data["target_param"],
                 "search_range": [float(x) for x in form_data["search_range"]], # array handling needed
                 "tolerance": float(form_data["tolerance"]),
                 "max_iterations": int(form_data["max_iterations"])
             }

        return base_config

    @staticmethod
    def _get_default_metrics():
        # Copy from example
        return {
            "Startup_Inventory": { "source_column": "sds.I[1]", "method": "calculate_startup_inventory" },
            "Self_Sufficiency_Time": { "source_column": "sds.I[1]", "method": "time_of_turning_point" },
            "Doubling_Time": { "source_column": "sds.I[1]", "method": "calculate_doubling_time" }
        }

    @staticmethod
    def _get_default_units():
        return {
            "Doubling_Time": { "unit": "days", "conversion_factor": 24 },
            "Startup_Inventory": { "unit": "kg", "conversion_factor": 1000 }
        }
