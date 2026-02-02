from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, status
from tricys_backend.services.connection_manager import manager
from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task
from tricys_backend.models.project import Project
from tricys_backend.models.user import User
from tricys_backend.core.config import settings
from tricys_backend.services.file_manager import FileManager
from jose import jwt, JWTError
from sqlmodel import Session, select
import logging
import os

router = APIRouter()
logger = logging.getLogger(__name__)

async def get_token_user(session: Session, token: str) -> User:
    """Helper to validate token from query string."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if not user_id: return None
        return session.get(User, user_id)
    except (JWTError, Exception):
        return None

@router.websocket("/ws/tasks/{task_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    task_id: str, 
    token: str = Query(...),
    db: Session = Depends(get_session)
):
    # 1. Authentication
    user = await get_token_user(db, token)
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 2. Authorization (Check ownership)
    task = db.get(Task, task_id)
    if not task:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    project = db.get(Project, task.project_id)
    if not project or project.user_id != user.id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 3. Accept Connection
    await manager.connect(websocket, task_id)
    
    try:
        # 4. Push Initial State
        await websocket.send_json({
            "type": "status", 
            "status": task.status,
            "task_id": task_id
        })
        
        # 5. Push Existing Logs (Tail)
        log_path = FileManager.get_log_path(task.project_id, task_id)
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    # Send last 100 lines to avoid overwhelming client
                    lines = f.readlines()
                    history = "".join(lines[-100:])
                    if history:
                        await websocket.send_json({
                            "type": "log_history",
                            "data": history
                        })
            except Exception as e:
                logger.warning(f"Failed to read log history: {e}")

        # 6. Keep-alive loop
        while True:
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}")
        manager.disconnect(websocket, task_id)
