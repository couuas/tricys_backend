from fastapi import APIRouter
from tricys_backend.api.v1.endpoints import configuration, monitoring, visualization, websockets, project, library, user, auth, admin, analysis

api_router = APIRouter()

# 0. Auth
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])

# 1. Configuration (Pre-simulation)
api_router.include_router(configuration.router, tags=["Configuration"])

# 2. Monitoring (In-simulation)
api_router.include_router(monitoring.router, tags=["Monitoring"])

# 3. Visualization (Post-simulation)
api_router.include_router(visualization.router, tags=["Visualization"])

# 4. Project & Model Tools (New)
api_router.include_router(project.router, prefix="/project", tags=["Project"])
api_router.include_router(library.router, prefix="/library", tags=["Library"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["Analysis"])

# 5. User Management
api_router.include_router(user.router, prefix="/user", tags=["User"])

# 6. Utilities
api_router.include_router(websockets.router, tags=["WebSockets"])  

@api_router.get("/health")
def health_check():
    return {"status": "ok", "version": "0.4.0"}