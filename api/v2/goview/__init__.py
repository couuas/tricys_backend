from fastapi import APIRouter
from tricys_backend.api.v2.goview import sys, project, data

router = APIRouter()
router.include_router(sys.router, prefix="/sys", tags=["GoView System"])
router.include_router(project.router, prefix="/project", tags=["GoView Project"])
router.include_router(data.router, prefix="/data", tags=["GoView Data Adapter"])
