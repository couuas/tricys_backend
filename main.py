import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager

from tricys_backend.core.config import settings
from tricys_backend.api.v1.api import api_router
from tricys_backend.utils.db import create_db_and_tables
from tricys_backend.services.task_queue import TaskQueue

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
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
