"""
LiveStreamManager: In-Memory On-Demand Live Streaming Service.

Quản lý luồng video JPEG thời gian thực từ Jetson Nano qua Backend tới WebGIS.
Đặc tính kỹ thuật:
- Zero-Queue: Luôn cập nhật và phân phối frame mới nhất (loại bỏ độ trễ tích lũy).
- On-Demand: Chỉ kích hoạt luồng camera khi có ít nhất 1 viewer trên WebGIS đang xem.
- Asyncio Condition: Đánh thức các coroutine viewer khi có frame mới mà không lock mạng.
- Rate-limiting & Giới hạn kết nối (per-node & total viewers).
"""

import asyncio
import json
import logging
import time
from typing import Dict, Set, Optional, Tuple, Any
from fastapi import WebSocket

from config import (
    LIVE_MAX_VIEWERS_PER_NODE,
    LIVE_MAX_VIEWERS_TOTAL,
    LIVE_MAX_FRAME_BYTES,
)

logger = logging.getLogger("LiveStreamManager")


class NodeStreamState:
    """Trạng thái luồng streaming của một Edge Node."""

    def __init__(self, edge_id: str):
        self.edge_id: str = edge_id
        self.jetson_ws: Optional[WebSocket] = None
        self.jetson_info: Dict[str, Any] = {}
        self.viewers: Set[WebSocket] = set()
        self.latest_frame: Optional[bytes] = None
        self.frame_seq: int = 0
        self.last_frame_time: float = 0.0
        self.is_streaming: bool = False
        self.condition: asyncio.Condition = asyncio.Condition()

    async def send_to_jetson(self, payload: dict) -> bool:
        """Gửi lệnh JSON điều khiển (start/stop) tới Jetson Nano."""
        if not self.jetson_ws:
            return False
        try:
            await self.jetson_ws.send_text(json.dumps(payload))
            return True
        except Exception as e:
            logger.warning("[LiveStream:%s] Failed to send to Jetson: %s", self.edge_id, e)
            return False


