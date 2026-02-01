from fastapi import APIRouter
from tricys_backend.api.v1.endpoints import configuration, monitoring, visualization, websockets

api_router = APIRouter()

# 1. Configuration (Pre-simulation)
api_router.include_router(configuration.router, tags=["Configuration"])

# 2. Monitoring (In-simulation)
api_router.include_router(monitoring.router, tags=["Monitoring"])

# 3. Visualization (Post-simulation)
api_router.include_router(visualization.router, tags=["Visualization"])

# 4. Utilities
api_router.include_router(websockets.router, tags=["WebSockets"])

@api_router.get("/health")
def health_check():
    return {"status": "ok", "version": "0.3.0"}
