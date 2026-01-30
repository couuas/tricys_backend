import os
from pathlib import Path
from typing import List, Dict, Any, Tuple
import pandas as pd
import logging

logger = logging.getLogger(__name__)

class HDF5ReaderService:
    def __init__(self, root_dir: str = None):
        # root_dir is optional now as we prefer explicit workspace_path in query
        self.root_dir = list(Path(root_dir).glob("*")) if root_dir else None

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

    def query_results(
        self, 
        task_id: str, 
        workspace_path: Path,
        variables: List[str] = None, 
        time_range: Tuple[float, float] = None,
        job_id: int = None,
        job_ids: List[int] = None
    ) -> Dict[str, Any]:
        """
        Query simulation results from HDF5 or CSV.
        """
        # Normalize job_ids
        target_jobs = []
        if job_ids:
            target_jobs.extend(job_ids)
        if job_id is not None and job_id not in target_jobs:
            target_jobs.append(job_id)
            
        try:
            # 1. Try HDF5
            hdf5_file = self._find_result_file(workspace_path, "sweep_results.h5")
            if hdf5_file and hdf5_file.exists():
                return self._query_hdf5(hdf5_file, variables, time_range, target_jobs)
            
            # 2. Try CSV (sweep)
            csv_sweep = self._find_result_file(workspace_path, "sweep_results.csv")
            if csv_sweep and csv_sweep.exists():
                return self._query_csv(csv_sweep, variables, time_range, target_jobs)
                
            # 3. Try CSV (single)
            csv_single = self._find_result_file(workspace_path, "simulation_result.csv")
            if csv_single and csv_single.exists():
                return self._query_csv(csv_single, variables, time_range, target_jobs)
                
            raise FileNotFoundError(f"No result files found for task {task_id} in {workspace_path}")
            
        except Exception as e:
            logger.error(f"Error querying results for task {task_id}: {str(e)}")
            raise

    def _query_hdf5(
        self, 
        path: Path, 
        variables: List[str], 
        time_range: Tuple[float, float],
        job_ids: List[int]
    ) -> Dict[str, Any]:
        """Optimized query for HDF5 files using 'where' clause."""
        where_clauses = []
        
        if time_range:
            start, end = time_range
            where_clauses.append(f"time >= {start} & time <= {end}")
            
        if job_ids:
            if len(job_ids) == 1:
                where_clauses.append(f"job_id == {job_ids[0]}")
            else:
                # Use "in" clause for list
                where_clauses.append(f"job_id in {job_ids}")
            
        where_str = " & ".join(where_clauses) if where_clauses else None
        
        # Determine columns to read
        columns = None
        if variables:
            # always include time and job_id context
            columns = list(set(variables + ["time", "job_id"]))

        # Use efficient slicing
        with pd.HDFStore(path, mode='r') as store:
            if '/results' not in store:
                return {"error": "No results key in HDF5 file"}
                
            df = store.select('results', where=where_str, columns=columns)
            
        return df.to_dict(orient='list')

    def _query_csv(
        self, 
        path: Path, 
        variables: List[str], 
        time_range: Tuple[float, float],
        job_ids: List[int]
    ) -> Dict[str, Any]:
        """Fallback query for CSV files. Reads full file then filters (slower)."""
        df = pd.read_csv(path)
        
        # Filter by time
        if time_range:
            start, end = time_range
            if "time" in df.columns:
                df = df[(df["time"] >= start) & (df["time"] <= end)]
        
        # Handling job_ids
        if job_ids:
             if "job_id" in df.columns:
                 df = df[df["job_id"].isin(job_ids)]
             else:
                 # If job_id not in columns, ignore filter as discussed
                 pass
            
        # Select variables with support for "wide" format (var&param=val)
        if variables:
            cols_to_keep = []
            
            # 1. Always keep context columns
            for ctx in ["time", "job_id"]:
                if ctx in df.columns:
                    cols_to_keep.append(ctx)
            
            # 2. Find matching data columns
            available_cols = df.columns
            for var in variables:
                for col in available_cols:
                    if col == var:
                        cols_to_keep.append(col)
                    elif col.startswith(f"{var}&"):
                        # Matches "sds.I[1]&param=val"
                        cols_to_keep.append(col)
                        
            # Remove duplicates and filter
            cols_to_keep = list(set(cols_to_keep))
            
            if cols_to_keep:
                df = df[cols_to_keep]
            
        return df.to_dict(orient='list')

    def get_summary_metrics(self, task_id: str, workspace_path: Path) -> List[Dict[str, Any]]:
        """
        Retrieves summary metrics from the HDF5 file.
        Returns a list of dicts: [{'job_id': 1, 'metric_name': 'X', 'metric_value': 10.0}, ...]
        """
        try:
            hdf5_file = self._find_result_file(workspace_path, "sweep_results.h5")
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