class LiveStreamManager:
    """Quản lý in-memory tất cả các luồng streaming Jetson <-> WebGIS."""

    def __init__(self):
        self._streams: Dict[str, NodeStreamState] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get_or_create(self, edge_id: str) -> NodeStreamState:
        async with self._lock:
            if edge_id not in self._streams:
                self._streams[edge_id] = NodeStreamState(edge_id)
            return self._streams[edge_id]

    def get_stream(self, edge_id: str) -> Optional[NodeStreamState]:
        return self._streams.get(edge_id)

    def total_viewers(self) -> int:
        return sum(len(s.viewers) for s in self._streams.values())

    async def register_jetson(self, edge_id: str, ws: WebSocket, hello_info: dict) -> NodeStreamState:
        """Jetson Nano kết nối WS Ingest và gửi handshake hello."""
        stream = await self.get_or_create(edge_id)
        
        # Nếu có WS cũ còn sót lại, đóng an toàn
        if stream.jetson_ws and stream.jetson_ws != ws:
            try:
                await stream.jetson_ws.close(code=1000, reason="New connection registered")
            except Exception:
                pass

        stream.jetson_ws = ws
        stream.jetson_info = hello_info
        logger.info("[LiveStream:%s] Jetson registered: %s (active viewers: %d)",
                    edge_id, hello_info, len(stream.viewers))

        # Nếu đã có người xem đang đợi sẵn, kích hoạt Jetson stream ngay lập tức
        if len(stream.viewers) > 0 and not stream.is_streaming:
            stream.is_streaming = True
            await stream.send_to_jetson({"type": "start", "fps": 10, "quality": 60})

        # Đánh thức viewer để chuyển trạng thái từ offline -> connecting
        async with stream.condition:
            stream.condition.notify_all()

        return stream

    async def unregister_jetson(self, edge_id: str, ws: WebSocket):
        """Jetson Nano ngắt kết nối WS Ingest."""
        stream = self.get_stream(edge_id)
        if not stream:
            return

        if stream.jetson_ws == ws:
            stream.jetson_ws = None
            stream.is_streaming = False
            logger.info("[LiveStream:%s] Jetson disconnected", edge_id)

            # Báo cho tất cả viewers biết Jetson đã ngắt kết nối
            async with stream.condition:
                stream.condition.notify_all()

    async def receive_frame(self, edge_id: str, frame_bytes: bytes) -> bool:
        """Nhận 1 frame binary JPEG từ Jetson Nano."""
        if len(frame_bytes) > LIVE_MAX_FRAME_BYTES:
            logger.warning("[LiveStream:%s] Dropped oversized frame: %d bytes > %d limit",
                           edge_id, len(frame_bytes), LIVE_MAX_FRAME_BYTES)
            return False

        stream = self.get_stream(edge_id)
        if not stream:
            return False

        # Cập nhật Zero-Queue (chỉ lưu frame mới nhất)
        stream.latest_frame = frame_bytes
        stream.frame_seq += 1
        stream.last_frame_time = time.time()

        # Đánh thức tất cả các viewer đang chờ frame
        async with stream.condition:
            stream.condition.notify_all()

        return True

    async def add_viewer(self, edge_id: str, ws: WebSocket) -> Tuple[bool, str]:
        """Người dùng mở popup hover xem stream trên WebGIS."""
        if self.total_viewers() >= LIVE_MAX_VIEWERS_TOTAL:
            return False, "full_total"

        stream = await self.get_or_create(edge_id)

        if len(stream.viewers) >= LIVE_MAX_VIEWERS_PER_NODE:
            return False, "full_node"

        stream.viewers.add(ws)
        logger.info("[LiveStream:%s] Viewer added. Viewers count: %d", edge_id, len(stream.viewers))

        # Nếu là viewer đầu tiên và Jetson đang kết nối -> gửi lệnh start
        if len(stream.viewers) == 1 and stream.jetson_ws is not None and not stream.is_streaming:
            stream.is_streaming = True
            await stream.send_to_jetson({"type": "start", "fps": 10, "quality": 60})
            logger.info("[LiveStream:%s] First viewer connected -> Sent START to Jetson", edge_id)

        return True, "ok"

    async def remove_viewer(self, edge_id: str, ws: WebSocket):
        """Người dùng rời chuột hoặc đóng popup hover."""
        stream = self.get_stream(edge_id)
        if not stream:
            return

        stream.viewers.discard(ws)
        logger.info("[LiveStream:%s] Viewer removed. Remaining viewers: %d", edge_id, len(stream.viewers))

        # Nếu không còn ai xem -> gửi lệnh stop cho Jetson để tiết kiệm tài nguyên
        if len(stream.viewers) == 0:
            if stream.jetson_ws is not None and stream.is_streaming:
                stream.is_streaming = False
                await stream.send_to_jetson({"type": "stop"})
                logger.info("[LiveStream:%s] 0 viewers left -> Sent STOP to Jetson (On-Demand Idle)", edge_id)

    def get_status(self, edge_id: str) -> dict:
        """Lấy trạng thái chi tiết của luồng stream."""
        stream = self.get_stream(edge_id)
        if not stream:
            return {
                "edge_id": edge_id,
                "jetson_connected": False,
                "viewers": 0,
                "last_frame_age_s": -1.0,
                "state": "offline"
            }

        now = time.time()
        age = (now - stream.last_frame_time) if stream.last_frame_time > 0 else -1.0

        if not stream.jetson_ws:
            state = "offline"
        elif stream.is_streaming and age >= 0 and age < 5.0:
            state = "live"
        elif stream.is_streaming and age >= 5.0:
            state = "stalled"
        else:
            state = "ready"

        return {
            "edge_id": edge_id,
            "jetson_connected": stream.jetson_ws is not None,
            "viewers": len(stream.viewers),
            "last_frame_age_s": round(age, 2),
            "state": state
        }


live_stream_manager = LiveStreamManager()
