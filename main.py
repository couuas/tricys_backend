import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from tricys_backend.core.config import settings
from tricys_backend.api.v1.api import api_router
from tricys_backend.api.v2.api import api_v2_router
from tricys_backend.utils.db import create_db_and_tables
from tricys_backend.services.task_queue import TaskQueue

# Global Exception Handlers
async def validation_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=400,
        content={"code": "VALIDATION_ERROR", "message": str(exc)},
    )

async def generic_exception_handler(request: Request, exc: Exception):
    import logging
    logging.getLogger("uvicorn.error").error(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "An internal error occurred."},
    )

async def recover_tasks():
    """
    Recover orphaned RUNNING tasks and requeue PENDING tasks.
    """
    import logging
    from sqlmodel import Session, select
    from tricys_backend.models.task import Task
    from tricys_backend.services.task_queue import db_engine, TaskQueue
    import psutil
    
    logger = logging.getLogger(__name__)
    logger.info("Starting task recovery...")
    
    with Session(db_engine) as session:
        # 1. Recover Orphaned RUNNING Tasks
        running_tasks = session.exec(select(Task).where(Task.status == "RUNNING")).all()
        recovered_count = 0
        for task in running_tasks:
            # Check if process still exists
            is_alive = False
            process_obj = None
            if task.pid and psutil.pid_exists(task.pid):
                try:
                    proc = psutil.Process(task.pid)
                    cmdline = " ".join(proc.cmdline()).lower()
                    if "tricys" in cmdline:
                        is_alive = True
                        process_obj = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            if is_alive and process_obj:
                 logger.warning(f"Killing orphaned task {task.id} (PID {task.pid})")
                 try:
                     process_obj.terminate()
                     # Give it a moment, but don't block startup too long
                 except Exception:
                     pass
            
            # Always mark as FAILED because the LogReader and Waiter threads are lost
            task.status = "FAILED"
            task.error_msg = "Task interrupted by server restart"
            task.pid = None
            session.add(task)
            recovered_count += 1
                 
        # 2. Re-queue PENDING Tasks
        pending_tasks = session.exec(select(Task).where(Task.status == "PENDING")).all()
        requeued_count = 0
        for task in pending_tasks:
            # Re-add to asyncio Queue
            await TaskQueue.add_task(task.id)
            requeued_count += 1
            
        session.commit()
        logger.info(f"Recovery complete: {recovered_count} failed orphaned, {requeued_count} requeued pending")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    
    # Recover tasks
    await recover_tasks()
    
    # Start TaskQueue worker in background
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

# Exception Handlers
from fastapi.exceptions import RequestValidationError
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# Configure Logging
import logging
import sys

# Setup root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(settings.BASE_DIR / "backend.log", encoding='utf-8')
    ]
)

# Silence watchfiles to prevent infinite loop if log file triggers reload
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

from fastapi.middleware.cors import CORSMiddleware

# CORS configuration
origins = settings.cors_origins_list
allow_all = "*" in origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if allow_all else origins,
    allow_origin_regex=".*" if allow_all else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(api_v2_router, prefix="/api/v2")

# Mount static assets
assets_dir = settings.BASE_DIR / "assets"
assets_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=assets_dir), name="static")

# Mount workspaces for serving custom model files
workspaces_dir = settings.WORKSPACES_DIR
workspaces_dir.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=workspaces_dir), name="assets")

@app.get("/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("tricys_backend.main:app", host="0.0.0.0", port=8000, reload=True)
