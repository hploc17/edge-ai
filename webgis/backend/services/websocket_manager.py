import asyncio
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
        """Phát sóng dữ liệu song song không block: từng client có timeout 1.5s riêng (Fix D4, D6)."""
        msg_type = message.get("type")
        payload = json.dumps(message, ensure_ascii=False)

        connections_to_send = []
        for connection, client_info in list(self.active_connections.items()):
            # Lọc quyền cho các sự kiện nhạy cảm (Fix D6)
            if msg_type in STAFF_ONLY_EVENTS:
                client_role = client_info.get("role")
                if client_role not in STAFF_ROLES:
                    continue  # Bỏ qua không gửi cho Khách/USER
            connections_to_send.append(connection)

        if not connections_to_send:
            return

        async def _send_to_one(conn: WebSocket):
            try:
                # Bọc timeout 1.5s cho từng client riêng biệt: client chậm không làm nghẽn client khác (Fix D4)
                await asyncio.wait_for(conn.send_text(payload), timeout=1.5)
                return None
            except Exception:
                return conn

        results = await asyncio.gather(*[_send_to_one(c) for c in connections_to_send], return_exceptions=True)
        for res in results:
            if res is not None and not isinstance(res, Exception):
                self.disconnect(res)

    async def send_to_user(self, user_id: str, message: dict) -> bool:
        """Gửi thông điệp riêng cho một user_id cụ thể (Fix F3).
        
        Tránh phát tán dữ liệu riêng (như preview ROI) cho toàn bộ client khác.
        Trả về True nếu gửi thành công cho ít nhất 1 socket của user, ngược lại False.
        """
        if not user_id:
            return False

        payload = json.dumps(message, ensure_ascii=False)
        target_connections = [
            conn for conn, info in list(self.active_connections.items())
            if str(info.get("userId")) == str(user_id)
        ]

        if not target_connections:
            return False

        async def _send_to_one(conn: WebSocket):
            try:
                await asyncio.wait_for(conn.send_text(payload), timeout=1.5)
                return True
            except Exception:
                self.disconnect(conn)
                return False

        results = await asyncio.gather(*[_send_to_one(c) for c in target_connections], return_exceptions=True)
        return any(res is True for res in results)


ws_manager = WebSocketManager()
