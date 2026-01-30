from typing import Dict, List
from fastapi import WebSocket
import asyncio
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Map task_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)
        logger.info(f"WebSocket connected for task {task_id}. Total clients: {len(self.active_connections[task_id])}")

    def disconnect(self, websocket: WebSocket, task_id: str):
        if task_id in self.active_connections:
            if websocket in self.active_connections[task_id]:
                self.active_connections[task_id].remove(websocket)
                if not self.active_connections[task_id]:
                    del self.active_connections[task_id]
            logger.info(f"WebSocket disconnected for task {task_id}")

    async def broadcast_to_task(self, task_id: str, message: dict):
        if task_id in self.active_connections:
            # Create a copy of the list to iterate safely in case of disconnects during iteration
            connections = self.active_connections[task_id][:]
            
            # Send messages in parallel using asyncio.gather for better performance
            # This prevents blocking when multiple clients are connected
            send_tasks = []
            for connection in connections:
                send_tasks.append(self._safe_send(connection, message, task_id))
            
            # Execute all sends concurrently, ignore exceptions
            await asyncio.gather(*send_tasks, return_exceptions=True)
    
    async def _safe_send(self, connection: WebSocket, message: dict, task_id: str):
        """Helper to safely send a message and handle errors."""
        try:
            await connection.send_json(message)
        except Exception as e:
            logger.warning(f"Failed to send message to client for task {task_id}: {e}")
            # Could cleanup here, but disconnect() usually handles it
                    
manager = ConnectionManager()
