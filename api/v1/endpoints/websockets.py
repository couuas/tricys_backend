from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from tricys_backend.services.connection_manager import manager
from tricys_backend.utils.db import get_session
from sqlmodel import Session
from tricys_backend.models.task import Task
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/ws/tasks/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await manager.connect(websocket, task_id)
    try:
        while True:
            # Keep connection alive and handle client disconnects
            # We don't necessarily expect messages from client, but we must listen
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}")
        manager.disconnect(websocket, task_id)
