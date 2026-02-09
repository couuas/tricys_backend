from fastapi import APIRouter
from tricys_backend.api.v2.endpoints import goview

api_v2_router = APIRouter()
api_v2_router.include_router(goview.router, prefix="/goview", tags=["GoView"])

@api_v2_router.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}
