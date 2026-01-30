import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager

from tricys_backend.core.config import settings
from tricys_backend.api.v1.api import api_router
from tricys_backend.utils.db import create_db_and_tables
from tricys_backend.services.task_queue import TaskQueue

async def recover_orphaned_tasks():
    """
    Scan database for tasks stuck in RUNNING state and mark them as FAILED.
    This handles server crashes where processes may have been lost.
    """
    import logging
    from sqlmodel import Session, select
    from tricys_backend.models.task import Task
    from tricys_backend.services.task_queue import db_engine
    import psutil
    
    logger = logging.getLogger(__name__)
    logger.info("Starting orphaned task recovery...")
    
    with Session(db_engine) as session:
        running_tasks = session.exec(
            select(Task).where(Task.status == "RUNNING")
        ).all()
        
        recovered_count = 0
        for task in running_tasks:
            # Check if process still exists
            if not task.pid:
                # No PID recorded, mark as failed
                task.status = "FAILED"
                task.error_msg = "Process lost: No PID recorded"
                task.pid = None
                recovered_count += 1
            else:
                try:
                    # Check if PID exists
                    if psutil.pid_exists(task.pid):
                        # Verify it's actually a tricys process to detect PID reuse
                        try:
                            proc = psutil.Process(task.pid)
                            cmdline = " ".join(proc.cmdline())
                            if "tricys" not in cmdline.lower():
                                # PID reused by different process
                                task.status = "FAILED"
                                task.error_msg = "Process lost: PID reuse detected"
                                task.pid = None
                                recovered_count += 1
                            else:
                                logger.warning(f"Task {task.id} still running with PID {task.pid}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            task.status = "FAILED"
                            task.error_msg = "Process lost: Cannot access process"
                            task.pid = None
                            recovered_count += 1
                    else:
                        # Process doesn't exist
                        task.status = "FAILED"
                        task.error_msg = "Process lost during server restart"
                        task.pid = None
                        recovered_count += 1
                except Exception as e:
                    logger.error(f"Error checking task {task.id}: {e}")
                    task.status = "FAILED"
                    task.error_msg = f"Recovery error: {str(e)}"
                    task.pid = None
                    recovered_count += 1
            
            session.add(task)
        
        session.commit()
        logger.info(f"Orphaned task recovery complete: {recovered_count} tasks recovered")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    
    # Recover orphaned tasks from previous server runs
    await recover_orphaned_tasks()
    
    # Start TaskQueue worker in background
    # We use asyncio.create_task to run the worker loop
    worker_task = asyncio.create_task(TaskQueue.worker())
    
    # Start Cleanup Service
    from tricys_backend.services.cleanup_service import run_cleanup_loop
    cleanup_task = asyncio.create_task(run_cleanup_loop(str(settings.WORKSPACES_DIR)))
    
    yield
    
    # Shutdown
    worker_task.cancel()
    cleanup_task.cancel()
    try:
        await worker_task
        await cleanup_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title=settings.PROJECT_NAME, 
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # Specific origins instead of wildcard
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("tricys_backend.main:app", host="0.0.0.0", port=8000, reload=True)
