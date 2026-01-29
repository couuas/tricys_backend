from fastapi import APIRouter
from tricys_backend.api.v1.endpoints import simulation, websockets, data

api_router = APIRouter()
api_router.include_router(simulation.router, tags=["simulation"])
api_router.include_router(websockets.router, tags=["websockets"])
api_router.include_router(data.router, prefix="/results", tags=["data"])

@api_router.get("/health")
def health_check():
    return {"status": "ok", "version": "0.3.0"}
