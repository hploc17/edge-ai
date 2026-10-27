import json
from typing import Dict, Optional
from fastapi import WebSocket
import jwt
import os

JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_jwt_key_traffic_gis_2026_change_in_production")
STAFF_ROLES = {"ADMIN", "MANAGER"}

# Các sự kiện nhạy cảm chỉ gửi cho STAFF
STAFF_ONLY_EVENTS = {"device_pending", "preview_frame"}

class WebSocketManager:
    """Manages active WebGIS client WebSocket connections with role-based filtering."""

    def __init__(self):
        # Lưu websocket -> {"role": str | None, "userId": str | None}
        self.active_connections: Dict[WebSocket, Dict[str, Optional[str]]] = {}

    async def connect(self, websocket: WebSocket, token: Optional[str] = None):
        await websocket.accept()
        role = None
        user_id = None
        if token:
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
                role = payload.get("role")
                user_id = payload.get("userId")
            except Exception:
                pass
        self.active_connections[websocket] = {"role": role, "userId": user_id}

    def set_client_token(self, websocket: WebSocket, token: str):
        """Cập nhật quyền hạn khi client gửi message authenticate qua socket."""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            self.active_connections[websocket] = {
                "role": payload.get("role"),
                "userId": payload.get("userId"),
            }
        except Exception:
            pass

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            del self.active_connections[websocket]

    async def broadcast(self, message: dict):
        dead_connections = []
        msg_type = message.get("type")
        payload = json.dumps(message, ensure_ascii=False)

        for connection, client_info in list(self.active_connections.items()):
            # Lọc quyền cho các sự kiện nhạy cảm
            if msg_type in STAFF_ONLY_EVENTS:
                client_role = client_info.get("role")
                if client_role not in STAFF_ROLES:
                    continue  # Bỏ qua không gửi cho Khách/USER

            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(dead)


ws_manager = WebSocketManager()
