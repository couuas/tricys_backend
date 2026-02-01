import json
import subprocess
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from tricys_backend.core.config import settings

logger = logging.getLogger(__name__)

class ModelService:
    """
    Service to interact with Modelica models via the 'tricys parse' CLI command.
    """

    @staticmethod
    def _get_tricys_cli_path() -> List[str]:
        """
        Determines the command to invoke the tricys CLI.
        Directly uses sys.executable and finds tricys/main.py relative to the backend.
        This ensures we use the same python environment and code.
        """
        # Assuming tricys_backend and tricys are in the same parent directory (root of repo)
        # tricys_backend/core/config.py -> BASE_DIR is tricys_backend/
        # Repo root is BASE_DIR.parent
        repo_root = settings.BASE_DIR.parent
        cli_path = repo_root / "tricys" / "main.py"
        
        if not cli_path.exists():
            # Fallback or error logging
            logger.error(f"Tricys CLI not found at expected path: {cli_path}")
            # If installed as a package, maybe "tricys" is on path?
            # But for this dev setup, we expect main.py
            raise FileNotFoundError(f"Tricys CLI main.py not found at {cli_path}")

        return [sys.executable, str(cli_path)]

    @classmethod
    def parse_model(cls, package_path: str, model_name: str) -> List[Dict[str, Any]]:
        """
        Parses a Modelica model to extract parameters.

        Args:
            package_path: Absolute path to the .mo package file.
            model_name: Fully qualified model name (e.g. 'Cycle.Example').

        Returns:
            A list of parameter definitions (dictionaries).
        
        Raises:
            subprocess.CalledProcessError: If the CLI command fails.
            json.JSONDecodeError: If the CLI output is not valid JSON.
        """
        cmd = cls._get_tricys_cli_path() + ["parse", package_path, model_name]
        
        logger.info(f"Parsing model {model_name} from {package_path}", extra={"cmd": cmd})

        try:
            # Run subprocess, capturing stdout/stderr
            # We must be careful that 'tricys parse' outputs ONLY JSON to stdout.
            # Any logging from tricys should go to stderr.
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=str(settings.BASE_DIR.parent) # Run from repo root
            )
            
            # Parse JSON from stdout
            output_json = result.stdout.strip()
            if not output_json:
                 logger.warning("CLI returned empty output")
                 return []
            
            try:
                parameters = json.loads(output_json)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from CLI output: {output_json[:200]}...", extra={"error": str(e)})
                raise
                
            # Check if it's an error object
            if isinstance(parameters, dict) and "error" in parameters:
                 raise ValueError(f"CLI Error: {parameters['error']}")

            return parameters

        except subprocess.CalledProcessError as e:
            logger.error(
                f"CLI command failed with return code {e.returncode}", 
                extra={"stderr": e.stderr}
            )
            raise RuntimeError(f"Failed to parse model: {e.stderr}") from e
