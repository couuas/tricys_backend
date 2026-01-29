import subprocess
import threading
import os
import sys
import logging
import asyncio
import signal
from typing import Optional
from pathlib import Path
from tricys_backend.core.config import settings
from tricys_backend.services.connection_manager import manager
import psutil

logger = logging.getLogger(__name__)

class LogReaderThread(threading.Thread):
    """
    Background thread to read subprocess stdout/stderr, write to file,
    and broadcast to WebSocket clients via ConnectionManager.
    """
    def __init__(self, process: subprocess.Popen, log_path: Path, task_id: str, loop: asyncio.AbstractEventLoop):
        super().__init__(daemon=True)
        self.process = process
        self.log_path = log_path
        self.task_id = task_id
        self.loop = loop

    def run(self):
        try:
            with open(self.log_path, "a", encoding="utf-8", buffering=1) as f:
                # Iterate line by line
                for line in iter(self.process.stdout.readline, b''):
                    decoded_line = line.decode('utf-8', errors='replace')
                    
                    # 1. Write to file
                    f.write(decoded_line)
                    
                    # 2. Broadcast
                    # We use run_coroutine_threadsafe to schedule the async broadcast on the main loop
                    if self.loop and self.loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            manager.broadcast_to_task(self.task_id, {"type": "log", "data": decoded_line}),
                            self.loop
                        )
                        
                        # TODO: Stage 2 - Progress Regex Parsing here
                        # if "Progress:" in decoded_line: ...
                        
        except Exception as e:
            logger.error(f"Error in LogReaderThread for task {self.task_id}: {e}")

class SimulationEngine:
    def __init__(self):
        pass

    def run_task(self, task_id: str, workspace_path: Path, config_path: Path, task_type: str, enhanced: bool = False, turbo: bool = False) -> tuple[int, Optional[str]]:
        """
        Spawns a subprocess to run the tricys simulation.
        Starts a background thread to handle logging.
        Returns: (pid, error_message)
        """
        cmd = ["tricys"]
        
        # Add arguments
        # Command map: BASIC -> basic, ANALYSIS -> analysis
        subcommand = "basic" if task_type == "BASIC" else "analysis"
        
        # Construct command: tricys basic -c config.json [--enhanced] [--turbo]
        cmd.extend([subcommand, "-c", str(config_path)])
        
        if enhanced:
            cmd.append("--enhanced")
        
        if turbo:
            cmd.append("--turbo")
            
        logger.info(f"Starting process: {' '.join(cmd)} in {workspace_path}")
        
        log_file = workspace_path / "simulation.log"
        
        try:
            # Open log file initially to clear it or ensure it exists? 
            # LogReaderThread opens in "a" mode.
            # Let's ensure directory exists (it should).
            
            # Popen with PIPE for stdout
            process = subprocess.Popen(
                cmd,
                cwd=str(workspace_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Merge stderr to stdout
                env=os.environ.copy() # Pass current env
            )
            
            # Get current event loop for threadsafe calls
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # Should typically assume called from async context in TaskQueue
                loop = None
                logger.warning("No running event loop found for EngineService.run_task. WebSocket broadcast may fail.")

            # Start Log Reader Thread
            log_thread = LogReaderThread(process, log_file, task_id, loop)
            log_thread.start()
                
            return process.pid, None
            
        except Exception as e:
            logger.error(f"Failed to start process: {e}")
            return -1, str(e)

    def stop_task(self, pid: int) -> bool:
        """
        Stops the process with the given PID.
        Returns True if successful, False otherwise.
        """
        try:
            parent = psutil.Process(pid)
            # Terminate children first (if any, e.g. from shell=True or sub-subprocesses)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
            return True
        except ImportError:
            # Fallback to os.kill
            try:
                os.kill(pid, signal.SIGTERM)
                return True
            except OSError:
                return False
        except Exception as e:
            logger.error(f"Error stopping process {pid}: {e}")
            return False
