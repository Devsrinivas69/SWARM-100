"""
SWARM-100 Real-Time WebSocket Manager
Manages active WebSocket connections from dashboard browser clients.
Broadcasts genuine backend events (task state changes, critic reviews, tool audits, goal progress).
Maintains an in-memory ring buffer of recent events to hydrate newly connected clients.
"""

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Set
from fastapi import WebSocket

logger = logging.getLogger("swarm100.websocket")

class WebSocketManager:
    def __init__(self, max_event_history: int = 50):
        self.active_connections: Set[WebSocket] = set()
        self._event_history: deque = deque(maxlen=max_event_history)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accepts a new WebSocket connection and sends recent event history."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Active clients: {len(self.active_connections)}")

        # Hydrate newly connected client with recent genuine activity
        try:
            recent_events = list(self._event_history)
            if recent_events:
                await websocket.send_text(json.dumps({
                    "event_type": "initial_state",
                    "history": recent_events,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }))
        except Exception as e:
            logger.warning(f"Failed to send initial history to client: {e}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Removes a disconnected WebSocket client."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Active clients: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Broadcasts a genuine backend event to all connected dashboard clients.
        Also records the event in the history buffer.
        """
        payload = {
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._event_history.append(payload)

        message = json.dumps(payload, default=str)
        stale_connections = set()

        async with self._lock:
            connections = list(self.active_connections)

        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.debug(f"Failed to send to client; marking stale: {e}")
                stale_connections.add(connection)

        if stale_connections:
            async with self._lock:
                for c in stale_connections:
                    self.active_connections.discard(c)

    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Safe event emitter that can be called from synchronous or asynchronous code.
        Appends to history immediately, and schedules broadcast if an active event loop exists.
        """
        payload = {
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._event_history.append(payload)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send_broadcast(payload))
        except RuntimeError:
            pass

    async def _send_broadcast(self, payload: Dict[str, Any]) -> None:
        message = json.dumps(payload, default=str)
        stale_connections = set()
        async with self._lock:
            connections = list(self.active_connections)

        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                stale_connections.add(connection)

        if stale_connections:
            async with self._lock:
                for c in stale_connections:
                    self.active_connections.discard(c)

    def get_recent_events(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Returns the most recent broadcast events."""
        events = list(self._event_history)
        return events[-limit:]

# Global WebSocket manager singleton
ws_manager = WebSocketManager()
