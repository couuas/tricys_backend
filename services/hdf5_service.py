import os
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd
import numpy as np
import logging
from tricys_backend.utils.sampling import lttb_downsample

logger = logging.getLogger(__name__)

class HDF5ReaderService:
    def __init__(self, root_dir: str = None):
        # root_dir is optional now as we prefer explicit workspace_path in query
        self.root_dir = list(Path(root_dir).glob("*")) if root_dir else None

    def resolve_hdf5_file(
        self,
        task_id: str,
        workspace_path: Path,
        selected_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """Resolve an HDF5 results file for a task workspace."""
        if selected_path:
            if selected_path.exists() and selected_path.suffix.lower() == ".h5":
                return selected_path
            logger.warning(
                f"Selected HDF5 file for task {task_id} is invalid or missing: {selected_path}"
            )

        hdf5_file = self._find_result_file(workspace_path, "sweep_results.h5")
        if not hdf5_file or not hdf5_file.exists():
            hdf5_file = self._find_any_hdf5(workspace_path)
        if not hdf5_file or not hdf5_file.exists():
            logger.warning(f"No HDF5 file found for task {task_id} in {workspace_path}")
            return None
        return hdf5_file

    def get_jobs_df(
        self,
        task_id: str,
        workspace_path: Path,
        selected_path: Optional[Path] = None,
    ) -> pd.DataFrame:
        """Load jobs table as DataFrame."""
        hdf5_file = self.resolve_hdf5_file(task_id, workspace_path, selected_path)
        if not hdf5_file:
            return pd.DataFrame()
        try:
            jobs_df = pd.read_hdf(hdf5_file, "jobs")
            return jobs_df
        except Exception as e:
            logger.error(f"Error reading jobs table for task {task_id}: {str(e)}")
            return pd.DataFrame()

    def get_config_log(
        self,
        task_id: str,
        workspace_path: Path,
        selected_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Load config and log data from HDF5."""
        hdf5_file = self.resolve_hdf5_file(task_id, workspace_path, selected_path)
        if not hdf5_file:
            return {"config_data": None, "log_data": None}

        config_data = None
        log_data = None
        try:
            with pd.HDFStore(hdf5_file, mode="r") as store:
                if "/config" in store.keys():
                    try:
                        config_raw = store.select("config").iloc[0, 0]
                        config_data = json.loads(config_raw) if isinstance(config_raw, str) else config_raw
                    except Exception:
                        config_data = None

                if "/log" in store.keys():
                    try:
                        log_raw = store.select("log").iloc[0, 0]
                        log_data = json.loads(log_raw) if isinstance(log_raw, str) else log_raw
                    except Exception:
                        log_data = None
        except Exception as e:
            logger.error(f"Error reading config/log for task {task_id}: {str(e)}")

        return {"config_data": config_data, "log_data": log_data}

    def _find_result_file(self, workspace_path: Path, filename: str) -> Path:
        """Finds a file recursively in the workspace, preferring the most deeply nested or latest one."""
        # User specified pattern: workspace / {timestamp} / results / filename
        # We try to match that, or just find the file anywhere.
        matches = list(workspace_path.glob(f"**/{filename}"))
        
        if not matches:
            return None
            
        # If multiple, sort by modification time (newest first)
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0]

    def _find_any_hdf5(self, workspace_path: Path) -> Optional[Path]:
        """Finds the newest .h5 file in the workspace as a fallback."""
        matches = list(workspace_path.glob("**/*.h5"))
        if not matches:
            return None
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0]

    def get_visualizer_metadata(
        self,
        task_id: str,
        workspace_path: Path,
        selected_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Loads visualizer metadata from HDF5: variables, parameters, jobs table, config, log.
        Returns a dict with keys: variable_options, parameter_options, table_columns, jobs_data, config_data, log_data.
        """
        try:
            hdf5_file = self.resolve_hdf5_file(task_id, workspace_path, selected_path)

            if not hdf5_file or not hdf5_file.exists():
                return {
                    "variable_options": [],
                    "parameter_options": [],
                    "table_columns": [],
                    "jobs_data": [],
                    "config_data": None,
                    "log_data": None,
                }

            # Defaults
            variable_options: List[str] = []
            parameter_options: List[str] = []
            table_columns: List[Dict[str, Any]] = []
            jobs_data: List[Dict[str, Any]] = []
            config_data: Any = None
            log_data: Any = None

            # Load jobs & results columns
            with pd.HDFStore(hdf5_file, mode="r") as store:
                # Results columns
                if "/results" in store.keys():
                    try:
                        results_cols = store.select("results", start=0, stop=0).columns
                        variable_options = [c for c in results_cols if c not in ["time", "job_id"]]
                    except Exception:
                        variable_options = []

                # Config
                if "/config" in store.keys():
                    try:
                        config_raw = store.select("config").iloc[0, 0]
                        config_data = json.loads(config_raw) if isinstance(config_raw, str) else config_raw
                    except Exception:
                        config_data = None

                # Log
                if "/log" in store.keys():
                    try:
                        log_raw = store.select("log").iloc[0, 0]
                        log_data = json.loads(log_raw) if isinstance(log_raw, str) else log_raw
                    except Exception:
                        log_data = None

            # Load jobs separately (may be large)
            try:
                jobs_df = pd.read_hdf(hdf5_file, "jobs")
                if "job_id" in jobs_df.columns:
                    cols = ["job_id"] + [c for c in jobs_df.columns if c != "job_id"]
                    jobs_df = jobs_df[cols]

                parameter_options = [c for c in jobs_df.columns if c != "job_id"]
                table_columns = [{"name": c, "id": c} for c in jobs_df.columns]
                jobs_data = jobs_df.to_dict("records")
            except Exception:
                parameter_options = []
                table_columns = []
                jobs_data = []

            return {
                "variable_options": variable_options,
                "parameter_options": parameter_options,
                "table_columns": table_columns,
                "jobs_data": jobs_data,
                "config_data": config_data,
                "log_data": log_data,
                "hdf5_file": str(hdf5_file),
            }
        except Exception as e:
            logger.error(f"Error loading visualizer metadata for task {task_id}: {str(e)}")
            return {
                "variable_options": [],
                "parameter_options": [],
                "table_columns": [],
                "jobs_data": [],
                "config_data": None,
                "log_data": None,
                "hdf5_file": None,
            }

    def query_results(
        self, 
        task_id: str, 
        workspace_path: Path,
        variables: List[str] = None, 
        time_range: Tuple[float, float] = None,
        job_id: int = None,
        job_ids: List[int] = None,
        limit: Optional[int] = 2000, # Default limit for visualization performance
        selected_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Query simulation results from HDF5 with optional LTTB downsampling.
        """
        # Normalize job_ids
        target_jobs = []
        if job_ids:
            target_jobs.extend(job_ids)
        if job_id is not None and job_id not in target_jobs:
            target_jobs.append(job_id)
            
        try:
            # 1. Fetch raw data
            hdf5_file = self.resolve_hdf5_file(task_id, workspace_path, selected_path)
            if hdf5_file and hdf5_file.exists():
                raw_df = self._query_hdf5_df(hdf5_file, variables, time_range, target_jobs)
            else:
                raise FileNotFoundError(f"No result files found for task {task_id}")

            # 2. Filter & Clean DataFrame (if from CSV)
            if "time" not in raw_df.columns:
                 return raw_df.to_dict(orient='list')

            # 3. Apply Downsampling if needed
            if limit and len(raw_df) > limit:
                logger.info(f"Downsampling results for task {task_id} from {len(raw_df)} to {limit} points")
                
                # We need to downsample each variable against the 'time' column
                # To keep data aligned, we pick the indices from the LTTB of the first requested variable or time itself
                times = raw_df["time"].values
                
                # If we have multiple variables, we should ideally downsample each 
                # but for alignment, let's use a simplified approach: 
                # Downsample based on the first data variable to get representative indices
                data_cols = [c for c in raw_df.columns if c not in ["time", "job_id"]]
                
                if data_cols:
                    # Use the first variable as the reference for triangle areas
                    ref_var = data_cols[0]
                    # Prepare (time, value) pairs for LTTB
                    # Fill NaNs for LTTB processing
                    points = np.column_stack((times, raw_df[ref_var].fillna(0).values))
                    downsampled_points = lttb_downsample(points, limit)
                    
                    # Instead of just taking points, let's find the nearest original indices 
                    # to keep other variables in sync. 
                    # For simplicity in this implementation, we'll return the downsampled pairs.
                    # A more robust way is to interpolate, but LTTB's point selection is usually fine.
                    
                    # Result dict
                    res = {"time": downsampled_points[:, 0].tolist()}
                    for col in raw_df.columns:
                        if col == "time": continue
                        # For each other column, we apply the same "importance" logic 
                        # or just simple interpolation/re-sampling.
                        # To keep it high performance, we'll just downsample each series independently
                        series_points = np.column_stack((times, raw_df[col].fillna(0).values))
                        ds_series = lttb_downsample(series_points, limit)
                        res[col] = ds_series[:, 1].tolist()
                    return res
                
            return raw_df.to_dict(orient='list')
            
        except Exception as e:
            logger.error(f"Error querying results for task {task_id}: {str(e)}")
            raise

    def _query_hdf5_df(
        self, 
        path: Path, 
        variables: List[str], 
        time_range: Tuple[float, float],
        job_ids: List[int]
    ) -> pd.DataFrame:
        """Helper to return DataFrame from HDF5."""
        where_clauses = []
        if time_range:
            start, end = time_range
            where_clauses.append(f"time >= {start} & time <= {end}")
        if job_ids:
            if len(job_ids) == 1:
                where_clauses.append(f"job_id == {job_ids[0]}")
            else:
                where_clauses.append(f"job_id in {job_ids}")
            
        where_str = " & ".join(where_clauses) if where_clauses else None
        
        columns = None
        if variables:
            columns = list(set(variables + ["time", "job_id"]))

        with pd.HDFStore(path, mode='r') as store:
            if '/results' not in store:
                return pd.DataFrame()
            return store.select('results', where=where_str, columns=columns)

    def get_summary_metrics(
        self,
        task_id: str,
        workspace_path: Path,
        selected_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves summary metrics from the HDF5 file.
        Returns a list of dicts: [{'job_id': 1, 'metric_name': 'X', 'metric_value': 10.0}, ...]
        """
        try:
            hdf5_file = self.resolve_hdf5_file(task_id, workspace_path, selected_path)
            if not hdf5_file or not hdf5_file.exists():
                # Fallback or return empty
                return []
            
            with pd.HDFStore(hdf5_file, mode='r') as store:
                if '/summary' in store:
                    df = store.select('summary')
                    return df.to_dict(orient='records')
                else:
                    return []
        except Exception as e:
            logger.error(f"Error reading summary metrics for task {task_id}: {str(e)}")
            return []

    def query_results_bi(
        self,
        task_id: str,
        workspace_path: Path,
        request_data: Dict[str, Any],
        selected_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query results and format for Grafana SimpleJSON Datasource.
        Applies LTTB downsampling for large datasets.
        """
        targets = request_data.get("targets", [])
        range_data = request_data.get("range", {})
        
        # Parse time range from ISO strings if present
        start_time = 0.0
        stop_time = float('inf')
        # TODO: Parse range["from"] and range["to"] to float seconds if needed.
        
        variables = [t.get("target") for t in targets if t.get("target")]
        if not variables:
            return []
            
        # internal query
        data_dict = self.query_results(
            task_id, 
            workspace_path, 
            variables=variables,
            time_range=(start_time, stop_time)
            ,selected_path=selected_path
        )
        
        # Transform to Grafana format
        # data_dict = {"time": [t1, t2...], "var1": [v1, v2...], "job_id": [...]}
        # Grafana expects timestamp in ms
        
        if "time" not in data_dict:
            return []
            
        times = data_dict["time"]
        count = len(times)
        
        # Downsampling Config
        MAX_POINTS = 1000 # Limit per series
        
        response = []
        for var in variables:
            if var in data_dict:
                values = data_dict[var]
                
                # Zip time and value
                # LTTB requires list of [time, value]
                # Filter None/NaN before LTTB
                raw_data = []
                for t, v in zip(times, values):
                    if pd.notnull(v):
                        raw_data.append([t, v])
                
                if not raw_data:
                    continue
                    
                if len(raw_data) > MAX_POINTS:
                    # Apply Internal LTTB Downsampling
                    # Convert list to numpy array for efficiency
                    np_data = np.array(raw_data)
                    downsampled = lttb_downsample(np_data, MAX_POINTS)
                    # Convert back to Grafana format [value, time_ms]
                    datapoints = [[float(row[1]), float(row[0] * 1000)] for row in downsampled]
                else:
                    # No downsampling needed
                    datapoints = [[float(v), float(t * 1000)] for t, v in raw_data]
                
                response.append({
                    "target": var,
                    "datapoints": datapoints
                })
                
        return response

